"""Cancelable, hash-bound local singing alignment and recoverable proposals."""
from pathlib import Path
import copy
import hashlib
import json
import os
import sys
import tempfile
from studio_backend import acoustic
from studio_backend.settings import atomic_json
from .paths import ROOT,RUNTIME,ffmpeg
from .project import file_stamp
from .vocal_audio import digest,cancelled,run,bound

from audio_contract import TIFA_ENGINE_VERSION as ENGINE_VERSION,TIFA_MODEL_SHA256 as MODEL_SHA256,TIFA_FILES

def engine_command():
    if not getattr(sys,'frozen',False):
        python=ROOT/'.venv-align/Scripts/python.exe'
        if python.is_file():return [str(python),str(ROOT/'desktop/vocal_engine.py')]
    frozen=RUNTIME/'vocal-engine'/'shengao-vocals.exe'
    if frozen.is_file():return [str(frozen)]
    raise ValueError('缺少本地歌声对齐引擎，请完整解压运行包。')

def model_path():
    for folder in [RUNTIME/'vocal-engine/tifa-model',ROOT/'vendor/tifa-model']:
        if (folder/'model.pt').is_file():return folder
    raise ValueError('缺少本地歌声模型，请完整解压运行包。')

def available():
    engine_command();folder=model_path()
    for name,expected in TIFA_FILES.items():
        if not (folder/name).is_file() or digest(folder/name)!=expected:raise ValueError('本地歌声模型或配置不完整，请完整解压运行包。')
    return folder

def cache_key(prepared,source_hash,audio_hash):
    return hashlib.sha256(json.dumps([ENGINE_VERSION,MODEL_SHA256,source_hash,audio_hash,prepared],ensure_ascii=True,sort_keys=True).encode()).hexdigest()

def read_cache(home,key,prepared,source_hash,audio_hash,role):
    cache=Path(home)/'alignment-cache'/key/'aligned.json'
    try:
        value=json.loads(cache.read_text(encoding='utf-8'));raw=value['result'];payload=json.dumps(raw,ensure_ascii=True,sort_keys=True).encode()
        if value['key']!=key or value.get('result_sha256')!=hashlib.sha256(payload).hexdigest() or raw['engine']!=ENGINE_VERSION or raw['model_sha256']!=MODEL_SHA256:return None
        acoustic.propose(prepared,raw,source_hash,audio_hash,role);return raw
    except (OSError,ValueError,KeyError,TypeError):return None

def write_cache(home,key,raw):
    payload=json.dumps(raw,ensure_ascii=True,sort_keys=True).encode();cache=Path(home)/'alignment-cache'/key/'aligned.json';cache.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(cache,{'key':key,'result':raw,'result_sha256':hashlib.sha256(payload).hexdigest()})

def generate(prepared,source,track,home,cancel,progress=lambda x:None):
    source=str(Path(source).resolve());stamp=file_stamp(source)
    if not stamp:raise ValueError('当前素材不存在')
    progress('正在核对当前素材与歌声对齐缓存…');source_hash=digest(source,cancel)
    audio=source;role='original';audio_hash=source_hash
    if track:
        if not bound(track,source) or track['source_sha256']!=source_hash:raise ValueError('人声与当前素材不一致，请先重新生成人声或改用原声。')
        audio_hash=digest(track['path'],cancel)
        if audio_hash!=track['sha256']:raise ValueError('人声缓存内容已变化，未开始对齐。')
        audio=track['path'];role='vocals'
    key=cache_key(prepared,source_hash,audio_hash)
    folder=Path(home)/'alignment-cache'/key;folder.mkdir(parents=True,exist_ok=True)
    raw=read_cache(home,key,prepared,source_hash,audio_hash,role)
    if raw is not None:progress('复用本次素材、假名及固定边界完全一致的对齐结果。')
    if raw is None:
        with tempfile.TemporaryDirectory(prefix='pending-',dir=folder) as temp:
            work=Path(temp);jobs=copy.deepcopy(prepared['jobs'])
            progress('正在本机提取当前句音频；无需密钥，不上传素材。')
            # Decode once, then slice by sample index so multiple human anchors
            # share exactly the same audio clock without repeated lossy seeks.
            window_start=jobs[0]['start'];window_end=jobs[-1]['end'];pcm=work/'window.f32'
            run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',audio,'-ss',f'{window_start/1000:.3f}','-t',f'{(window_end-window_start)/1000:.3f}','-vn','-ac','1','-ar','48000','-f','f32le',pcm],cancel)
            expected=(window_end-window_start)*48*4
            if pcm.stat().st_size!=expected:raise ValueError('本句范围超出有效音轨，未重算；请先修正整句范围。')
            with pcm.open('rb') as stream:
                for i,job in enumerate(jobs):
                    cancelled(cancel);path=work/f'run-{i}.f32';stream.seek((job['start']-window_start)*48*4)
                    path.write_bytes(stream.read((job['end']-job['start'])*48*4));job['pcm']=str(path)
            request=work/'request.json';report=work/'report.json'
            atomic_json(request,{'jobs':jobs,'cache_dir':str(Path(home)/'alignment-cache')})
            run(engine_command()+['--model',str(model_path()),'--align-request',str(request),'--report',str(report)],cancel,progress,engine=True,kind='alignment')
            raw=json.loads(report.read_text(encoding='utf-8'))
            if raw['engine']!=ENGINE_VERSION or raw['model_sha256']!=MODEL_SHA256:raise ValueError('歌声引擎版本不一致，未采用。')
            acoustic.propose(prepared,raw,source_hash,audio_hash,role)
            cancelled(cancel);write_cache(home,key,raw)
    cancelled(cancel)
    if file_stamp(source)!=stamp or digest(source,cancel)!=source_hash or digest(audio,cancel)!=audio_hash:raise ValueError('对齐期间素材或人声已变化，结果保留但未采用。')
    line=acoustic.propose(prepared,raw,source_hash,audio_hash,role)
    return {'ok':True,'action':'acoustic','suggestions':[line.to_dict()],'message':'本地歌声对齐完成。原文、读音、整句头尾及人工固定时间保留；请比较音节新旧时间，试听后勾选采用。模型分数不是准确率。','cache_key':key,'seconds':raw.get('seconds'), 'source_sha256':source_hash,'audio_role':role}
