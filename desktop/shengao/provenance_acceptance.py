"""Inspect and calibrate actual TIFA output produced earlier in this self-test."""
import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog
from studio_backend.provenance import summary,rows
from .project import History,save_project,load_project,SCHEMA
from .paths import ASSETS
from .time_transform import transform_project,TimeTransform
from .timing_sources import TimingSourceDialog


def exercise(app,StudioWindow,out,check,wait):
    w=StudioWindow(out/'timing-source-home',test=True);w.playback.audio.setMuted(True);w.show()
    try:
        w.history=History(load_project(out/'整首声学候选.sgproj'));w.current=0;w.refresh();w.load_media(ASSETS/'alignment-demo/pjs056_song.wav',edit=False)
        check('timing_basis_public_audio_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000));w.set_stage(2);w.history.mark_saved();before=w.project.to_dict()
        values=[h for line in w.project.lines[:3] for u in line.units for h in u.highlights]
        check('timing_basis_37_real_voice_origins_and_ranges',len(values)==37 and all(h.timing_origin['kind']=='acoustic' and h.timing_origin['reference']==[h.start,h.end] and h.timing_origin['provider']=='tifa' for h in values))
        w.select_target(0,0);check('timing_basis_selected_voice_is_explicit','歌声候选' in w.timing_origin_info.text())
        d=TimingSourceDialog(w.line,w.playback,0,0,w);d.resize(960,560);d.show();app.processEvents()
        check('timing_basis_actual_voice_details_have_input_reading','本地歌声模型' in d.details.toPlainText() and '假名' in d.details.toPlainText())
        d.filter.setCurrentIndex(2);check('timing_basis_empty_filter_has_no_dangling_actions',d.current() is None and not d.listen.isEnabled() and not d.edit.isEnabled())
        d.filter.setCurrentIndex(3);d.grab().save(str(out/'timing-source-voice-details.png'))
        check('timing_basis_dialog_footer_reachable',d.edit.visibleRegion().boundingRect().height()==d.edit.height())
        d.reject();check('timing_basis_inspection_never_edits_project',w.project.to_dict()==before and not w.history.dirty)
        def choose():
            current=next(d for d in w.findChildren(TimingSourceDialog) if d.isVisible())
            index=next(i for i,v in enumerate(current.values) if (v['word'],v['part'])==(0,3));current.table.setCurrentCell(index,1);current.edit.click()
        QTimer.singleShot(25,choose);w.timing_sources_button.click()
        check('timing_basis_voice_details_handoff_to_exact_mora',(w.timeline.word,w.timeline.part)==(0,3) and w.project.to_dict()==before)
        w.edit('验收：本句整体平移',lambda p:setattr(p,'lines',transform_project(p,[0],TimeTransform(offset=200)).project.lines));w.select_target(0,0)
        moved=w.line.units[0].highlights[0]
        check('timing_basis_shift_keeps_original_voice_reference',moved.source=='manual' and moved.timing_origin['kind']=='acoustic' and moved.timing_origin['reference']==values[0].timing_origin['reference'] and 'shift' in moved.timing_origin['operations'])
        check('timing_basis_shift_not_claimed_as_individual_calibration','歌声候选' in w.timing_origin_info.text() and '人工时间' not in w.timing_origin_info.text())
        w.undo();check('timing_basis_shift_is_one_undo',w.project.to_dict()==before)
        w.select_target(0,0);w.timeline.focus_selection();w.seek_selection_preview();h=w.line.units[0].highlights[0];w.change_boundary(0,0,h.start+10,h.end)
        check('timing_basis_actual_mora_manual_adjustment_is_explicit','人工调整' in w.timing_origin_info.text() and summary(w.line.units[0].highlights[0],mora=True)['display_kind']=='manual')
        target=out/'时间来源与人工校对.sgproj';save_project(w.project,target);again=load_project(target)
        check('timing_basis_current_schema_roundtrips_original_and_edits',again.to_dict()==w.project.to_dict() and again.to_dict()['version']==SCHEMA==14)
        w.show_editor_widget(w.timing_origin_info);app.processEvents();w.grab().save(str(out/'timing-source-manual-axis.png'))
        audit={'schema':SCHEMA,'real_mora':37,'original_voice':values[0].timing_origin,'manual_result':w.line.units[0].highlights[0].timing_origin,
               'current_line':rows(w.line),'interpretation':'Origins refer to actual earlier TIFA inference on one public sample; manual movement and corrections are not new acoustic inference or a general accuracy claim.'}
        (out/'timing-provenance-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
        w.undo();check('timing_basis_manual_adjustment_is_one_undo',w.project.to_dict()==before)
    finally:w.close();app.processEvents()
