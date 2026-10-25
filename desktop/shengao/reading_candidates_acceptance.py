"""Actual inline editing and audio playback with explicitly synthetic lyrics."""
import copy,json
from .paths import ASSETS
from .project import Project,History,save_project,load_project
from .subtitle_files import export_subtitle
from .subtitles import compose
from studio_backend.model import LyricLine,Unit,Highlight


def exercise(app,StudioWindow,out,check,wait):
    parts=[Highlight(k,a,b,'manual') for k,a,b in [('に',1000,1100),('ん',1210,1400),('き',1400,1800)]]
    parts[1].fixed_edges=['start']
    line=LyricLine('reading-controlled','人気の街',900,3000,[Unit('人気',1000,1800,'にんき',highlights=parts),Unit('の街',1900,3000,'のまち')],reviewed=True)
    w=StudioWindow(out/'reading-candidates-home',test=True);w.playback.audio.setMuted(True);w.show()
    try:
        w.history=History(Project(title='合成练习：比较词典多读法',lines=[line],checks={line.id:{'reading':True}}));w.current=0;w.refresh();w.load_media(ASSETS/'demo/tutorial.mp4')
        check('reading_choices_actual_demo_audio_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000))
        w.set_stage(2);w.calibration_tabs.setCurrentIndex(1);w.granularity.setCurrentIndex(w.granularity.findData('words'));w.select_target(0,-1);app.processEvents()
        before=w.project.to_dict();panel=w.reading_candidates
        check('reading_choices_same_selected_word_inline',panel.isVisible() and '人気' in panel.title.text() and not panel.apply.isEnabled())
        check('reading_choices_actual_ipadic_alternatives',{'にんき','ひとけ'}<={v['kana'] for v in panel.data['choices']} and '不是歌声识别' in next(v for v in panel.data['choices'] if v['kana']=='にんき')['reasons'][1])
        panel.choices.setCurrentIndex(panel.choices.findData('ひとけ'))
        check('reading_choices_preview_does_not_edit_or_confirm',panel.apply.isEnabled() and '保留 3' in panel.change.text() and w.project.to_dict()==before)
        panel.listen.click();check('reading_choices_original_audio_range_with_context',w.playback.range==(820,1980));w.playback.stop()
        w.resize(900,620);w.show_editor_widget(panel.apply);app.processEvents();w.grab().save(str(out/'reading-candidates-inline.png'))
        check('reading_choices_small_window_adopt_is_reachable',panel.apply.isVisible() and panel.apply.mapTo(w,panel.apply.rect().bottomRight()).y()<w.height() and panel.width()<=w.width())
        panel.apply.click();candidate=w.line
        check('reading_choices_adoption_keeps_manual_and_fixed_times',candidate.units[0].kana=='ひとけ' and [(h.start,h.end,h.fixed_edges) for h in candidate.units[0].highlights]==[(1000,1100,[]),(1210,1400,['start']),(1400,1800,[])])
        check('reading_choices_neighbor_original_and_checks',candidate.text==line.text and candidate.to_dict()['units'][1]==before['lines'][0]['units'][1] and not candidate.reviewed and not w.project.checks[line.id]['reading'])
        target=out/'读音候选校对.sgproj';ass=out/'读音候选校对.ass';save_project(w.project,target);export_subtitle(w.project,ass)
        check('reading_choices_project_and_own_ass_keep_evidence',load_project(target).to_dict()==w.project.to_dict() and compose(load_project(ass))==compose(w.project) and load_project(ass).lines[0].reading_review['manual_choices'][-1]['chosen']=='ひとけ')
        w.undo();check('reading_choices_one_undo_restores_confirmed_axis',w.project.to_dict()==before)
        old={'original':copy.deepcopy(panel.data['original']),'context':copy.deepcopy(panel.context),'word':0,'kana':'ひとけ'};w.project.checks[line.id]['reading']=False;snapshot=w.project.to_dict()
        check('reading_choices_late_confirmation_change_rejects_old_choice',not w.apply_reading_candidate(old) and w.project.to_dict()==snapshot)
        w.calibration_tabs.setCurrentIndex(0);check('reading_choices_timing_mode_hides_extra_choices',panel.isHidden())
        guarded=LyricLine('guarded-choice','明日',900,2400,[Unit('明日',1000,2200,'あした',highlights=[Highlight('あ',1000,1300,'manual'),Highlight('し',1300,1700,'manual'),Highlight('た',1700,2200,'manual')])])
        w.history=History(Project(media=w.project.media,media_stamp=copy.deepcopy(w.project.media_stamp),duration=w.project.duration,lines=[guarded]));w.current=0;w.refresh();w.calibration_tabs.setCurrentIndex(1);w.select_target(0,-1)
        protected=w.project.to_dict();panel.choices.setCurrentIndex(panel.choices.findData('あす'))
        check('reading_choices_incompatible_mora_count_preserves_human_axis',not panel.apply.isEnabled() and '旧轴保持' in panel.change.text() and w.project.to_dict()==protected)
        (out/'reading-candidates-audit.json').write_text(json.dumps({'passed':True,'actual_qt':True,'actual_audio_source':'bundled synthetic tutorial.mp4','synthetic_lyrics':True,'actual_dictionary':'pinned Janome IPADIC exact-surface alternatives','audition_range':[820,1980],'preserved_manual_intervals':3,'preserved_fixed_edges':1,'new_api_calls':0,'human_singing_accuracy':False,'interpretation':'Inline UI, actual synthetic audio range, dictionary provenance, manual/fixed protection, project/ASS, stale choice and undo. Synthetic text and tones do not prove sung pronunciation.'},ensure_ascii=False,indent=2),encoding='utf-8')
    finally:w.close();app.processEvents()
