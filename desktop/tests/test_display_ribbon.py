import copy
import pytest
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from shengao.display_timing import edit_context,bounded_window,change_display
from shengao.presentation import DisplayWindow,display_windows
from shengao.project import History,save_project,load_project
from shengao.subtitle_files import export_subtitle
from shengao.subtitles import compose
from test_time_correction import song,window


def without_display(value):
    result=copy.deepcopy(value)
    for line in result['lines']:line.pop('display_start',None);line.pop('display_end',None)
    return result


def test_edges_and_translation_never_clip_singing_or_exceed_media():
    line=song().lines[0];w=DisplayWindow(500,3000)
    assert bounded_window(line,w,15000,'start',9999)==(1000,3000)
    assert bounded_window(line,w,15000,'start',-9999)==(0,3000)
    assert bounded_window(line,w,15000,'end',0)==(500,1800)
    assert bounded_window(line,w,15000,'end',99999)==(500,15000)
    assert bounded_window(line,w,15000,'move',99999)==(1000,3500)
    assert bounded_window(line,w,15000,'move',-99999)==(0,2500)
    with pytest.raises(ValueError,match='演唱'):bounded_window(line,w,1200,'end',1400)


def test_one_edge_keeps_other_edge_automatic_and_all_human_content():
    p=song();before=p.to_dict();context=edit_context(p,0)
    change_display(p,0,600,1800,part='start',context=context)
    assert p.lines[0].display_start==600 and p.lines[0].display_end is None
    assert without_display(p.to_dict())==without_display(before)


@pytest.mark.parametrize('change',['reading','confirmation','other_time','mode','source'])
def test_late_edit_rejected_when_its_relevant_basis_changes(tmp_path,change):
    p=song();source=tmp_path/'source.bin';source.write_bytes(b'original');p.media=str(source);context=edit_context(p,0)
    if change=='reading':p.lines[0].translation='人工新译文'
    elif change=='confirmation':p.checks[p.lines[0].id]['reading']=False
    elif change=='other_time':p.lines[2].display_start=4500
    elif change=='mode':p.style.display_mode='alternating'
    else:source.write_bytes(b'replacement bytes')
    before=p.to_dict()
    with pytest.raises(ValueError,match='已变化'):change_display(p,0,600,2000,context=context)
    assert p.to_dict()==before


@pytest.mark.parametrize('mode',['locked','original_ass'])
def test_protected_display_edits_do_not_change_the_document(mode):
    p=song()
    if mode=='locked':p.lines[0].locked=True
    else:p.source_ass_active=True;p.source_ass='[Script Info]\nScriptType: v4.00+'
    before=p.to_dict()
    with pytest.raises(ValueError):change_display(p,0,500,2200)
    assert p.to_dict()==before


def test_display_edit_is_one_history_step_and_roundtrips_project_and_ass(tmp_path):
    p=song();h=History(p);before=p.to_dict();context=edit_context(p,0)
    assert h.apply('留屏',lambda value:change_display(value,0,500,2200,context=context))
    assert len(h.undo_stack)==1 and without_display(h.project.to_dict())==without_display(before)
    project=tmp_path/'留屏.sgproj';ass=tmp_path/'留屏.ass';save_project(h.project,project);export_subtitle(h.project,ass)
    assert load_project(project).to_dict()==h.project.to_dict() and compose(load_project(ass))==compose(h.project)
    h.undo();assert h.project.to_dict()==before


def show_ribbon(qapp,tmp_path):
    w=window(qapp,tmp_path);w.display_ribbon_toggle.setChecked(True);w.timeline.left=0;w.timeline.span=8000;w.timeline.invalidate();qapp.processEvents()
    assert w.display_ribbon.isVisible() and w.display_ribbon.width()==w.timeline.width()
    return w


def point(r,row,ms):return QPoint(round(r.x_at(ms)),round(r.row_rect(row).center().y()))


