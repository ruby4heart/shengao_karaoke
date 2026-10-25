"""Explicitly release editor protection on known, uncalibrated internals only."""
import copy
from .model import LyricLine
from .provenance import inferred


def inspect(line):
    line.validate();released=[];kept=[]
    for i,unit in enumerate(line.units):
        for j,h in enumerate(unit.highlights):
            reason='';origin=inferred(h)
            if line.locked or unit.locked:reason='歌词或词组已锁定'
            elif set(h.fixed_edges)=={'start','end'}:reason='起止点都已固定'
            elif h.source=='manual' and origin['method'] in {'manual_mora_split','manual_mora_merge','manual_mora_reset'}:reason='手工拆合结构保留，重算其余音节'
            elif origin['kind']=='manual' and not (origin['method']=='legacy' and h.source=='manual'):reason='逐音人工时间保留'
            elif not h.fixed_edges and 'manual_boundary' in origin.get('operations',[]):reason='逐音人工调整保留'
            elif h.source!='manual':continue
            else:
                origin=inferred(h)
                if origin['method']=='legacy' and origin['kind']=='manual':reason='旧人工记录没有逐音依据，保守保留'
                elif origin['kind']=='manual' or 'manual_boundary' in origin.get('operations',[]):reason='逐音人工调整保留'
                elif origin['kind'] not in {'estimated','character','word','reference','acoustic'}:reason='导入时间或来源未明确，保守保留'
                elif origin['current']!=[h.start,h.end]:reason='时间来源与当前位置不一致，保守保留'
                else:
                    released.append({'unit':i,'highlight':j,'kana':h.kana,'basis':origin['kind'],
                                     'operations':copy.deepcopy(origin.get('operations',[]))})
                    continue
            kept.append({'unit':i,'highlight':j,'kana':h.kana,'reason':reason})
    return {'released':released,'kept':kept,'locked_units':sum(bool(u.locked) for u in line.units)}


def prepare(line,allow_reviewed=False,release_old_protection=True):
    """Preparing is read-only; the actual axis changes only after review adoption."""
    from .acoustic import plan
    if type(allow_reviewed) is not bool or type(release_old_protection) is not bool:raise ValueError('时间确认重算选项无效。')
    line.validate()
    if line.locked:raise ValueError('本句已锁定，请先解除锁定。')
    if line.reviewed and not allow_reviewed:raise ValueError('本句时间已确认；需明确允许重新计算，采用后才恢复待确认。')
    details=inspect(line)
    if not release_old_protection:
        details['kept'] += [{'unit':p['unit'],'highlight':p['highlight'],'kana':p['kana'],'reason':'旧估算保护保持（未勾选重算）'} for p in details['released']]
        details['released']=[]
    if not details['released'] and not line.reviewed:
        raise ValueError('没有需要重新计算的旧估算保护；可直接按本句歌声重算其余音节。')
    baseline=copy.deepcopy(line);baseline.reviewed=False
    for ref in details['released']:
        baseline.units[ref['unit']].highlights[ref['highlight']].source='estimated'
    prepared=plan(baseline)
    prepared['original']=line.to_dict()
    prepared['recalculation']={'version':1,'allow_reviewed':allow_reviewed,'release_old_protection':release_old_protection,**details}
    return prepared


def validate_result(prepared,candidate):
    """Rebuild authorization from the original, never trust an arbitrary allowlist."""
    from .acoustic import protected_equal
    old=LyricLine.from_dict(prepared['original']);opt=prepared.get('recalculation',{})
    if not isinstance(opt,dict) or type(opt.get('version')) is not int or opt.get('version')!=1 or type(opt.get('allow_reviewed')) is not bool or type(opt.get('release_old_protection')) is not bool:
        raise ValueError('缺少明确的内部重算请求，未采用。')
    expected=prepare(old,opt['allow_reviewed'],opt['release_old_protection'])
    for key in ('baseline','jobs','protected','recalculation'):
        if prepared.get(key)!=expected.get(key):raise ValueError('内部重算请求或保护范围已变化，未采用。')
    if prepared.get('guide_points'):raise ValueError('旧保护释放与新的固定点请求不能混用。')
    computed={(m['unit'],m['highlight']) for job in prepared['jobs'] for m in job['mora']}
    successful={(m['unit'],m['highlight']) for run in candidate.timing_evidence.get('runs',[]) for m in run.get('mora',[])}
    if not successful or not successful<=computed:raise ValueError('声音结果与内部重算范围不一致。')
    allowed={(p['unit'],p['highlight']) for p in opt['released']}
    relaxed=copy.deepcopy(old)
    if len(candidate.units)!=len(old.units):raise ValueError('内部重算不能更改分词。')
    for i,(before,after) in enumerate(zip(old.units,candidate.units)):
        if before.highlights and len(before.highlights)!=len(after.highlights):raise ValueError('内部重算不能更改已有音节数量。')
        for j,h in enumerate(before.highlights):
            key=(i,j)
            if key not in successful and h!=after.highlights[j]:raise ValueError('固定、失败或范围外音节已变化，未采用。')
            if key in allowed and key in successful:relaxed.units[i].highlights[j].source='estimated'
            if h.fixed_edges!=after.highlights[j].fixed_edges:raise ValueError('内部重算不能建立或解除人工固定点。')
    if candidate.reviewed:raise ValueError('内部重算候选必须保持时间待确认。')
    protected_equal(relaxed,candidate)
