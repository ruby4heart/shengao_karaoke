"""Real new controls in dev and frozen processes, with synthetic media only."""
import copy,hashlib,json,subprocess,sys,types
from pathlib import Path
from PySide6.QtCore import QTimer,QPoint,Qt,QThreadPool
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from studio_backend.model import LyricLine,Unit
from studio_backend.japanese import add_mora
from .project import Project,History,SCHEMA,file_stamp,save_project,load_project
from .paths import ASSETS,ffmpeg
from .style_workflow import StyleWorkbenchDialog
from .presentation import display_windows
from .line_layout import make_setting
from .color_states import update_settings,preset_profile
from .subtitles import compose
from .subtitle_files import export_subtitle
from .render import AssRenderer
from .encode import encode,EncodeOptions
from . import proxy_video


def exercise(app,StudioWindow,out,check,wait):
    out=Path(out);metrics={};seen={};passed=False;w=StudioWindow(out/'style-preview-home',test=True);w.playback.audio.setMuted(True);w.resize(1280,800);w.show()
    source=out/'style-preview-synthetic-1080.mp4'
    result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i','color=c=0x142238:s=1920x1080:r=25:d=8',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=8','-c:v','h264_mf','-hw_encoding','0','-b:v','3M','-pix_fmt','nv12','-c:a','aac',str(source)],capture_output=True,timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
    def schedule(fn):
        def invoke():
            d=QApplication.activeModalWidget()
            try:fn(d)
            except Exception as error:
                seen['error']=repr(error)
                if d is not None:d.reject()
        QTimer.singleShot(20,invoke)
    def without_display(value):
        value=copy.deepcopy(value)
        for line in value['lines']:line.pop('display_start',None);line.pop('display_end',None)
        return value
    def point(r,row,time):return QPoint(round(r.x_at(time)),round(r.row_rect(row).center().y()))
    try:
        check('style_preview_actual_synthetic_source_created',result.returncode==0 and source.is_file())
        lines=[LyricLine('style-a','明日も歌おう',1000,4000,[Unit('明日',1000,2100,'あした'),Unit('も',2100,2400,'も'),Unit('歌おう',2400,4000,'うたおう')],reviewed=True),
               LyricLine('style-b','光の中へ',5000,7000,[Unit('光',5000,5700,'ひかり'),Unit('の',5700,6000,'の'),Unit('中へ',6000,7000,'なかへ')],reviewed=True)]
        for line in lines:
            for unit in line.units:
                add_mora(unit)
                for h in unit.highlights:h.source='manual'
        p=Project(title='受控练习：样式与轻量预览',lines=lines,checks={v.id:{'reading':True} for v in lines});p.style=w.preset_style(2);p.color_styles=update_settings({},preset_profile(p.style,'ruby'))
        w.history=History(p);w.current=1;w.refresh();w.load_media(source,preview=True)
        check('style_preview_actual_1080_video_wave_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None and not w.playback.preview_pending and not w.playback.canvas.frame.isNull(),25000) and w.project.width==1920)
        w.set_stage(3);w.open_display_ribbon();w.timeline.left=0;w.timeline.span=8000;w.timeline.invalidate();w.reveal_center_widget(w.display_ribbon)
        check('display_ribbon_same_scale_and_reachable',wait(lambda:w.display_ribbon.visibleRegion().boundingRect().height()==w.display_ribbon.height(),3000) and w.display_ribbon.width()==w.timeline.width())
        before=w.project.to_dict();steps=len(w.history.undo_stack);r=w.display_ribbon;start=display_windows(w.project)[1].start;a=point(r,1,start);b=point(r,1,start-300)
        QTest.mousePress(r,Qt.MouseButton.LeftButton,pos=a);QTest.mouseMove(r,b);app.processEvents()
        check('display_ribbon_real_drag_is_private_preview',bool(r.drag) and w.project.to_dict()==before)
        QTest.mouseRelease(r,Qt.MouseButton.LeftButton,pos=b);app.processEvents()
        check('display_ribbon_real_release_keeps_singing_and_checks',w.line.display_start<start and w.line.display_end is None and len(w.history.undo_stack)==steps+1 and without_display(w.project.to_dict())==without_display(before))
        w.undo();check('display_ribbon_real_drag_one_undo',w.project.to_dict()==before)
        r=w.display_ribbon;a=point(r,1,start);b=point(r,1,start-300);QTest.mousePress(r,Qt.MouseButton.LeftButton,pos=a);QTest.mouseMove(r,b);QTest.keyClick(w,Qt.Key.Key_Escape);QTest.mouseRelease(r,Qt.MouseButton.LeftButton,pos=b)
        check('display_ribbon_global_escape_cancels_commit',r.drag is None and w.project.to_dict()==before)
        w.set_stage(3);w.playback.seek(6000);position=w.playback.canvas.position;seen.clear()
        def choose(d):
            assert isinstance(d,StyleWorkbenchDialog);d.cards[2].click();d.local_fields['size_percent'].setValue(85);d.local_fields['ruby_percent'].setValue(90)
            item=next(d.breaks.item(i) for i in range(d.breaks.count()) if d.breaks.item(i).data(Qt.ItemDataRole.UserRole)==2);item.setCheckState(Qt.CheckState.Checked);d.render_preview()
            seen['private']=w.project.to_dict()==before and w.playback.canvas.position==position;seen['images']=all(not card.icon().isNull() for card in d.cards) and not d.detail.pixmap().isNull()
            for width,height in [(900,800),(640,600)]:
                d.resize(width,height);app.processEvents();d.scroll.ensureWidgetVisible(d.breaks);app.processEvents();metrics.setdefault('dialog_geometry',[]).append({'size':[width,height],'horizontal_overflow':d.scroll.horizontalScrollBar().maximum(),'footer_inside':d.rect().contains(d.buttons.geometry())});d.grab().save(str(out/f'style-workbench-{width}.png'))
            d.scroll.verticalScrollBar().setValue(0);d.accept()
        schedule(choose);adopted=w.edit_style_workbench()
        check('font_workbench_actual_frame_four_cards_private',seen.get('private') and seen.get('images') and not seen.get('error'))
        check('font_workbench_small_windows_footer_reachable',all(v['horizontal_overflow']==0 and v['footer_inside'] for v in metrics['dialog_geometry']))
        check('font_and_line_layout_real_controls_one_edit',adopted and w.project.style.font=='Noto Serif CJK JP Black' and w.project.layout_styles['style-b']==make_setting(w.line,85,90,[2]) and len(w.history.undo_stack)==steps+1)
        check('line_layout_original_axis_readings_colors_checks_preserved',[v.to_dict() for v in w.project.lines]==before['lines'] and w.project.color_styles==before['color_styles'] and w.project.checks==before['checks'])
        saved=out/'受控本句外观.sgproj';ass=out/'受控本句外观.ass';save_project(w.project,saved);export_subtitle(w.project,ass)
        check('layout_schema14_project_and_own_ass_reopen',SCHEMA==14 and load_project(saved).layout_styles==w.project.layout_styles and compose(load_project(saved))==compose(w.project)==compose(load_project(ass)))
        renderer=AssRenderer()
        try:
            equal=True
            for when in (1000,2500,4000,6000,7000):
                renderer.set_text(compose(w.project));full=renderer.rgba(640,360,when);renderer.set_text(compose(w.project,preview_time=when));equal=equal and full==renderer.rgba(640,360,when)
            check('style_private_filter_exact_native_pixels',equal)
        finally:renderer.close()
        manifest=json.loads((ASSETS/'compatibility/project-v029-source.json').read_text());raw=(ASSETS/'compatibility/project-v029.py.txt').read_bytes()
        check('schema14_actual_v029_parser_fingerprint',manifest['commit']=='34f4ef435705d71d4309e2091c5b7ff5dba102db' and hashlib.sha256(raw).hexdigest()==manifest['sha256']=='2e0038535b2bbc9f96ae27d108e8086f4de97ddc55a88eed332741371cbb5939')
        module=types.ModuleType('shengao._style_v029_project');module.__package__='shengao';sys.modules[module.__name__]=module
        try:
            exec(compile(raw,'actual-v029-project.py','exec'),module.__dict__);old=module.Project.from_dict({'version':13,'lines':[]});rejected=False
            try:module.Project.from_dict(w.project.to_dict())
            except ValueError:rejected=True
            check('schema14_actual_v029_reader_accepts13_rejects14',module.SCHEMA==13 and old.to_dict()['version']==13 and rejected)
        finally:sys.modules.pop(module.__name__,None)
        changed=w.project.to_dict();w.undo();check('font_and_layout_one_undo_restores_whole_project',w.project.to_dict()==before);w.redo();check('font_and_layout_redo_restores_draft',w.project.to_dict()==changed)
        w.set_stage(0);w.pages.widget(0).ensureWidgetVisible(w.proxy_buttons[0]);app.processEvents();w.playback.set_zoom(.5);w.playback.seek(1800);proxy_before=w.project.to_dict();count=len(w.history.undo_stack)
        QTest.mouseClick(w.proxy_buttons[0],Qt.MouseButton.LeftButton,pos=QPoint(12,w.proxy_buttons[0].height()//2))
        check('proxy_actual_button_starts_without_document_edit',w.proxy_job is not None and w.project.to_dict()==proxy_before)
        w.edit('代理期间人工译文',lambda p:setattr(p.lines[1],'translation','受控人工修改'));w.playback.seek(2400)
        check('proxy_actual_worker_returns_verified_video',wait(lambda:w.proxy_job is None and w.proxy_active and not w.playback.preview_pending,25000))
        metrics['proxy_verification']=w.proxy_base['verification'];metrics['proxy_reused']=w.proxy_base['reused']
        check('proxy_keeps_latest_edits_and_original_source',w.line.translation=='受控人工修改' and w.project.media==proxy_before['media'] and len(w.history.undo_stack)==count+1 and w.project.checks==proxy_before['checks'])
        check('proxy_clock_zoom_and_original_dimensions_preserved',w.playback.canvas.position==2400 and w.playback.zoom==.5 and w.playback.source_size.width()==1920 and w.playback.canvas.frame.width()==1280)
        w.grab().save(str(out/'proxy-preview-workspace.png'))
        output=out/'style-proxy-original-sample.mp4';encoded=encode(w.project,EncodeOptions(str(output),start=6000,duration=400))
        check('proxy_active_encode_uses_original_source',encoded['media']==w.project.media and Path(encoded['media'])!=Path(w.proxy_display_path) and output.is_file())
        original=w.project.to_dict();check('proxy_original_choice_works',w.use_original_preview() and wait(lambda:not w.playback.preview_pending) and Path(w.playback.player.source().toLocalFile())==source and w.project.to_dict()==original)
        # Generated tone stands for an already available audition artifact.
        # No claim that a model separated these controlled samples.
        from vocal_engine import MODEL_SHA256,ENGINE_VERSION
        voice=out/'proxy-controlled-vocal.wav';result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i','sine=frequency=880:duration=8:sample_rate=44100','-ac','2','-c:a','pcm_f32le',str(voice)],capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        check('proxy_controlled_audition_fixture_created',result.returncode==0)
        track={'path':str(voice),'source_path':w.project.media,'source_stamp':file_stamp(w.project.media),'source_sha256':proxy_video.digest(w.project.media),'sha256':proxy_video.digest(voice),'frames':8*44100,'sample_rate':44100,'model_sha256':MODEL_SHA256,'engine':ENGINE_VERSION}
        w.edit('受控试听资源',lambda p:setattr(p,'vocal_track',track));w.select_vocal_audition('vocals')
        check('proxy_existing_human_audition_ready',wait(lambda:w.audition_role=='vocals' and w.source_job is None and not w.playback.preview_pending,25000))
        before_mix=w.project.to_dict();w.prepare_proxy()
        check('proxy_human_mix_verified_and_selected',wait(lambda:w.proxy_active and w.proxy_job is None and not w.playback.preview_pending,25000) and w.audition_role=='vocals' and proxy_video.audio_digest(w.proxy_display_path)==proxy_video.audio_digest(voice) and w.project.to_dict()==before_mix)
        voice_source=w._proxy_vocal_path;w.vocal_play_error('受控代理失败')
        check('proxy_play_error_preserves_human_audition',wait(lambda:not w.playback.preview_pending) and not w.proxy_active and w.audition_role=='vocals' and Path(w.playback.player.source().toLocalFile())==Path(voice_source) and w.project.to_dict()==before_mix)
        w.prepare_proxy();work=w.proxy_job;w.cancel_task();check('proxy_cancel_controls_keep_existing_audition',work.cancel.is_set() and w.proxy_job is None and not w.proxy_active and w.project.to_dict()==before_mix)
        check('proxy_cancel_worker_releases_process',wait(lambda:QThreadPool.globalInstance().activeThreadCount()==0,15000))
        from .workspace_acceptance import exercise_stable_timing
        def unconfirmed(project):
            project.checks={}
            for line in project.lines:line.reviewed=False
        w.edit('受控待校对状态',unconfirmed)
        metrics['stable_timing_workspace']=exercise_stable_timing(app,w,check)
        passed=True
    finally:
        (out/'style-preview-audit.json').write_text(json.dumps({'passed':passed,'metrics':metrics,'scope':'Actual controls, synthetic 1080p media, display-only layout, native pixels, schema14 source-parser compatibility, verified proxy and controlled audition artifact; no human reference or clean Windows certification.','computer_use':False,'paid_api_calls':0},ensure_ascii=False,indent=2),encoding='utf-8')
        w.close();w.deleteLater();app.processEvents()
