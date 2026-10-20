"""Measure a real local song without editing it or sending it to a service."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import threading
import time

root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root/'desktop'),str(root/'backend')]
from shengao import vocal_audio as vocal,media
from shengao.paths import ffmpeg
from shengao.project import file_stamp
parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
source=Path(args.input).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
before=file_stamp(source);original_sha=vocal.digest(source);cancel=threading.Event();started=time.monotonic()
track=vocal.generate(source,out/'home',cancel,lambda x:print(x,flush=True));generation_seconds=round(time.monotonic()-started,3)
original=media.analyze(source,out/'home/wave-cache',cancel)
prepared=vocal.prepare(track,source,out/'home',cancel,lambda x:print(x,flush=True),original)
assert int(original['duration'])==round(track['frames']*1000/track['sample_rate'])
assert int(prepared['audio']['duration'])==int(original['duration'])
for name,path in [('original',source),('vocals',track['path'])]:
    subprocess.run([ffmpeg(),'-v','error','-nostdin','-y','-ss','45','-i',str(path),'-t','15','-vn','-ac','2','-c:a','pcm_s16le',str(out/(name+'-45s-60s.wav'))],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
assert file_stamp(source)==before and vocal.digest(source)==original_sha
record={'passed':True,'original_unchanged':True,'source':str(source),'source_sha256':original_sha,'duration_ms':int(original['duration']),'track':track,'preview':prepared['path'],'generation_seconds':generation_seconds,'external_api_calls':0,'quality':'Real inference and sample/time-base checks; no human lyric/mora accuracy reference was used.'}
(out/'report.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=True),flush=True)
