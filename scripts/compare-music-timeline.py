"""Private real-music pixel parity against original Aegisub drawing bodies.

Outputs include user audio and screenshots: keep the entire output directory
local. Signal-selected windows do not certify vocal/lyric meaning or timing.
The reference uses original drawing bodies with a shared plain scene adapter;
this verifies pixels, not every Aegisub input/controller behavior.
"""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'desktop'),str(ROOT/'backend'),str(ROOT/'desktop/tests')]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PIL import Image
from shengao.paths import ffmpeg,RUNTIME
from shengao.timeline import Timeline
from shengao.timeline_view import TimelineRenderer
from shengao.project import load_project
from shengao.tail_model import shift_line
from test_aeg_audio import reference
from desktop_source_state import snapshot


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(2*1024*1024),b''):value.update(block)
    return value.hexdigest()


def windows(samples,rate):
    step=rate//5
    energy=np.array([np.sqrt(np.mean(np.asarray(samples[n:n+step],np.float64)**2)) for n in range(0,len(samples),step)])
    valid=np.arange(min(150,len(energy)//4),max(min(150,len(energy)//4)+1,len(energy)-30))
    fall=np.maximum(0,energy[:-1]-energy[1:])
    return [('opening',min(5,max(0,len(samples)/rate-6))),
            ('higher_energy',float(valid[np.argmax(energy[valid])])*.2),
            ('lower_energy',float(valid[np.argmin(energy[valid])])*.2),
            ('energy_fall',float(valid[np.argmax(fall[valid])])*.2),
            ('middle',max(0,len(samples)/rate/2-2))]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--media',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=args.media.resolve();out=args.output.resolve()
    assert source.is_file() and out.is_relative_to(ROOT/'build') and not out.exists()
    out.mkdir(parents=True);(out/'.private-user-media').write_text('Do not publish audio or screenshots.\n',encoding='utf-8')
    source_hash=sha(source);pcm=out/'private-music.s16';before=snapshot(ROOT);rate=48000
    command=[ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-threads','2','-i',str(source),'-vn','-sn','-dn','-ac','1','-ar',str(rate),'-f','s16le',str(pcm)]
    subprocess.run(command,check=True,capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    assert sha(source)==source_hash
    samples=np.memmap(pcm,dtype='<i2',mode='r');assert len(samples)>rate*12
    app=QApplication.instance() or QApplication([]);ref_path=ROOT/'build/desktop-reference/shengao-view-reference.dll';ref=TimelineRenderer(ref_path)
    project=load_project(ROOT/'demo/tutorial.json');records=[]
    try:
        for name,second in windows(samples,rate):
            base=round(max(0,min(second-1,len(samples)/rate-6))*1000)
            for mode,level,gain,quality,curve in [(1,0,1.,1,0),(0,10,1.5,1,0),(2,-5,.6,2,2)]:
                timeline=Timeline();timeline.resize(900,280)
                try:
                    line=shift_line(project.lines[0],base+500-project.lines[0].start);timeline.set_line(line);timeline.word=1
                    timeline.show_spectrum=mode==1;timeline.waveform_averages=mode==2;timeline.quality=quality;timeline.curve=curve;timeline.amplitude=gain
                    timeline.set_audio({'pcm':str(pcm),'sample_rate':rate,'duration':len(samples)*1000//rate,'peaks':np.ones(12),'keyframes':[base+2000,base+4000]})
                    timeline.set_zoom(level);pixel_ms=timeline.pixel_ms/timeline.devicePixelRatioF();timeline.left=round(base/pixel_ms)*pixel_ms;timeline.hover=base+2455
                    timeline.show();app.processEvents();timeline.render_audio();scene,markers,labels=timeline.scene();height=scene.height-ref.top(scene.dpr)-15
                    body=reference(samples,rate,scene.start_pixel,scene.width,height,scene.pixel_ms,gain,mode,quality,curve,0)
                    for a,b,style in [(line.start,line.end,2),(scene.selection_start,scene.selection_end,3)]:
                        original=reference(samples,rate,scene.start_pixel,scene.width,height,scene.pixel_ms,gain,mode,quality,curve,style)
                        left=max(0,min(scene.width,int(a/scene.pixel_ms)-scene.start_pixel));right=max(0,min(scene.width,int(b/scene.pixel_ms)-scene.start_pixel));body[:,left:right]=original[:,left:right]
                    expected=ref.rgb(scene,body,markers,labels);image=timeline.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
                    actual=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*3].reshape(image.height(),image.width(),3).copy()
                    assert actual.shape==expected.shape
                    different=np.any(actual!=expected,axis=2);prefix=out/f'{name}-mode-{mode}'
                    Image.fromarray(actual).save(str(prefix)+'-shengao.png');Image.fromarray(expected).save(str(prefix)+'-aeg.png')
                    records.append({'window':name,'start_ms':base,'mode':mode,'zoom':level,'gain':gain,'quality':quality,'curve':curve,'dpr':scene.dpr,'pixels':int(different.size),'different_pixels':int(different.sum()),'passed':not bool(different.any())})
                finally:
                    if timeline.audio is not None:timeline.audio.close();timeline.audio=None
                    timeline.close();app.processEvents()
    finally:
        unchanged=snapshot(ROOT)==before and sha(source)==source_hash
        record={'passed':len(records)==15 and all(r['passed'] for r in records) and unchanged,'private_user_media':True,'source_sha256':source_hash,'pcm_sha256':sha(pcm),'rate':rate,
                'reference_view_sha256':sha(ref_path),'reference_audio_sha256':sha(ROOT/'build/desktop-reference/shengao-reference.dll'),
                'application_view_sha256':sha(RUNTIME/'shengao-view.dll'),'application_audio_sha256':sha(RUNTIME/'shengao-audio.dll'),
                'sources':before,'source_unchanged':unchanged,'cases':records,'computer_use':False,'paid_api_calls':0,'performance_workload':False,
                'limits':'Signal-selected real music windows, not semantic vocal/weak-tail identification, manual lyric accuracy, or all input gestures. Shared plain scene adapter.'}
        (out/'report.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');samples._mmap.close()
    print(json.dumps({'passed':record['passed'],'cases':len(records),'different_pixels':sum(r['different_pixels'] for r in records),'private_user_media':True}),flush=True)
    if not record['passed']:raise SystemExit(1)


if __name__=='__main__':main()
