from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from studio_backend.model import LyricLine,Unit,Highlight
from shengao.ruby_dialog import RubyDialog
from shengao.project import Project
from test_reading_candidates_workflow import reading_window


def test_dialog_real_preview_is_readonly_and_cancel_keeps_time(reading_window,qapp):
    w=reading_window;before=w.project.to_dict();position=w.playback.canvas.position;d=RubyDialog(w.project,0,0,w)
    d.mode.setCurrentIndex(d.mode.findData('whole'));d.render_preview()
    assert not d.picture.pixmap().isNull() and '区域放大' in d.caption.text() and w.project.to_dict()==before and w.playback.canvas.position==position
    d.reject();assert d.renderer.closed and w.project.to_dict()==before


def test_actual_apply_and_undo_keep_fixed_axis_and_confirmation(reading_window):
    w=reading_window;before=w.project.to_dict()
    def choose():
        d=QApplication.activeModalWidget();assert isinstance(d,RubyDialog);d.mode.setCurrentIndex(d.mode.findData('whole'));d.accept()
    QTimer.singleShot(0,choose);assert w.edit_ruby_correspondence()
    assert w.line.units[0].reading_options['ruby']=={'mode':'whole'} and w.line.reviewed and w.project.checks['line']['reading']
    assert w.line.units[0].highlights[1].start==1210 and w.line.units[0].highlights[1].fixed_edges==['start']
    w.undo();assert w.project.to_dict()==before


def test_invalid_custom_span_stays_in_dialog_and_does_not_apply(reading_window):
    w=reading_window;d=RubyDialog(w.project,0,0,w);d.mode.setCurrentIndex(d.mode.findData('custom'));d.spans=[[0,2,0,1]];d.refresh()
    assert not d.apply.isEnabled() and d.candidate is None
    d.reject()


def test_user_can_edit_two_real_character_ranges_with_visible_controls(reading_window):
    w=reading_window;line=LyricLine('stars','お星様',1000,3000,[Unit('お星様',1000,3000,'おほしさま')]);d=RubyDialog(Project(lines=[line]),0,0,w)
    d.mode.setCurrentIndex(d.mode.findData('custom'));d.table.setCurrentCell(0,0)
    for field,value in zip(d.fields,[2,2,2,3]):field.setValue(value)
    d.update.click();assert not d.apply.isEnabled()
    for field,value in zip(d.fields,[3,3,4,5]):field.setValue(value)
    d.add.click();assert d.apply.isEnabled();d.accept()
    assert d.result_line.units[0].reading_options['ruby']['spans']==[[1,2,1,3],[2,3,3,5]]
