"""Real worker/GUI races: snapshots, clear, manual saves, replacement and close."""
from pathlib import Path
import json,threading,time
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from shengao import recovery
from test_reading_candidates_workflow import reading_window


def wait(qapp,predicate,seconds=5):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        qapp.processEvents();QTest.qWait(2)
        if predicate():return
    assert predicate(),'background recovery did not finish'


def test_worker_releases_owned_payload_before_gui_dispatches_completion(qapp,tmp_path,monkeypatch):
    import weakref
    entered=threading.Event();release=threading.Event();freed=threading.Event();threads=[];original=recovery.atomic_json
    class Payload(dict):
        def __del__(self):threads.append(threading.get_ident());freed.set()
    def gated(path,value,**kwargs):
        entered.set()
        if not release.wait(5):raise TimeoutError('worker was not released')
        return original(path,value,**kwargs)
    monkeypatch.setattr(recovery,'atomic_json',gated)
    writer=recovery.RecoveryWriter(tmp_path/'recovery.json',lambda error:None)
    owned=Payload(project={'title':'后台释放'},pending=None,path='');reference=weakref.ref(owned)
    try:
        writer.queue_owned(owned);del owned;assert entered.wait(5);release.set()
        # Intentionally do not process GUI events yet: Work.fn must not keep
        # the document until its queued completion callback reaches the GUI.
        assert freed.wait(5) and reference() is None and len(threads)==1 and threads[0]!=threading.get_ident()
        assert writer.active is not None
        wait(qapp,lambda:writer.idle)
        assert json.loads(writer.path.read_text(encoding='utf-8'))['project']['title']=='后台释放'
    finally:release.set();writer.close()


@pytest.fixture
def held_writer(monkeypatch):
    original=recovery.atomic_json;entered=threading.Event();release=threading.Event();writes=[]
    def write(path,value,**kwargs):
        if '.prepare-' in Path(path).name:
            writes.append((value['project']['title'],threading.get_ident()));entered.set()
            if not release.wait(5):raise TimeoutError('test did not release the worker')
        return original(path,value,**kwargs)
    monkeypatch.setattr(recovery,'atomic_json',write)
    try:yield entered,release,writes
    finally:release.set()


def test_actual_timer_keeps_gui_responsive_and_owns_project_and_pending_data(reading_window,qapp,held_writer):
    w=reading_window;entered,release,writes=held_writer
    w.pending={'result':{'notes':['最初']}};project=w.project.to_dict();pending=json.loads(json.dumps(w.pending))
    w.autosave.setInterval(5);w.autosave.start();wait(qapp,entered.is_set);w.autosave.stop()
    assert not w.recovery_path().exists() and writes[0][1]!=threading.get_ident()
    w.project.title='后续修改';w.pending['result']['notes'].append('后续');w.refresh()
    beats=[];timer=QTimer(w);timer.setInterval(5);timer.timeout.connect(lambda:beats.append(True));timer.start()
    wait(qapp,lambda:len(beats)>=5);timer.stop()
    release.set();wait(qapp,lambda:w.recovery_writer.idle)
    saved=json.loads(w.recovery_path().read_text(encoding='utf-8'))
    assert saved['project']==project and saved['pending']==pending
    assert w.project.title=='后续修改' and w.pending['result']['notes']==['最初','后续']
    assert not list(w.home.glob('*.prepare-*')) and not list(w.home.glob('*.tmp'))


@pytest.mark.parametrize('action',['clear','new','save','close','sync'])
def test_late_worker_cannot_recreate_or_overwrite_a_superseding_result(reading_window,qapp,tmp_path,monkeypatch,held_writer,action):
    w=reading_window;entered,release,writes=held_writer;w.save_recovery();previous=w.recovery_path().read_bytes()
    w.project.title='旧的后台任务';w.queue_recovery();wait(qapp,entered.is_set)
    if action=='clear':w.clear_recovery();expected=None
    elif action=='new':
        monkeypatch.setattr(w,'can_replace',lambda:True);w.new();expected=None
    elif action=='save':
        w.path=tmp_path/'当前工程.sgproj';assert w.save();expected=None
    elif action=='close':w.close();expected=previous
    else:
        w.project.title='最新同步检查点';w.save_recovery();expected=w.recovery_path().read_bytes()
    release.set();wait(qapp,lambda:w.recovery_writer.idle)
    assert (w.recovery_path().read_bytes() if w.recovery_path().exists() else None)==expected
    assert not list(w.home.glob('*.prepare-*')) and not list(w.home.glob('*.tmp'))


def test_rapid_requests_coalesce_to_one_latest_pending_snapshot(reading_window,qapp,held_writer):
    w=reading_window;entered,release,writes=held_writer
    w.project.title='0';w.queue_recovery();wait(qapp,entered.is_set);active=w.recovery_writer.active
    for index in range(1,21):
        w.project.title=str(index);w.queue_recovery();assert w.recovery_writer.active is active
    release.set();wait(qapp,lambda:w.recovery_writer.idle)
    assert [title for title,thread in writes]==['0','20']
    saved=json.loads(w.recovery_path().read_text(encoding='utf-8'));assert saved['project']==w.project.to_dict()


def test_write_failure_preserves_previous_checkpoint_and_reports_on_gui_thread(reading_window,qapp,monkeypatch):
    w=reading_window;w.save_recovery();previous=w.recovery_path().read_bytes();reported=[]
    original_message=w.message
    def message(text):reported.append((threading.get_ident(),text));original_message(text)
    monkeypatch.setattr(w,'message',message)
    def failed(*args,**kwargs):raise OSError('磁盘已满')
    monkeypatch.setattr(recovery,'atomic_json',failed);w.project.title='尚未保存';w.queue_recovery()
    wait(qapp,lambda:w.recovery_writer.idle)
    assert w.recovery_path().read_bytes()==previous
    assert reported and all(thread==threading.get_ident() for thread,text in reported)
    assert '自动恢复' in reported[-1][1] and '磁盘已满' in reported[-1][1]


def test_destination_retry_releases_lock_and_can_be_invalidated(reading_window,qapp,monkeypatch):
    w=reading_window;w.save_recovery();entered=threading.Event();original=recovery.os.replace
    def locked(source,target):
        if Path(target)==w.recovery_path() and '.prepare-' in Path(source).name:
            entered.set();raise PermissionError('destination is temporarily locked')
        return original(source,target)
    monkeypatch.setattr(recovery.os,'replace',locked);w.project.title='正在重试';w.queue_recovery();wait(qapp,entered.is_set)
    w.clear_recovery();wait(qapp,lambda:w.recovery_writer.idle)
    assert not w.recovery_path().exists() and not list(w.home.glob('*.prepare-*'))
