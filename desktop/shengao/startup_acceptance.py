"""Owned hidden startup readiness, timed from the external launcher clock."""
from pathlib import Path
import argparse,json,os,sys,time,traceback


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--startup-readiness-test',action='store_true')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--home',type=Path,required=True)
    parser.add_argument('--launch-start',type=float,required=True);parser.add_argument('--cache-label',required=True)
    parser.add_argument('--startup-limit-ms',type=int,choices=(10000,20000),required=True)
    args=parser.parse_args();entered=time.perf_counter()
    if not 0<args.launch_start<=entered:parser.error('launch clock must come from the external monotonic launcher')
    from .paths import ROOT,RUNTIME
    frozen=bool(getattr(sys,'frozen',False));out=args.output.resolve()
    if frozen and out.is_relative_to(RUNTIME.resolve()):parser.error('output must be outside the runtime')
    out.mkdir(parents=True,exist_ok=False);os.environ['QT_QPA_PLATFORM']='windows'
    report={'completed':False,'passed':False,'scope':__doc__,'frozen':frozen,'cache_label':args.cache_label,
            'system_cache_flushed':False,'home':str(args.home.resolve()),'limit_ms':args.startup_limit_ms,
            'launch_start':args.launch_start,'entered_main_ms':(entered-args.launch_start)*1000,
            'computer_use':False,'paid_api_calls':0,'errors':[],
            'pending':['OS cold-cache certification and clean Windows','Full media/editing pressure and finished-song accuracy']}
    app=w=policy=None;before=None;manifest_before=None
    try:
        from .proxy_video import digest
        if frozen:manifest_before=digest(RUNTIME/'package-manifest.json')
        else:
            sys.path.insert(0,str(ROOT/'scripts'));from desktop_source_state import snapshot
            before=snapshot(ROOT);report['source_snapshot']=before
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from PySide6.QtTest import QTest
        from .app import StudioWindow
        from .gui_gc import install
        from .theme import STYLE
        app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE);policy=install(app)
        w=StudioWindow(args.home,test=True);w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen,True);w.show()
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            app.processEvents();QTest.qWait(2)
            if w.isVisible() and not w.refreshing and not w.workflow_toggle.visibleRegion().isEmpty():break
        else:raise RuntimeError('Complete window was not ready for an input event')
        image=w.grab();assert not image.isNull(),'Window did not paint'
        original=w.project.to_dict();button=w.workflow_toggle;initial=button.isChecked()
        QTest.mouseClick(button,Qt.MouseButton.LeftButton,pos=button.rect().center());app.processEvents()
        interactive=button.isChecked()!=initial
        QTest.mouseClick(button,Qt.MouseButton.LeftButton,pos=button.rect().center());app.processEvents()
        assert interactive and button.isChecked()==initial and w.project.to_dict()==original,'Window input did not complete and restore its state'
        ready=time.perf_counter();duration=(ready-args.launch_start)*1000
        report.update({'window_ready_ms':duration,'painted_window_size':[image.width(),image.height()],
                       'device_pixel_ratio':w.devicePixelRatioF(),'interaction_verified':True,
                       'project_unchanged':True,'ready_monotonic':ready,'completed':True,
                       'passed':duration<=args.startup_limit_ms})
        from .performance_acceptance import hardware
        report['hardware_after']=hardware()
    except Exception:report['errors'].append(traceback.format_exc())
    finally:
        # Integrity I/O is after the measured readiness point. The launcher
        # also audits the complete runtime before and after the whole series.
        try:
            if frozen:
                from .runtime_integrity import verify_runtime
                integrity=verify_runtime(RUNTIME);report['runtime_integrity_after']=integrity
                report['package_manifest_unchanged']=integrity['manifest_sha256']==manifest_before
                if not report['package_manifest_unchanged']:report['errors'].append('Package manifest changed')
                report['source_snapshot_unchanged']=None
            elif before is not None:
                report['source_snapshot_unchanged']=snapshot(ROOT)==before
                if not report['source_snapshot_unchanged']:report['errors'].append('Source snapshot changed')
        except Exception:report['errors'].append(traceback.format_exc())
        try:
            if w is not None:w.close();app.processEvents()
            if policy is not None:report['gui_gc']=policy.report();policy.close()
        except Exception:report['errors'].append(traceback.format_exc())
        report['passed']=bool(report['completed'] and report['passed'] and not report['errors'])
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1
