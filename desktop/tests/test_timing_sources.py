import copy
import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog
from shengao.app import StudioWindow
from shengao.project import Project,History,save_project,load_project,SCHEMA
from shengao.timing_sources import TimingSourceDialog
from shengao.time_transform import transform_project,TimeTransform
from shengao.subtitle_files import export_subtitle
from shengao.dialogs import ReviewDialog
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.provenance import create,summary
from studio_backend.japanese import add_mora


def sample():
    first=Unit('今日',1000,2000,'きょう',source='alignment',timing_origin=create('character',1000,2000,'elevenlabs','text_alignment'));add_mora(first)
    voice=Unit('歌',2000,2700,'うた',source='acoustic',timing_origin=create('acoustic',2000,2700,'tifa','phoneme_envelope','うた'))
    voice.highlights=[Highlight(k,a,b,'acoustic',create('acoustic',a,b,'tifa','phoneme_alignment',k)) for k,a,b in [('う',2000,2300),('た',2300,2700)]]
    last=Unit('う',2700,3000,'う',source='manual',timing_origin=create('manual',2700,3000,method='manual_input'));add_mora(last)
    return Project(duration=5000,lines=[LyricLine('a','今日歌う',1000,3000,[first,voice,last],kana='きょううたう')])


def window(qapp,tmp_path):
    w=StudioWindow(tmp_path/'home',test=True);w.history=History(sample());w.current=0;w.playback.audio.setMuted(True);w.show();w.refresh();w.set_stage(2);qapp.processEvents();return w


def test_sources_are_read_only_and_filter_audition_maps_to_real_mora(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();calls=[];w.playback.audition=lambda *v:calls.append(v)
    d=TimingSourceDialog(w.line,w.playback,0,0,w);d.show();qapp.processEvents()
    assert '估算音节' in d.details.toPlainText() and 'ElevenLabs' in d.details.toPlainText()
    d.filter.setCurrentIndex(2);d.listen.click();assert calls[-1][:2]==(880,1620)
    d.edit.click();assert d.result()==QDialog.DialogCode.Accepted and d.selection==(0,0)
    assert w.project.to_dict()==before and not w.history.dirty;w.close()


def test_voice_details_distinguish_analysis_track_from_current_audition(qapp,tmp_path):
    w=window(qapp,tmp_path);w.line.timing_evidence={'audio_role':'vocals'}
    d=TimingSourceDialog(w.line,w.playback,1,0,w)
    assert '声音依据使用：人声辅助' in d.details.toPlainText() and '当前音轨' in d.details.toPlainText()
    d.reject();w.close()


def test_source_button_handoff_selects_exact_word_and_mora_without_retiming(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict()
    def choose():
        d=next(d for d in w.findChildren(TimingSourceDialog) if d.isVisible())
        row=next(i for i,v in enumerate(d.values) if (v['word'],v['part'])==(1,1));d.table.setCurrentCell(row,1);d.edit.click()
    QTimer.singleShot(20,choose);w.timing_sources_button.click()
    assert (w.timeline.word,w.timeline.part)==(1,1) and '歌声候选' in w.timing_origin_info.text()
    assert (w.begin.value(),w.end.value())==(2300,2700) and w.project.to_dict()==before;w.close()


def test_bulk_shift_does_not_display_estimates_as_individually_calibrated(qapp,tmp_path):
    w=window(qapp,tmp_path);w.history=History(transform_project(w.project,[0],TimeTransform(offset=300)).project);w.refresh()
    w.select_target(0,0)
    assert '估算音节' in w.timing_origin_info.text() and '人工时间' not in w.timing_origin_info.text()
    assert '整体手动平移' in w.timing_origin_info.toolTip()
    before=w.project.to_dict();w.set_timing_confirmed(True)
    assert '已人工确认' in w.timing_origin_info.text() and w.project.lines[0].reviewed
    assert summary(w.line.units[0].highlights[0],True,True)['kind']=='estimated'
    w.undo();assert w.project.to_dict()==before;w.close()


def test_legacy_inspection_never_upgrades_or_modifies_old_timing(qapp,tmp_path):
    w=window(qapp,tmp_path);old=LyricLine('old','今日',1000,2000,[Unit('今日',1000,2000,'きょう',source='manual')]);w.history=History(Project(lines=[old]));w.refresh();before=w.project.to_dict()
    d=TimingSourceDialog(w.line,w.playback,0,-1,w)
    assert '旧版人工标记' in d.details.toPlainText() and w.project.to_dict()==before
    d.reject();assert 'timing_origin' not in json.dumps(old.to_dict());w.close()


def test_schema_eight_and_exported_ass_preserve_each_timing_basis(qapp,tmp_path):
    p=sample();target=tmp_path/'来源.sgproj';save_project(p,target);again=load_project(target)
    assert again.to_dict()==p.to_dict() and p.to_dict()['version']==SCHEMA==9
    ass=tmp_path/'来源.ass';export_subtitle(p,ass);restored=load_project(ass)
    assert [v.to_dict() for v in restored.lines]==[v.to_dict() for v in p.lines]


def test_plain_review_exposes_estimates_and_audition_before_adopting(qapp,tmp_path):
    w=window(qapp,tmp_path);d=ReviewDialog(w.project,{'suggestions':[w.line.to_dict()]},w.playback,w)
    assert d.table.columnCount()==5 and '估算' in d.table.item(0,4).text()
    assert '时间依据' in d.details.toPlainText() and d.acoustic_mora.count()==5
    assert any('估算音节' in d.acoustic_mora.itemText(i) for i in range(d.acoustic_mora.count()))
    d.reject();w.close()
