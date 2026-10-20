"""Bounded visible-range rendering over a one-hour synthetic PCM cache."""
from pathlib import Path
import argparse
import ctypes as C
import hashlib
import json
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'desktop'),str(ROOT/'backend')]
from shengao.audio_render import AudioRenderer,milliseconds_per_pixel
from shengao.paths import RUNTIME
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
out=args.output.resolve();assert out.is_relative_to(ROOT) and out!=ROOT;out.mkdir(parents=True,exist_ok=True)
class Memory(C.Structure):
    _fields_=[('cb',C.c_ulong),('PageFaultCount',C.c_ulong)]+[(n,C.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
def memory():
    value=Memory();value.cb=C.sizeof(value)
    psapi=C.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[C.c_void_p,C.POINTER(Memory),C.c_ulong]
    assert psapi.GetProcessMemoryInfo(C.c_void_p(-1),C.byref(value),value.cb)
    return {'working_set':value.WorkingSetSize,'private_commit':value.PagefileUsage}
rate=48000;count=rate*3600;path=out/'one-hour.s16'
with path.open('wb') as stream:stream.seek(count*2-1);stream.write(b'\0')
samples=np.memmap(path,dtype=np.int16,mode='r+')
tone=(np.sin(np.arange(rate*2)/rate*2*np.pi*440)*16000).astype(np.int16)
for second in [0,300,600,900,1200,1500,1800,2100,2400,2700,3000,3598]:samples[second*rate:second*rate+len(tone)]=tone
samples.flush();samples._mmap.close();before=memory();renderer=AudioRenderer(path,rate);timings=[];peak=before
try:
    for index in range(90):
        mode=index%3;level=[0,10,20][index%3];pp=milliseconds_per_pixel(level)
        left=[0,300,600,900,1200,1500,1800,2100,2400,2700,3000,3598][index%12]*1000
        styles=np.full(900,index%4,np.uint8);started=time.perf_counter()
        pixels=renderer.rgb(int(left/pp),900,220,pp,1.,mode,1,index%5,styles)
        timings.append((time.perf_counter()-started)*1000);assert pixels.shape==(220,900,3)
        now=memory();peak={k:max(peak[k],now[k]) for k in now}
finally:renderer.close();path.unlink()
record={'passed':len(timings)==90,'duration_seconds':3600,'sample_rate':rate,'pcm_bytes':count*2,'renders':len(timings),'median_ms':float(np.median(timings)),'p95_ms':float(np.percentile(timings,95)),'memory_before':before,'memory_peak':peak,'native_spectrum_cache_limit_bytes':128*1024*1024,'engine_sha256':hashlib.sha256((RUNTIME/'shengao-audio.dll').read_bytes()).hexdigest(),'note':'Synthetic one-hour disk PCM; only visible ranges rendered; temporary PCM removed. Working set includes file-backed memory mapping.'}
(out/'report.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record))
