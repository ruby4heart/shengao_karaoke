"""Durable local chorus reuse followed by new target-audio alignment."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from .model import LyricLine
from .settings import Settings,atomic_json
from .draft import digest,exclusive
from .chorus_reuse import prepare,source_valid,signature
from . import singing_stage


def path_for(root,uid):
    if not isinstance(uid,str) or not re.fullmatch('[a-f0-9]{32}',uid):raise ValueError('副歌复用任务编号无效。')
    return Settings(root).root/'chorus-workflows'/uid/'state.json'


def rows(values):
    if not isinstance(values,list) or len(values)>3000:raise ValueError('副歌复用范围无效，请分段处理。')
    result=[LyricLine.from_dict(copy.deepcopy(v)) for v in values]
    if len({v.id for v in result})!=len(result) or sum(len(v.text) for v in result)>60000:raise ValueError('歌词编号重复或范围过大。')
    return result


def inputs(request):
    source=LyricLine.from_dict(copy.deepcopy(request['source_line']));source_valid(source,request.get('source_reading_confirmed'))
    targets=rows(request.get('lines',[]))
    if not targets:raise ValueError('请先选择要复用读音的句子。')
    options=request.get('chorus_options',{});align=options.get('align',True);fit=options.get('fit_range',True);role=options.get('audio_role','auto')
    if type(align) is not bool or type(fit) is not bool or role not in {'auto','original','vocals'}:raise ValueError('副歌声音处理选项无效。')
    confirmed=request.get('reading_confirmed_ids',[])
    if not isinstance(confirmed,list) or any(not isinstance(v,str) for v in confirmed):raise ValueError('读音确认状态无效。')
    neighbors=rows(request.get('neighbor_lines',[]))
    context=request.get('_studio_context',{})
    if not isinstance(context,dict):raise ValueError('任务对应的工程信息无效。')
    return {'source_line':source.to_dict(),'source_reading_confirmed':True,'lines':[v.to_dict() for v in targets],
        'reading_confirmed_ids':sorted(set(confirmed)),'neighbor_lines':[v.to_dict() for v in neighbors],
        'chorus_options':{'align':align,'fit_range':fit,'audio_role':role},'media':str(request.get('media','')),
        'vocal_track':copy.deepcopy(request.get('vocal_track',{})),'_studio_context':copy.deepcopy(context)}


def load(root,uid):
    state=json.loads(path_for(root,uid).read_text(encoding='utf-8'))
    if state.get('version')!=1 or state.get('id')!=uid or state.get('result_hash')!=digest(state.get('data',{})):
        raise ValueError('副歌复用检查点无效，未自动重新处理。')
    if state.get('signature')!=digest([1,state.get('request'),state.get('media_sha256')]) or state.get('prepared_hash')!=digest(state.get('prepared')):
        raise ValueError('副歌复用输入或准备阶段已损坏，未自动重新处理。')
    values=rows(state['data']['suggestions']);originals=rows(state['request']['lines'])
    if [(v.id,v.text) for v in values]!=[(v.id,v.text) for v in originals]:raise ValueError('复用检查点更改了原歌词。')
    prepared=rows(state['prepared'])
    if {v.id for v in prepared}!=set(state['eligible_ids']):raise ValueError('副歌准备阶段的范围已变化。')
    if state['source_signature']!=signature(LyricLine.from_dict(state['request']['source_line'])):raise ValueError('来源句的复用依据已损坏。')
    return state


def result(state):
    value=copy.deepcopy(state['data']);source=state['request']['source_line']
    value.update(review_required=True,local=True,partial=state['status']!='completed',message=state.get('message',''))
    value['reading_reuse']={'source_id':source['id'],'source_sha256':state['source_signature'],
        'source_reading_confirmed':True,'timing_copied':False,'skipped':copy.deepcopy(state['skipped']),
        'eligible_ids':list(state['eligible_ids']),'needs_new_audio':state['request']['chorus_options']['align']}
    value['chorus_workflow']={'id':state['id'],'status':state['status'],'context':state['request']['_studio_context'],
        'readings_prepared':True,'eligible':len(state['eligible_ids']),'skipped':len(state['skipped'])}
    return value


def saved_result(request,root):
    try:return result(load(root,request['workflow_id']))
    except (OSError,ValueError,KeyError,TypeError):return {}


def mark_stopped(root,uid):
    path=path_for(root,uid)
    with exclusive(path.parent/'.lock'):
        state=load(root,uid)
        if state['status']!='running':return
        state.update(status='paused',updated=time.time(),message='本地声音任务已结束；复用读音及已完成声音结果保留，可审核或继续。')
        atomic_json(path,state)


async def run(request,root,report):
    uid=request.get('workflow_id') or uuid.uuid4().hex;path=path_for(root,uid)
    with exclusive(path.parent/'.lock'):
        supplied=inputs(request);options=supplied['chorus_options'];media=Path(supplied['media'])
        def fingerprint():
            with media.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
        media_hash=await asyncio.to_thread(fingerprint) if options['align'] and media.is_file() else ''
        input_signature=digest([1,supplied,media_hash])
        if request.get('resume'):
            state=load(root,uid)
            if state['signature']!=input_signature:raise ValueError('来源、目标、素材或选项已变化，旧结果保留；请新建复用任务。')
            if state['status']=='completed':return result(state)
        else:
            if path.exists():raise ValueError('该任务已经存在，请继续原任务或新建任务。')
            source=LyricLine.from_dict(supplied['source_line']);values=[];eligible=[];skipped=[]
            for target in rows(supplied['lines']):
                try:
                    value=prepare(source,target,True,target.id in supplied['reading_confirmed_ids']);eligible.append(target.id)
                except ValueError as error:value=target;skipped.append({'id':target.id,'reason':str(error)})
                values.append(value.to_dict())
            ready=[v for v in values if v['id'] in eligible]
            state={'version':1,'id':uid,'signature':input_signature,'media_sha256':media_hash,'source_signature':signature(source),'request':supplied,
                'prepared':copy.deepcopy(ready),'prepared_hash':digest(ready),
                'eligible_ids':eligible,'skipped':skipped,'status':'prepared','updated':time.time(),'message':'分词与读音候选已保存；未复制来源时间。',
                'data':{'suggestions':values}}
        def save(message=None,status=None):
            if message is not None:state['message']=message
            if status is not None:state['status']=status
            state['updated']=time.time();state['result_hash']=digest(state['data']);atomic_json(path,state)
        save()
        if not state['eligible_ids'] or not options['align']:
            save('复用分词读音候选已保存，尚未按声音重算；时间为本句旧范围内的估算，请审核。' if state['eligible_ids'] else '所选句均需保留现有内容，未改动工程或调用声音模型。','completed')
            return result(state)
        eligible=set(state['eligible_ids']);prepared=copy.deepcopy(state['prepared'])
        voice_request={'media':supplied['media'],'vocal_track':supplied['vocal_track'],'workflow_id':uid,
            'neighbor_lines':supplied['neighbor_lines'],
            'draft_options':{'acoustic_audio':options['audio_role'],'fit_range':options['fit_range']}}
        def checkpoint(data):
            updates={v.id:v.to_dict() for v in rows(data['suggestions'])}
            if set(updates)!=eligible:raise ValueError('声音结果的歌词范围发生变化。')
            original={v['id']:v for v in supplied['lines']}
            if any(v['text']!=original[uid]['text'] for uid,v in updates.items()):raise ValueError('声音结果更改了原歌词。')
            by_id={v['id']:v for v in state['prepared']}
            for uid,value in updates.items():
                before=by_id[uid]
                if any(before.get(k)!=value.get(k) for k in ('kana','romaji','translation','reading_review','display_start','display_end')):
                    raise ValueError('声音结果更改了复用文字或读音，原候选保留。')
                fields=lambda row:[(u['text'],u.get('kana',''),u.get('romaji',''),u.get('reading_source',''),u.get('locked',False),[h['kana'] for h in u.get('highlights',[])]) for u in row['units']]
                if fields(before)!=fields(value):raise ValueError('声音结果更改了复用词组或读音，原候选保留。')
            state['data']={**copy.deepcopy(data),'suggestions':[updates.get(v['id'],v) for v in state['data']['suggestions']]}
            save('本段声音结果已逐句保存，仍需试听确认。','running')
        try:
            if not media_hash:raise ValueError('请先添加有效音视频；复用读音候选已保留，时间仍需手工处理。')
            save('正在本机按目标段落的声音重算；不会使用来源段的音节时间。','running')
            report('chorus_reuse',state['message'])
            await singing_stage.preflight(voice_request,media_hash)
            completed=state['data'].get('acoustic_checkpoint')
            data=await singing_stage.run(prepared,voice_request,root,report,checkpoint,completed)
            if await asyncio.to_thread(fingerprint)!=media_hash:raise ValueError('声音处理期间素材内容已变化，旧结果保留，请检查素材。')
            checkpoint(data)
            save('分词读音与本段歌声候选已保存；未形成声音候选的句子仍需手工校对，请逐句审核。','paused' if data.get('partial') else 'completed')
        except asyncio.CancelledError:
            save('本地已取消，复用读音及完成的声音结果保留，可继续未完成部分。','paused');raise
        except Exception as error:
            message=str(error) if isinstance(error,ValueError) else '本段歌声处理未完成；复用读音及完成的声音结果已保留，可审核或继续。'
            save(message,'paused')
        return result(state)
