from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from shengao.romanization_dialog import RomanizationDialog
from test_reading_candidates_workflow import reading_window


def test_dialog_manual_preview_and_cancel_do_not_change_project(reading_window):
    w=reading_window;before=w.project.to_dict();d=RomanizationDialog(w.project,0,0,w);d.mode.setCurrentIndex(d.mode.findData('manual'));d.manual.setText('ni-n-ki')
    assert d.apply.isEnabled() and d.result_lines[0].units[0].romaji=='ni-n-ki' and w.project.to_dict()==before;d.reject()


def test_actual_apply_source_and_one_undo_keep_human_axis_and_confirmation(reading_window):
    w=reading_window;before=w.project.to_dict()
    def choose():
        d=QApplication.activeModalWidget();d.mode.setCurrentIndex(d.mode.findData('manual'));d.manual.setText('NINKI');d.accept()
    QTimer.singleShot(0,choose);assert w.edit_romanization()
    assert w.line.units[0].romaji=='NINKI' and w.line.units[0].reading_options['romaji']['mode']=='manual'
    assert w.line.reviewed and w.project.checks['line']['reading'] and w.line.units[0].highlights[1].fixed_edges==['start']
    w.undo();assert w.project.to_dict()==before


def test_current_word_restore_auto_and_global_defaults_are_explicit(reading_window):
    w=reading_window;d=RomanizationDialog(w.project,0,0,w);d.system.setCurrentIndex(d.system.findData('kunrei'));d.default.setChecked(True)
    assert d.result_preferences['romaji']['system']=='kunrei' and d.result_lines[0].units[0].romaji=='ninki'
    assert w.project.reading_preferences=={};d.reject()
