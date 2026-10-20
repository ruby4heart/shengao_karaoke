import copy
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
from shengao.app import StudioWindow
from shengao.project import Project,History
from shengao.continuity_dialog import ContinuityDialog
from studio_backend.model import LyricLine,Unit,Highlight


def project():
    return Project(lines=[LyricLine('a','歌う',0,1000,[Unit('歌',0,400,kana='うた',highlights=[Highlight('う',0,150),Highlight('た',200,400)]),Unit('う',600,1000,kana='う')]),LyricLine('b','よ',1200,2000,[Unit('よ',1200,2000,kana='よ')])])


def window(qapp,tmp_path):
    w=StudioWindow(home=tmp_path/'home',test=True);w.history=History(project());w.current=0;w.show();w.refresh();return w


def test_ui_requests_enable_continuity_for_timing_only_and_remember_preference(qapp,tmp_path,monkeypatch):
    from shengao.theme import STYLE
    qapp.setStyleSheet(STYLE)
    w=window(qapp,tmp_path);requests=[];monkeypatch.setattr(w.api,'start',lambda r:requests.append(r))
    w.resize(960,680);w.set_stage(1);qapp.processEvents();assert w.pages.widget(1).horizontalScrollBar().maximum()==0
    w.start_api('segment',mode='mora');assert requests[-1]['gap_ms']==500 and requests[-1]['join_lines']
    w.continuous_timing.setChecked(False);w.start_api('segment',mode='mora');assert requests[-1]['gap_ms']==0
    w.continuous_timing.setChecked(True);w.start_api('refine',use_llm=False);assert requests[-1]['gap_ms']==0
    assert w.preferences.data['continuous_timing'];w.close()


def test_cleanup_preview_scope_and_threshold_are_reversible_before_apply(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();dialog=ContinuityDialog(w.project,0,w.playback,w)
    assert len(dialog.changes)==3 and {c['kind'] for c in dialog.changes}=={'line','word','mora'}
    assert w.project.to_dict()==before
    dialog.scope.setCurrentIndex(1);assert len(dialog.changes)==2 and dialog.result_lines[1]==w.project.lines[1]
    dialog.maximum.setValue(100);assert len(dialog.changes)==1 and dialog.changes[0]['kind']=='mora'
    dialog.reject();assert w.project.to_dict()==before;w.close()


def test_actual_cleanup_command_applies_once_and_undo_restores_all_gaps(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict()
    def apply():
        dialog=next(x for x in w.findChildren(ContinuityDialog) if x.isVisible());dialog.apply_button.click()
    QTimer.singleShot(20,apply);w.cleanup_auto_gaps()
    assert w.project.lines[0].end==1200 and w.project.lines[0].units[0].end==600
    assert len(w.history.undo_stack)==1
    w.undo();assert w.project.to_dict()==before
    w.redo();assert w.project.lines[0].units[0].highlights[0].end==200
    w.change_boundary(0,-1,0,650)
    assert w.line.units[0].end==w.line.units[1].start==650
    w.undo();assert w.line.units[0].end==w.line.units[1].start==600;w.close()


def test_confirmed_or_manual_project_has_no_cleanup_and_apply_disabled(qapp,tmp_path):
    w=window(qapp,tmp_path);w.project.lines[0].reviewed=True;w.project.lines[1].units[0].source='manual'
    dialog=ContinuityDialog(w.project,0,w.playback,w);assert not dialog.changes and not dialog.apply_button.isEnabled()
    dialog.reject();w.close()
