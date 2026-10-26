"""Structured review items and version-bound human decisions, without UI or API calls."""
import copy
import hashlib
import json
import re
from dataclasses import dataclass,asdict,field
from pathlib import Path
from studio_backend.model import LyricLine
from studio_backend.analysis import kana_only,recognition_for
from studio_backend.reading_candidates import _transcript_word
from studio_backend import translation


KINDS={'media':'素材','match':'匹配／错段','reading':'读音分歧','missing':'缺少词组／音节','duration':'异常时长','gap':'音节间隔','range':'范围','layout':'排版','translation':'译文','confirmation':'待确认','proposal':'待审任务建议'}
SEVERITIES={'error':'需处理','warning':'需检查','notice':'参考提示'}
DECISIONS={'keep','defer','adopted'}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_states(value):
    if not isinstance(value,dict) or len(value)>20000:raise ValueError('疑点处理记录格式无效或超过 20000 条')
    keys={'version','fingerprint','decision','title','current','suggested','why'}
    for key,entry in value.items():
        if not isinstance(key,str) or not re.fullmatch('[a-f0-9]{64}',key) or not isinstance(entry,dict) or set(entry)!=keys:raise ValueError('疑点处理记录字段无效')
        if type(entry['version']) is not int or entry['version']!=1 or not isinstance(entry['fingerprint'],str) or not re.fullmatch('[a-f0-9]{64}',entry['fingerprint']) or not isinstance(entry['decision'],str) or entry['decision'] not in DECISIONS:raise ValueError('疑点处理版本、指纹或决定无效')
        if any(not isinstance(entry[name],str) or len(entry[name])>20000 for name in ('title','current','suggested','why')):raise ValueError('疑点处理比较文字无效')


@dataclass(frozen=True)
class Issue:
    id:str
    fingerprint:str
    kind:str
    severity:str
    line_id:str|None
    row:int
    word:int
    part:int
    title:str
    why:str
    current:str
    suggested:str
    proposal:dict=field(default_factory=dict)

    def to_dict(self):return asdict(self)


def state(issue,records):
    previous=records.get(issue.id)
    if not previous:return 'open'
    # Adoption resolves the old problem by changing its value. If the problem
    # is present again, even with identical old inputs, that past action must
    # not hide it as already resolved.
    if previous['decision']=='adopted':return 'changed'
    return previous['decision'] if previous['fingerprint']==issue.fingerprint else 'changed'


def record_decision(records,issue,decision):
    validate_states(records)
    if not isinstance(decision,str) or decision not in DECISIONS:raise ValueError('疑点处理方式无效')
    result=copy.deepcopy(records)
    result[issue.id]={'version':1,'fingerprint':issue.fingerprint,'decision':decision,'title':issue.title,'current':issue.current[:20000],'suggested':issue.suggested[:20000],'why':issue.why[:20000]}
    validate_states(result);return result


def progress(issues,records):
    validate_states(records);counts={key:0 for key in ('open','changed','keep','defer','adopted')}
    for item in issues:counts[state(item,records)]+=1
    return {'total':len(issues),'pending':counts['open']+counts['changed']+counts['defer'],**counts,
            'saved_adoptions':sum(v['decision']=='adopted' for v in records.values())}


