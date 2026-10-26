import pytest
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.project import History
from test_time_correction import window,song


def settle(qapp):qapp.processEvents();QTest.qWait(60);qapp.processEvents()
def in_center(w,control):
    viewport=w.workspace_scroll.viewport();pos=control.mapTo(viewport,QPoint())
    return viewport.rect().contains(control.rect().translated(pos))


def test_calibration_default_has_large_video_and_resize_keeps_the_choice(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict()
    for width,height in [(1280,800),(960,680),(1460,940)]:
        w.resize(width,height);settle(qapp)
        assert w.view_choice.currentIndex()==0 and w.playback.isVisible() and w.playback.height()>=280
        assert w.transport_controls.visibleRegion().boundingRect().height()>=30 and w.project.to_dict()==before


def test_user_view_choice_is_saved_per_stage_and_survives_reopening(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();w.view_choice.setFocus();QTest.keyClick(w.view_choice,Qt.Key.Key_Down);settle(qapp)
    assert w.view_choice.currentIndex()==1 and w.preferences.data['stage_views']['2']==1
    w.resize(960,680);w.set_stage(3);w.set_stage(2);settle(qapp)
    assert w.view_choice.currentIndex()==1 and not w.playback.isVisible() and w.project.to_dict()==before
    w.close();other=StudioWindow(tmp_path/'home',test=True);other.history=History(song());other.current=0;other.refresh();other.set_stage(2);other.show();settle(qapp)
    assert other.view_choice.currentIndex()==1 and not other.playback.isVisible()


@pytest.mark.parametrize('raw',[{'2':True},{'2':'1'},{'2':99},[],None])
def test_invalid_saved_layout_does_not_hide_video_or_break_the_workflow(qapp,tmp_path,raw):
    w=window(qapp,tmp_path);w.preferences.set('stage_views',raw);w.set_stage(2);settle(qapp)
    assert w.view_choice.currentIndex()==0 and w.playback.isVisible()


def test_every_center_region_can_be_reached_without_clipping_and_transport_stays_fixed(qapp,tmp_path):
    w=window(qapp,tmp_path);w.resize(960,680);w.display_ribbon_toggle.setChecked(True);settle(qapp)
    fixed={name:getattr(w,name).mapTo(w,QPoint()) for name in ('transport_controls','seek_controls')}
    before=w.project.to_dict()
    for control in (w.playback,w.timeline,w.audio_controls,w.display_ribbon):
        w.workspace_scroll.ensureWidgetVisible(control,2,2);settle(qapp);assert in_center(w,control)
        assert all(getattr(w,name).mapTo(w,QPoint())==pos for name,pos in fixed.items())
    assert w.workspace_scroll.horizontalScrollBar().maximum()==0 and w.project.to_dict()==before


def test_timing_entry_reveals_axis_and_style_display_entry_reveals_ribbon(qapp,tmp_path):
    w=window(qapp,tmp_path);w.resize(960,680);settle(qapp);w.workspace_scroll.verticalScrollBar().setValue(0);w.quick_timing.click();settle(qapp)
    assert in_center(w,w.timeline)
    before=w.project.to_dict();w.set_stage(3);w.display_axis_button.click();settle(qapp)
    assert w.view_choice.currentIndex()==0 and in_center(w,w.timeline) and in_center(w,w.display_ribbon) and w.project.to_dict()==before
    w.preview_display_boundary(w.current,'start');settle(qapp);assert in_center(w,w.playback)


def test_queued_center_navigation_is_stopped_on_close(qapp,tmp_path):
    w=window(qapp,tmp_path);w.reveal_center_widget(w.timeline);assert w.center_reveal_timer.isActive()
    w.close();settle(qapp)
    assert not w.center_reveal_timer.isActive() and w._center_reveal_widget is None and w.closing


def test_returning_to_calibration_reveals_axis_when_view_choice_is_unchanged(qapp,tmp_path):
    w=window(qapp,tmp_path);w.resize(960,620);settle(qapp);before=w.project.to_dict()
    assert w.view_choice.currentIndex()==0
    w.workspace_scroll.verticalScrollBar().setValue(0);settle(qapp);assert not in_center(w,w.timeline)
    w.set_stage(2);settle(qapp)
    assert w.view_choice.currentIndex()==0 and in_center(w,w.timeline) and w.project.to_dict()==before


def test_returning_to_calibration_preserves_explicit_video_only_choice(qapp,tmp_path):
    w=window(qapp,tmp_path);w.view_choice.setFocus()
    QTest.keyClick(w.view_choice,Qt.Key.Key_Down);QTest.keyClick(w.view_choice,Qt.Key.Key_Down);settle(qapp);before=w.project.to_dict()
    assert w.preferences.data['stage_views']['2']==2
    w.set_stage(3);w.set_stage(2);settle(qapp)
    assert w.view_choice.currentIndex()==2 and w.playback.isVisible() and not w.timeline.isVisible()
    assert w._center_reveal_widget is None and w.project.to_dict()==before


@pytest.mark.parametrize('height',[620,680])
@pytest.mark.parametrize('view',[0,1])
def test_workflow_toggle_keeps_current_audio_axis_wholly_visible(qapp,tmp_path,height,view):
    w=window(qapp,tmp_path);w.resize(960,height);w.view_choice.setCurrentIndex(view);w.reveal_center_widget(w.timeline);settle(qapp)
    before=w.project.to_dict();assert in_center(w,w.timeline)
    for _ in range(4):
        w.workflow_toggle.click();settle(qapp)
        assert in_center(w,w.timeline) and w.view_choice.currentIndex()==view and w.project.to_dict()==before
    assert not w.workflow_toggle.isChecked()


@pytest.mark.parametrize('view',[0,2])
def test_workflow_toggle_respects_video_focus_and_video_only_choice(qapp,tmp_path,view):
    w=window(qapp,tmp_path);w.resize(960,680);w.view_choice.setCurrentIndex(view);settle(qapp)
    w.workspace_scroll.verticalScrollBar().setValue(0);settle(qapp);before=w.project.to_dict()
    assert not w.timeline.visibleRegion().contains(w.timeline.rect().center())
    for _ in range(2):
        w.workflow_toggle.click();settle(qapp)
        assert w.workspace_scroll.verticalScrollBar().value()==0 and w.view_choice.currentIndex()==view
        assert w._center_reveal_widget is None and w.project.to_dict()==before
