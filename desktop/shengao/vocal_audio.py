"""Cancelable local stem cache and single-player, sample-aligned A/B previews."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile
import time
from .paths import ROOT,RUNTIME,ffmpeg
from .project import file_stamp
from . import media
from vocal_engine import MODEL_SHA256,ENGINE_VERSION

def digest(path,cancel=None):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data:=stream.read(2*1024*1024):
            cancelled(cancel);h.update(data)
    return h.hexdigest()

def cancelled(cancel):
    if cancel is not None and cancel.is_set():raise ValueError('已取消人声任务，原素材与字幕保留。')

def valid_track(value):
    import re
    if not isinstance(value,dict):raise ValueError('人声辅助音轨记录无效')
    if not value:return
    for name in ('path','source_path','engine'):
        if not isinstance(value.get(name),str) or not value[name]:raise ValueError('人声辅助音轨路径或引擎无效')
    for name in ('sha256','source_sha256','model_sha256'):
        if not isinstance(value.get(name),str) or not re.fullmatch('[0-9a-f]{64}',value[name]):raise ValueError('人声辅助音轨指纹无效')
    if not isinstance(value.get('source_stamp'),dict):raise ValueError('人声辅助原素材记录无效')
    for name in ('frames','sample_rate'):
        if type(value.get(name)) is not int or value[name]<=0:raise ValueError('人声辅助音轨长度无效')

def bound(track,source):
    return bool(track and Path(track['path']).is_file() and track['source_stamp']==file_stamp(source))

def engine_command():
    executable=RUNTIME/'vocal-engine'/'shengao-vocals.exe'
    if executable.is_file():return [str(executable)]
    import sys
    if not getattr(sys,'frozen',False):
        executable=ROOT/'.venv-vocals'/'Scripts'/'python.exe'
        if executable.is_file():return [str(executable),str(ROOT/'desktop'/'vocal_engine.py')]
    raise ValueError('缺少本地人声引擎，请完整解压运行包。')

def model_path():
    for path in [RUNTIME/'vocal-engine'/'955717e8-8726e21a.th',ROOT/'vendor'/'vocal-model'/'955717e8-8726e21a.th']:
        if path.is_file():return path
    raise ValueError('缺少已校验的人声模型，请完整解压运行包。')

def run(command,cancel,progress=lambda x:None,engine=False,kind='vocals',event=None):
    # Independent read/write handles: seeking a duplicated stdout handle can
    # otherwise rewind the child's file pointer and overwrite an unread event.
    with tempfile.TemporaryDirectory(prefix='shengao-engine-log-') as temp, (Path(temp)/'worker.log').open('wb') as writer, (Path(temp)/'worker.log').open('rb') as log:
        child_job=None;command=[str(x) for x in command]
        if engine and os.name=='nt':
            from .process_tree import ProcessTree
            child_job=ProcessTree();command+=['--owner-job',child_job.name]
        try:process=subprocess.Popen(command,stdout=writer,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        except BaseException:
            if child_job:child_job.close()
            raise
        position=0;buffer=b'';started=time.monotonic();reported=0
        def drain(final=False):
            nonlocal position,buffer,reported
            if engine:
                    # The worker reports completed inference segments, rather
                    # than manufacturing a timer-based percentage.
                    log.seek(position);buffer+=log.read();position=log.tell()
                    lines=buffer.split(b'\n');buffer=lines.pop()
                    if final and buffer:lines.append(buffer);buffer=b''
                    for line in lines:
                        try:value=json.loads(line)
                        except (ValueError,UnicodeDecodeError):continue
                        if event:event(value)
                        if value.get('stage')=='separate':progress(f'分离人声 {value["completed"]}/{value["total"]} 段 · 已用 {time.monotonic()-started:.0f} 秒')
                        elif value.get('stage')=='align':progress(f'歌声音节对齐 {value["completed"]}/{value["total"]} 段 · 已用 {time.monotonic()-started:.0f} 秒')
                        elif value.get('stage')=='model':progress('正在载入本地歌声对齐模型…' if kind=='alignment' else '正在载入本地人声模型…')
                    reported=time.monotonic()
        try:
            while process.poll() is None:
                if engine and time.monotonic()-reported>.1:drain()
                cancelled(cancel)
                try:process.wait(timeout=.1)
                except subprocess.TimeoutExpired:pass
            drain(final=True)
            cancelled(cancel)
            if process.returncode:
                log.seek(0);message=log.read().decode('utf-8',errors='replace')[-1600:]
                raise ValueError(('歌声对齐失败：' if kind=='alignment' else '人声处理失败：')+message)
        finally:
            try:
                if child_job:child_job.terminate();child_job.wait_empty()
            finally:
                if child_job:child_job.close()
                if process.poll() is None:process.kill();process.wait()
                drain(final=True)

def generate(source,home,cancel,progress=lambda x:None):
    source=str(Path(source).resolve());stamp=file_stamp(source)
    if not stamp:raise ValueError('原素材不存在')
    progress('正在核对素材与可复用的人声缓存…');fingerprint=digest(source,cancel)
    folder=Path(home)/'vocal-cache'/(fingerprint+'-'+ENGINE_VERSION);folder.mkdir(parents=True,exist_ok=True)
    # Separate application instances cannot write the same cache concurrently.
    import msvcrt
    with (folder/'lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as error:raise ValueError('另一个声稿窗口正在为此素材分离人声，请稍后复用结果。') from error
        try:
            ready=folder/'ready.json';target=folder/'vocals.wav'
            if ready.is_file() and target.is_file():
                try:
                    info=json.loads(ready.read_text(encoding='utf-8'));valid_track(info)
                    if info['source_sha256']==fingerprint and info['model_sha256']==MODEL_SHA256 and info['engine']==ENGINE_VERSION and digest(target,cancel)==info['sha256']:
                        progress('正在复用已完成人声，无需重新分离。')
                        info.update(source_path=source,source_stamp=stamp);return info
                except (ValueError,KeyError,OSError):pass
            with tempfile.TemporaryDirectory(prefix='pending-',dir=folder) as work:
                work=Path(work);raw=work/'input.f32';output=work/'vocals.f32';report=work/'report.json';wav=work/'vocals.wav'
                progress('正在提取原声；不会上传素材。')
                run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',source,'-vn','-ac','2','-ar','44100','-f','f32le',raw],cancel)
                frames=raw.stat().st_size//8
                if frames<=0 or raw.stat().st_size%8:raise ValueError('素材没有完整音轨')
                run(engine_command()+['--model',str(model_path()),'--input',str(raw),'--output',str(output),'--report',str(report)],cancel,progress,engine=True)
                result=json.loads(report.read_text(encoding='utf-8'))
                if result['frames']!=frames or result['sample_rate']!=44100 or output.stat().st_size!=frames*8 or result['model_sha256']!=MODEL_SHA256:raise ValueError('人声输出的时间基准不一致，尚未采用。')
                progress('正在保存无损人声缓存…')
                run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-f','f32le','-ar','44100','-ac','2','-i',output,'-c:a','pcm_f32le',wav],cancel)
                if file_stamp(source)!=stamp:raise ValueError('处理期间原素材已变化，结果未采用。')
                info={k:result[k] for k in ('engine','frames','sample_rate','model_sha256')}
                info.update(path=str(target),source_path=source,source_stamp=stamp,source_sha256=fingerprint,sha256=digest(wav,cancel))
                cancelled(cancel);os.replace(wav,target)
                from studio_backend.settings import atomic_json
                atomic_json(ready,info);return info
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def prepare(track,source,home,cancel,progress=lambda x:None,source_audio=None):
    valid_track(track)
    if track.get('engine')!=ENGINE_VERSION or track.get('model_sha256')!=MODEL_SHA256:raise ValueError('人声引擎版本变化，请重新生成人声。')
    if not bound(track,source):raise ValueError('人声对应的原素材或缓存已变化，请先为当前源生成人声。')
    if digest(source,cancel)!=track['source_sha256']:raise ValueError('原素材内容已变化，不能复用旧人声。')
    if digest(track['path'],cancel)!=track['sha256']:raise ValueError('人声文件已变化，请重新生成；当前源保留。')
    progress('正在准备人声频谱与同步预览…')
    result=media.analyze(track['path'],Path(home)/'wave-cache',cancel,progress)
    if abs(int(result['duration'])-round(track['frames']*1000/track['sample_rate']))>1:raise ValueError('人声缓存长度不一致')
    has_video=media.has_video(source)
    if not has_video:return {'path':track['path'],'audio':result}
    folder=Path(home)/'vocal-previews';folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(json.dumps([file_stamp(source),track['sha256']],sort_keys=True).encode()).hexdigest()
    target=folder/(key+'.mkv')
    result['keyframes']=source_audio['keyframes'] if source_audio is not None else media.keyframes(source,cancel)
    ready=target.with_suffix('.json')
    if target.is_file() and ready.is_file():
        try:
            saved=json.loads(ready.read_text(encoding='utf-8'))
            if digest(target,cancel)==saved['sha256']:return {'path':str(target),'audio':result}
        except (OSError,ValueError,KeyError):pass
    fd,name=tempfile.mkstemp(suffix='.mkv',dir=folder);os.close(fd);temp=Path(name)
    try:
        run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',source,'-i',track['path'],'-map','0:v:0','-map','1:a:0','-c','copy',temp],cancel)
        cancelled(cancel)
        if not bound(track,source):raise ValueError('准备期间素材变化，尚未切换试听。')
        os.replace(temp,target)
        from studio_backend.settings import atomic_json
        atomic_json(ready,{'sha256':digest(target,cancel)})
        return {'path':str(target),'audio':result}
    finally:temp.unlink(missing_ok=True)
