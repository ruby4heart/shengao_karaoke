"""Actual TIFA between two public human positions, using the visible workflow."""
import copy
import json
import statistics
from PySide6.QtCore import QTimer
from .paths import ASSETS
from .project import Project,History,save_project,load_project
from .guide_dialog import GuideDialog
from .subtitles import compose
from .subtitle_files import export_subtitle
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.provenance import create


def exercise(app,StudioWindow,out,check,wait):
    reference=json.loads((ASSETS/'alignment-demo/sample.json').read_text(encoding='utf-8'))
    refs=reference['mora'];parts=[]
    # Outside is a controlled retained draft. Only the middle run is offset,
    # and only its first start / last end are supplied as human constraints.
    for n,m in enumerate(refs):
        offset=30 if 4<=n<23 else 0
        a,b=round(m['start'])+offset,round(m['end'])+offset
        parts.append(Highlight(m['kana'],a,b,'estimated',create('estimated',a,b,method='controlled_public_reference_draft')))
    text=reference['kana'];line=LyricLine('guided-public',text,parts[0].start-100,parts[-1].end+150,
        [Unit(text,parts[0].start,parts[-1].end,text,highlights=parts)],kana=text)
    points=[dict(unit=0,highlight=4,edge='start',time=round(refs[4]['start'])),dict(unit=0,highlight=22,edge='end',time=round(refs[22]['end']))]
    w=StudioWindow(out/'guided-home',test=True);w.playback.audio.setMuted(True);w.show();seen={}
    def schedule(fn):
        def safe():
            dialog=next(d for d in w.findChildren(GuideDialog) if d.isVisible())
            try:fn(dialog)
            except Exception as error:
                seen['error']=type(error).__name__+': '+str(error);dialog.reject()
        QTimer.singleShot(30,safe)
    try:
        w.history=History(Project(title='人工点之间的公开演唱验收',lines=[line],checks={line.id:{'reading':True}}));w.current=0;w.refresh()
        w.load_media(ASSETS/'alignment-demo/pjs056_song.wav')
        check('guided_public_audio_and_original_spectrum_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000))
        w.set_stage(2);before=w.project.to_dict()
        def draft(d):
            for p in points:
                d.mora.setCurrentIndex(p['highlight']);d.edge.setCurrentIndex(d.edge.findData(p['edge']));d.time.setValue(p['time']);d.add.click()
            d.resize(650,430);app.processEvents()
            seen['footer']=d.buttons.geometry().bottom()<=d.height() and d.run.isEnabled()
            seen['own_audio']=d.timeline.audio is not w.timeline.audio and d.timeline.audio.handle!=w.timeline.audio.handle
            seen['markers']=d.timeline.guide_points==points
            d.grab().save(str(out/'guided-position-options.png'));d.reject()
        schedule(draft);w.open_acoustic_guides()
        check('guided_scrolled_small_dialog_has_reachable_footer',seen.get('footer') and not seen.get('error'))
        check('guided_timeline_owns_audio_and_marks_exact_human_positions',seen.get('own_audio') and seen.get('markers') and w.timeline.audio.handle)
        check('guided_cancel_preserves_axis_and_durable_points',w.project.to_dict()==before and w.guide_draft_path().is_file())
        def resume(d):
            seen['restored']=d.points==points
            d.accept()
        schedule(resume);w.open_acoustic_guides()
        check('guided_reopen_restores_two_points_and_starts_local_job',seen.get('restored') and w.source_job is not None)
        check('guided_real_tifa_returns_reviewable_candidate',wait(lambda:w.source_job is None,90000) and w.pending is not None)
        check('guided_model_never_applies_or_confirms_automatically',w.project.to_dict()==before)
        prepared=w.pending['plan'];candidate=w.pending['result']['suggestions'][0]
        actual=candidate['units'][0]['highlights'];runs=candidate['timing_evidence']['runs']
        check('guided_actual_model_computes_only_19_middle_mora',len(prepared['jobs'])==1 and len(runs)==1 and len(runs[0]['mora'])==19 and all(h['source']=='acoustic' for h in actual[4:23]))
        check('guided_two_human_edges_exact_other_edges_unconfirmed',actual[4]['start']==points[0]['time'] and actual[22]['end']==points[1]['time'] and actual[4]['fixed_edges']==['start'] and actual[22]['fixed_edges']==['end'] and not candidate['reviewed'])
        check('guided_outside_mora_kept_byte_for_byte',actual[:4]==before['lines'][0]['units'][0]['highlights'][:4] and actual[23:]==before['lines'][0]['units'][0]['highlights'][23:])
        w.apply_suggestions([candidate]);check('guided_review_adoption_keeps_reading_confirmation',w.pending is None and w.project.checks[line.id]['reading'] and not w.line.reviewed)
        target=out/'固定位置局部重算.sgproj';save_project(w.project,target)
        ass=out/'固定位置局部重算.ass';export_subtitle(w.project,ass)
        check('guided_project_and_ass_roundtrip_preserve_fixed_edges',load_project(target).to_dict()==w.project.to_dict() and compose(load_project(ass))==compose(w.project))
        w.granularity.setCurrentIndex(w.granularity.findData('mora'));w.select_target(0,4)
        times=w.selected_times();w.release_acoustic_guide()
        check('guided_unfix_does_not_move_time_or_selection',w.selected_times()==times and not w.line.units[0].highlights[4].fixed_edges)
        w.undo();check('guided_unfix_is_undoable',w.line.units[0].highlights[4].fixed_edges==['start'])
        w.undo();check('guided_entire_adoption_is_one_undo',w.project.to_dict()==before)
        error=[actual[n]['start']-round(refs[n]['start']) for n in range(5,23)]
        report={'passed':True,'actual_inferred_mora':19,'fixed_human_edges':points,'jobs':prepared['jobs'],
                'unfixed_onset_count':len(error),'unfixed_onset_abs_mean_ms':statistics.mean(abs(v) for v in error),
                'unfixed_onset_abs_max_ms':max(abs(v) for v in error),'unfixed_onset_error_ms':error,
                'engine':candidate['timing_evidence']['engine'],'model_sha256':candidate['timing_evidence']['model_sha256'],
                'interpretation':'Controlled public PJS056 draft with two manual positions; remaining middle onsets are generated by actual TIFA. Outside uses retained public reference-derived data. Training overlap unknown; not independent MV accuracy or finished lyrics.'}
        (out/'guided-alignment-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:w.close();app.processEvents()
