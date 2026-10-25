import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.romanization import set_manual
from studio_backend.reading_options import set_ruby
from shengao.project import Project,History,save_project,load_project
from shengao.subtitle_files import export_subtitle
from shengao.subtitles import compose
from test_reading_candidates_workflow import reading_window


@pytest.fixture
def mora_window(reading_window,qapp):
    w=reading_window
    line=LyricLine('mora','今日も',1000,4000,[Unit('今日',1000,3000,'きょう',highlights=[Highlight('きょう',1000,3000,'manual')]),Unit('も',3200,4000,'も',highlights=[Highlight('も',3200,4000,'manual',fixed_edges=['start'])])],translation='今天也',reviewed=True)
    line=set_ruby(set_manual(line,0,'KYOH'),0,{'mode':'whole'})
    w.history=History(Project(media=w.project.media,duration=6000,lines=[line],checks={'mora':{'reading':True}}));w.current=0;w.refresh()
    w.granularity.setCurrentIndex(w.granularity.findData('mora'));w.select_target(0,0);w.mora_editing.toggle.setChecked(True);qapp.processEvents()
    return w


def test_actual_inline_split_preview_adopt_and_undo_keep_reading_and_neighbor(mora_window):
    w=mora_window;p=w.mora_editor;before=w.project.to_dict()
    assert p.split.isEnabled() and p.cut.currentText()=='きょ │ う'
    p.split.click();assert p.apply.isEnabled() and '1 个估算' in p.status.text() and w.project.to_dict()==before
    p.apply.click();parts=w.line.units[0].highlights
    assert [(h.kana,h.start,h.end) for h in parts]==[('きょ',1000,2000),('う',2000,3000)]
    assert parts[0].fixed_edges==['start'] and parts[1].fixed_edges==['end'] and not w.line.reviewed and w.project.checks['mora']['reading']
    assert w.line.units[0].reading_options==before['lines'][0]['units'][0]['reading_options'] and w.line.units[0].romaji=='KYOH'
    assert w.line.to_dict()['units'][1]==before['lines'][0]['units'][1]
    w.undo();assert w.project.to_dict()==before


def test_playhead_is_only_used_after_explicit_control_and_becomes_internal_pin(mora_window):
    w=mora_window;p=w.mora_editor;w.playback.canvas.position=2180;p.use_playhead.click()
    assert p.fixed.isChecked() and p.time.value()==2180
    p.split.click();p.apply.click();left,right=w.line.units[0].highlights
    assert left.end==right.start==2180 and left.fixed_edges==right.fixed_edges==['start','end']


def test_inline_merge_requires_separate_manual_and_gap_choices(mora_window):
    w=mora_window;w.line.units[0].highlights=[Highlight('きょ',1000,1800,'manual'),Highlight('う',1900,3000,'manual')];w.refresh();w.select_target(0,0);p=w.mora_editor;before=w.project.to_dict()
    p.merge.click();assert not p.apply.isEnabled() and '人工边界' in p.status.text()
    p.allow_manual.setChecked(True);p.merge.click();assert not p.apply.isEnabled() and '100 ms' in p.status.text()
    p.allow_gaps.setChecked(True);p.merge.click();assert p.apply.isEnabled() and '100 ms' in p.status.text() and w.project.to_dict()==before
    p.listen.click();assert w.playback.range==(880,3120)
    p.apply.click();assert len(w.line.units[0].highlights)==1 and w.line.units[0].highlights[0].fixed_edges==['start','end']
    w.undo();assert w.project.to_dict()==before


def test_fixed_internal_point_cannot_be_removed_by_allow_checkboxes(mora_window):
    w=mora_window;p=w.mora_editor;p.use_playhead.click();p.time.setValue(2100);p.split.click();p.apply.click();p=w.mora_editor
    p.allow_manual.setChecked(True);p.allow_gaps.setChecked(True);p.merge.click()
    assert not p.apply.isEnabled() and '固定点' in p.status.text()


def test_advanced_character_split_and_reset_work_in_same_editor(mora_window):
    w=mora_window;p=w.mora_editor;p.advanced.setChecked(True);p.cut.setCurrentIndex(p.cut.findData(1));p.split.click();p.apply.click()
    assert [h.kana for h in w.line.units[0].highlights]==['き','ょう']
    p=w.mora_editor;p.reset.click();assert p.apply.isEnabled();p.apply.click()
    assert [h.kana for h in w.line.units[0].highlights]==['きょ','う'] and w.line.units[0].kana=='きょう' and w.line.units[0].romaji=='KYOH'


def test_confirmation_or_source_changes_reject_stale_preview(mora_window):
    w=mora_window;p=w.mora_editor;p.split.click();payload=copy.deepcopy(p.payload);w.project.checks['mora']['reading']=False;before=w.project.to_dict()
    assert not w.apply_mora_edit(payload) and w.project.to_dict()==before and '已变化' in w.status.text()


def test_forged_preview_cannot_move_other_word(mora_window):
    w=mora_window;p=w.mora_editor;p.split.click();payload=copy.deepcopy(p.payload);payload['preview']['units'][1]['end']-=50;before=w.project.to_dict()
    assert not w.apply_mora_edit(payload) and w.project.to_dict()==before and '参数不一致' in w.status.text()


def test_editing_parameters_invalidates_the_previous_adoption(mora_window):
    p=mora_window.mora_editor;p.split.click();assert p.apply.isEnabled()
    p.fixed.setChecked(True);assert not p.apply.isEnabled() and p.payload is None
    p.split.click();assert p.apply.isEnabled();p.time.setValue(2080);assert not p.apply.isEnabled()


def test_highlight_group_history_and_human_pins_roundtrip_project_and_ass(mora_window,tmp_path):
    w=mora_window;p=w.mora_editor;p.split.click();p.apply.click();before=w.project.to_dict()
    for ext in ('sgproj','ass'):
        path=tmp_path/('手工音节.'+ext)
        if ext=='ass':export_subtitle(w.project,path)
        else:save_project(w.project,path)
        loaded=load_project(path)
        assert loaded.lines[0].to_dict()==w.line.to_dict() and loaded.checks==w.project.checks and compose(loaded)==compose(w.project)
    assert w.project.to_dict()==before


def test_locked_target_disables_changes_but_locked_neighbor_does_not(mora_window):
    w=mora_window;w.line.units[1].locked=True;w.refresh();w.select_target(0,0);assert w.mora_editor.split.isEnabled()
    w.line.units[0].locked=True;w.refresh_target();assert not w.mora_editor.split.isEnabled() and not w.mora_editor.reset.isEnabled()
