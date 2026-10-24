"""Real singing after a real bulk move, with explicit protection release."""
import copy
import json
import statistics
from pathlib import Path
from PySide6.QtCore import QTimer
from .paths import ASSETS
from .project import Project,History,save_project,load_project
from .time_transform import TimeTransform,transform_project
from .recalculation_dialog import RecalculationDialog
from .dialogs import ReviewDialog
from .subtitles import compose
from .subtitle_files import export_subtitle
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.provenance import create
from studio_backend.acoustic import plan


def exercise(app,StudioWindow,out,check,wait):
    reference=json.loads((ASSETS/'alignment-demo/sample.json').read_text(encoding='utf-8'))
    refs=reference['mora'][4:23];manual_index=9;offset=700
    a=round(refs[0]['start']);b=round(refs[-1]['end']);ma=round(refs[manual_index]['start']);mb=round(refs[manual_index]['end'])
    parts=[]
    for i,m in enumerate(refs):
        if i<manual_index:
            begin=a+round((ma-a)*i/manual_index);end=a+round((ma-a)*(i+1)/manual_index)
        elif i==manual_index:begin,end=ma,mb
        else:
            j=i-manual_index-1;n=len(refs)-manual_index-1
            begin=mb+round((b-mb)*j/n);end=mb+round((b-mb)*(j+1)/n)
        kind='manual' if i==manual_index else 'estimated'
        origin=create(kind,begin-offset,end-offset,method='public_reference_in_shifted_draft' if kind=='manual' else 'controlled_range_distribution')
        parts.append(Highlight(m['kana'],begin-offset,end-offset,kind,origin,['start'] if i==0 else []))
    text=''.join(h.kana for h in parts)
    line=LyricLine('recalc-public',text,a-100-offset,b+150-offset,[Unit(text,a-100-offset,b+150-offset,text,highlights=parts)],kana=text)
    w=StudioWindow(out/'recalculation-home',test=True);w.playback.audio.setMuted(True);w.show();seen={}
    def schedule(fn):
        def safe():
            dialog=next(d for d in w.findChildren(RecalculationDialog) if d.isVisible())
            try:fn(dialog)
            except Exception as error:seen['error']=type(error).__name__+': '+str(error);dialog.reject()
        QTimer.singleShot(30,safe)
    try:
        w.history=History(Project(title='整体校轴后重新计算内部',lines=[line],checks={line.id:{'reading':True}}));w.current=0;w.refresh()
        w.load_media(ASSETS/'alignment-demo/pjs056_song.wav')
        check('recalc_public_audio_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000))
        moved=transform_project(w.project,[0],TimeTransform(offset=offset)).project
        w.history=History(moved);w.line.reviewed=True;w.current=0;w.refresh();w.set_stage(2)
        before=w.project.to_dict()
        check('recalc_real_bulk_move_keeps_coarse_range',w.line.start==a-100 and w.line.end==b+150 and all(h.source=='manual' for h in w.line.units[0].highlights))
        protected=False
        try:plan(w.line)
        except ValueError:protected=True
        check('recalc_default_still_protects_confirmed_draft',protected)
        def choose(d):
            d.resize(650,430);app.processEvents()
            seen['initial']=not d.run.isEnabled() and not d.release.isChecked() and not d.reviewed.isChecked()
            seen['footer']=d.buttons.geometry().bottom()<=d.height()
            d.release.setChecked(True);seen['still_blocked']=not d.run.isEnabled()
            d.reviewed.setChecked(True);seen['explicit']=d.run.isEnabled() and len(d.prepared['recalculation']['released'])==18
            d.grab().save(str(out/'recalculation-options.png'));d.accept()
        schedule(choose);w.acoustic_button.click()
        check('recalc_same_button_requires_clear_choices',seen.get('initial') and seen.get('still_blocked') and not seen.get('error'))
        check('recalc_small_dialog_footer_and_exact_scope',seen.get('footer') and seen.get('explicit'))
        check('recalc_inference_does_not_clear_confirmation',w.source_job is not None and w.project.to_dict()==before and w.line.reviewed)
        check('recalc_actual_tifa_candidate_returns',wait(lambda:w.source_job is None,90000) and w.pending is not None)
        result=copy.deepcopy(w.pending['result']);candidate=result['suggestions'][0];actual=candidate['units'][0]['highlights']
        runs=candidate['timing_evidence']['runs'];raw=[m for run in runs for m in run['mora']]
        check('recalc_real_model_only_computes_18_unfixed_mora',len(runs)==2 and len(raw)==18 and len(candidate['timing_evidence']['recalculation']['applied'])==18)
        check('recalc_real_manual_interval_and_fixed_edge_kept',actual[manual_index]==before['lines'][0]['units'][0]['highlights'][manual_index] and actual[0]['start']==a and actual[0]['fixed_edges']==['start'])
        check('recalc_candidate_never_auto_applied',w.project.to_dict()==before and w.line.reviewed and not candidate['reviewed'])
        request=json.loads((Path(w.pending['folder'])/'request.json').read_text(encoding='utf-8'))
        d=ReviewDialog(w.project,result,w.playback,w);d.show();app.processEvents();d.check_all(True)
        check('recalc_confirmed_row_is_reviewable',d.apply_button.isEnabled() and len(d.selected())==1 and '明确允许' in d.details.toPlainText())
        d.grab().save(str(out/'recalculation-review.png'));w.apply_suggestions(d.selected());d.reject()
        check('recalc_adoption_resets_only_time_confirmation',w.pending is None and not w.line.reviewed and w.project.checks[line.id]['reading'] and w.line.start==before['lines'][0]['start'] and w.line.end==before['lines'][0]['end'])
        path=out/'整体校轴后重算.sgproj';save_project(w.project,path);ass=out/'整体校轴后重算.ass';export_subtitle(w.project,ass)
        check('recalc_project_and_ass_keep_release_evidence',load_project(path).to_dict()==w.project.to_dict() and compose(load_project(ass))==compose(w.project))
        from .guide_dialog import GuideDialog
        guide=GuideDialog(w.line,w.playback,w);guide.mora.setCurrentIndex(manual_index);guide.edge.setCurrentIndex(guide.edge.findData('end'));guide.add.click()
        check('recalc_manual_reference_bounds_guides_inside_coarse_word',guide.time.isReadOnly() and guide.prepared is not None and len(guide.prepared['jobs'])==1 and guide.prepared['jobs'][0]['start']==a and guide.prepared['jobs'][0]['end']==ma and guide.prepared['baseline']['units'][0]['start']==a-100)
        guide.reject()
        w.undo();check('recalc_one_undo_restores_confirmation_and_protection',w.project.to_dict()==before)
        def resume(d):seen['resumed']=d.release.isChecked() and d.reviewed.isChecked() and d.run.isEnabled();d.reject()
        schedule(resume);w.resume_acoustic_recalculation(request)
        check('recalc_saved_permission_request_reopens',seen.get('resumed'))
        check('recalc_resumed_cancel_preserves_draft',w.source_job is None and w.project.to_dict()==before)
        errors=[actual[i]['start']-round(refs[i]['start']) for i in range(len(refs)) if i not in (0,manual_index)]
        report={'passed':True,'actual_inferred_mora':18,'preserved_human_mora':1,'fixed_human_edges':1,'unfixed_onset_count':len(errors),
                'unfixed_onset_error_ms':errors,'unfixed_onset_abs_mean_ms':statistics.mean(abs(v) for v in errors),'unfixed_onset_abs_max_ms':max(abs(v) for v in errors),
                'engine':candidate['timing_evidence']['engine'],'model_sha256':candidate['timing_evidence']['model_sha256'],'bulk_offset_ms':offset,'new_api_calls':0,
                'interpretation':'Controlled public PJS056 draft: 700ms bulk move, range-distributed estimated internals, one public human interval and one fixed start. Actual TIFA computes the other 18 mora. Training overlap unknown; not independent MV accuracy or a finished project.'}
        (out/'recalculation-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:w.close();app.processEvents()
