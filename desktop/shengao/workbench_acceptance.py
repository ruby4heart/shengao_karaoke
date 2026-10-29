"""Same real Qt workbench checks in source and frozen processes, offline."""
from pathlib import Path
import json,subprocess
from PySide6.QtCore import Qt,QPoint,QEvent
from PySide6.QtGui import QInputMethodEvent,QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialogButtonBox
from PySide6.QtMultimedia import QMediaPlayer
from studio_backend.model import LyricLine,Unit,Highlight
from .project import Project,History
from .paths import ffmpeg,ASSETS
from .audio_shortcuts import Profile,import_preview
from .audio_shortcut_dialog import AudioShortcutDialog,ImportReview
from .preview_preferences import PreviewPreferencesDialog


def exercise(app,StudioWindow,out,check,wait):
    out=Path(out);w=StudioWindow(out/'workbench-home',test=True);w.playback.audio.setMuted(True);w.resize(1280,800);w.show();dialogs=[];metrics={}
    source=out/'workbench-synthetic.mp4'
    result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i','color=c=0x173344:s=640x360:r=25:d=8',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=8','-c:v','h264_mf','-hw_encoding','0','-b:v','1M','-pix_fmt','nv12','-c:a','aac',str(source)],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    def profile(*,protect=True):
        data=w.audio_profile.to_data();data['contexts']['Audio']['audio/play/line']=['F9'];data.update(medusa=True,protect_text=protect);return Profile.from_data(data)
    def fill(d):
        for _,_,h in d.draft.notes:d.draft.add(h.start+10);d.draft.add(h.end)
        d.allow_manual.setChecked(True);d.render()
    try:
        check('workbench_controlled_source_created',result.returncode==0 and source.is_file())
        lines=[LyricLine('workbench-a','あいう',1000,3500,[Unit('あいう',1000,3500,'あいう','aiu',highlights=[Highlight('あ',1000,1700),Highlight('い',1800,2500),Highlight('う',2700,3500)])],reviewed=True),
               LyricLine('workbench-b','えお',4500,6500,[Unit('えお',4500,6500,'えお','eo',highlights=[Highlight('え',4500,5400),Highlight('お',5500,6500)])],reviewed=True)]
        w.history=History(Project(title='工作台受控练习',lines=lines,checks={line.id:{'reading':True} for line in lines}));w.current=0;w.refresh();w.load_media(source,preview=True)
        check('workbench_actual_player_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None and not w.playback.preview_pending and w.playback.pending_seek is None and w.playback.player.duration()>0,25000))
        w.set_stage(0);w.refresh();before=w.project.to_dict();w.prepare_next.click()
        check('workbench_confirmed_lyrics_continue_to_style',w.stage==3 and w.project.to_dict()==before)
        w.set_stage(4);check('workbench_visiting_export_does_not_finish_output',not w.steps[4].complete)
        w.set_stage(0);check('workbench_return_keeps_correct_next_step',w.prepare_next.text()=='检查字幕样式 →' and w.prepare_next.text()==w.next_button.text())
        w.set_stage(2);old_profile=w.audio_profile.to_data();w.adopt_audio_profile(profile())
        actions=[];original_action=w.audio_action;w.timeline.action.disconnect(original_action);w.timeline.action.connect(actions.append);w.audio_action=actions.append
        try:
            w.timeline.setFocus();QTest.keyClick(w.timeline,Qt.Key.Key_F9);QTest.keyClick(w.timeline,Qt.Key.Key_R)
            check('workbench_custom_audio_key_replaces_default',actions==['line']);actions.clear()
            w.calibration_tabs.setCurrentIndex(1);w.translation.setFocus();QTest.keyClick(w.translation,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier)
            check('workbench_medusa_text_input_protected',not actions)
            w.adopt_audio_profile(profile(protect=False));QTest.keyClick(w.translation,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier)
            check('workbench_explicit_original_always_mode',actions==['selection']);actions.clear()
            QApplication.sendEvent(w.translation,QInputMethodEvent('かな',[]));QTest.keyClick(w.translation,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier)
            commit=QInputMethodEvent();commit.setCommitString('かな');QApplication.sendEvent(w.translation,commit)
            QApplication.sendEvent(w.translation,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Enter,Qt.KeyboardModifier.KeypadModifier))
            check('workbench_ime_and_ending_enter_do_not_submit',not actions)
            QApplication.sendEvent(w.translation,QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_Enter,Qt.KeyboardModifier.KeypadModifier))
        finally:
            w.timeline.action.disconnect(actions.append);w.audio_action=original_action;w.timeline.action.connect(original_action)
        # The simulated IME intentionally edits only a text widget: discard its
        # pending text before continuing a different test case.
        w.refresh();w.adopt_audio_profile(Profile.from_data(old_profile));w.calibration_tabs.setCurrentIndex(0)
        d=AudioShortcutDialog(w.audio_profile,w.reserved_audio_shortcuts(),w.adopt_audio_profile,w);dialogs.append(d);d.resize(560,480);d.show();app.processEvents()
        point=d.save_button.mapTo(d,QPoint(0,0));check('workbench_shortcut_save_reachable',d.rect().contains(point+d.save_button.rect().bottomRight()))
        d.set_binding('Audio','audio/play/line',['F9']);d.set_binding('Audio','audio/play/selection',['F9'])
        check('workbench_conflict_blocks_save',not d.save_button.isEnabled())
        d.resize(820,720);app.processEvents();d.grab().save(str(out/'workbench-shortcut-conflict.png'));d.reject()
        aeg=import_preview(json.loads((ASSETS/'compatibility/aeg-3.5.0-default-hotkeys.json').read_text(encoding='utf-8')),w.audio_profile)
        review=ImportReview(aeg,w);dialogs.append(review);ok=review.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        check('workbench_original_import_requires_ack',aeg.needs_acknowledgement and not ok.isEnabled());review.acknowledge.setChecked(True)
        check('workbench_ack_loads_supported_keys_only',ok.isEnabled() and bool(aeg.to_draft(acknowledge_unsupported=True)));review.reject()
        key_path=out/'audio-shortcuts.json';d=AudioShortcutDialog(w.audio_profile,w.reserved_audio_shortcuts(),w.adopt_audio_profile,w);dialogs.append(d);d.export_file(key_path)
        check('workbench_export_has_no_service_settings',set(json.loads(key_path.read_text(encoding='utf-8')))=={'application','version','medusa','protect_text','contexts'})
        settings=PreviewPreferencesDialog(w);dialogs.append(settings);settings.gpu.setChecked(False);settings.workers.setCurrentIndex(1);project_before=w.project.to_dict();settings.apply()
        check('workbench_optional_preview_preserves_project',not w.playback.canvas.gpu_enabled and w.local_worker_limit==1 and w.project.to_dict()==project_before)
        reopened=StudioWindow(w.home,test=True)
        try:check('workbench_local_preferences_survive_restart',not reopened.playback.canvas.gpu_enabled and reopened.local_worker_limit==1 and reopened.audio_profile.to_data()==old_profile)
        finally:reopened.close();app.processEvents()
        w.adopt_preview_preferences(True,0)
        settings=PreviewPreferencesDialog(w);dialogs.append(settings);settings.resize(400,340);settings.show();app.processEvents();settings.grab().save(str(out/'workbench-preview-settings.png'));settings.reject()
        before=w.project.to_dict();d=w.open_tap_timing();dialogs.append(d);d.start()
        check('workbench_tap_actual_playback_started',wait(lambda:d.recording and w.playback.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState and w.playback.canvas.position>=w.line.start+30,6000))
        QTest.keyClick(d.capture,Qt.Key.Key_Space);check('workbench_tap_records_current_source_clock',len(d.draft.points)==1 and w.line.start<=d.draft.points[0]<w.line.end)
        d.pause();points=list(d.draft.points);QTest.keyClick(d.capture,Qt.Key.Key_Space);check('workbench_tap_paused_keeps_draft',d.draft.points==points and not d.recording)
        d.start();check('workbench_tap_resumes_same_player',wait(lambda:d.recording and w.playback.canvas.position>=points[-1]+50,4000))
        QTest.keyClick(d.capture,Qt.Key.Key_Space);w.playback.seek(w.line.start)
        check('workbench_external_seek_stops_recording',not d.recording and len(d.draft.points)==2 and w.playback.temporary_owner is None)
        d.reject();check('workbench_tap_cancel_keeps_project',w.project.to_dict()==before)
        d=w.open_tap_timing();dialogs.append(d);fill(d);d.resize(500,460);app.processEvents();point=d.apply_button.mapTo(d,QPoint(0,0))
        check('workbench_tap_apply_reachable',d.rect().contains(point+d.apply_button.rect().bottomRight()))
        d.resize(700,650);app.processEvents();d.grab().save(str(out/'workbench-tap-comparison.png'))
        steps=len(w.history.undo_stack);d.apply();check('workbench_tap_apply_one_transaction',d.applied and len(w.history.undo_stack)==steps+1 and not w.line.reviewed and w.project.checks==before['checks'])
        w.undo();check('workbench_tap_one_undo_restores_all',w.project.to_dict()==before)
        d=w.open_tap_timing();dialogs.append(d);fill(d);points=list(d.draft.points);w.edit('受控迟到修改',lambda p:setattr(p.lines[0],'translation','后来的文字'))
        changed=w.project.to_dict();d.apply();check('workbench_tap_late_edit_never_overwrites',d.stale and not d.applied and d.draft.points==points and w.project.to_dict()==changed);d.reject();w.undo()
        metrics={'dpr':w.devicePixelRatioF(),'computer_use':False,'paid_api_calls':0,'performance_workload':False,'source':'controlled synthetic media','real_player_exercised':True,'audio_output_latency_certified':False}
        return metrics
    finally:
        for dialog in dialogs:dialog.reject()
        w.close();app.processEvents();(out/'workbench-metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