def test_actual_drag_previews_then_commits_once_and_undo_keeps_axis(qapp,tmp_path):
    w=show_ribbon(qapp,tmp_path);r=w.display_ribbon;before=w.project.to_dict();steps=len(w.history.undo_stack)
    start=display_windows(w.project)[0].start;a=point(r,0,start);b=point(r,0,start-300)
    QTest.mousePress(r,Qt.MouseButton.LeftButton,pos=a);QTest.mouseMove(r,b);qapp.processEvents()
    assert r.drag and w.project.to_dict()==before
    QTest.mouseRelease(r,Qt.MouseButton.LeftButton,pos=b);qapp.processEvents()
    assert r.drag is None and len(w.history.undo_stack)==steps+1 and w.line.display_start<start
    assert w.line.display_end is None and without_display(w.project.to_dict())==without_display(before)
    w.undo();assert w.project.to_dict()==before


def test_escape_and_late_confirmation_cancel_actual_drag(qapp,tmp_path):
    w=show_ribbon(qapp,tmp_path);r=w.display_ribbon;before=w.project.to_dict();start=display_windows(w.project)[0].start
    a=point(r,0,start);b=point(r,0,start-200)
    QTest.mousePress(r,Qt.MouseButton.LeftButton,pos=a);QTest.mouseMove(r,b);QTest.keyClick(r,Qt.Key.Key_Escape);QTest.mouseRelease(r,Qt.MouseButton.LeftButton,pos=b)
    assert r.drag is None and w.project.to_dict()==before
    QTest.mousePress(r,Qt.MouseButton.LeftButton,pos=a);QTest.mouseMove(r,b)
    w.edit('测试期间新确认',lambda p:p.checks[p.lines[0].id].update(reading=False));current=w.project.to_dict();steps=len(w.history.undo_stack)
    assert r.drag is None
    QTest.mouseRelease(r,Qt.MouseButton.LeftButton,pos=b)
    assert w.project.to_dict()==current and len(w.history.undo_stack)==steps


def test_keyboard_selects_display_edge_and_respects_singing(qapp,tmp_path):
    w=show_ribbon(qapp,tmp_path);r=w.display_ribbon;before=w.project.to_dict()
    QTest.keyClick(r,Qt.Key.Key_Home);QTest.keyClick(r,Qt.Key.Key_Left,Qt.KeyboardModifier.ShiftModifier)
    assert w.line.display_start==900 and w.line.display_end is None
    QTest.keyClick(r,Qt.Key.Key_End);QTest.keyClick(r,Qt.Key.Key_Right)
    assert w.line.display_end==1810 and without_display(w.project.to_dict())==without_display(before)


def test_neighbor_selection_preserves_common_view_and_double_click_is_readonly(qapp,tmp_path):
    w=show_ribbon(qapp,tmp_path);r=w.display_ribbon;before=w.project.to_dict();view=(w.timeline.left,w.timeline.span)
    point_next=point(r,1,2800);QTest.mouseClick(r,Qt.MouseButton.LeftButton,pos=point_next);qapp.processEvents()
    # Native resize math can differ by sub-nanosecond floating point noise;
    # the shared view is stable well below a pixel, all document data exact.
    assert w.current==1 and (w.timeline.left,w.timeline.span)==pytest.approx(view,abs=1e-6) and w.project.to_dict()==before
    target=display_windows(w.project)[1].end;QTest.mouseDClick(r,Qt.MouseButton.LeftButton,pos=point(r,1,target));qapp.processEvents()
    assert w.project.to_dict()==before and w.playback.canvas.position==target


def test_style_entry_opens_same_timeline_without_changing_document(qapp,tmp_path):
    w=window(qapp,tmp_path);w.set_stage(3);before=w.project.to_dict();w.display_axis_button.click();qapp.processEvents()
    assert w.stage==3 and w.display_ribbon.isVisible() and w.audio_group.isVisible() and w.project.to_dict()==before
