"""Gather timing plans from saved results and this computer only; nothing paid is sent."""
import copy
from studio_backend import draft,timing_plans
from studio_backend.model import LyricLine
from . import acoustic_batch
from .project import file_stamp
from .vocal_audio import bound

SOURCES=('scribe','alignment','local_original','local_vocals','reading','chorus')
SKIPPED='本次未选择。'


def transcript_rows(project):
    """The stored transcript, only when it belongs to the current media."""
    stamp=file_stamp(project.media)
    if not project.transcript:return None,'本工程没有保存的 Scribe 转录。'
    if not project.transcript_stamp:return None,'保存的转录没有素材记录，不能确认对应当前素材。'
    if project.transcript_stamp!=stamp:return None,'保存的转录对应另一版素材，未使用。'
    try:rows=[LyricLine.from_dict(v).to_dict() for v in project.transcript]
    except (TypeError,ValueError,KeyError,AttributeError):return None,'保存的转录记录无效。'
    return rows,''


def saved_alignment(home,project):
    """Text-alignment rows from this project's latest draft workflow; never requested again."""
    try:state=draft.latest(home,project.uid)
    except (OSError,ValueError,KeyError,TypeError):state=None
    if not state:return None,'本工程没有保存的初稿流程，所以没有文字对齐结果。'
    if state['request'].get('_studio_context',{}).get('media')!=file_stamp(project.media):return None,'保存的文字对齐对应另一版素材，未使用。'
    stage=next((s for s in state['stages'] if s.get('key')=='alignment'),None)
    if not stage or stage.get('state')!='completed' or not isinstance(stage.get('result'),dict):
        return None,'最近一次初稿流程没有完成文字对齐（可能跳过了）；这次也不会去请求。'
    rows={v['id']:copy.deepcopy(v) for v in stage['result'].get('suggestions',[]) if isinstance(v,dict) and isinstance(v.get('id'),str)}
    if not rows:return None,'保存的文字对齐没有可用句子。'
    return rows,''


def confirmed_ids(project):
    return sorted(uid for uid,value in project.checks.items() if isinstance(value,dict) and value.get('reading') is True)


def availability(home,project):
    """Why each source cannot be used now, or '' when it can; quick checks only."""
    _,scribe=transcript_rows(project);_,alignment=saved_alignment(home,project)
    vocals='' if bound(project.vocal_track,project.media) else '还没有对应当前素材的人声辅助，可先在人声菜单准备。'
    return {'scribe':scribe,'alignment':alignment,'local_original':'','local_vocals':vocals,'reading':'','chorus':''}


def inputs(home,project,dictionaries=(None,None)):
    """Plain copies of everything the background job reads, taken on the GUI thread."""
    transcript,scribe=transcript_rows(project);alignment,saved=saved_alignment(home,project)
    track=copy.deepcopy(project.vocal_track) if bound(project.vocal_track,project.media) else None
    return {'media':project.media,'track':track,'transcript':transcript,'alignment':alignment,'confirmed':confirmed_ids(project),
            'romaji':copy.deepcopy(project.reading_preferences.get('romaji')),'song':copy.deepcopy(dictionaries[0]),'personal':copy.deepcopy(dictionaries[1]),
            'notes':{'scribe':scribe,'alignment':saved,'local_vocals':'' if track else '还没有对应当前素材的人声辅助。'}}


def _local(lines,rows,media,track,choice,home,cancel,progress,neighbors):
    result=acoustic_batch.generate([lines[n].to_dict() for n in rows],media,track,home,cancel,progress,audio_choice=choice,neighbors=neighbors)
    return timing_plans.local_lines(lines,rows,result)


