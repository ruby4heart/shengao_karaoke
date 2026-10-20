"""Content-bound local PCM for continuity review, separate from paid APIs."""
from pathlib import Path
import copy
import json
import os
import tempfile
from studio_backend.sound_gaps import analyze
from studio_backend.settings import atomic_json
from .vocal_audio import digest,cancelled,run,bound
from .project import file_stamp
from .paths import ffmpeg


def input_audio(source,track,role,cancel):
    stamp=file_stamp(source)
    if not stamp:raise ValueError('当前素材不存在')
    source_hash=digest(source,cancel)
    if role=='vocals':
        if not bound(track,source) or track.get('source_sha256')!=source_hash:raise ValueError('人声与当前素材不对应，请重新生成人声或切到原声')
        audio=Path(track['path']);audio_hash=digest(audio,cancel)
        if audio_hash!=track['sha256']:raise ValueError('人声内容已变化，请重新准备后检查')
    elif role=='original':audio=Path(source);audio_hash=source_hash
    else:raise ValueError('声音来源无效')
    return audio,stamp,{'source_sha256':source_hash,'audio_sha256':audio_hash,'audio_role':role}


def verify(source,track,binding,cancel):
    audio,stamp,current=input_audio(source,track,binding['audio_role'],cancel)
    if any(current[k]!=binding[k] for k in current):raise ValueError('素材或分析音轨已变化，旧建议保留但未采用')
    return stamp


def generate(lines,source,track,role,home,cancel,progress=lambda value:None,maximum=2000,join_lines=True,indices=None):
    progress('正在核对当前素材和分析音轨指纹…')
    audio,stamp,binding=input_audio(source,track,role,cancel)
    folder=Path(home)/'sound-gap-audio'/binding['audio_sha256'];folder.mkdir(parents=True,exist_ok=True)
    pcm=folder/'audio.s16';metadata=folder/'audio.json';rate=48000;valid=False
    if pcm.is_file() and metadata.is_file():
        try:
            saved=json.loads(metadata.read_text(encoding='utf-8'))
            valid=(saved['audio_sha256']==binding['audio_sha256'] and saved['sample_rate']==rate and
                   pcm.stat().st_size==saved['frames']*2 and digest(pcm,cancel)==saved['pcm_sha256'])
        except (OSError,ValueError,KeyError,TypeError):pass
    if not valid:
        progress('正在本机准备声音；不上传、不调用转录服务…')
        with tempfile.TemporaryDirectory(prefix='pending-',dir=folder) as temp:
            pending=Path(temp)/'audio.s16'
            run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(audio),'-map','0:a:0','-vn','-ac','1','-ar',str(rate),'-f','s16le',str(pending)],cancel)
            if not pending.is_file() or not pending.stat().st_size or pending.stat().st_size%2:raise ValueError('没有生成完整音轨，原时间保留')
            saved={'audio_sha256':binding['audio_sha256'],'sample_rate':rate,'frames':pending.stat().st_size//2,'pcm_sha256':digest(pending,cancel)}
            cancelled(cancel);os.replace(pending,pcm);atomic_json(metadata,saved)
    cancelled(cancel);binding.update(pcm_sha256=saved['pcm_sha256'],sample_rate=rate)
    progress('正在检查声音连续性与已有音素边界…')
    report=analyze(lines,pcm,rate,binding,maximum,join_lines,cancel,progress,indices)
    if digest(pcm,cancel)!=binding['pcm_sha256']:raise ValueError('分析声音缓存在处理期间已变化，原时间保留')
    if file_stamp(source)!=stamp:raise ValueError('分析期间素材已变化，原时间保留')
    verify(source,track,binding,cancel);cancelled(cancel)
    return report
