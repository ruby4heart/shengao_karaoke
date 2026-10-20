"""Real staged singing QA on licensed public audio; no cloud or user keys."""
import copy
import json
import statistics
from pathlib import Path
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QDialogButtonBox
from .paths import ASSETS
from .project import Project,History,save_project,load_project
from .draft_workflow import DraftDialog,ResumeDraftDialog
from .dialogs import ReviewDialog
from studio_backend.model import LyricLine,Unit
from studio_backend.japanese import romaji

def sample_project():
    reference=json.loads((ASSETS/'alignment-demo/sample.json').read_text(encoding='utf-8'));parts=reference['mora'];rows=[]
    for i,(a,b) in enumerate([(0,4),(4,23),(23,37)]):
        kana=''.join(m['kana'] for m in parts[a:b]);start=max(0,round(parts[a]['start'])-150);end=min(reference['duration'],round(parts[b-1]['end'])+180)
        rows.append(LyricLine('staged-pjs-'+str(i),kana,start,end,[Unit(kana,start,end,kana,romaji(kana),reading_source='manual')],kana,romaji(kana)))
    rows.append(LyricLine('intentional-invalid-reading','待修正示例',15600,15900,[Unit('待修正示例',15600,15900,'ー','',reading_source='manual')],kana='ー'))
    return Project(title='公开演唱 · 分阶段验收',lines=rows,checks={v.id:{'reading':True} for v in rows}),reference

def exercise(app,StudioWindow,out,check,wait):
    p,reference=sample_project();w=StudioWindow(out/'staged-singing-home',test=True);w.playback.audio.setMuted(True);w.show()
    try:
        w.history=History(p);w.current=0;w.refresh();w.load_media(ASSETS/'alignment-demo/pjs056_song.wav')
        check('staged_singing_public_audio_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000));w.set_stage(1);before=w.project.to_dict();ui=[]
        def choose():
            d=next(d for d in w.findChildren(DraftDialog) if d.isVisible());d.acoustic.setChecked(True);d.audio.setCurrentIndex(1);d.resize(660,450);app.processEvents()
            controls=d.findChild(QDialogButtonBox);ui.append(controls.geometry().bottom()<=d.height() and '歌声音节' in d.overview.text())
            d.grab().save(str(out/'staged-singing-options.png'));controls.button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(30,choose);w.start_draft()
        check('staged_singing_scrolled_options_keep_footer',ui==[True] and w.api.busy)
        check('staged_singing_real_worker_completes',wait(lambda:not w.api.busy and w.pending is not None,90000));result=copy.deepcopy(w.pending['result']);workflow=result['workflow']['id']
        check('staged_singing_six_stages_and_actual_mixed_status',len(result['workflow']['stages'])==6 and not result['partial'] and result['acoustic']['aligned']==3 and result['acoustic']['needs_manual']==1)
        check('staged_singing_one_model_load_for_three_lines',result['acoustic']['model_loads']==1)
        check('staged_singing_never_auto_applies_or_confirms',w.project.to_dict()==before)
        candidates=result['suggestions'][:3];highlights=[h for row in candidates for u in row['units'] for h in u['highlights']]
        check('staged_singing_37_actual_acoustic_mora',len(highlights)==37 and all(h['source']=='acoustic' for h in highlights))
        check('staged_singing_custom_confirmed_groups_and_romaji_kept',all(len(v['units'])==1 and v['kana']==old.kana and v['romaji']==old.romaji for v,old in zip(candidates,p.lines)))
        errors=[{'kana':h['kana'],'onset_error_ms':h['start']-r['start'],'offset_error_ms':h['end']-r['end']} for h,r in zip(highlights,reference['mora'])]
        onset=[abs(v['onset_error_ms']) for v in errors];offset=[abs(v['offset_error_ms']) for v in errors]
        metrics={'count':37,'onset_mean_ms':statistics.mean(onset),'onset_median_ms':statistics.median(onset),'onset_max_ms':max(onset),'offset_mean_ms':statistics.mean(offset),'offset_max_ms':max(offset),'errors':errors,'acoustic':result['acoustic'],
            'interpretation':'One public singing sample, no timing anchors; training overlap unknown. The fourth row is a deliberately invalid reading fixture with no human audio reference. Not a general accuracy claim.'}
        (out/'staged-acoustic-reference.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
        check('staged_singing_human_reference_error_recorded',metrics['onset_median_ms']<100 and metrics['onset_max_ms']<250)
        d=ReviewDialog(w.project,result,w.playback,w);d.show();app.processEvents()
        check('staged_singing_review_marks_unaligned_row',d.table.columnCount()==5 and '需手工' in d.table.item(3,4).text())
        d.grab().save(str(out/'staged-singing-review.png'))
        for i in range(3):d.table.item(i,0).setCheckState(Qt.CheckState.Checked)
        w.apply_suggestions(d.selected());d.reject()
        check('staged_singing_partial_adoption_keeps_failed_original',w.project.lines[3].to_dict()==before['lines'][3] and w.pending and len(w.pending['result']['suggestions'])==1)
        check('staged_singing_reading_flags_survive_time_draft',all(w.project.checks[v.id]['reading'] and not v.reviewed for v in w.project.lines[:3]))
        target=out/'整首声学候选.sgproj';save_project(w.project,target)
        check('staged_singing_fitted_axis_roundtrips',load_project(target).to_dict()==w.project.to_dict())
        w.current=1;w.refresh();w.playback.seek(6500);app.processEvents();w.grab().save(str(out/'staged-singing-axis.png'))
        w.undo();check('staged_singing_one_action_undo',w.project.to_dict()==before)
        original=out/'整首声学原稿.sgproj';save_project(w.project,original);home=w.home;w.close();app.processEvents()
        caches={str(f):f.stat().st_mtime_ns for f in (home/'alignment-cache').glob('*/aligned.json')}
        w=StudioWindow(home,test=True);w.playback.audio.setMuted(True);w.history=History(load_project(original));w.current=0;w.show();w.refresh();w.set_stage(1)
        def resume():
            d=next(d for d in w.findChildren(ResumeDraftDialog) if d.isVisible());d.continue_button.click()
        QTimer.singleShot(30,resume);w.resume_draft(workflow)
        check('staged_singing_completed_workflow_reopens_from_checkpoint',wait(lambda:not w.api.busy and w.pending is not None,15000) and w.pending['result']['workflow']['id']==workflow)
        check('staged_singing_resume_does_not_rewrite_voice_cache',caches=={str(f):f.stat().st_mtime_ns for f in (home/'alignment-cache').glob('*/aligned.json')})
        def manual():
            d=next(d for d in w.findChildren(ReviewDialog) if d.isVisible());d.table.setCurrentCell(3,1);d.manual_button.click()
        QTimer.singleShot(30,manual);w.review_pending()
        check('staged_singing_failed_row_opens_unified_manual_editor',w.pending is None and w.stage==2 and w.line.id=='intentional-invalid-reading' and w.timeline.word==-1)
        check('staged_singing_shelved_suggestions_are_recoverable',any(json.loads(f.read_text(encoding='utf-8')).get('action')=='review_saved' for f in (home/'desktop-tasks').glob('*/request.json')))
        w.grab().save(str(out/'staged-singing-manual-handoff.png'))
    finally:w.close();app.processEvents()