def collect(lines,options,data,home,cancel,progress=lambda value:None):
    """Every chosen plan for the chosen lines, then a side-by-side report; the project is not touched."""
    indices=list(options['indices']);chosen=set(options.get('sources',SOURCES))
    sources={};unavailable={}
    targets=[n for n in indices if not timing_plans.protected(lines[n])]
    neighbors=[v.to_dict() for v in lines]
    def stopped():
        if cancel is not None and cancel.is_set():raise ValueError('已取消多方案比对，原时间保留。')
    for kind in SOURCES:
        if kind not in chosen:unavailable[kind]=SKIPPED
    if 'scribe' in chosen:
        if data['transcript'] is None:unavailable['scribe']=data['notes']['scribe']
        else:
            progress('正在用已保存的转录在本机重新匹配…');sources['scribe']=timing_plans.scribe_lines(lines,data['transcript'])
    if 'alignment' in chosen:
        if data['alignment'] is None:unavailable['alignment']=data['notes']['alignment']
        else:sources['alignment']=timing_plans.alignment_lines(lines,data['alignment'],targets)
    ran={}
    for kind,choice in (('local_original','original'),('local_vocals','vocals')):
        if kind not in chosen:continue
        track=data['track'] if choice=='vocals' else None
        if choice=='vocals' and not track:unavailable[kind]=data['notes']['local_vocals'];continue
        if not targets:continue
        stopped();progress('本机模型 · '+('人声辅助' if track else '原声')+'：正在生成候选…')
        try:sources[kind]=_local(lines,targets,data['media'],track,choice,home,cancel,progress,neighbors);ran[kind]=choice
        except Exception as error:
            if cancel is not None and cancel.is_set():raise
            unavailable[kind]='本机模型没有完成：'+str(error)
    stopped()
    if 'reading' in chosen:
        choice='vocals' if 'local_vocals' in ran else 'original' if 'local_original' in ran else None
        if choice is None:unavailable['reading']='另一读音要靠本机模型重新对齐，请同时选择本机模型（原声或人声辅助）。'
        else:
            first=timing_plans.analyze(lines,sources,indices,data['confirmed'],unavailable,chorus=False)
            confirmed=set(data['confirmed'])
            rows=[v['row'] for v in first['lines'] if v['status'] in {'conflict','uncertain'} and not v['protected'] and v['line_id'] not in confirmed][:timing_plans.MAX_READING_LINES]
            variants={}
            for n in rows:
                found=timing_plans.reading_variants(lines[n],data['transcript'] or (),data['transcript'] is not None,data['romaji'],song=data['song'],personal=data['personal'])
                if found:variants[n]=found
            readings={n:[] for n in variants}
            for k in range(timing_plans.MAX_READINGS):
                batch=[n for n,found in variants.items() if len(found)>k]
                if not batch:break
                stopped();progress(f'本机模型 · 另一读音（第 {k+1} 组，{len(batch)} 句）…')
                trial=copy.copy(lines)
                for n in batch:trial[n]=variants[n][k]['line']
                try:result=_local(trial,batch,data['media'],data['track'] if choice=='vocals' else None,choice,home,cancel,progress,[v.to_dict() for v in trial])
                except Exception as error:
                    if cancel is not None and cancel.is_set():raise
                    result={n:{'line':None,'note':'本机模型没有完成：'+str(error)} for n in batch}
                for n in batch:
                    variant=variants[n][k];value=result.get(n,{});note=variant['note']
                    if value.get('line') is None:note+=' 本机模型未能按这个读音生成：'+value.get('note','')
                    readings[n].append({**{key:variant[key] for key in ('word','text','kana','before','source')},'line':value.get('line'),'note':note})
            sources['reading']=readings
            if not variants:unavailable['reading']='有分歧的句子没有其他可用读音（人工、锁定或已确认的读音不参与）。'
    if 'chorus' in chosen and not data['confirmed']:unavailable['chorus']='还没有读音和时间都已人工确认的句子可作副歌节奏参考。'
    stopped();progress('正在逐音节并列比较…')
    return timing_plans.analyze(lines,sources,indices,data['confirmed'],unavailable,chorus='chorus' in chosen)
