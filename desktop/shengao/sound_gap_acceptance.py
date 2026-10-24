"""Review actual public singing output without another model/API request."""
import copy
import json
from PySide6.QtCore import QTimer
from studio_backend.provenance import create
from .paths import ASSETS
from .project import History,SCHEMA,save_project,load_project
from .sound_gap_dialog import SoundGapDialog,SoundGapOptions


def exercise(app,StudioWindow,out,check,wait):
    w=StudioWindow(out/'sound-gap-home',test=True);w.playback.audio.setMuted(True);w.show()
    try:
        p=load_project(out/'整首声学候选.sgproj');p.lines=p.lines[:3]
        # A controlled defect inside an existing retained vowel is not a new
        # human annotation or a claim about general model accuracy.
        h=p.lines[0].units[0].highlights[0];phone=p.lines[0].timing_evidence['runs'][0]['mora'][0]['phones'][-1]
        original_end=h.end
        check('sound_gap_actual_public_vowel_available',phone['phone'] in {'a','i','u','e','o'} and phone['end']==original_end and phone['end']-phone['start']>40)
        h.end-=40;h.source='estimated';h.timing_origin=create('estimated',h.start,h.end,method='controlled_fault')
        p.lines[0].units[0].source='estimated';w.history=History(p);w.current=0;w.refresh()
        w.load_media(ASSETS/'alignment-demo/pjs056_song.wav',edit=False)
        check('sound_gap_actual_public_audio_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000))
        w.set_stage(2);w.history.mark_saved();before=w.project.to_dict()
        options=SoundGapOptions(w.project,0,[],'original',w);options.show();app.processEvents()
        check('sound_gap_options_default_current_and_count',options.indices()==[0] and '1 句' in options.count.text())
        options.grab().save(str(out/'sound-gap-options.png'));options.reject()
        w.run_sound_gaps({'indices':[0,1,2],'maximum':2000,'join_lines':True})
        check('sound_gap_analysis_never_edits_original',w.source_job is not None and w.project.to_dict()==before)
        check('sound_gap_real_pcm_analysis_completes',wait(lambda:w.source_job is None and w.pending is not None,20000))
        pending=copy.deepcopy(w.pending);report=pending['result']['gap_report'];fault=next(v for v in report['gaps'] if v['left']==[0,0,0])
        pauses=[v for v in report['gaps'] if v['kind']=='line']
        check('sound_gap_retained_vowel_supports_controlled_defect',fault['status']=='continuous' and bool(fault['phoneme']))
        check('sound_gap_natural_interphrase_pauses_kept',len(pauses)==2 and all(v['status']!='continuous' for v in pauses))
        dialog=SoundGapDialog(w.project,report,w.playback,parent=w);dialog.show();app.processEvents()
        check('sound_gap_review_footer_reachable',dialog.apply_button.visibleRegion().boundingRect().height()==dialog.apply_button.height())
        dialog.listen();check('sound_gap_context_listen_includes_gap',w.playback.range==(max(0,fault['start']-250),fault['end']+250))
        dialog.grab().save(str(out/'sound-gap-review.png'))
        dialog.filter.setCurrentIndex(dialog.filter.findData('keep'))
        check('sound_gap_empty_filter_clears_actions',dialog.table.currentRow()==-1 and not dialog.listen_button.isEnabled() and not dialog.calibrate_button.isEnabled())
        dialog.reject();check('sound_gap_inspection_and_listen_read_only',w.project.to_dict()==before and not w.history.dirty)
        def accept():
            d=next(d for d in w.findChildren(SoundGapDialog) if d.isVisible());d.apply_button.click()
        QTimer.singleShot(30,accept);w.review_pending()
        check('sound_gap_content_verified_adoption_completes',wait(lambda:w.source_job is None and w.pending is None,20000))
        fixed=w.line.units[0].highlights[0]
        check('sound_gap_only_selected_tail_restored',fixed.end==original_end and [h.start for row in w.project.lines for u in row.units for h in u.highlights]==[h['start'] for row in before['lines'] for u in row['units'] for h in u['highlights']])
        check('sound_gap_not_human_confirmation',not w.line.reviewed and 'sound_gap' in fixed.timing_origin['operations'] and fixed.source!='manual')
        target=out/'声音空隙审核.sgproj';save_project(w.project,target)
        check('sound_gap_current_schema_save_roundtrip',SCHEMA==11 and load_project(target).to_dict()==w.project.to_dict())
        audit={'passed':True,'schema':SCHEMA,'controlled_defects':1,'restored':1,'natural_pauses':pauses,'binding':report['binding'],
               'origin':fixed.timing_origin,'result_sha256':report['result_sha256'],'new_inference':False,'new_api_calls':0,
               'interpretation':'One artificial 40ms gap inside an earlier actual PJS056 vowel. Natural interphrase boundaries preserved. Unknown training overlap; not general accuracy or human confirmation.'}
        (out/'sound-gap-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
        w.undo();check('sound_gap_adoption_is_one_undo',w.project.to_dict()==before)
        w.pending=pending
        QTimer.singleShot(30,lambda:next(d for d in w.findChildren(SoundGapDialog) if d.isVisible()).calibrate_button.click())
        w.review_pending()
        check('sound_gap_handoff_exact_mora_read_only',w.pending is None and w.granularity.currentData()=='mora' and (w.timeline.word,w.timeline.part)==(0,0) and w.project.to_dict()==before)
    finally:w.close();app.processEvents()
