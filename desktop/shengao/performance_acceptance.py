"""The same complete editing-pressure measurement in source and frozen apps.

Synthetic lyrics and actual local media stay in the supplied new directory.
This does not certify standalone startup, human accuracy or acoustic A/V.
"""
from pathlib import Path
import argparse,ctypes,hashlib,json,math,os,platform,sys,time,traceback

from .paths import ROOT,RUNTIME
if not getattr(sys,'frozen',False):sys.path.insert(0,str(ROOT/'scripts'))
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
from shengao.process_memory import sample as process_memory
from studio_backend.model import LyricLine,Unit
from studio_backend.japanese import add_mora
from .runtime_integrity import verify_runtime


def source_snapshot():
    from desktop_source_state import snapshot
    return snapshot(ROOT)


def stats(values):
    ordered=sorted(values)
    return {'values_ms':values,'count':len(values),'p95_ms':ordered[max(0,math.ceil(len(values)*.95)-1)] if values else None,'max_ms':max(values) if values else None}


def hardware():
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),*[(name,ctypes.c_ulonglong) for name in ('physical','available_physical','page','available_page','virtual','available_virtual','extended')]]
    memory=Memory();memory.length=ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):raise ctypes.WinError()
    return {'windows':platform.platform(),'cpu':platform.processor(),'logical_processors':os.cpu_count(),'physical_bytes':memory.physical,'available_bytes':memory.available_physical,'process':process_memory(),'python':sys.version,'qt_scale_factor':os.getenv('QT_SCALE_FACTOR','1'),'qt_platform':os.getenv('QT_QPA_PLATFORM'),'threads':{key:os.getenv(key) for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preview-performance-test',action='store_true');parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--cache-label',required=True);parser.add_argument('--with-proxy',action='store_true');parser.add_argument('--native-hidden',action='store_true');args=parser.parse_args()
    if args.native_hidden:os.environ['QT_QPA_PLATFORM']='windows'
    source=args.source.resolve();out=args.output.resolve()
    if not source.is_file():parser.error('source does not exist')
    frozen=bool(getattr(sys,'frozen',False))
    if frozen and out.is_relative_to(RUNTIME.resolve()):parser.error('output must be outside the verified runtime')
    out.mkdir(parents=True,exist_ok=False)
    before_sources=None if frozen else source_snapshot()
    before_runtime=verify_runtime(RUNTIME) if frozen else None
    report={'completed':False,'passed_measured_targets':False,'scope':'Source checkout, controlled 1000-line lyrics with actual local media; excludes standalone cold/warm startup, human accuracy and acoustic A/V measurement.','spec':'docs/V030-PROXY-PERFORMANCE-SPEC.md','hardware_before':hardware(),'cache_label':args.cache_label,'system_cache_flushed':False,'source_stamp':file_stamp(source),'source_sha256':digest(source),'ffmpeg_sha256':digest(ffmpeg()),'source_snapshot':before_sources,'computer_use':False,'paid_api_calls':0,'measurements':{},'targets':{},'pending':['Standalone cold and warm startup, three fresh processes each','Packaged normal and 150% reproduction','Human finished-song accuracy and acoustic A/V judgement']}
    report['native_hidden']=args.native_hidden
    report['frozen']=frozen;report['runtime_integrity_before']=before_runtime
    report['runtime_integrity_read_warms_files']=frozen
    report['scope']=('Frozen executable' if frozen else 'Source checkout')+', '+('native Windows Qt with owned hidden window' if args.native_hidden else 'offscreen Qt')+', controlled 1000-line lyrics and actual local media; excludes standalone startup, human accuracy and acoustic A/V measurement.'
    report['qt_environment']={name:os.getenv(name) for name in ('QT_FFMPEG_EXCLUDE_ENCODERS','QT_FFMPEG_DECODING_HW_DEVICE_TYPES','QT_FFMPEG_ENCODING_HW_DEVICE_TYPES','QSG_RHI_BACKEND','QT_QUICK_BACKEND')}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    from shengao.gui_gc import install
    gc_policy=install(app)
    w=StudioWindow(out/'home',test=True);w.playback.audio.setMuted(True);w.resize(1280,800)
    if args.native_hidden:w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen,True)
    w.show();frames=[];source_opened=None
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
    def presented(sequence,target):
        canvas=w.playback.canvas;start=canvas.painted_frame_start_us;end=canvas.painted_frame_end_us
        return canvas.painted_sequence>sequence and start is not None and start>=0 and start<=target*1000+50000 and max(end or start,start+50000)>=target*1000
    def record(name,values,target,*,maximum=False,expected_count=None):
        value=stats(values);value['target_ms']=target;value['target_statistic']='max' if maximum else 'p95'
        value['passed']=bool(values) and value['max_ms' if maximum else 'p95_ms']<=target and (expected_count is None or len(values)==expected_count)
        report['measurements'][name]=value;report['targets'][name]=value['passed']
        if sys.stdout is not None:print(name,json.dumps({k:v for k,v in value.items() if k!='values_ms'}),flush=True)
    try:
        lines=[]
        for index in range(1000):
            start=index*260+50;units=[Unit('明日',start,start+90,'あした'),Unit('も',start+90,start+125,'も'),Unit('歌う',start+125,start+220,'うたう')]
            for unit in units:add_mora(unit)
            lines.append(LyricLine('stress-'+str(index),'明日も歌う',start,start+220,units))
        p=Project(lines=lines);p.style.display_mode='alternating';p.style.show_romaji=False;p.style.show_translation=False
        w.history=History(p);w.current=0;w.refresh();source_opened=time.perf_counter();w.load_media(source,preview=True)
        assert wait(lambda:w.analysis_job is None and not w.playback.preview_pending and not w.playback.canvas.frame.isNull() and w.playback.canvas.painted_at_s is not None and bool(frames),90),'source was not ready'
        report['measurements']['first_video_frame_ms']=(frames[0]['received_s']-source_opened)*1000;report['targets']['first_video_frame']=report['measurements']['first_video_frame_ms']<=3000
        report['measurements']['first_painted_frame_ms']=(w.playback.canvas.first_painted_at_s-source_opened)*1000;report['targets']['first_painted_frame']=report['measurements']['first_painted_frame_ms']<=3000
        w.set_stage(2);w.render_subtitles();assert wait(settled);original=w.project.to_dict()
        report['fixture']={'lines':len(lines),'words':sum(len(v.units) for v in lines),'highlights':sum(len(u.highlights) for v in lines for u in v.units),'window':[w.width(),w.height()],'device_pixel_ratio':w.devicePixelRatioF(),'source_display_size':[w.project.width,w.project.height],'snapshot_accelerator':w.snapshot_accelerator}
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
        # Consecutive genuine commits retain their undo steps; the memory
        # guard records a failure before this diagnostic can exhaust the host.
        memory_before=process_memory();memory_samples=[];commits=[];steps=len(w.history.undo_stack);budget=256*1024*1024
        for index in range(50):
            axis.span=1000;axis.left=max(0,w.line.start-350);axis.invalidate();app.processEvents()
            point=QPoint(round(axis.tx(w.line.start)),y);destination=point+QPoint(8 if index%2==0 else -8,0)
            began=time.perf_counter();QTest.mousePress(axis,Qt.MouseButton.LeftButton,pos=point);QTest.mouseMove(axis,destination);QTest.mouseRelease(axis,Qt.MouseButton.LeftButton,pos=destination);assert wait(settled,8)
            commits.append((time.perf_counter()-began)*1000);assert len(w.history.undo_stack)==steps+index+1,'gesture did not create exactly one undo step'
            memory_samples.append(process_memory())
            if memory_samples[-1]['private_bytes']-memory_before['private_bytes']>budget:break
        record('axis_commit_repeat_50',commits,250,maximum=True,expected_count=50)
        report['measurements']['history_memory']={'before':memory_before,'after_each_commit':memory_samples,'private_growth_budget_bytes':budget,'completed_commits':len(commits)}
        report['targets']['history_private_growth_256mib']=all(v['private_bytes']-memory_before['private_bytes']<=budget for v in memory_samples)
        changed=w.project.to_dict();undo_times=[];redo_times=[];history_memory=[]
        for _ in commits:
            began=time.perf_counter();w.undo();assert wait(settled,8);undo_times.append((time.perf_counter()-began)*1000);history_memory.append(process_memory())
        assert len(w.history.undo_stack)==steps and w.project.to_dict()==original
        for _ in commits:
            began=time.perf_counter();w.redo();assert wait(settled,8);redo_times.append((time.perf_counter()-began)*1000);history_memory.append(process_memory())
        assert w.project.to_dict()==changed
        for _ in commits:w.undo();assert wait(settled,8)
        assert w.project.to_dict()==original
        report['measurements']['undo_repeat']=stats(undo_times);report['measurements']['redo_repeat']=stats(redo_times);report['measurements']['history_memory']['after_undo_redo']=process_memory()
        report['measurements']['history_memory']['during_undo_redo']=history_memory
        report['targets']['history_private_growth_256mib']=report['targets']['history_private_growth_256mib'] and all(v['private_bytes']-memory_before['private_bytes']<=budget for v in history_memory)
        # Video checks observe actual paint completion in a visible canvas,
        # independently of the decoder callback retained for diagnosis.
        w.view_choice.setCurrentIndex(2);w.reveal_center_widget(w.playback)
        assert wait(lambda:w.playback.visibleRegion().boundingRect().height()==w.playback.height(),5)
        def seeks(label):
            values=[];observations=[]
            for fraction in (.05,.75,.25,.9,.5,.15,.65,.35,.8,.45):
                target=round((w.project.duration-1000)*fraction);count=len(frames);sequence=w.playback.canvas.painted_sequence;began=time.perf_counter();w.playback.stop();w.playback.seek(target)
                found=wait(lambda:presented(sequence,target),4)
                values.append((time.perf_counter()-began)*1000);observations.append({'target_ms':target,'matched_painted_frame':found,'painted_start_us':w.playback.canvas.painted_frame_start_us,'painted_end_us':w.playback.canvas.painted_frame_end_us,'decoder_frames':frames[count:]})
            record(label,values,500);report['measurements'][label]['observations']=observations;report['targets'][label]=report['targets'][label] and all(v['matched_painted_frame'] for v in observations)
        seeks('original_random_seek_10')
        values=[]
        for fraction in (.1,.4,.2,.6,.3,.8,.45,.7,.15,.55):
            start=round((w.project.duration-2000)*fraction);sequence=w.playback.canvas.painted_sequence;began=time.perf_counter();assert w.playback.audition(start,start+1000)
            advanced=wait(lambda:start+20<=w.playback.player.position()<start+1000 and w.playback.canvas.painted_sequence>sequence and w.playback.canvas.painted_frame_start_us is not None and start*1000<=w.playback.canvas.painted_frame_start_us<(start+1000)*1000,4)
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
        if frozen:
            after_runtime=verify_runtime(RUNTIME);report['runtime_integrity_after']=after_runtime
            report['runtime_snapshot_unchanged']=after_runtime==before_runtime;assert report['runtime_snapshot_unchanged']
            report['source_snapshot_unchanged']=None
        else:
            report['source_snapshot_unchanged']=source_snapshot()==before_sources;assert report['source_snapshot_unchanged']
        report['completed']=True;report['passed_measured_targets']=all(report['targets'].values())
    except Exception:
        report['error']=traceback.format_exc();raise
    finally:
        report['gui_gc']=gc_policy.report() if gc_policy is not None else None
        from .checkpoint_encoding import status as checkpoint_status
        report['checkpoint_encoder']=checkpoint_status()
        report['video_frame_scaler']=w.playback.canvas.frame_scaler_status()
        report['hardware_after']=hardware();report['source_unchanged']=file_stamp(source)==report['source_stamp'] and digest(source)==report['source_sha256']
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');w.close();app.processEvents()
        if gc_policy is not None:gc_policy.close()
    return 0 if report['passed_measured_targets'] and report['source_unchanged'] else 1


if __name__=='__main__':raise SystemExit(main())
