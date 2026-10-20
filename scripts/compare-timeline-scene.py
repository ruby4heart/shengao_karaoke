"""Full Qt timeline pixels vs original offscreen drawing + original audio.

Run twice, normally and with QT_SCALE_FACTOR=1.5. Requires both test-only
reference DLLs. All input is synthetic; no user media or desktop is touched.
The scene adapter is shared; original drawing bodies are hash audited.
"""
from pathlib import Path
import argparse
import json
import os
import sys
import hashlib
from desktop_source_state import snapshot

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'desktop'),str(ROOT/'backend'),str(ROOT/'desktop'/'tests')]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PIL import Image
from shengao.timeline import Timeline
from shengao.timeline_view import TimelineRenderer
from shengao.project import load_project
from shengao.timing import set_time
from test_aeg_audio import reference

parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
out=args.output.resolve();assert out.is_relative_to(ROOT) and out!=ROOT
out.mkdir(parents=True,exist_ok=True)
ref=TimelineRenderer(ROOT/'build/desktop-reference/shengao-view-reference.dll')
app=QApplication([]);rate=48000;time=np.arange(rate*12,dtype=np.float64)/rate
rng=np.random.default_rng(731)
samples=np.clip((np.sin(time*2*np.pi*223)*.3+np.sin(time*2*np.pi*1723)*.18+rng.normal(0,.07,len(time)))*32768,-32768,32767).astype(np.int16)
pcm=out/'synthetic.s16';samples.tofile(pcm)
project=load_project(ROOT/'demo/tutorial.json');project.lines[0]=set_time(project.lines[0],-1,1010,6010)
records=[]
source_before=snapshot(ROOT)
try:
    for index,(mode,level,quality,curve,gain) in enumerate([(1,0,1,0,1.),(0,10,1,0,1.),(2,3,1,0,1.),(1,20,3,2,1.5),(1,-5,0,4,.6),(1,35,5,3,2.)]):
        t=Timeline();t.resize(900,280);t.set_line(project.lines[0]);t.word=1;t.show_spectrum=mode==1;t.waveform_averages=mode==2;t.quality=quality;t.curve=curve;t.amplitude=gain
        t.set_audio({'pcm':str(pcm),'sample_rate':rate,'duration':12000,'peaks':np.ones(12),'keyframes':[2000,4000]});t.set_zoom(level);t.left=round(300/(t.pixel_ms/t.devicePixelRatioF()))*(t.pixel_ms/t.devicePixelRatioF());t.hover=2455
        t.show();app.processEvents();t.render_audio();scene,markers,labels=t.scene();height=scene.height-ref.top(scene.dpr)-15
        body=reference(samples,rate,scene.start_pixel,scene.width,height,scene.pixel_ms,gain,mode,quality,curve,0)
        for a,b,style in [(t.line.start,t.line.end,2),(scene.selection_start,scene.selection_end,3)]:
            original=reference(samples,rate,scene.start_pixel,scene.width,height,scene.pixel_ms,gain,mode,quality,curve,style)
            left=max(0,min(scene.width,int(a/scene.pixel_ms)-scene.start_pixel));right=max(0,min(scene.width,int(b/scene.pixel_ms)-scene.start_pixel))
            body[:,left:right]=original[:,left:right]
        expected=ref.rgb(scene,body,markers,labels)
        img=t.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
        actual=np.frombuffer(img.constBits(),np.uint8).reshape(img.height(),img.bytesPerLine())[:,:img.width()*3].reshape(img.height(),img.width(),3).copy()
        assert actual.shape==expected.shape
        diff=np.any(actual!=expected,axis=2);prefix=out/f'case-{index+1}'
        Image.fromarray(actual).save(str(prefix)+'-shengao.png');Image.fromarray(expected).save(str(prefix)+'-aeg-original.png')
        record={'case':index+1,'mode':mode,'zoom':level,'dpr':scene.dpr,'pixels':int(diff.size),'different_pixels':int(diff.sum()),'pass':not bool(diff.any())};records.append(record)
        t.audio.close();t.audio=None;t.close();app.processEvents()
finally:
    (out/'report.json').write_text(json.dumps({'passed':bool(records) and len(records)==6 and all(r['pass'] for r in records) and snapshot(ROOT)==source_before,'sources':source_before,'scope':'Original drawing bodies + original audio; shared plain scene adapter. Does not certify every Aegisub interaction.','cases':records},indent=2),encoding='utf-8')
assert len(records)==6 and all(r['pass'] for r in records),out
print(json.dumps({'passed':True,'cases':len(records),'output':str(out)}))
