import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.romanization import DEFAULT,set_manual,apply_rules
from studio_backend.reading_options import set_ruby
from shengao.tail_model import replace_mora
from shengao.segmentation_dialog import regroup
from test_reading_candidates_workflow import reading_window


@pytest.mark.parametrize('mode,expected',[('manual','SU-MANUAL'),('auto','zu'),('legacy','SOO')])
def test_tail_reading_edit_respects_romanization_source_and_fixed_axis(mode,expected):
    old=LyricLine('tail','す',1000,2000,[Unit('す',1000,2000,'す','SOO',highlights=[Highlight('す',1000,2000,'manual',fixed_edges=['start'])],reading_source='manual')])
    if mode=='manual':old=set_manual(old,0,'SU-MANUAL')
    elif mode=='auto':old=apply_rules(old,[0],DEFAULT,True)['line']
    value=replace_mora(old,0,0,'ず')
    assert value.units[0].romaji==expected and value.units[0].kana=='ず'
    assert (value.units[0].highlights[0].start,value.units[0].highlights[0].end,value.units[0].highlights[0].fixed_edges)==(1000,2000,['start'])
    assert value.units[0].reading_options['romaji']['mode']==('auto' if mode=='auto' else 'manual')


def ruby_line():return set_ruby(set_manual(LyricLine('ruby','お星様',1000,3000,[Unit('お星様',1000,3000,'おほしさま','ohoshisama')]),0,'STAR'),0,{'mode':'whole'})


def test_advanced_range_rebuild_keeps_unchanged_ruby_and_manual_roman_settings():
    old=ruby_line();value=regroup(old,[],2000,4000)
    assert (value.start,value.end)==(2000,4000)
    assert value.units[0].reading_options==old.units[0].reading_options and value.units[0].romaji=='STAR'


def test_advanced_resegmentation_cannot_discard_manual_ruby_mapping():
    old=ruby_line();before=copy.deepcopy(old.to_dict())
    with pytest.raises(ValueError,match='手工注音对应'):regroup(old,[1])
    assert old.to_dict()==before


def test_tail_reading_change_switches_to_generated_style_and_undo_keeps_original_ass(reading_window):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from shengao.subtitles import compose
    w=reading_window;raw=compose(w.project);w.project.source_ass=raw;w.project.source_ass_active=True;w.refresh();before=w.project.to_dict()
    def choose():
        d=QApplication.activeModalWidget();d.reading.setText('け');d.apply_reading();d.accept_changes()
    QTimer.singleShot(0,choose);w.inspect_tail()
    assert w.line.units[0].kana=='にんけ' and not w.project.source_ass_active and w.project.source_ass==raw
    w.undo();assert w.project.to_dict()==before
