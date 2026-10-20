"""One decode/model session, durable per-line results and cancellable resume."""
from pathlib import Path
import copy
import hashlib
import json
import os
import tempfile
from studio_backend.model import LyricLine
from studio_backend.settings import atomic_json
from studio_backend import acoustic_batch as planning
from audio_contract import WORKER_PROTOCOL
from . import acoustic_audio as audio
from .vocal_audio import digest,cancelled,run,bound
from .project import file_stamp
from .paths import ffmpeg

def preflight(source,track,audio_choice,source_hash=None):
    from .vocal_audio import valid_track
    audio.available()
    if audio_choice not in {'auto','original','vocals'}:raise ValueError('对齐音轨选项无效')
    valid_track(track)
    if audio_choice=='vocals' or (audio_choice=='auto' and track):
        if not bound(track,source) or (source_hash is not None and track.get('source_sha256')!=source_hash):raise ValueError('人声不对应当前素材，请重新生成或在流程中选择原声。')
        if digest(track['path'])!=track['sha256']:raise ValueError('人声资源已变化，请重新生成或在流程中选择原声。')

def generate(rows,source,track,home,cancel,progress=lambda x:None,checkpoint=lambda *x:None,fit_range=True,audio_choice='auto',completed=None,work_root=None):
    source=str(Path(source).resolve());stamp=file_stamp(source)
    if not stamp:raise ValueError('请先添加有效音视频，再按歌声对齐。')
    if audio_choice not in {'auto','original','vocals'}:raise ValueError('对齐音轨选项无效')
    progress('正在核对整首素材和音轨指纹…');source_hash=digest(source,cancel)
    input_path=source;audio_hash=source_hash;role='original'
    if audio_choice=='vocals' or (audio_choice=='auto' and track):
        if not bound(track,source) or track.get('source_sha256')!=source_hash:raise ValueError('现有人声与当前素材不一致，请重新生成人声或选择原声。')
        if digest(track['path'],cancel)!=track['sha256']:raise ValueError('人声缓存内容已变化，请重新生成或改用原声。')
        input_path=track['path'];audio_hash=track['sha256'];role='vocals'
    model=audio.available();dictionary={line.split('\t',1)[0] for line in (model/'dictionaries/japanese_dict_full.txt').read_text(encoding='utf-8').splitlines() if line.strip()}
    originals=[LyricLine.from_dict(v) for v in rows];output={v.id:v.to_dict() for v in originals};statuses={};saved={};reused=0;model_loads=0
    if len({v.id for v in originals})!=len(originals):raise ValueError('整首歌词编号重复')
    work_root=Path(work_root) if work_root else Path(home)/'alignment-work';work_root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='batch-',dir=work_root) as temp:
        work=Path(temp);pcm=work/'audio.f32'
        progress('正在本机准备整首音频；不会上传，也不改变成片音轨。')
        run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',input_path,'-vn','-ac','1','-ar','48000','-f','f32le',pcm],cancel)
        frames=pcm.stat().st_size//4
        if frames<=0 or pcm.stat().st_size%4:raise ValueError('素材没有完整音轨')
        if digest(source,cancel)!=source_hash or digest(input_path,cancel)!=audio_hash:raise ValueError('准备音频期间素材已变化，原初稿保留。')
        pcm_hash=digest(pcm,cancel);duration=frames//48;plans={};keys={};jobs=[];owners=[];parts={}
        previous=completed if isinstance(completed,dict) else {}
        previous=previous.get('processed',{}) if previous.get('source_sha256')==source_hash and previous.get('audio_sha256')==audio_hash and previous.get('pcm_sha256')==pcm_hash else {}
        def state(partial):
            aligned=sum(v['status']=='aligned' for v in statuses.values());manual=sum(v['status']=='needs_manual' for v in statuses.values())
            return {'suggestions':[copy.deepcopy(output[v.id]) for v in originals],'local':True,'partial':partial,
                'acoustic':{'total':len(originals),'processed':len(statuses),'aligned':aligned,'needs_manual':manual,'reused':reused,'model_loads':model_loads,'audio_role':role,'source_sha256':source_hash,'lines':copy.deepcopy(statuses)},
                'acoustic_checkpoint':{'source_sha256':source_hash,'audio_sha256':audio_hash,'pcm_sha256':pcm_hash,'processed':copy.deepcopy(saved)}}
        def publish():
            checkpoint(state(True));progress(f'歌声处理 {len(statuses)}/{len(originals)} 句 · {sum(s["status"]=="aligned" for s in statuses.values())} 句形成候选，{sum(s["status"]=="needs_manual" for s in statuses.values())} 句需手工核对')
        def finish(uid,raw=None,reason=''):
            if raw is not None:
                try:
                    if raw.get('engine')!=audio.ENGINE_VERSION or raw.get('model_sha256')!=audio.MODEL_SHA256:raise ValueError('本地歌声引擎版本不一致，请完整解压运行包。')
                    output[uid]=planning.finalize(plans[uid],raw,source_hash,audio_hash,role).to_dict()
                except ValueError as error:reason=str(error)
            count=len(output[uid].get('timing_evidence',{}).get('notes',[])) if not reason else 0
            statuses[uid]={'status':'needs_manual' if reason else 'aligned','reason':reason or (f'已生成歌声候选，另有 {count} 项声音提示；可展开依据并试听。' if count else '已生成歌声候选，仍需试听确认。')}
            saved[uid]={'key':keys.get(uid,''),'raw':copy.deepcopy(raw),'reason':reason};publish()
        with pcm.open('rb') as stream:
            for original in originals:
                cancelled(cancel);uid=original.id
                try:
                    prepared=planning.prepare(original,duration,fit_range,originals);plans[uid]=prepared
                    if any(m['pronunciation'] not in dictionary for j in prepared['plan']['jobs'] for m in j['mora']):raise ValueError('存在尚不支持的假名组合，请先在本句修改实际读音。')
                except ValueError as error:
                    keys[uid]=hashlib.sha256(json.dumps(original.to_dict(),ensure_ascii=True,sort_keys=True).encode()).hexdigest();finish(uid,reason=str(error));continue
                inference_plan=prepared['plan']
                # Cache numerical inputs, not unrelated translations or UI
                # snapshots. Rebuild proposals against the current line and
                # let the GUI's snapshot guard protect concurrent human edits.
                key=hashlib.sha256(json.dumps([audio.ENGINE_VERSION,audio.MODEL_SHA256,source_hash,audio_hash,pcm_hash,inference_plan['jobs']],ensure_ascii=True,sort_keys=True).encode()).hexdigest();keys[uid]=key
                old=previous.get(uid,{})
                if old.get('key')==key and old.get('reason'):
                    reused+=1;finish(uid,reason=old['reason']);continue
                raw=audio.read_cache(home,key,inference_plan,source_hash,audio_hash,role)
                if raw is None and old.get('key')==key and old.get('raw'):
                    try:
                        planning.finalize(prepared,old['raw'],source_hash,audio_hash,role);raw=old['raw']
                    except (ValueError,KeyError,TypeError):pass
                if raw is not None:reused+=1;finish(uid,raw);continue
                parts[uid]={}
                for local,j in enumerate(inference_plan['jobs']):
                    chunk=work/f'run-{len(jobs)}.f32';stream.seek(j['start']*48*4);data=stream.read((j['end']-j['start'])*48*4)
                    if len(data)!=(j['end']-j['start'])*48*4:raise ValueError('对齐范围超出有效音轨')
                    chunk.write_bytes(data);jobs.append({**j,'pcm':str(chunk)});owners.append((uid,local))
        if jobs:
            request=work/'request.json';report=work/'report.json';atomic_json(request,{'jobs':jobs,'cache_dir':str(Path(home)/'alignment-cache')})
            def event(value):
                nonlocal model_loads
                if value.get('stage')=='model':model_loads+=1;checkpoint(state(True))
                if value.get('stage')!='aligned_job':return
                if value.get('protocol')!=WORKER_PROTOCOL or value.get('engine')!=audio.ENGINE_VERSION or value.get('model_sha256')!=audio.MODEL_SHA256:raise ValueError('整首歌声引擎协议不一致，请完整解压新版本。')
                result=value.get('result',{});index=result.get('index')
                if type(index) is not int or not 0<=index<len(owners):raise ValueError('引擎返回了未知的对齐区间')
                uid,local=owners[index]
                if local in parts[uid]:raise ValueError('引擎重复返回对齐区间')
                parts[uid][local]={**result,'index':local}
                if len(parts[uid])==len(plans[uid]['plan']['jobs']):
                    raw={'engine':audio.ENGINE_VERSION,'model_sha256':audio.MODEL_SHA256,'jobs':[parts[uid][i] for i in range(len(parts[uid]))],'timestep_ms':10,'sample_rate':48000,'protocol':WORKER_PROTOCOL}
                    try:planning.finalize(plans[uid],raw,source_hash,audio_hash,role)
                    except ValueError:pass
                    else:audio.write_cache(home,keys[uid],raw)
                    finish(uid,raw)
            run(audio.engine_command()+['--model',str(model),'--align-request',str(request),'--report',str(report)],cancel,progress,engine=True,kind='alignment',event=event)
            if len(statuses)!=len(originals):raise ValueError('歌声引擎没有返回全部区间；已完成句子保留，请继续未完成部分。')
        cancelled(cancel)
        if file_stamp(source)!=stamp or digest(source,cancel)!=source_hash or digest(input_path,cancel)!=audio_hash:raise ValueError('对齐期间素材或人声变化，结果保留但未采用。')
        value=state(False);value['message']=f'本地歌声处理完成：{value["acoustic"]["aligned"]} 句候选，{value["acoustic"]["needs_manual"]} 句保留初稿待手工核对。所有时间仍需试听确认。';return value