def collect(project,include_layout=True,pending=None):
    """Heuristic warnings identify things to listen to, never assert an AI score.

    An alternate dictionary entry alone is not a pronunciation conflict.
    Transcript kana must come from the currently bound media; old/stale text
    proposals remain comparable but cannot become a new sound observation.
    """
    project.validate()
    from .project import file_stamp
    stamp=file_stamp(project.media);context={'project':project.uid,'media':stamp};found=[]
    def add(kind,severity,row,word,part,tag,title,why,current,suggested,proposal=None,basis=None):
        uid=project.lines[row].id if row>=0 else None
        identity={'project':project.uid,'kind':kind,'line':uid,'word':word,'part':part,'tag':tag}
        data={'context':context,'current':current,'suggested':suggested,'why':why,'basis':basis,'proposal':proposal or {}}
        found.append(Issue(digest(identity),digest(data),kind,severity,uid,row,word,part,title,why,str(current),str(suggested),copy.deepcopy(proposal or {})))
    if not project.media or not Path(project.media).is_file():add('media','error',-1,-1,-1,'missing','素材未就绪','素材未添加或路径已移动；仍可先编辑歌词。',project.media,'添加素材或重新定位原文件')
    bound=bool(stamp and project.transcript_stamp and stamp==project.transcript_stamp)
    transcript=[]
    if bound:
        try:transcript=[LyricLine.from_dict(v) for v in project.transcript]
        except (TypeError,ValueError):transcript=[]
    if project.transcript and project.transcript_stamp and not bound:
        add('media','warning',-1,-1,-1,'transcript-stale','旧转录与当前素材不同','没有使用旧识别文字提出实际读音分歧。','旧转录已保留','核对视频版本；需要时重新转录或手工校对',basis=project.transcript_stamp)
    for row,line in enumerate(project.lines):
        match=line.match;status=match.get('status')
        if status in {'unmatched','uncertain'}:
            add('match','warning',row,-1,-1,'match','未匹配到或匹配不确定','可能缺唱、重复副歌或识别不完整；不是已确定的错误。',str(match.get('recognized','未找到可靠对应')),'试听本句；必要时限定正确时段只重配这一句',basis=match)
        if row and line.start<project.lines[row-1].start:
            add('match','warning',row,-1,-1,'order','本句起点早于上一句','可能是合唱，也可能配到了另一遍副歌；不会自动重排歌词。',f'{line.start} ms；上一句 {project.lines[row-1].start} ms','带上下文试听；保留合理合唱或限定正确区间',basis=[line.start,project.lines[row-1].start])
        if project.duration and max(line.end,line.display_end or 0)>project.duration:
            add('range','error',row,-1,-1,'end','本句超出片尾','演唱或留屏结束晚于当前素材；换源后请检查同步。',f'唱到 {line.end} ms；留屏到 {line.display_end} ms；媒体 {project.duration} ms','修正本句范围、显示时间或选择正确素材版本',basis=[line.start,line.end,line.display_start,line.display_end,project.duration])
        if not line.units:
            add('missing','warning',row,-1,-1,'units','本句尚未分词','即使没有匹配也可先圈整句范围，再按原歌词分词。',line.text,'直接在原文切分或预览本地词典分词')
        nearby=recognition_for(line,transcript) if transcript else []
        words=line.reading_review.get('words',[]);words=words if isinstance(words,list) else []
        for index,unit in enumerate(line.units):
            if index and unit.start>line.units[index-1].end:
                previous=line.units[index-1];gap=unit.start-previous.end
                add('gap','notice',row,index,-1,'word-gap','词组之间有空白','可能是真实休止，也可能是自动分轴留下的间隔；需结合声音检查，不会自动填平。',f'{previous.text} → {unit.text}：{gap} ms','带前词试听，使用声音空隙审核或手工微调',basis=[previous.end,unit.start,previous.locked,unit.locked])
            if not unit.kana:
                add('missing','warning',row,index,-1,'kana','词组缺少假名','原文保留；先填写实际日语读音，再划分音节。',unit.text,'填写假名；可比较词典和已保存文字建议')
            elif not unit.highlights:
                add('missing','warning',row,index,-1,'mora','词组缺少演唱音节','可只为本词按已有范围均分估算；这不是声音对齐或确认。',f'{unit.text}／{unit.kana}；{unit.start}–{unit.end} ms','只为本词生成估算音节，之后按歌声校对',{'kind':'missing_mora','word':index},basis=[unit.text,unit.kana,unit.start,unit.end,unit.locked,line.locked])
            heard=_transcript_word(unit,nearby) if nearby else {}
            actual=heard.get('kana','')
            if actual and actual!=kana_only(unit.kana):
                add('reading','warning',row,index,-1,'transcript','读音与对应转录假名不同','识别结果已绑定当前素材，但仍可能听错；须原声复核，转录不是确认事实。',unit.kana,actual,{'kind':'reading','word':index,'kana':actual},basis={'heard':heard,'source':project.transcript_stamp})
            saved=words[index] if index<len(words) and isinstance(words[index],dict) else {}
            if str(line.reading_review.get('method','')).startswith('deepseek') and saved.get('text')==unit.text:
                raw=saved.get('deepseek_suggested',saved.get('suggested',''));candidate=kana_only(raw) if isinstance(raw,str) else ''
                if candidate and candidate!=kana_only(unit.kana):
                    stale=bool(line.reading_review.get('stale'))
                    add('reading','warning',row,index,-1,'deepseek','已存文字读音建议与当前不同','DeepSeek 是文字候选，不能证明声音。'+('原文／读音已改，此旧建议只可比较。' if stale else str(saved.get('reason','请结合上下文试听决定。'))),unit.kana,candidate,{} if stale else {'kind':'reading','word':index,'kana':candidate},basis=[unit.text,saved,stale])
            roman=unit.reading_options.get('romaji',{})
            if roman.get('mode')=='manual' and roman.get('basis')!=unit.kana:
                add('reading','notice',row,index,-1,'romaji','手写罗马音对应旧读音','手写内容已保留；确认这是有意写法，或在罗马音设置中修改。',unit.romaji,'当前假名：'+unit.kana,basis=roman)
            for part,h in enumerate(unit.highlights):
                if not line.reviewed and (h.end-h.start<20 or h.end-h.start>2500):
                    add('duration','notice',row,index,part,'length','音节时长需要试听','仅由时长规则提示：可能是弱短音，也可能是合理拖长音；不会自动缩短或补齐。',f'{h.kana}：{h.end-h.start} ms','带前音慢放，必要时拆合或微调',basis=[h.start,h.end,h.fixed_edges,h.timing_origin])
                if part and h.start>unit.highlights[part-1].end:
                    previous=unit.highlights[part-1];gap=h.start-previous.end
                    add('gap','notice',row,index,part,'gap','音节之间有空白','可能是真实休止，也可能是自动划轴留下的间隔；仅靠时长不能决定填平。',f'{previous.kana} → {h.kana}：{gap} ms','试听原声／人声，使用声音空隙审核或手工微调',basis=[previous.end,h.start,previous.fixed_edges,h.fixed_edges])
        proposal=translation.suggestion(line)
        if proposal and proposal['text']!=line.translation:
            stale=proposal['for_text']!=line.text
            add('translation','notice',row,-1,-1,'translation','有已保存的译文备选','当前手写或已确认译文没有被后台替换。'+('旧建议属于其他原文，仅供比较。' if stale else '可比较后采用，仍需独立确认译文。'),line.translation,proposal['text'],{} if stale else {'kind':'translation'},basis=proposal)
        if not line.reviewed:add('confirmation','notice',row,-1,-1,'timing','本句时间尚未确认','自动生成、采用建议、保留疑点都不等于已听过并确认时间。',f'{line.start}–{line.end} ms','试听并校准后，用本句时间确认按钮确认',basis=[line.start,line.end,line.reviewed])
        if not project.checks.get(line.id,{}).get('reading'):
            add('confirmation','notice',row,-1,-1,'reading','本句读音尚未确认','文字建议与声音对齐均不会自动完成读音确认。',line.kana or ''.join(u.kana for u in line.units),'核对实际唱法后，用本句读音确认按钮确认',basis=[line.text,[(u.text,u.kana) for u in line.units],project.checks.get(line.id,{})])
    if pending:
        task=pending if isinstance(pending,dict) else {};result=task.get('result',{});result=result if isinstance(result,dict) else {}
        snapshots=task.get('snapshots',{});snapshots=snapshots if isinstance(snapshots,dict) else {};task_context=task.get('context',{});task_context=task_context if isinstance(task_context,dict) else {}
        by_id={line.id:row for row,line in enumerate(project.lines)};suggestions=result.get('suggestions',[])
        if not isinstance(suggestions,list):suggestions=[]
        if not result or not suggestions:
            add('proposal','warning',-1,-1,-1,'no-result','待审任务没有可用建议','任务记录保留；不能据此认定服务未处理，也不会自动重复付费提交。','当前工程保持','查看任务阶段、原结果或诊断记录，再决定是否重试')
        for number,raw in enumerate(suggestions):
            try:candidate=LyricLine.from_dict(raw)
            except (TypeError,ValueError,KeyError,AttributeError):
                add('proposal','warning',-1,-1,-1,'invalid-'+str(number),'任务建议格式需要检查','原结果仍保留；没有把无效字幕写入工程。','当前工程保持','查看任务记录或脱敏诊断，勿重复付费提交');continue
            row=by_id.get(candidate.id,-1);current=project.lines[row] if row>=0 else None
            stale=current is None or snapshots.get(candidate.id)!=(current.to_dict() if current else None) or bool(task_context and (task_context.get('project')!=project.uid or task_context.get('media')!=stamp))
            def summary(line):
                if line is None:return '当前工程已没有这句歌词'
                groups='；'.join(f'{u.text}／{u.kana} [{u.start}–{u.end} ms]' for u in line.units[:200])
                return f'{line.text}\n{line.start}–{line.end} ms\n{groups}'[:18000]
            add('proposal','warning',row,-1,-1,'task-'+candidate.id,'有待审任务建议'+('（当前已变化）' if stale else ''),
                '任务结果不会自动覆盖人工内容。'+('素材、本句或原始依据已变化；旧建议仅供比较，采用仍由原审核保护检查。' if stale else '请从待审任务审核逐项比较；采用不等于时间或读音确认。'),
                summary(current),summary(candidate),basis={'candidate':candidate.to_dict(),'original':snapshots.get(candidate.id),'context':task_context,'stale':stale})
    if include_layout:
        from .subtitles import layout_issues
        try:layout=layout_issues(project)
        except (ValueError,OSError) as error:layout=[(None,'排版检查未完成：'+str(error))]
        ordinals={}
        for uid,message in layout:
            row=next((i for i,line in enumerate(project.lines) if line.id==uid),-1);number=ordinals.get(uid,0);ordinals[uid]=number+1
            add('layout','warning',row,-1,-1,str(number),'排版需要检查',message,'当前字体、注音或显示设置','进入样式调整，先看预览和样片',basis={'style':asdict(project.style),'colors':project.color_styles,'layouts':project.layout_styles,'song_info':project.song_info,'line':project.lines[row].to_dict() if row>=0 else None})
    return found


def current_issue(project,expected,include_layout=True,pending=None):
    fresh=next((v for v in collect(project,include_layout,pending) if v.id==expected.id),None)
    if fresh is None or fresh.fingerprint!=expected.fingerprint:raise ValueError('疑点依据、素材或建议已变化；旧比较保留，请刷新后再处理。')
    return fresh


def proposed_line(project,issue):
    """Recompute an explicit local proposal using protected editing primitives."""
    fresh=current_issue(project,issue,include_layout=False)
    if fresh.row<0 or not fresh.proposal:raise ValueError('这项没有可直接采用的明确建议，请定位后手工校对。')
    line=project.lines[fresh.row];proposal=fresh.proposal
    if proposal['kind']=='translation':return translation.accept_suggestion(line)
    if proposal['kind']=='reading':
        from studio_backend.reading_change import preview
        return preview(line,proposal['word'],proposal['kana'],project.reading_preferences.get('romaji'))['line']
    if proposal['kind']=='missing_mora':
        from .editor_model import missing_mora_preview
        return missing_mora_preview(line,[proposal['word']]).line
    raise ValueError('这项没有可直接采用的建议')
