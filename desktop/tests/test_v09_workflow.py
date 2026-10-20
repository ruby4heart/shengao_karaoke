import copy
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit,QMessageBox
from shengao.app import StudioWindow
from shengao.project import History,save_project
from shengao.preferences import Preferences
from shengao.widgets import TimeEdit,parse_time
from shengao.theme import STYLE

def two_lines(project):
    other=copy.deepcopy(project.lines[0]);other.id='second-line';other.start+=6000;other.end+=6000
    for u in other.units:
        u.start+=6000;u.end+=6000
        for h in u.highlights:h.start+=6000;h.end+=6000
    project.lines.append(other);return project

def window(qapp,tmp_path,project):
    qapp.setStyleSheet(STYLE);w=StudioWindow(home=tmp_path/'home',test=True);w.history=History(project);w.current=0;w.show();w.refresh();w.set_stage(2);qapp.processEvents();return w

def edit_kana(qapp,w,text):
    w.calibration_tabs.setCurrentIndex(1)
    w.units.editItem(w.units.item(0,1));qapp.processEvents();editor=qapp.focusWidget();assert isinstance(editor,QLineEdit);editor.setText(text)

def test_time_input_understands_timecodes_seconds_and_explicit_milliseconds(qapp):
    edit=TimeEdit();edit.show();edit.setValue(123450);assert edit.text()=='02:03.450'
    edit.lineEdit().setText('01:23.450');QTest.keyClick(edit,Qt.Key.Key_Return);assert edit.value()==83450
    QTest.keyClick(edit,Qt.Key.Key_Up);assert edit.value()==83460
    edit.lineEdit().setText('12345ms');QTest.keyClick(edit,Qt.Key.Key_Return);assert edit.value()==12345
    assert parse_time('1:02:03.456')==3723456 and parse_time('12.5')==12500
    edit.close()

def test_switching_line_commits_reading_to_original_line(qapp,tmp_path,project):
    w=window(qapp,tmp_path,two_lines(project));before=w.project.lines[0].units[0].kana;edit_kana(qapp,w,'こんにち');w.move_line(1)
    assert w.current==1 and w.project.lines[0].units[0].kana=='こんにち'
    assert w.line.units[0].kana==before
    w.undo();assert w.project.lines[0].units[0].kana==before
    w.close()

def test_invalid_reading_prevents_navigation_without_changing_project(qapp,tmp_path,project):
    w=window(qapp,tmp_path,two_lines(project));before=w.project.to_dict();edit_kana(qapp,w,'今日');w.move_line(1)
    assert w.current==0 and w.project.to_dict()==before and '假名' in w.status.text()
    w.close()

def test_failed_open_after_discard_does_not_mark_current_work_saved(qapp,tmp_path,project,monkeypatch):
    w=window(qapp,tmp_path,project);w.edit('manual',lambda p:setattr(p,'title','尚未保存的内容'));w.save_recovery()
    bad=tmp_path/'broken.sgproj';bad.write_text('{invalid',encoding='utf-8')
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**kw:QMessageBox.StandardButton.Discard)
    assert not w.open_path(bad);assert w.history.dirty and w.project.title=='尚未保存的内容' and w.recovery_path().is_file()
    w.close()

def pending(w):
    values=[x.to_dict() for x in w.project.lines]
    w.pending={'result':{'suggestions':copy.deepcopy(values)},'snapshots':{x['id']:copy.deepcopy(x) for x in values}}
    return values

def test_partial_adoption_keeps_unselected_suggestions(qapp,tmp_path,project):
    w=window(qapp,tmp_path,two_lines(project));values=pending(w);suggestion=copy.deepcopy(values[0]);suggestion['translation']='已审核译文';w.apply_suggestions([suggestion])
    assert w.project.lines[0].translation=='已审核译文'
    assert w.pending and [x['id'] for x in w.pending['result']['suggestions']]==[values[1]['id']]
    w.close()

def test_invalid_suggestion_keeps_pending_result_and_original_text(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);values=pending(w);original=w.project.to_dict();bad=copy.deepcopy(values[0]);bad['text']='不能改写原文';w.apply_suggestions([bad])
    assert w.project.to_dict()==original and w.pending and '原歌词' in w.status.text()
    w.close()

