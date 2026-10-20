"""Cancelable PCM cache; native Aegisub-derived code renders visible audio only."""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import tempfile
import time
import numpy as np
from .paths import ffmpeg

def video_stream(log):
    return next((line for line in log.splitlines() if 'Stream #' in line and 'Video:' in line and 'attached pic' not in line.lower()),'')

def has_video(path):
    result=subprocess.run([ffmpeg(),'-hide_banner','-nostdin','-i',str(path)],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    return bool(video_stream(result.stderr.decode('utf-8',errors='replace')))

def original_rate(path,rate,cancel=None):
    """Aegisub SampleDoublingAudioProvider: linear S16 doubling below 32kHz.

    Source: libaegisub/audio/provider_convert.cpp (ISC). Even samples are
    unchanged; odd samples average their two neighbours, truncating toward
    zero. The final neighbour is zero padding. Work stays bounded in memory.
    """
    path=Path(path)
    while rate<32000:
        fd,name=tempfile.mkstemp(prefix=path.stem+'.rate.',suffix='.s16.tmp',dir=path.parent);os.close(fd);temp=Path(name)
        samples=np.memmap(path,dtype='<i2',mode='r')
        try:
            with temp.open('wb') as output:
                for start in range(0,len(samples),262144):
                    if cancel is not None and cancel.is_set():raise ValueError('已取消音频分析')
                    stop=min(len(samples),start+262144);source=np.asarray(samples[start:stop],np.int32)
                    following=np.empty(len(source),np.int32)
                    if len(source)>1:following[:-1]=source[1:]
                    following[-1]=int(samples[stop]) if stop<len(samples) else 0
                    values=np.empty(len(source)*2,np.int16);values[::2]=source;values[1::2]=np.trunc((source+following)/2).astype(np.int16)
                    output.write(values.tobytes())
            samples._mmap.close();os.replace(temp,path);rate*=2
        finally:
            if samples._mmap is not None and not samples._mmap.closed:samples._mmap.close()
            temp.unlink(missing_ok=True)
    return rate

def keyframes(path,cancel=None):
    command=[ffmpeg(),'-hide_banner','-nostdin','-skip_frame','nokey','-i',str(path),
             '-map','0:v:0','-vf','showinfo','-an','-sn','-fps_mode','passthrough','-f','null','-']
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=errors,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while process.poll() is None:
                if cancel is not None and cancel.is_set():process.kill();process.wait();raise ValueError('已取消关键帧分析')
                try:process.wait(timeout=.1)
                except subprocess.TimeoutExpired:pass
            errors.seek(0);text=errors.read().decode('utf-8',errors='replace')
            if process.returncode:return []
            return sorted(set(round(float(x)*1000) for x in re.findall(r'pts_time:([0-9.+eE-]+)',text)))
        finally:
            if process.poll() is None:process.kill();process.wait()

def analyze(path,cache,cancel=None,progress=lambda x:None):
    path=Path(path);stat=path.stat()
    def stable():
        current=path.stat()
        return (current.st_size,current.st_mtime_ns)==(stat.st_size,stat.st_mtime_ns)
    def fingerprint(value):
        if cancel is not None and cancel.is_set():raise ValueError('已取消音频分析')
        result=hashlib.sha256()
        with Path(value).open('rb') as stream:
            while data:=stream.read(2*1024*1024):
                if cancel is not None and cancel.is_set():raise ValueError('已取消音频分析')
                result.update(data)
        return result.hexdigest()
    progress('正在核对素材内容与音频缓存…');source_hash=fingerprint(path)
    signature=hashlib.sha256(f'{path.resolve()}:{source_hash}:aeg-pcm-keyframes-v7'.encode()).hexdigest()
    target=Path(cache)/(signature+'.npz');target.parent.mkdir(parents=True,exist_ok=True);pcm=target.with_suffix('.s16')
    if target.exists() and pcm.exists() and pcm.stat().st_size:
        try:
            with np.load(target,allow_pickle=False) as saved:
                data={k:saved[k] for k in saved.files}
            if (all(k in data for k in ('sample_rate','duration','peaks','keyframes','width','height','fps','has_video','frames','pcm_sha256','source_sha256')) and
                    str(data['source_sha256'])==source_hash and int(data['frames'])*2==pcm.stat().st_size and fingerprint(pcm)==str(data['pcm_sha256'])):
                if not stable() or fingerprint(path)!=source_hash:raise ValueError('素材在读取缓存期间已变化，请重新载入')
                return {**data,'pcm':str(pcm)}
        except (ValueError,OSError,EOFError,TypeError):pass
    if cancel is not None and cancel.is_set():raise ValueError('已取消音频分析')
    command=[ffmpeg(),'-hide_banner','-nostdin','-nostats','-i',str(path),'-vn','-ac','1','-f','s16le','pipe:1']
    fd,name=tempfile.mkstemp(prefix=signature+'.',suffix='.s16.tmp',dir=pcm.parent);os.close(fd);staging=Path(name)
    fd,name=tempfile.mkstemp(prefix=signature+'.',suffix='.npz',dir=pcm.parent);os.close(fd);metadata=Path(name)
    def cancelled():return cancel is not None and cancel.is_set()
    try:
        with tempfile.TemporaryFile() as errors,staging.open('wb') as raw:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,creationflags=subprocess.CREATE_NO_WINDOW)
            peaks=[];carry=np.empty(0,np.int16);count=0;reported=0.
            try:
                while True:
                    if cancelled():raise ValueError('已取消音频分析')
                    data=process.stdout.read(32768)
                    if not data:break
                    raw.write(data);samples=np.frombuffer(data,dtype='<i2');count+=len(samples)
                    carry=np.concatenate((carry,samples));cells=len(carry)//4096
                    if cells:
                        blocks=carry[:cells*4096].astype(np.int32).reshape(cells,4096)
                        peaks.extend((np.max(np.abs(blocks),axis=1)/32768).tolist());carry=carry[cells*4096:]
                    if time.monotonic()-reported>.15:progress(count*2);reported=time.monotonic()
                code=process.wait();errors.seek(0);log=errors.read().decode('utf-8',errors='replace')
                if code:raise ValueError('无法读取音轨，请检查媒体是否有声音：'+log[-500:])
                if carry.size:peaks.append(float(np.max(np.abs(carry.astype(np.int32)))/32768))
                if not count:raise ValueError('媒体没有可用的音频样本')
            finally:
                if process.poll() is None:process.kill();process.wait()
                process.stdout.close()
        rate_match=re.search(r'Audio:.*? (\d+) Hz',log);rate=int(rate_match[1]) if rate_match else 48000
        if rate<32000:
            progress('正在对齐原版低采样率音频');rate=original_rate(staging,rate,cancel);count=staging.stat().st_size//2
        video=video_stream(log);size=re.search(r'Video:.*? (\d{2,5})x(\d{2,5})(?:[ ,\[])',video);fps=re.search(r'(\d+(?:\.\d+)?) fps',video)
        result={'peaks':np.asarray(peaks,np.float32),'spectrum':np.empty((96,0),np.uint8),
                'duration':np.array(round(count*1000/rate)),'sample_rate':np.array(rate),
                'width':np.array(int(size[1]) if size else 1920),'height':np.array(int(size[2]) if size else 1080),
                'fps':np.array(float(fps[1]) if fps else 25),'has_video':np.array(bool(video))}
        result.update(source_sha256=np.array(source_hash),pcm_sha256=np.array(fingerprint(staging)),frames=np.array(count))
        progress('正在索引视频关键帧' if size else '音频分析完成')
        result['keyframes']=np.asarray(keyframes(path,cancel) if size else [],np.int64)
        if cancelled():raise ValueError('已取消音频分析')
        if not stable() or fingerprint(path)!=source_hash:raise ValueError('素材在分析期间已变化，请重新载入；原文件保持')
        np.savez_compressed(metadata,**result)
        os.replace(staging,pcm);os.replace(metadata,target)
        return {**result,'pcm':str(pcm)}
    finally:
        staging.unlink(missing_ok=True);metadata.unlink(missing_ok=True)
