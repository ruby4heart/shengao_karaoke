"""Reproducible local measurements; synthetic lyrics, private media stays local.

Run with .venv-desktop/Scripts/python.exe. Results are measurements of this
checkout and machine, not standalone startup or a finished-song certification.
"""
from pathlib import Path
import argparse,ctypes,hashlib,json,math,os,platform,sys,time,traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'desktop'),str(ROOT/'backend'),str(ROOT/'scripts')]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt,QPoint,QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.project import Project,History,file_stamp
from shengao.paths import ffmpeg
from shengao.theme import STYLE
from shengao.proxy_video import digest
from studio_backend.model import LyricLine,Unit
from studio_backend.japanese import add_mora
from desktop_source_state import snapshot


def stats(values):
    ordered=sorted(values)
    return {'values_ms':values,'count':len(values),'p95_ms':ordered[max(0,math.ceil(len(values)*.95)-1)] if values else None,'max_ms':max(values) if values else None}


def hardware():
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),*[(name,ctypes.c_ulonglong) for name in ('physical','available_physical','page','available_page','virtual','available_virtual','extended')]]
    memory=Memory();memory.length=ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):raise ctypes.WinError()
    return {'windows':platform.platform(),'cpu':platform.processor(),'logical_processors':os.cpu_count(),'physical_bytes':memory.physical,'available_bytes':memory.available_physical,'python':sys.version,'qt_scale_factor':os.getenv('QT_SCALE_FACTOR','1'),'qt_platform':os.getenv('QT_QPA_PLATFORM'),'threads':{key:os.getenv(key) for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--cache-label',required=True);parser.add_argument('--with-proxy',action='store_true');args=parser.parse_args()
    source=args.source.resolve();out=args.output.resolve()
    if not source.is_file():parser.error('source does not exist')
    out.mkdir(parents=True,exist_ok=False)
    before_sources=snapshot(ROOT)
    report={'completed':False,'passed_measured_targets':False,'scope':'Source checkout, controlled 1000-line lyrics with actual local media; excludes standalone cold/warm startup, human accuracy and acoustic A/V measurement.','spec':'docs/V030-PROXY-PERFORMANCE-SPEC.md','hardware_before':hardware(),'cache_label':args.cache_label,'system_cache_flushed':False,'source_stamp':file_stamp(source),'source_sha256':digest(source),'ffmpeg_sha256':digest(ffmpeg()),'source_snapshot':before_sources,'computer_use':False,'paid_api_calls':0,'measurements':{},'targets':{},'pending':['Standalone cold and warm startup, three fresh processes each','Packaged normal and 150% reproduction','Human finished-song accuracy and acoustic A/V judgement']}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE);w=StudioWindow(out/'home',test=True);w.playback.audio.setMuted(True);w.resize(1280,800);w.show();frames=[];source_opened=None
    def frame_ready(frame):
        if frame.isValid():frames.append({'received_s':time.perf_counter(),'pts_us':frame.startTime(),'end_us':frame.endTime(),'player_ms':w.playback.player.position()})
    w.playback.sink.videoFrameChanged.connect(frame_ready,Qt.ConnectionType.QueuedConnection)
    def wait(fn,seconds=30):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents();QTest.qWait(2)
            if fn():return True
        return False
    def settled():return not w.render_timer.isActive() and not w.refreshing
    def record(name,values,target):
        value=stats(values);value['target_ms']=target;value['passed']=bool(values) and value['p95_ms']<=target
        report['measurements'][name]=value;report['targets'][name]=value['passed'];print(name,json.dumps({k:v for k,v in value.items() if k!='values_ms'}),flush=True)
    try:
        lines=[]
        for index in range(1000):
            start=index*260+50;units=[Unit('明日',start,start+90,'あした'),Unit('も',start+90,start+125,'も'),Unit('歌う',start+125,start+220,'うたう')]
            for unit in units:add_mora(unit)
            lines.append(LyricLine('stress-'+str(index),'明日も歌う',start,start+220,units))
        p=Project(lines=lines);p.style.display_mode='alternating';p.style.show_romaji=False;p.style.show_translation=False
        w.history=History(p);w.current=0;w.refresh();source_opened=time.perf_counter();w.load_media(source,preview=True)
        assert wait(lambda:w.analysis_job is None and not w.playback.preview_pending and not w.playback.canvas.frame.isNull() and bool(frames),90),'source was not ready'
        report['measurements']['first_video_frame_ms']=(frames[0]['received_s']-source_opened)*1000;report['targets']['first_video_frame']=report['measurements']['first_video_frame_ms']<=3000
        w.set_stage(2);w.render_subtitles();assert wait(settled);original=w.project.to_dict()
        report['fixture']={'lines':len(lines),'words':sum(len(v.units) for v in lines),'highlights':sum(len(u.highlights) for v in lines for u in v.units),'window':[w.width(),w.height()],'device_pixel_ratio':w.devicePixelRatioF(),'source_display_size':[w.project.width,w.project.height]}
        values=[]
        for _ in range(50):
            row=w.current+1;began=time.perf_counter();w.move_line(1);assert wait(lambda:w.current==row and w.timeline.line is w.line and settled(),5);values.append((time.perf_counter()-began)*1000)
        record('next_line_50',values,250);assert w.project.to_dict()==original
        values=[]
        for row in range(51,101):
            item=w.lyrics.item(row);w.lyrics.scrollToItem(item);app.processEvents();rect=w.lyrics.visualItemRect(item);assert w.lyrics.viewport().rect().contains(rect.center())
            began=time.perf_counter();QTest.mouseClick(w.lyrics.viewport(),Qt.MouseButton.LeftButton,pos=rect.center());assert wait(lambda:w.current==row and w.timeline.line is w.line and settled(),5);values.append((time.perf_counter()-began)*1000)
        record('list_click_50',values,250);assert w.project.to_dict()==original
        w.timeline.granularity='line';w.timeline.set_line(w.line);w.timeline.span=1000;w.timeline.left=max(0,w.line.start-350);w.timeline.invalidate();w.reveal_center_widget(w.timeline);assert wait(lambda:w.timeline.visibleRegion().boundingRect().height()==w.timeline.height(),5)
        axis=w.timeline;y=round((axis.audio_top+axis.audio_bottom)/2);point=QPoint(round(axis.tx(w.line.start)),y);QTest.mousePress(axis,Qt.MouseButton.LeftButton,pos=point);assert axis.drag
        values=[]
        for index in range(50):
            began=time.perf_counter();QTest.mouseMove(axis,point+QPoint(8 if index%2 else 12,0));app.processEvents();values.append((time.perf_counter()-began)*1000)
        record('axis_drag_move_50',values,50);assert w.project.to_dict()==original
        began=time.perf_counter();QTest.mouseRelease(axis,Qt.MouseButton.LeftButton,pos=point+QPoint(8,0));assert wait(settled,8);commit=(time.perf_counter()-began)*1000
        record('axis_commit_including_render',[commit],250);w.undo();assert wait(settled,8) and w.project.to_dict()==original
        def seeks(label):
            values=[];observations=[]
            for fraction in (.05,.75,.25,.9,.5,.15,.65,.35,.8,.45):
                target=round((w.project.duration-1000)*fraction);count=len(frames);began=time.perf_counter();w.playback.stop();w.playback.seek(target)
                found=wait(lambda:any(v['pts_us']<=target*1000+50000 and max(v['end_us'],v['pts_us']+50000)>=target*1000 for v in frames[count:]),4)
                values.append((time.perf_counter()-began)*1000);observations.append({'target_ms':target,'matched_frame':found,'frames':frames[count:]})
            record(label,values,500);report['measurements'][label]['observations']=observations;report['targets'][label]=report['targets'][label] and all(v['matched_frame'] for v in observations)
        seeks('original_random_seek_10')
        values=[]
        for fraction in (.1,.4,.2,.6,.3,.8,.45,.7,.15,.55):
            start=round((w.project.duration-2000)*fraction);count=len(frames);began=time.perf_counter();assert w.playback.audition(start,start+1000)
            advanced=wait(lambda:start+20<=w.playback.player.position()<start+1000 and any(start*1000<=v['pts_us']<(start+1000)*1000 for v in frames[count:]),4)
            values.append((time.perf_counter()-began)*1000);w.playback.stop();assert advanced,'audition did not advance in the requested range'
        record('original_hot_audition_10',values,500)
        if args.with_proxy:
            beats=[];last=[time.perf_counter()];heartbeat=QTimer(w);heartbeat.setInterval(20)
            def beat():
                now=time.perf_counter();beats.append((now-last[0])*1000);last[0]=now
            heartbeat.timeout.connect(beat);heartbeat.start();save_interval=w.autosave.interval();w.autosave.setInterval(1000);w.autosave.start();began=time.perf_counter();w.prepare_proxy();edits=0;next_edit=time.monotonic()+.3
            while w.proxy_job is not None and time.perf_counter()-began<600:
                app.processEvents();QTest.qWait(5)
                if time.monotonic()>=next_edit:
                    w.move_line(1);edits+=1;next_edit=time.monotonic()+.3
            assert wait(lambda:w.proxy_job is None and w.proxy_active and not w.playback.preview_pending,15),'proxy did not become ready'
            heartbeat.stop();w.autosave.setInterval(save_interval);record('proxy_background_20ms_heartbeat',beats,150)
            report['targets']['proxy_background_max_500']=bool(beats) and max(beats)<=500
            report['measurements']['proxy_generation']={'seconds':time.perf_counter()-began,'ordinary_navigation_count':edits,'verification':w.proxy_base['verification'],'reused':w.proxy_base['reused'],'document_unchanged':w.project.to_dict()==original,'autosave_interval_ms':1000}
            assert edits>0 and w.project.to_dict()==original
            seeks('proxy_random_seek_10')
        else:report['pending'].append('V2 proxy background heartbeat, random seeks and sustained playback')
        report['source_snapshot_unchanged']=snapshot(ROOT)==before_sources;assert report['source_snapshot_unchanged']
        report['completed']=True;report['passed_measured_targets']=all(report['targets'].values())
    except Exception:
        report['error']=traceback.format_exc();raise
    finally:
        report['hardware_after']=hardware();report['source_unchanged']=file_stamp(source)==report['source_stamp'] and digest(source)==report['source_sha256']
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');w.close();app.processEvents()
    return 0 if report['passed_measured_targets'] and report['source_unchanged'] else 1


if __name__=='__main__':raise SystemExit(main())
