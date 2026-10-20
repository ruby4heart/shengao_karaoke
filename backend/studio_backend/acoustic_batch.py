"""Automatic-draft range fitting, separate from manual local alignment."""
import copy
from .model import LyricLine
from . import acoustic

def prepare(line,duration,fit_range=True,neighbors=()):
    from .draft import protected
    line.validate()
    if protected(line):raise ValueError('人工校准、已确认或锁定的歌词保留，不参与整首重算。')
    if line.match.get('status') in {'unmatched','uncertain'}:raise ValueError('歌词位置尚有匹配疑点，请先限定本句范围或重新匹配。')
    if line.end>duration or line.start>=duration:raise ValueError('此句超出有效音轨，请先修正整句范围。')
    original=line.to_dict();value=copy.deepcopy(line)
    if fit_range:
        # Padding must not introduce another lyric into a short forced run.
        # Existing overlaps remain untouched; only the extra search area is
        # limited by adjacent coarse ranges, including protected rows.
        left=max((v.end for v in neighbors if v.id!=line.id and v.start<line.start),default=0)
        right=min((v.start for v in neighbors if v.id!=line.id and v.start>line.start),default=duration)
        budget=max(0,60000-(value.end-value.start));before=min(500,budget,max(0,line.start-left));after=min(1500,budget-before,max(0,right-line.end))
        value.start=max(0,value.start-before);value.end=min(duration,value.end+after)
        # Keep explicit presentation times in the final proposal; they must
        # not constrain analysis or be silently changed by range fitting.
        value.display_start=value.display_end=None
    prepared=acoustic.plan(value)
    return {'plan':prepared,'input':original,'fit_range':fit_range}

def finalize(prepared,raw,source_hash,audio_hash,role):
    value=acoustic.propose(prepared['plan'],raw,source_hash,audio_hash,role,leading_gap=not prepared['fit_range'])
    if prepared['fit_range']:
        value.start=min(u.start for u in value.units);value.end=max(u.end for u in value.units)
        from .provenance import create
        value.timing_origin=create('acoustic',value.start,value.end,'tifa','phoneme_envelope',value.kana)
        original=prepared['input'];value.display_start=original.get('display_start');value.display_end=original.get('display_end')
        try:value.validate()
        except ValueError as error:raise ValueError('歌声边界与手工留屏范围有冲突，请先调整本句显示范围；保留初稿。') from error
        value.timing_evidence.update(input_range=[original['start'],original['end']],analysis_range=[prepared['plan']['original']['start'],prepared['plan']['original']['end']],fit_range=True,
            notice='以本次建议假名强制对齐实际歌声，并微调粗略句首句尾；原文、分词和输入读音保留。假名与演唱时间仍需试听确认，模型分数不是准确率。')
        first=next(h for u in value.units for h in u.highlights);last=[h for u in value.units for h in u.highlights][-1]
        if first.start-prepared['plan']['jobs'][0]['start']<=20 or prepared['plan']['jobs'][-1]['end']-last.end<=20:
            value.timing_evidence['notes'].append('歌声候选贴近分析范围边缘，可能有截音；请扩大本句范围，细听起音或拖长尾音。')
    value.validate();return value
