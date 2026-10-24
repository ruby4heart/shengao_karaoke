import copy
import time
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox,QDialog,QListWidget,QPushButton
from shengao.app import StudioWindow
from shengao.chorus_dialog import ChorusDialog
from shengao.dialogs import ReviewDialog
from shengao.project import Project,History
from chorus_fixtures import fixture


def window(qapp,tmp_path):
    source,target=fixture();project=Project(lines=[source,target],checks={source.id:{'reading':True}},duration=22000)
    w=StudioWindow(tmp_path/'home',test=True);w.history=History(project);w.current=1;w.refresh();w.set_stage(1);w.show();qapp.processEvents();return w


def wait(qapp,fn,seconds=10):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        qapp.processEvents();QTest.qWait(20)
        if fn():return True
    return False


def start(w,qapp):
    assert w.chorus_button.isVisible()
    def choose():
        d=next(d for d in w.findChildren(ChorusDialog) if d.isVisible());d.voice.setChecked(False);d.apply.click()
    QTimer.singleShot(20,choose);w.chorus_button.click()
    assert w.api.busy and wait(qapp,lambda:not w.api.busy and w.pending is not None)


def test_real_dialog_and_worker_create_readonly_candidates_then_one_undo(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();start(w,qapp)
    assert w.project.to_dict()==before and w.pending['action']=='chorus_reuse'
    assert w.api.request['neighbor_lines']==before['lines'] and w.api.request['_studio_checks']==before['checks']
    result=copy.deepcopy(w.pending['result']);d=ReviewDialog(w.project,result,w.playback,w)
    assert '复用' in d.details.toPlainText() and d.manual_button.isEnabled();d.reject()
    w.apply_suggestions(result['suggestions'])
    assert [u.text for u in w.project.lines[1].units]==['君と','歌う'] and w.project.lines[1].kana=='キミトウタウ'
    assert w.project.lines[0].to_dict()==before['lines'][0] and not w.project.lines[1].reviewed and w.pending is None
    w.undo();assert w.project.to_dict()==before;w.close()


def test_late_source_change_blocks_adoption_without_losing_candidate(qapp,tmp_path):
    w=window(qapp,tmp_path);start(w,qapp);target=w.project.lines[1].to_dict();result=copy.deepcopy(w.pending['result'])
    w.edit('手工修改来源罗马音',lambda p:setattr(p.lines[0].units[0],'romaji','new manual value'))
    w.apply_suggestions(result['suggestions'])
    assert w.pending and w.project.lines[1].to_dict()==target and w.project.lines[0].units[0].romaji=='new manual value'
    assert '来源' in w.status.text();w.close()


def test_late_target_reading_confirmation_is_preserved(qapp,tmp_path):
    w=window(qapp,tmp_path);start(w,qapp);target=w.project.lines[1].to_dict();result=copy.deepcopy(w.pending['result'])
    w.edit('确认目标读音',lambda p:p.checks.setdefault('target',{}).__setitem__('reading',True))
    w.apply_suggestions(result['suggestions'])
    assert w.pending and w.project.lines[1].to_dict()==target and w.project.checks['target']['reading'];w.close()


def test_small_options_footer_reachable_and_protected_target_cannot_be_selected(qapp,tmp_path):
    w=window(qapp,tmp_path);w.project.lines[1].reviewed=True
    d=ChorusDialog(w.project,1,w.playback,w);d.resize(700,430);d.show();qapp.processEvents()
    assert d.selected_ids()==[] and not d.apply.isEnabled()
    footer=d.findChild(QDialogButtonBox);assert footer.isVisible() and footer.geometry().bottom()<d.height()
    assert '保留' in d.table.item(0,3).text();d.reject();w.close()


def test_shelved_chorus_task_can_resume_its_original_checkpoint(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);start(w,qapp);uid=w.pending['result']['chorus_workflow']['id']
    assert w.shelve_for_manual('target');calls=[];monkeypatch.setattr(w,'resume_chorus_workflow',lambda value:calls.append(value))
    def choose():
        d=next(d for d in w.findChildren(QDialog) if d.isVisible() and d.windowTitle()=='任务记录与结果恢复')
        items=d.findChild(QListWidget);index=next(i for i in range(items.count()) if '暂存的校对建议' in items.item(i).text());items.setCurrentRow(index)
        next(b for b in d.findChildren(QPushButton) if b.text()=='继续所选处理流程…').click()
    QTimer.singleShot(20,choose);w.task_history();assert calls==[uid] and w.pending is None;w.close()
