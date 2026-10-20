"""Own offscreen Qt acceptance instance; never controls the user's desktop."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');parser.add_argument('--output',required=True)
    args=parser.parse_args();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtMultimedia import QMediaPlayer
    from .app import StudioWindow
    from .theme import STYLE
    from .paths import ROOT
    from .timing import set_time
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    window=StudioWindow(home=out/'home',test=True);window.playback.audio.setMuted(True);window.show()
    checks=[]
    def check(name,condition):
        checks.append({'name':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    def wait(fn,timeout=10000):
        deadline=time.monotonic()+timeout/1000
        while time.monotonic()<deadline:
            app.processEvents();QTest.qWait(25)
            if fn():return True
        return False
    try:
        app.processEvents();check('independent_qt_window',window.metaObject().className()=='StudioWindow')
        check('initial_guidance','添加' in window.next_hint.text());window.grab().save(str(out/'first-use.png'))
        check('workflow_collapsed_by_default',not window.navigation_panel.isVisible() and not window.workflow_toggle.isChecked())
        # Own offline project exercises the entire resumable route in both the
        # development and frozen process, without modifying tutorial timings.
        import copy
        from .project import Project,History,load_project
        from .draft_workflow import DraftDialog,ResumeDraftDialog
        from studio_backend import draft
        from PySide6.QtWidgets import QDialogButtonBox
        practice=Project();practice.replace_lyrics('今日も歌う\n明日も歌う')
        window.history=History(practice);window.current=0;window.refresh();window.set_stage(1)
        original_draft=window.project.to_dict();draft_ui={}
        def start_offline_draft():
            d=next((d for d in window.findChildren(DraftDialog) if d.isVisible()),None)
            if d:
                draft_ui['offline']=d.options()=={'source':'offline','provider':'elevenlabs','readings':'dictionary','align':False}
                d.grab().save(str(out/'draft-workflow-options.png'));d.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(30,start_offline_draft);window.draft_button.click()
        check('staged_draft_defaults_do_not_upload',draft_ui.get('offline'))
        check('staged_draft_starts_without_changing_original',window.api.busy and window.project.to_dict()==original_draft)
        check('staged_draft_worker_returns_reviewable_result',wait(lambda:not window.api.busy and window.pending is not None,15000))
        staged=window.pending['result'];workflow_id=staged['workflow']['id']
        check('staged_draft_records_all_six_stages',[s['state'] for s in staged['workflow']['stages']]==['skipped','completed','completed','skipped','skipped','completed'])
        check('staged_draft_preserves_original_and_requires_review',window.project.to_dict()==original_draft and not staged['partial'])
        app.processEvents();window.grab().save(str(out/'draft-workflow-completed.png'))
        window.apply_suggestions(staged['suggestions'])
        check('staged_draft_generates_editable_estimated_mora',all(line.units and all(u.highlights for u in line.units) and not line.reviewed for line in window.project.lines))
        window.undo();check('staged_draft_adoption_one_undo',window.project.to_dict()==original_draft)
        window.path=out/'分阶段初稿.sgproj';check('staged_draft_original_project_saves',window.save())
        window.history=History(load_project(window.path));window.current=0;window.pending=None;window.refresh()
        def continue_saved_draft():
            d=next((d for d in window.findChildren(ResumeDraftDialog) if d.isVisible()),None)
            if d:
                d.grab().save(str(out/'draft-workflow-resume.png'));d.continue_button.click()
        QTimer.singleShot(30,continue_saved_draft);window.resume_draft()
        check('staged_draft_reopen_reuses_completed_steps',wait(lambda:not window.api.busy and window.pending is not None,15000) and window.pending['result']['workflow']['id']==workflow_id)
        window.edit('验收期间人工修改',lambda p:setattr(p.lines[0],'translation','保留人工译文'))
        window.apply_suggestions(window.pending['result']['suggestions'])
        check('staged_draft_protects_late_manual_edit',window.project.lines[0].translation=='保留人工译文' and window.pending is not None)
        paused=copy.deepcopy(draft.load(window.home,workflow_id));paused['status']='paused';paused['stages'][2].update(state='failed',paid=True);paused['message']='模拟联网阶段未返回，已完成步骤保留。'
        d=ResumeDraftDialog(window,paused);d.show();app.processEvents();d.grab().save(str(out/'draft-workflow-paused.png'))
        check('staged_draft_unknown_paid_request_needs_explicit_retry',not d.continue_button.isEnabled() and d.review_button.isEnabled())
        d.retry.click();check('staged_draft_retry_is_user_controlled',d.continue_button.isEnabled());d.reject()
        window.pending=None;window.history=History(Project());window.current=-1;window.path=None;window.refresh();window.save_recovery()
        window.open_demo();check('demo_original',window.line.text=='今日も歌う')
        check('demo_audio_and_wave',wait(lambda:window.analysis_job is None and window.timeline.peaks is not None))
        check('real_media_loaded',wait(lambda:window.playback.player.duration()>0))
        window.playback.seek(1200);window.playback.player.play()
        check('playback_advances',wait(lambda:window.playback.player.position()>1500,5000));window.playback.stop()
        check('real_video_frame_received',not window.playback.canvas.frame.isNull())
        window.playback.player.setPlaybackRate(.75)
        check('slow_keeps_pitch',window.playback.player.pitchCompensation())
        window.playback.player.setPlaybackRate(1)
        # A video-only project uses a stored synthetic recognition response;
        # wording review and the subsequent worker are entirely local.
        from .recognition_workflow import RecognitionChoiceDialog,RecognitionDialog
        from .project import file_stamp
        from studio_backend.model import LyricLine,Unit
        from studio_backend import recognition
        import hashlib
        saved_project=window.project.to_dict();saved_path=window.path;saved_current=window.current;saved_position=window.playback.canvas.position
        video_only=Project.from_dict(saved_project);video_only.lines=[];video_only.checks={}
        text='今日 も 歌う';raw_text=[LyricLine('synthetic-recognition',text,1000,2400,[Unit(char,1000+i*200,1200+i*200,source='recognition') for i,char in enumerate(text)]).to_dict()]
        video_only.transcript=copy.deepcopy(raw_text);video_only.transcript_stamp=file_stamp(video_only.media)
        video_only.transcript_fingerprint=hashlib.sha256(Path(video_only.media).read_bytes()).hexdigest();video_only.recognition_draft={}
        window.history=History(video_only);window.path=None;window.current=-1;window.refresh();window.set_stage(1);app.processEvents()
        check('video_only_has_recognition_entry',window.recognition_generate_button.isVisible() and window.recognition_generate_button.isEnabled() and not window.draft_button.isVisible())
        check('recognition_unconfirmed_wording_not_rendered',wait(lambda:not window.render_timer.isActive()) and not any(row.startswith('Dialogue:') for row in window.playback.canvas.renderer.text.splitlines()))
        app.processEvents();QTest.qWait(80)
        window.grab().save(str(out/'recognition-video-only.png'));recognition_ui={}
        def edit_recognition():
            d=next((d for d in window.findChildren(RecognitionDialog) if d.isVisible()),None)
            if d:
                d.editor.setCursorPosition(2);d.split_button.click();recognition_ui['split']=len(d.value['rows'])==2
                d.merge_button.click();recognition_ui['merge']=len(d.value['rows'])==1
                d.speed.setCurrentIndex(1);d.context_button.click();recognition_ui['listen']=window.playback.range==(650,2750) and window.playback.player.playbackRate()==.75
                d.editor.setText('今日も歌おう');d.editor.textEdited.emit(d.editor.text());d.grab().save(str(out/'recognition-wording-editor.png'));d.reject()
        def reuse_recognition():
            d=next((d for d in window.findChildren(RecognitionChoiceDialog) if d.isVisible()),None)
            if d:
                recognition_ui['reuse']=d.mode.currentData()=='reuse';d.grab().save(str(out/'recognition-source-choice.png'))
                QTimer.singleShot(35,edit_recognition);d.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(35,reuse_recognition);window.recognition_generate_button.click()
        check('recognition_reuses_existing_result_without_upload',recognition_ui.get('reuse') and not window.api.busy)
        check('recognition_editor_splits_and_merges_locally',recognition_ui.get('split') and recognition_ui.get('merge'))
        check('recognition_context_audition_and_speed_restore',recognition_ui.get('listen') and window.playback.range is None and window.playback.player.playbackRate()==1)
        check('recognition_wording_is_separate_until_confirmed',not window.project.lines and window.project.recognition_draft['rows'][0]['text']=='今日も歌おう')
        check('recognition_raw_evidence_is_unchanged',window.project.transcript==raw_text)
        window.path=out/'识别原文待确认.sgproj';check('recognition_unconfirmed_project_saves',window.save())
        window.history=History(load_project(window.path));window.current=-1;window.refresh()
        check('recognition_unconfirmed_edit_survives_reopen',window.project.recognition_draft['rows'][0]['text']=='今日も歌おう' and not window.project.lines)
        def confirm_recognition():
            d=next((d for d in window.findChildren(RecognitionDialog) if d.isVisible()),None)
            if d:
                d.grab().save(str(out/'recognition-confirm-wording.png'));d.confirm_button.click()
        QTimer.singleShot(35,confirm_recognition);window.review_recognition()
        check('recognition_confirmation_starts_local_worker',window.api.busy and not window.project.lines)
        check('recognition_confirmation_creates_editable_rough_axis',wait(lambda:not window.api.busy and bool(window.project.lines),15000))
        check('recognition_confirmed_wording_is_exact',window.line.text=='今日も歌おう' and window.line.match.get('text_confirmed'))
        check('recognition_time_and_reading_still_need_confirmation',not window.line.reviewed and not window.project.checks[window.line.id]['reading'])
        check('recognition_rough_mora_and_original_result_preserved',all(unit.highlights for unit in window.line.units) and window.project.transcript==raw_text)
        window.undo();check('recognition_adoption_one_undo_restores_text_draft',not window.project.lines and window.project.recognition_draft['rows'][0]['text']=='今日も歌おう')
        window.redo();check('recognition_adoption_redo',bool(window.project.lines) and not window.project.recognition_draft)
        app.processEvents();QTest.qWait(180);app.processEvents()
        window.grab().save(str(out/'recognition-confirmed-axis.png'))
        window.history=History(Project.from_dict(saved_project));window.path=saved_path;window.current=saved_current;window.pending=None;window.refresh(True);window.playback.seek(saved_position);window.save_recovery()
        # Two local files stand in for vocal/accompaniment editions. Validate
        # actual source, PCM, saved roles, and the one-click route without API.
        import shutil,copy
        original_source=window.project.media;source_copy=out/'伴奏版.mp4';shutil.copy2(original_source,source_copy)
        original_content=[line.to_dict() for line in window.project.lines];original_checks=copy.deepcopy(window.project.checks);old_pcm=window.timeline.audio.samples.filename
        window.choose_media_source=lambda role:window.switch_media_source(role,source_copy)
        window.source_switch.click()
        check('source_candidate_preserves_current_until_ready',window.project.media==original_source and window.source_job is not None)
        check('source_switch_to_accompaniment',wait(lambda:window.source_job is None and window.project.media_role=='instrumental'))
        check('source_switch_keeps_lyrics_readings_and_axis',[line.to_dict() for line in window.project.lines]==original_content and window.project.checks==original_checks)
        check('source_switch_reloads_audio_and_player',window.timeline.audio.samples.filename!=old_pcm and Path(window.playback.player.source().toLocalFile())==source_copy and wait(lambda:not window.playback.canvas.frame.isNull()))
        window.grab().save(str(out/'source-accompaniment.png'))
        window.source_switch.click();check('source_one_click_back_to_original',wait(lambda:window.source_job is None and window.project.media==original_source))
        from .encode import encode,EncodeOptions
        protected=False;before_source=source_copy.read_bytes()
        try:encode(window.project,EncodeOptions(str(source_copy),0,100,'source'))
        except ValueError as error:protected='源' in str(error)
        check('source_export_cannot_overwrite_inactive_edition',protected and source_copy.read_bytes()==before_source)
        from .project import save_project,load_project
        source_project=out/'双版本.sgproj';save_project(window.project,source_project)
        check('source_versions_persist',set(load_project(source_project).media_versions)=={'original','instrumental'})
        window.undo();check('source_switch_one_undo',window.project.media_role=='instrumental' and wait(lambda:window.analysis_job is None))
        window.redo();check('source_switch_redo',window.project.media_role=='original' and wait(lambda:window.analysis_job is None))
        # A real local inference also runs from the frozen app with no Python
        # on PATH. Synthetic tutorial audio proves packaging/synchronization,
        # not vocal quality or Japanese singing accuracy.
        from . import vocal_audio
        original=window.project.to_dict();position=window.playback.canvas.position;original_pcm=str(window.timeline.audio.samples.filename)
        window.playback.player.setPlaybackRate(.75);window.playback.set_zoom(.5)
        window.vocal_tools.click()
        check('local_vocal_worker_starts_without_replacing_original',window.source_job is not None and window.project.to_dict()==original)
        check('real_offline_vocal_inference_completes',wait(lambda:window.source_job is None and window.audition_role=='vocals',60000))
        track=window.project.vocal_track
        check('vocal_model_and_output_hash_verified',track.get('model_sha256')==vocal_audio.MODEL_SHA256 and vocal_audio.digest(track['path'])==track['sha256'])
        check('vocal_output_exact_original_sample_time_base',abs(round(track['frames']*1000/track['sample_rate'])-window.project.duration)<=1)
        check('vocal_audition_keeps_final_source_and_all_lyrics',{k:v for k,v in window.project.to_dict().items() if k!='vocal_track'}=={k:v for k,v in original.items() if k!='vocal_track'})
        check('vocal_pcm_and_player_both_switch',str(window.timeline.audio.samples.filename)!=original_pcm and Path(window.playback.player.source().toLocalFile())!=Path(window.project.media))
        check('vocal_preview_has_video_frame',wait(lambda:not window.playback.canvas.frame.isNull() and not window.playback.preview_pending))
        check('vocal_ab_keeps_position_speed_zoom_mute',abs(window.playback.canvas.position-position)<150 and window.playback.player.playbackRate()==.75 and window.playback.zoom==.5 and window.playback.audio.isMuted())
        check('vocal_switch_keeps_actual_subtitle_pixels',window.playback.canvas.show_subtitles and any(window.playback.canvas.renderer.rgba(640,360,window.playback.canvas.position)[3::4]))
        QTest.qWait(160);window.grab().save(str(out/'vocal-audition.png'))
        vocal_project=out/'人声辅助工程.sgproj';save_project(window.project,vocal_project);loaded=load_project(vocal_project)
        check('vocal_asset_portable_saved_and_reopened',Path(loaded.vocal_track['path']).is_file() and vocal_audio.digest(loaded.vocal_track['path'])==track['sha256'] and Path(loaded.vocal_track['path']).is_relative_to(out))
        window.vocal_tools.click()
        check('one_click_back_to_original_audio',window.audition_role=='original' and Path(window.playback.player.source().toLocalFile())==Path(window.project.media) and str(window.timeline.audio.samples.filename)==original_pcm)
        cached_mtime=Path(track['path']).stat().st_mtime_ns;window.vocal_tools.click()
        check('vocal_repeat_uses_existing_cache',wait(lambda:window.source_job is None and window.audition_role=='vocals') and Path(track['path']).stat().st_mtime_ns==cached_mtime)
        window.undo();check('adding_vocal_track_is_one_undo_and_restores_audition',window.project.to_dict()==original and window.audition_role=='original')
        window.playback.stop();window.playback.player.setPlaybackRate(1.);window.playback.set_zoom(None);window.playback.seek(position)
        from .acoustic_acceptance import exercise
        exercise(app,StudioWindow,out,check,wait)
        from .singing_acceptance import exercise as staged_singing
        staged_singing(app,StudioWindow,out,check,wait)
        from .provenance_acceptance import exercise as timing_basis
        timing_basis(app,StudioWindow,out,check,wait)
        original_mora=window.project.to_dict();word_times=[(u.start,u.end,u.kana,u.romaji) for u in window.line.units]
        window.fill_mora_button.click();check('missing_mora_is_previewed',window.inline_segment.pending and window.project.to_dict()==original_mora)
        window.inline_segment.apply.click();check('missing_mora_keeps_words_and_readings',all(u.highlights for u in window.line.units) and [(u.start,u.end,u.kana,u.romaji) for u in window.line.units]==word_times)
        window.undo();check('missing_mora_one_undo',window.project.to_dict()==original_mora)
        before=window.line.to_dict();window.timeline.word=0;window.change_boundary(0,-1,window.line.units[0].start+100,window.line.units[0].end)
        check('boundary_changes_model',window.line.units[0].start==before['units'][0]['start']+100)
        window.undo();check('boundary_one_step_undo',window.line.to_dict()==before);window.redo();check('boundary_redo',window.line.units[0].start==before['units'][0]['start']+100);window.undo()
        window.apply_preset(1);check('font_template',window.project.style.font=='Noto Serif CJK JP')
        app.processEvents();QTest.qWait(120);with_subtitles=window.playback.canvas.grab().toImage();window.subtitle_toggle.click();app.processEvents()
        check('subtitle_comparison_changes_actual_preview',not window.playback.canvas.show_subtitles and with_subtitles!=window.playback.canvas.grab().toImage());window.subtitle_toggle.click()
        for stage in range(5):
            window.set_stage(stage);app.processEvents();QTest.qWait(180);window.grab().save(str(out/f'stage-{stage+1}.png'))
            check(f'stage_{stage+1}_reachable',window.pages.currentIndex()==stage)
        window.resize(1280,800);window.set_stage(0);app.processEvents();window.grab().save(str(out/'laptop.png'))
        check('laptop_main_regions',window.timeline.width()>300 and window.pages.width()>=290)
        window.resize(960,680);window.set_stage(2);app.processEvents();window.grab().save(str(out/'compact-calibration.png'))
        check('compact_calibration_focus_and_footer',not window.playback.isVisible() and window.timeline.isVisible() and window.calibrate_footer.isVisible())
        check('compact_calibration_needs_no_horizontal_scroll',window.pages.widget(2).horizontalScrollBar().maximum()==0)
        window.set_stage(3);app.processEvents();window.grab().save(str(out/'compact-design.png'))
        check('compact_design_has_large_preview',window.playback.isVisible() and not window.audio_group.isVisible())
        check('compact_design_needs_no_horizontal_scroll',window.pages.widget(3).horizontalScrollBar().maximum()==0)
        window.workflow_toggle.click();app.processEvents()
        check('compact_step_navigation_not_clipped',all(button.height()>=60 and button.visibleRegion().boundingRect().height()>=60 for button in window.steps));window.workflow_toggle.click();app.processEvents()
        window.set_stage(4);app.processEvents();window.grab().save(str(out/'compact-export.png'))
        check('compact_export_primary_actions_visible',window.sample_button.isVisible() and window.encode_button.visibleRegion().boundingRect().height()>30)
        window.resize(1460,940);window.view_choice.setCurrentIndex(0);window.set_stage(2);app.processEvents()
        from .project import save_project,load_project
        path=out/'作品.sgproj';window.path=path;check('save_through_actual_ui',window.save());loaded=load_project(path)
        check('saved_project_in_recent_list',window.preferences.recent()[0]['path']==str(path.resolve()))
        check('time_inputs_show_readable_timecode',':' in window.begin.text() and '.' in window.begin.text())
        check('project_roundtrip_readings_times',loaded.lines[0].to_dict()==window.line.to_dict())
        check('portable_font_resource',Path(loaded.style.font_file).is_file() and str(out) in loaded.style.font_file)
        from .subtitles import compose
        text=compose(loaded,True);(out/'成品.ass').write_text(text,encoding='utf-8-sig')
        reopened=load_project(out/'成品.ass');check('ass_embeds_editable_project',reopened.lines[0].to_dict()==loaded.lines[0].to_dict())
        check('live_render_contains_subtitles',any(window.playback.canvas.renderer.rgba(640,360,2000)))
        window.start_api('segment',mode='mora')
        check('isolated_worker_returns_suggestions',wait(lambda:not window.api.busy and window.pending is not None,15000))
        window.apply_suggestions(window.pending['result']['suggestions'])
        check('reviewed_offline_suggestion_has_morae',bool(window.line.units[0].highlights))
        uid=window.line.id;window.calibration_tabs.setCurrentIndex(1);window.grab().save(str(out/'reading-review.png'));window.confirm_current()
        check('reading_confirm_separate_from_timing',window.project.checks[uid]['reading'] and not window.line.reviewed);window.undo();window.calibration_tabs.setCurrentIndex(0)
        from .encode import EncodeOptions
        sample=out/'试压.mp4';window.encode_to(EncodeOptions(str(sample),1000,2000))
        check('runtime_real_sample_encode',wait(lambda:window.local_job is None and sample.exists(),30000))
        final=out/'完整成品.mp4';window.encode_to(EncodeOptions(str(final)))
        check('runtime_real_full_encode',wait(lambda:window.local_job is None and final.exists(),30000))
        import subprocess
        from .paths import ffmpeg
        audio=out/'纯音频素材.wav'
        prepared=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',window.project.media,'-vn','-c:a','pcm_s16le',str(audio)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        check('prepare_audio_only_media',prepared.returncode==0)
        window.load_media(audio)
        check('audio_only_media_detected',wait(lambda:window.analysis_job is None and window.project.has_video is False))
        check('audio_only_preview_background',window.playback.canvas.audio_only and window.playback.canvas.frame.isNull())
        audio_video=out/'纯音频字幕成品.mp4';window.encode_to(EncodeOptions(str(audio_video),1000,1000,'720p'))
        check('runtime_audio_only_subtitle_video',wait(lambda:window.local_job is None and audio_video.exists(),30000))
        import copy
        from .project import History
        from .presentation import display_windows
        from .furigana import ruby_spans
        from .subtitles import layout_line
        p=copy.deepcopy(window.project);other=copy.deepcopy(p.lines[0]);other.id='adjacent-demo'
        other.start+=4600;other.end+=4600
        for u in other.units:
            u.start+=4600;u.end+=4600
            for h in u.highlights:h.start+=4600;h.end+=4600
        p.lines.append(other);p.duration=12000;window.history=History(p);window.current=1;window.refresh(True)
        window.resize(960,680);window.set_stage(2);app.processEvents()
        check('previous_mora_lane_and_overlap_visible',window.previous_context.isVisible() and '400 ms' in window.previous_context.caption.text())
        check('compact_adjacent_timeline_not_clipped',window.timeline.visibleRegion().boundingRect().height()>=180)
        window.grab().save(str(out/'previous-line-context.png'))
        window.previous_context.edit.click();check('jump_to_previous_exact_last_mora',window.current==0 and window.timeline.word==len(window.line.units)-1 and window.timeline.part==len(window.line.units[-1].highlights)-1)
        before=[x.to_dict() for x in window.project.lines];window.apply_preset(2);schedule=display_windows(window.project)
        check('rolling_preset_preserves_singing_axis',window.project.style.display_mode=='alternating' and before==[x.to_dict() for x in window.project.lines])
        check('upcoming_lyric_previews_before_singing',schedule[1].start<window.project.lines[1].start and schedule[0].end>=window.project.lines[0].end)
        check('ruby_anchors_to_kanji_only',ruby_spans('お相手は','おあいては')==((1,3,1,4),))
        mf,rf,size,rs,widths,width=layout_line(window.line,window.project.style)
        check('reading_does_not_expand_main_text',width==sum(mf.getlength(u.text) for u in window.line.units))
        from .continuity_dialog import ContinuityDialog
        p=copy.deepcopy(window.project)
        for line in p.lines:
            line.reviewed=False
            for u in line.units:
                u.source='estimated'
                for h in u.highlights:h.source='estimated'
        window.history=History(p);window.current=0;window.refresh(True);window.set_stage(2);app.processEvents()
        preview=ContinuityDialog(window.project,window.current,window.playback,window);check('automatic_gap_cleanup_has_reviewable_changes',len(preview.changes)>=2);preview.grab().save(str(out/'automatic-gap-preview.png'));preview.close()
        original=window.project.to_dict();onsets=[[(u.start,[h.start for h in u.highlights]) for u in line.units] for line in window.project.lines]
        def apply_cleanup():
            dialog=next((d for d in window.findChildren(ContinuityDialog) if d.isVisible()),None)
            if dialog:dialog.apply_button.click()
        QTimer.singleShot(30,apply_cleanup);window.cleanup_auto_gaps()
        check('automatic_gap_cleanup_keeps_vocal_onsets',onsets==[[(u.start,[h.start for h in u.highlights]) for u in line.units] for line in window.project.lines])
        check('automatic_gap_cleanup_has_shared_word_edges',window.line.units[0].end==window.line.units[1].start and window.line.units[1].end==window.line.units[2].start)
        window.grab().save(str(out/'continuous-syllable-axis.png'));window.undo();check('automatic_gap_cleanup_one_undo',window.project.to_dict()==original)
        window.redo();check('automatic_gap_cleanup_redo',window.line.units[0].end==window.line.units[1].start)
        window.resize(1460,940);window.view_choice.setCurrentIndex(0);window.set_stage(3);window.playback.seek(5800);window.render_subtitles();app.processEvents()
        check('standalone_two_rows_render',any(window.playback.canvas.renderer.rgba(640,360,5800)))
        window.grab().save(str(out/'rolling-karaoke.png'))
        original=window.project.to_dict();window.audio_view.setCurrentIndex(1);app.processEvents()
        check('direct_waveform_switch',not window.timeline.show_spectrum and window.project.to_dict()==original)
        window.audio_view.setCurrentIndex(0);check('direct_spectrum_switch',window.timeline.show_spectrum)
        window.playback.set_source_size(1920,1080);window.playback.set_zoom(.5);window.playback.zoom_steps(1)
        check('video_zoom_aeg_eighth_steps',window.playback.zoom==.625 and window.playback.canvas.width()==1200)
        window.playback.set_zoom(None);check('video_zoom_restore_fit',window.playback.zoom is None)
        window.large_video.click();app.processEvents();check('enlarge_video_hides_side_panels',not window.right_panel.isVisible() and not window.left_panel.isVisible());window.large_video.click()
        window.set_stage(2);window.view_choice.setCurrentIndex(0);window.granularity.setCurrentIndex(window.granularity.findData('words'));window.timeline.setFocus();window.select_target(0,-1);before=window.line.units[0].end
        QTest.keyClick(window.timeline,Qt.Key.Key_Plus,Qt.KeyboardModifier.KeypadModifier)
        check('aeg_keypad_length_shortcut',window.line.units[0].end==before+10);window.undo()
        original=window.project.to_dict();old_zoom=window.timeline.zoom_level
        window.audio_controls.zoom.setValue(20);window.audio_controls.gain.setValue(75);window.volume.setValue(40)
        check('three_audio_sliders_control_real_values',window.timeline.zoom_level==20 and abs(window.timeline.amplitude-3.375)<.001 and abs(window.playback.audio.volume()-.4)<.001)
        check('audio_sliders_preserve_project',window.project.to_dict()==original)
        window.audio_controls.zoom.setValue(old_zoom);window.audio_controls.gain.setValue(50);window.volume.setValue(70)
        window.playback.seek(1500);window.move_to_playhead.click()
        check('whole_phrase_moves_to_playhead',window.line.start==1500 and window.line.end-window.line.start==original['lines'][window.current]['end']-original['lines'][window.current]['start'])
        window.undo();check('whole_phrase_move_one_undo',window.project.to_dict()==original)
        from .time_correction_dialog import TimeCorrectionDialog
        original=window.project.to_dict();old_windows=display_windows(window.project);scope_state={}
        window.time_scope.setCurrentIndex(window.time_scope.findData('all'))
        def shift_scope():
            d=next((d for d in window.findChildren(TimeCorrectionDialog) if d.isVisible()),None)
            if d:
                d.set_shift(100);scope_state['preview']=window.project.to_dict()==original and len(d.preview_result.rows)==len(window.project.lines)
                scope_state['audio']=d.timeline.audio is not None;app.processEvents();d.grab().save(str(out/'scope-time-preview.png'))
                d.listen(True);scope_state['listen']=window.playback.range is not None
                d.apply_button.click()
        QTimer.singleShot(30,shift_scope);window.offset_button.click()
        check('scope_correction_preview_preserves_project',scope_state.get('preview'))
        check('scope_correction_has_original_audio_and_audition',scope_state.get('audio') and scope_state.get('listen'))
        check('whole_song_moves_all_words_and_morae',all(line.start==old['start']+100 and all(u.start==v['start']+100 and all(h.start==g['start']+100 for h,g in zip(u.highlights,v['highlights'])) for u,v in zip(line.units,old['units'])) for line,old in zip(window.project.lines,original['lines'])))
        schedule=display_windows(window.project)
        check('whole_song_also_moves_display_windows',all(w.start==old.start+100 and w.end==min(window.project.duration,old.end+100) for w,old in zip(schedule,old_windows)))
        window.undo();check('whole_song_correction_one_undo',window.project.to_dict()==original)
        last=max(line.end for line in window.project.lines);first=min(line.start for line in window.project.lines)
        def fix_drift():
            d=next((d for d in window.findChildren(TimeCorrectionDialog) if d.isVisible()),None)
            if d:d.set_anchors([(first,first),(last,last-100)]);app.processEvents();d.grab().save(str(out/'drift-time-preview.png'));d.apply_button.click()
        window.more_correction.toggle.setChecked(True);QTimer.singleShot(30,fix_drift);window.drift_button.click();window.more_correction.toggle.setChecked(False)
        check('two_point_drift_correction',window.project.lines[0].start==first and max(line.end for line in window.project.lines)==last-100)
        window.undo();check('drift_correction_one_undo',window.project.to_dict()==original)
        window.current=1;window.refresh();window.time_scope.setCurrentIndex(window.time_scope.findData('following'))
        check('suffix_scope_does_not_include_previous',window.timing_indices()==[1])
        window.current=0;window.refresh();window.time_scope.setCurrentIndex(window.time_scope.findData('current'))
        window.display_timing.toggle.setChecked(True);axis=[(line.start,line.end) for line in window.project.lines]
        window.display_begin.setValue(max(0,window.line.start-200));window.display_end.setValue(window.line.end+200);window.display_apply.click()
        check('manual_display_is_independent_of_singing_axis',[(line.start,line.end) for line in window.project.lines]==axis and window.line.display_start==max(0,window.line.start-200))
        window.undo();window.display_timing.toggle.setChecked(False);check('display_timing_one_undo',window.project.to_dict()==original)
        check('clear_editing_entry_points',all(b.isVisible() and b.toolTip() for b in [window.quick_segment,window.quick_reading,window.quick_timing,window.quick_tail]))
        app.processEvents();window.grab().save(str(out/'audio-three-sliders.png'))
        from .fonts import font_weight
        check('recommended_font_is_actual_black_face',font_weight(window.project.style.font_file,window.project.style.font)==900 and '\\b900' in window.playback.canvas.renderer.text)
        from .tail_dialog import TailDialog
        original=window.project.to_dict();tail_state={}
        def edit_tail():
            d=next((d for d in window.findChildren(TailDialog) if d.isVisible()),None)
            if d:
                tail_state['view']=d.timeline.span<2000 and d.controls_scroll.horizontalScrollBar().maximum()==0
                d.grab().save(str(out/'tail-review.png'))
                d.listen(True);tail_state['audition']=window.playback.range is not None and window.playback.player.playbackRate()==.75
                d.enhance.setChecked(True);d.listen(True);tail_state['enhance']=wait(lambda:d.filtered_player.position()>20,3000) and d.filtered_audio.isMuted();d.enhance.setChecked(False)
                d.end.setValue(d.end.value()+10);d.reading.setText('す');d.accept_changes()
        QTimer.singleShot(30,edit_tail);window.inspect_tail()
        check('tail_view_and_context_slow_audition',tail_state.get('view') and tail_state.get('audition'))
        check('tail_consonant_enhancement_plays_real_memory_clip',tail_state.get('enhance'))
        check('tail_time_and_reading_saved',window.line.units[-1].highlights[-1].kana=='す' and window.line.end==original['lines'][window.current]['end']+10)
        window.undo();check('tail_edit_one_undo',window.project.to_dict()==original)
        original=window.project.to_dict()
        from PySide6.QtWidgets import QLineEdit
        from PySide6.QtCore import QUrl
        from dataclasses import asdict
        window.resegment_button.click();check('inline_segmentation_without_modal',app.activeModalWidget() is None and window.inline_segment.mode.isChecked())
        window.inline_segment.whole.click();check('inline_segmentation_is_preview_only',window.inline_segment.pending and window.project.to_dict()==original)
        syllables=[asdict(part) for unit in window.line.units for part in unit.highlights]
        check('inline_merge_keeps_manual_syllables',[asdict(part) for part in window.inline_segment.preview.line.units[0].highlights]==syllables)
        window.inline_segment.apply.click()
        check('local_line_segmentation_applies',len(window.line.units)==1 and window.line.text==original['lines'][window.current]['text'])
        window.undo();check('local_line_segmentation_one_undo',window.project.to_dict()==original)
        window.activateWindow();app.processEvents()
        others=[asdict(unit) for unit in window.line.units[1:]];window.quick_reading.click();editor=app.focusWidget()
        check('inline_reading_uses_local_editor',wait(lambda:isinstance(app.focusWidget(),QLineEdit),2000) and app.activeModalWidget() is None);editor=app.focusWidget()
        editor.setText('こんにち');window.quick_timing.click()
        check('inline_reading_preserves_other_words',window.line.units[0].kana=='こんにち' and [asdict(unit) for unit in window.line.units[1:]]==others)
        window.undo();check('inline_reading_one_undo',window.project.to_dict()==original)
        window.mora_strip.anchorClicked.emit(QUrl('mora:0:1'));part=window.line.units[0].highlights[1]
        check('inline_mora_selection_matches_time_fields',(window.timeline.word,window.timeline.part)==(0,1) and (window.begin.value(),window.end.value())==(part.start,part.end))
        window.mora_strip.audition.emit(0,1);check('inline_mora_audition_uses_exact_range',window.playback.range==(part.start,part.end));window.playback.stop()
        window.show_editor_widget(window.mora_strip);app.processEvents();window.grab().save(str(out/'unified-line-editor.png'))
        window.next_context.edit.click();check('next_context_selects_first_mora',window.current==1 and (window.timeline.word,window.timeline.part)==(0,0))
        window.previous_context.edit.click();check('previous_context_returns_to_last_mora',window.current==0 and window.timeline.word==len(window.line.units)-1)
        before_locate=window.project.to_dict();position=max(window.project.lines[1].start+100,window.project.lines[0].end+100);window.playback.seek(position);window.locate_lyric_button.click()
        check('video_playhead_locates_lyric_and_mora',window.current==1 and window.timeline.word==0 and window.playback.canvas.position==position)
        check('video_locate_keeps_entire_singing_axis',window.project.to_dict()==before_locate);window.previous_context.edit.click()
        window.resegment_button.click();window.inline_segment.whole.click();window.inline_segment.apply.click()
        window.save_recovery();check('recovery_created',window.recovery_path().exists())
        print(json.dumps({'ok':True,'checks':len(checks),'output':str(out)},ensure_ascii=False))
    finally:
        (out/'report.json').write_text(json.dumps({'checks':checks,'passed':all(c['passed'] for c in checks),'runtime':'standalone' if getattr(sys,'frozen',False) else 'development','last_status':window.status.text()},ensure_ascii=False,indent=2),encoding='utf-8')
        window.close();app.processEvents()

if __name__=='__main__':main()
