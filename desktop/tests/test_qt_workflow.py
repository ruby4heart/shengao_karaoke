import time
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.project import History,Project
from shengao.theme import STYLE

def wait(qapp,fn,seconds=12):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        qapp.processEvents();QTest.qWait(20)
        if fn():return True
    return False

def window(qapp,tmp_path,project):
    qapp.setStyleSheet(STYLE);w=StudioWindow(home=tmp_path/'home',test=True);w.history=History(project);w.current=0;w.resize(1280,800);w.show();w.refresh(True);w.set_stage(2);qapp.processEvents();return w

def test_real_qt_drag_is_one_undo_step(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);t=w.timeline;before=w.line.to_dict();size=len(w.history.undo_stack)
    x=round(t.tx(w.line.units[0].end));destination=x+round(100/t.pixel_ms);y=t.audio_top+80
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,QPoint(x,y))
    QTest.mouseMove(t,QPoint(destination,y));QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,QPoint(destination,y))
    qapp.processEvents();assert w.line.units[0].end!=before['units'][0]['end'];assert len(w.history.undo_stack)==size+1
    w.undo();assert w.line.to_dict()==before;w.close();qapp.processEvents()

def test_aeg_right_audition_middle_seek_and_ruler_pan(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.playback.audio.setMuted(True);w.playback.open(project.media)
    assert wait(qapp,lambda:w.playback.player.duration()>0)
    t=w.timeline;at=round(t.tx(3500));y=t.audio_top+90
    QTest.mouseClick(t,Qt.MouseButton.RightButton,Qt.KeyboardModifier.NoModifier,QPoint(at,y));assert w.playback.range==(3200,4000)
    w.playback.stop();QTest.mouseClick(t,Qt.MouseButton.MiddleButton,Qt.KeyboardModifier.NoModifier,QPoint(round(t.tx(2400)),y))
    assert abs(w.playback.player.position()-2400)<25
    old=t.left;QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(250,10));QTest.mouseMove(t,QPoint(150,10));QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(150,10))
    assert t.left>old;w.close();qapp.processEvents()

def test_offline_backend_in_new_process_review_and_stale_protection(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.start_api('segment',mode='mora')
    assert wait(qapp,lambda:not w.api.busy and w.pending is not None),w.status.text()
    values=w.pending['result']['suggestions'];assert values[0]['text']==project.lines[0].text
    w.apply_suggestions(values);assert w.line.units[0].highlights
    w.start_api('segment',mode='mora');assert wait(qapp,lambda:not w.api.busy and w.pending is not None)
    row=w.current;w.edit('concurrent manual edit',lambda p:setattr(p.lines[row],'translation','人工修改，不能被迟到结果覆盖'))
    w.apply_suggestions(w.pending['result']['suggestions']);assert w.line.translation=='人工修改，不能被迟到结果覆盖'
    w.close();qapp.processEvents()

def test_confirm_footer_visible_on_laptop_and_separate_reading_state(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);assert w.calibrate_footer.isVisible();assert w.calibrate_footer.visibleRegion().boundingRect().height()>20
    w.confirm_reading(True);assert w.project.checks[w.line.id]['reading'];assert not w.line.reviewed
    w.confirm_next();assert w.line.reviewed;w.undo();assert not w.line.reviewed
    w.close();qapp.processEvents()

def test_aeg_focused_audio_shortcuts_do_not_require_global_mode(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.playback.audio.setMuted(True);w.playback.open(project.media)
    assert wait(qapp,lambda:w.playback.player.duration()>0)
    w.timeline.setFocus();QTest.keyClick(w.timeline,Qt.Key.Key_R);assert w.playback.range==(1000,6000)
    QTest.keyClick(w.timeline,Qt.Key.Key_H);assert w.playback.range is None
    QTest.keyClick(w.timeline,Qt.Key.Key_Right);assert w.timeline.word==1 and w.playback.range==(3200,4000)
    QTest.keyClick(w.timeline,Qt.Key.Key_Q);assert w.playback.range==(2700,3200)
    QTest.keyClick(w.timeline,Qt.Key.Key_H);before=w.line.to_dict()
    QTest.keyClick(w.timeline,Qt.Key.Key_Plus,Qt.KeyboardModifier.KeypadModifier);assert w.line.units[1].end==before['units'][1]['end']+10
    w.undo();assert w.line.to_dict()==before
    w.close();qapp.processEvents()

def test_old_result_cannot_apply_to_replaced_media(qapp,tmp_path,project):
    from shengao.project import file_stamp
    w=window(qapp,tmp_path,project);original=w.line.to_dict()
    w.pending={'context':{'project':w.project.uid,'media':{'path':'old-media','size':10,'modified_ns':10}},'snapshots':{w.line.id:original}}
    suggestion=dict(original);suggestion['translation']='不应写入'
    w.apply_suggestions([suggestion]);assert w.line.to_dict()==original
    assert '不同' in w.status.text();w.close();qapp.processEvents()

def test_inline_translation_is_immediate_and_typing_is_one_undo(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.calibration_tabs.setCurrentIndex(1);old=w.line.translation;w.translation.setFocus();w.translation.selectAll()
    QTest.keyClicks(w.translation,'manual translation')
    assert w.line.translation=='manual translation'
    w.undo();assert w.line.translation==old;w.close();qapp.processEvents()

def test_save_commits_active_table_editor_and_rebuilds_romaji(qapp,tmp_path,project):
    from PySide6.QtWidgets import QLineEdit
    from shengao.project import load_project
    w=window(qapp,tmp_path,project);w.calibration_tabs.setCurrentIndex(1);item=w.units.item(0,1);w.units.editItem(item);qapp.processEvents();editor=qapp.focusWidget()
    assert isinstance(editor,QLineEdit);editor.setText('こんにち');w.path=tmp_path/'editing.sgproj'
    assert w.save();loaded=load_project(w.path)
    assert loaded.lines[0].units[0].kana=='こんにち';assert loaded.lines[0].units[0].romaji=='konnichi'
    w.close();qapp.processEvents()

def test_aeg_dialogue_mode_left_start_right_end_and_undo(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.granularity.setCurrentIndex(2);qapp.processEvents();t=w.timeline
    old=w.line.to_dict();y=t.audio_top+70
    QTest.mouseClick(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,QPoint(round(t.tx(900)),y))
    assert abs(w.line.start-900)<=10
    QTest.mouseClick(t,Qt.MouseButton.RightButton,Qt.KeyboardModifier.ShiftModifier,QPoint(round(t.tx(6200)),y))
    assert abs(w.line.end-6200)<=10
    w.undo();w.undo();assert w.line.to_dict()==old
    w.close();qapp.processEvents()