def test_discarding_clean_pending_result_clears_only_its_recovery(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);pending(w);w.save_recovery();assert w.recovery_path().exists()
    w.discard_suggestions();assert w.pending is None and not w.recovery_path().exists()
    w.close()

def test_next_unconfirmed_wraps_and_playhead_edit_is_undoable(qapp,tmp_path,project):
    p=two_lines(project);p.lines[0].reviewed=True;w=window(qapp,tmp_path,p);w.next_unconfirmed();assert w.current==1
    w.current=0;w.refresh();w.playback.canvas.position=1500;old=w.line.units[0].start;w.set_edge_from_playhead(0)
    assert w.line.units[0].start==1500;w.undo();assert w.line.units[0].start==old
    w.close()

def test_recent_projects_are_deduplicated_and_damaged_preferences_are_safe(tmp_path):
    home=tmp_path/'home';home.mkdir();(home/'workspace.json').write_text('{broken',encoding='utf-8');prefs=Preferences(home);assert prefs.recent()==[]
    for i in range(10):prefs.remember(tmp_path/f'{i}.sgproj',f'作品 {i}')
    prefs.remember(tmp_path/'5.sgproj','重新打开');again=Preferences(home)
    assert len(again.recent())==8 and again.recent()[0]['title']=='重新打开'
    assert len({v['path'] for v in again.recent()})==8

def test_recent_project_save_and_missing_path_leave_current_document_safe(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.path=tmp_path/'日本語.sgproj';assert w.save()
    assert w.preferences.recent()[0]['path']==str(w.path.resolve())
    before=w.project.to_dict();w.open_recent(tmp_path/'missing.sgproj');assert w.project.to_dict()==before
    w.subtitle_toggle.setChecked(False);assert not w.playback.canvas.show_subtitles
    assert json.loads((w.home/'workspace.json').read_text(encoding='utf-8'))['subtitles'] is False
    w.close()

def test_playback_clamps_seek_and_active_loop_setting(qapp,tmp_path,project):
    import time
    w=window(qapp,tmp_path,project);w.playback.audio.setMuted(True);w.playback.open(project.media)
    deadline=time.monotonic()+5
    while w.playback.player.duration()<=0 and time.monotonic()<deadline:qapp.processEvents();QTest.qWait(20)
    duration=w.playback.player.duration();assert duration>0
    w.playback.seek(duration+10000);assert w.playback.canvas.position==duration
    assert not w.playback.audition(duration+100,duration+200)
    w.playback.audition(1000,3000);w.loop.setChecked(True);assert w.playback.loop
    w.loop.setChecked(False);assert not w.playback.loop;w.playback.stop();w.close()

def test_confirmation_footer_follows_reading_tab_without_confirming_time(qapp,tmp_path,project):
    w=window(qapp,tmp_path,two_lines(project));uid=w.line.id;w.calibration_tabs.setCurrentIndex(1)
    assert '读音' in w.calibrate_footer.text()
    QTest.mouseClick(w.calibrate_footer,Qt.MouseButton.LeftButton)
    assert w.project.checks[uid]['reading'] and not w.project.lines[0].reviewed and w.current==1
    w.undo();assert not w.project.checks.get(uid,{}).get('reading');w.close()

def test_background_completion_after_signal_object_destroyed_does_not_raise(qapp):
    import shiboken6
    from shengao.jobs import Work
    work=Work(lambda cancel,progress:(progress('late progress'),42)[1]);shiboken6.delete(work.signals)
    work.run()

def test_export_reading_issue_opens_the_reading_tab(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.set_stage(4)
    item=next(w.export_issues.item(i) for i in range(w.export_issues.count()) if (w.export_issues.item(i).data(Qt.ItemDataRole.UserRole) or [None,None])[1]=='reading')
    assert '第 1 句' in item.text();w.goto_issue(item)
    assert w.stage==2 and w.calibration_tabs.currentIndex()==1;w.close()
