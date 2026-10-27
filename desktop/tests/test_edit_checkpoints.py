"""Checkpoint the exact successful transaction, without a second full copy."""
import copy,json
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from shengao.project import Project
from shengao import checkpoint_encoding
from test_reading_candidates_workflow import reading_window
from test_recovery_background import held_writer,wait


def test_successful_edit_reuses_its_detached_snapshot_without_serializing_again(reading_window,monkeypatch):
    w=reading_window;records=[];calls=[];original=Project.to_dict
    def snapshot(project):calls.append(project);return original(project)
    monkeypatch.setattr(Project,'to_dict',snapshot)
    monkeypatch.setattr(w.recovery_writer,'queue_owned',lambda record:records.append(record) or True)
    w.change_boundary(0,0,1000,1120)
    assert len(calls)==1 and not records and w.edited_recovery_timer.isActive()
    w.publish_edited_checkpoint()
    assert len(calls)==1 and len(records)==1 and records[0]['project'] is w.history._applied_snapshot
    captured=copy.deepcopy(records[0]);w.project.title='稍后直接修改';w.line.units[0].kana='べつ'
    assert records[0]==captured and records[0]['project']['title']!=w.project.title
    assert w.autosave.isActive() and w.autosave.interval()==15000


def test_edited_checkpoint_coalesces_with_newer_edit_without_blocking_gui(reading_window,qapp,held_writer):
    w=reading_window;entered,release,writes=held_writer
    w.change_boundary(0,0,1000,1120);wait(qapp,entered.is_set)
    assert w.edit('后续编辑',lambda project:setattr(project,'title','最新编辑'))
    expected=w.project.to_dict();beats=[];timer=QTimer(w);timer.setInterval(5);timer.timeout.connect(lambda:beats.append(True));timer.start()
    wait(qapp,lambda:len(beats)>=5);timer.stop();release.set();wait(qapp,lambda:w.recovery_writer.idle and w._edited_recovery is None)
    saved=json.loads(w.recovery_path().read_text(encoding='utf-8'))
    assert saved['project']==expected and saved['pending'] is None and len(w.history.undo_stack)==2
    assert [value[0] for value in writes][-1]=='最新编辑' and len(writes)==2


def test_pending_results_and_missing_guard_keep_fresh_timed_capture(reading_window,monkeypatch):
    w=reading_window;records=[];monkeypatch.setattr(w.recovery_writer,'queue_owned',lambda record:records.append(record) or True)
    w.pending={'result':{'notes':['候选待审核']}};w.change_boundary(0,0,1000,1120);assert not records
    w.pending=None;monkeypatch.setattr(checkpoint_encoding,'shareable',lambda value:False)
    w.change_boundary(0,0,1000,1140);assert not records
    w.project.title='没有刷新也要捕获';w.queue_recovery()
    assert len(records)==1 and records[0]['project']==w.project.to_dict()
    assert records[0]['project'] is not w.history._applied_snapshot


def test_failed_and_unchanged_edits_do_not_queue_new_checkpoint(reading_window,monkeypatch):
    w=reading_window;records=[];monkeypatch.setattr(w.recovery_writer,'queue_owned',lambda record:records.append(record) or True)
    w.change_boundary(0,0,1300,1100);assert not records
    assert not w.edit('无变化',lambda project:None) and not records


def test_rapid_edits_stage_only_latest_complete_record(reading_window,monkeypatch):
    w=reading_window;records=[];monkeypatch.setattr(w.recovery_writer,'queue_owned',lambda record:records.append(record) or True)
    for index in range(20):assert w.edit('连续编辑',lambda project,index=index:setattr(project,'title',str(index)))
    assert not records and w.edited_recovery_timer.isActive()
    w.publish_edited_checkpoint()
    assert len(records)==1 and records[0]['project']==w.project.to_dict() and len(w.history.undo_stack)==20


@pytest.mark.parametrize('action',['clear','new','save','close','sync'])
def test_staged_edit_cannot_override_explicit_checkpoint_or_reappear_after_clear(reading_window,tmp_path,monkeypatch,action):
    w=reading_window;w.save_recovery();previous=w.recovery_path().read_bytes()
    w.change_boundary(0,0,1000,1120);assert w._edited_recovery is not None
    if action=='clear':w.clear_recovery();expected=None
    elif action=='new':
        monkeypatch.setattr(w,'can_replace',lambda:True);w.new();expected=None
    elif action=='save':
        w.path=tmp_path/'当前工程.sgproj';assert w.save();expected=None
    elif action=='close':w.close();expected=previous
    else:
        w.project.title='最新同步检查点';w.save_recovery();expected=w.recovery_path().read_bytes()
    w.publish_edited_checkpoint()
    assert w._edited_recovery is None and not w.edited_recovery_timer.isActive()
    assert (w.recovery_path().read_bytes() if w.recovery_path().exists() else None)==expected


def test_new_pending_result_uses_current_fresh_record_instead_of_staged_data(reading_window,monkeypatch):
    w=reading_window;records=[];monkeypatch.setattr(w.recovery_writer,'queue_owned',lambda record:records.append(record) or True)
    w.change_boundary(0,0,1000,1120);w.pending={'result':{'new':['已返回']}};w.project.title='后来直接变化'
    w.publish_edited_checkpoint()
    assert len(records)==1 and records[0]['project']==w.project.to_dict() and records[0]['pending']==w.pending
    assert records[0]['pending'] is not w.pending


def test_stopped_autosave_is_not_restarted_by_edit(reading_window,monkeypatch):
    w=reading_window;records=[];w.autosave.stop();monkeypatch.setattr(w.recovery_writer,'queue_owned',lambda record:records.append(record) or True)
    w.change_boundary(0,0,1000,1120);w.publish_edited_checkpoint()
    assert not records and not w.autosave.isActive() and w._edited_recovery is None


def test_undo_redo_replaces_staged_record_with_its_actual_current_document(reading_window,monkeypatch):
    w=reading_window;records=[];monkeypatch.setattr(w.recovery_writer,'queue_owned',lambda record:records.append(record) or True)
    w.history.saved=w.project.to_dict();w.clear_recovery()
    w.change_boundary(0,0,1000,1120);changed=w.project.to_dict();w.undo();w.publish_edited_checkpoint()
    assert not records and not w.recovery_path().exists()
    w.redo();w.publish_edited_checkpoint()
    assert len(records)==1 and records[0]['project']==changed
