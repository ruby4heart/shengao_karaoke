"""Real main-editor review, then actual partial TIFA after custom subdivision."""
import copy,json
from pathlib import Path
from PySide6.QtMultimedia import QMediaPlayer
from .paths import ASSETS
from .project import Project,History,save_project,load_project,file_stamp
from .subtitles import compose
from .subtitle_files import export_subtitle
from .review_issues import state,progress
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.romanization import set_manual
from studio_backend.reading_options import set_ruby
from studio_backend.provenance import create
from studio_backend.acoustic import plan


def exercise(app,StudioWindow,out,check,wait):
    out=Path(out);w=StudioWindow(out/'audio-review-home',test=True);w.playback.audio.setMuted(True);w.show();audit={}
    line=LyricLine('review-synthetic','今日も',1000,4000,[Unit('今日',1000,3000,'きょう',highlights=[Highlight('きょう',1000,3000,'manual')]),Unit('も',3200,4000,'も')],reviewed=True)
    line=set_ruby(set_manual(line,0,'KYOH'),0,{'mode':'whole'})
    def select(word,part):
        w.set_stage(2);w.granularity.setCurrentIndex(w.granularity.findData('mora' if part>=0 else 'words'));w.select_target(word,part);app.processEvents()
    def choose_issue(kind):
        d=w.issue_dialog;d.kind.setCurrentIndex(d.kind.findData(kind));d.status_filter.setCurrentIndex(d.status_filter.findData('pending'));d.refresh()
        assert d.filtered;d.table.setCurrentCell(0,0);return d,d.selected()
    try:
        w.history=History(Project(title='合成练习：细听与疑点',lines=[line],checks={line.id:{'reading':True}}));w.current=0;w.refresh();w.load_media(ASSETS/'demo/tutorial.mp4',preview=True)
        check('audio_review_actual_media_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None and not w.playback.canvas.frame.isNull() and not w.playback.preview_pending,25000));select(0,0)
        before=w.project.to_dict();p=w.mora_editor;w.mora_editing.toggle.setChecked(True);p.split.click()
        check('audio_review_inline_split_is_private_preview',p.apply.isEnabled() and w.project.to_dict()==before and p.candidate['estimated_new_boundaries']==1)
        p.apply.click();parts=w.line.units[0].highlights
        check('audio_review_split_keeps_reading_fixed_outer_and_neighbor',[h.kana for h in parts]==['きょ','う'] and parts[0].fixed_edges==['start'] and parts[1].fixed_edges==['end'] and w.line.units[0].romaji=='KYOH' and w.line.units[0].reading_options==before['lines'][0]['units'][0]['reading_options'] and w.line.to_dict()['units'][1]==before['lines'][0]['units'][1] and w.project.checks[line.id]['reading'] and not w.line.reviewed)
        after_split=w.project.to_dict();w.undo();check('audio_review_split_is_one_undo',w.project.to_dict()==before);w.redo();check('audio_review_split_redo_restores_history',w.project.to_dict()==after_split)
        select(0,1);w.quick_tail.click();f=w.fine_listener;regular_rate=w.playback.player.playbackRate();regular_loop=w.playback.loop;before_listen=w.project.to_dict();f.enhance.setChecked(True);f.context_button.click()
        check('audio_review_main_enhancement_real_player',wait(lambda:f.filtered_player.playbackState()==QMediaPlayer.PlaybackState.PlayingState and w.playback.canvas.position>f.filtered_start+30,6000) and f.filtered_audio.isMuted() and w.playback.temporary_owner is f)
        check('audio_review_enhancement_clock_and_readonly_project',w.timeline.position==w.playback.canvas.position and w.project.to_dict()==before_listen and '定位静帧' in f.status.text() and w.play_button.text()=='停止细听')
        w.show_editor_widget(f.context_button);app.processEvents();w.grab().save(str(out/'audio-review-inline-listening.png'))
        w.playback.seek(3500);app.processEvents()
        check('audio_review_regular_seek_cleans_clip_and_restores_settings',f.mode is None and w.playback.temporary_owner is None and w.playback.player.playbackRate()==regular_rate and w.playback.loop==regular_loop and w.playback.canvas.position==3500 and w.project.to_dict()==before_listen)
        select(0,1);f.compare.click()
        check('audio_review_original_context_slow_listening',not f.enhance.isChecked() and f.mode=='normal' and wait(lambda:w.playback.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState,5000) and w.playback.player.playbackRate()==.75)
        f.stop_button.click();check('audio_review_stop_returns_regular_settings',f.mode is None and w.playback.player.playbackRate()==regular_rate and w.playback.loop==regular_loop and w.project.to_dict()==before_listen)
        check('audio_review_workbench_opens_without_modal',w.open_review_issues() and not w.issue_dialog.isModal() and app.activeModalWidget() is None)
        d,item=choose_issue('missing');before_adopt=w.project.to_dict();old_manual=copy.deepcopy(before_adopt['lines'][0]['units'][0]);steps=len(w.history.undo_stack)
        check('audio_review_issue_current_and_estimated_proposal',d.current.toPlainText() and d.suggested.toPlainText() and d.adopt.isEnabled() and '估算' in d.why.text())
        app.processEvents();d.grab().save(str(out/'audio-review-issues.png'))
        d.adopt.click();check('audio_review_actual_issue_adoption_updates_only_selected_word',w.line.units[1].highlights and all(h.source=='estimated' for h in w.line.units[1].highlights) and w.line.to_dict()['units'][0]==old_manual and w.project.checks==before_adopt['checks'] and len(w.history.undo_stack)==steps+1)
        check('audio_review_progress_only_after_real_adoption',w.project.review_states[item.id]['decision']=='adopted' and progress(d.items,w.project.review_states)['saved_adoptions']==1 and '已直接采用 1' in d.summary.text() and not w.line.reviewed)
        d.undo_button.click();check('audio_review_issue_edit_and_decision_one_undo',w.project.to_dict()==before_adopt)
        d,item=choose_issue('missing');d.keep.click();after_keep=w.project.to_dict();check('audio_review_keep_does_not_change_axis_or_confirmation',state(item,w.project.review_states)=='keep' and w.line.to_dict()==before_adopt['lines'][0] and w.project.checks==before_adopt['checks'])
        select(1,-1);w.begin.setValue(3300);w.end.setValue(4000);w.apply_spins();d.refresh();d.status_filter.setCurrentIndex(d.status_filter.findData('changed'))
        check('audio_review_changed_basis_reopens_and_keeps_old_comparison',d.filtered and d.selected().id==item.id and d.old.isVisible() and '上次决定' in d.old.toPlainText())
        w.undo();check('audio_review_manual_boundary_undo_restores_keep',w.project.to_dict()==after_keep);w.undo();check('audio_review_keep_one_undo',w.project.to_dict()==before_adopt)
        d.refresh();d.close();old=w.line.to_dict();incoming=copy.deepcopy(old);incoming['start']-=50
        w.pending={'action':'align','context':{'project':w.project.uid,'media':file_stamp(w.project.media)},'snapshots':{w.line.id:old},'result':{'suggestions':[incoming]}}
        w.edit('受控模拟建议到达后的人工范围',lambda p:setattr(p.lines[0],'start',p.lines[0].start-10));w.open_review_issues();d,item=choose_issue('proposal');current=w.project.to_dict()
        check('audio_review_stale_background_result_is_comparable_not_directly_adopted','当前已变化' in item.title and d.current.toPlainText() and d.suggested.toPlainText() and not d.adopt.isEnabled() and w.project.to_dict()==current)
        d.keep.click();check('audio_review_keep_never_discards_background_result',w.pending is not None and w.pending['result']['suggestions'][0]==incoming and w.line.to_dict()==current['lines'][0])
        w.undo();w.undo();w.pending=None;d.refresh();d,item=choose_issue('gap');d.defer.click();d.close()
        saved=out/'主界面音节与疑点.sgproj';ass=out/'主界面音节与疑点.ass';save_project(w.project,saved);export_subtitle(w.project,ass)
        a=load_project(saved);b=load_project(ass)
        check('audio_review_history_and_decisions_project_ass_roundtrip',a.to_dict()==w.project.to_dict() and a.review_states and b.review_states==w.project.review_states and b.lines[0].reading_review['mora_edits']==w.line.reading_review['mora_edits'] and compose(a)==compose(w.project)==compose(b))
        # Actual singing inference. Reference positions make this a controlled
        # protection test; they are not an independent accuracy evaluation.
        reference=json.loads((ASSETS/'alignment-demo/sample.json').read_text(encoding='utf-8'));refs=reference['mora'][4:23];special=next(i for i,m in enumerate(refs) if len(m['kana'])>1)
        parts=[Highlight(m['kana'],round(m['start']),round(m['end']),'estimated',create('reference',round(m['start']),round(m['end']),method='public_reference_control',reading=m['kana'])) for m in refs]
        text=''.join(h.kana for h in parts);a=parts[0].start-100;b=parts[-1].end+100
        line=LyricLine('review-public',text,a,b,[Unit(text,a,b,text,highlights=parts)],kana=text)
        w.history=History(Project(title='公开演唱：手工细分后局部重算',lines=[line],checks={line.id:{'reading':False}}));w.current=0;w.refresh();w.load_media(ASSETS/'alignment-demo/pjs056_song.wav')
        check('audio_review_public_singing_source_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,25000));select(0,special);p=w.mora_editor;w.mora_editing.toggle.setChecked(True);p.advanced.setChecked(True);p.cut.setCurrentIndex(p.cut.findData(1));p.split.click();p.apply.click()
        protected=copy.deepcopy(w.line.to_dict()['units'][0]['highlights'][special:special+2]);before_model=w.project.to_dict();prepared=plan(w.line)
        check('audio_review_custom_subdivision_remains_estimated_and_protected',all(h['source']=='manual' and h['timing_origin']['kind']=='estimated' for h in protected) and sum(len(job['mora']) for job in prepared['jobs'])==len(refs)-1)
        w.acoustic_button.click();check('audio_review_actual_partial_tifa_starts_without_overwriting',w.source_job is not None and w.project.to_dict()==before_model)
        check('audio_review_actual_partial_tifa_returns',wait(lambda:w.source_job is None,120000) and w.pending is not None)
        candidate=w.pending['result']['suggestions'][0];computed=[m for run in candidate['timing_evidence']['runs'] for m in run['mora']]
        check('audio_review_real_inference_excludes_custom_segments',len(computed)==len(refs)-1 and candidate['units'][0]['highlights'][special:special+2]==protected and candidate['reading_review']['mora_edits']==w.line.reading_review['mora_edits'] and w.project.to_dict()==before_model)
        w.apply_suggestions([candidate]);check('audio_review_actual_partial_adoption_keeps_manual_reading_and_bounds',w.pending is None and w.line.to_dict()['units'][0]['highlights'][special:special+2]==protected and not w.line.reviewed and not w.project.checks[line.id]['reading'] and (w.line.start,w.line.end)==(a,b))
        saved=out/'自定义音节后真实局部对齐.sgproj';ass=out/'自定义音节后真实局部对齐.ass';save_project(w.project,saved);export_subtitle(w.project,ass)
        check('audio_review_real_partial_result_project_and_ass_keep_history',load_project(saved).to_dict()==w.project.to_dict() and compose(load_project(ass))==compose(w.project))
        w.undo();check('audio_review_real_partial_adoption_one_undo',w.project.to_dict()==before_model)
        audit={'passed':True,'public_mora':len(refs),'protected_custom_segments':2,'actual_computed_mora':len(computed),'engine':candidate['timing_evidence']['engine'],'model_sha256':candidate['timing_evidence']['model_sha256'],'paid_api_calls':0,'interpretation':'Controlled public PJS056 reference positions, one mora split inside a digraph by the actual main editor. Two manually grouped segments retain estimated time; actual TIFA computes only the other mora. This is protection/interop evidence, not an independent accuracy study, completed MV or human newcomer acceptance.'}
        (out/'audio-review-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:w.close();w.deleteLater();app.processEvents()
