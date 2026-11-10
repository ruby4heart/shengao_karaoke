"""An interrupted paid request is resent only after the person confirms."""
import json

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from shengao import paid_retry
from shengao.api_jobs import ApiJob
from shengao.draft_workflow import DraftWorkflow, ResumeDraftDialog
from shengao.project import History, file_stamp

RECORD = {'action': 'transcribe', 'label': '音频识别', 'stage': 'waiting', 'request_id': 'req-9'}


class Job:
    def __init__(self, request):
        self.request = request; self.failure = {'ok': False, 'resubmit_required': dict(RECORD)}
        self.busy = False; self.started = []
    def start(self, request): self.started.append(request)


class Studio(QWidget):
    def __init__(self, project):
        super().__init__(); self.history = History(project); self.pending = None; self.messages = []
        line = project.lines[0]; self.snapshots = {line.id: line.to_dict()}
        self.api = Job({'action': 'transcribe', 'lines': [line.to_dict()], 'media': project.media,
                        '_studio_context': {'project': project.uid, 'media': file_stamp(project.media)}})
    @property
    def project(self): return self.history.project
    def message(self, text): self.messages.append(text)


@pytest.fixture
def studio(qapp, project):
    window = Studio(project); yield window; window.deleteLater()


def answer(monkeypatch, value, asked=None):
    def question(parent, title, text, *args):
        if asked is not None: asked.append(text)
        return value
    monkeypatch.setattr(QMessageBox, 'question', question)


def test_confirmed_retry_resends_the_same_request_once(studio, monkeypatch):
    asked = []; answer(monkeypatch, QMessageBox.StandardButton.Yes, asked)
    assert paid_retry.offer_resubmit(studio)
    assert studio.api.started == [{**studio.api.request, 'confirm_resubmit': True}]
    assert '等待服务处理' in asked[0] and 'req-9' in asked[0] and '不会发送任何内容' in asked[0]


def test_declined_retry_sends_nothing(studio, monkeypatch):
    answer(monkeypatch, QMessageBox.StandardButton.No)
    assert not paid_retry.offer_resubmit(studio) and studio.api.started == []
    assert '没有重新提交' in studio.messages[-1]


def test_ordinary_failure_asks_nothing(studio, monkeypatch):
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: pytest.fail('nothing to confirm'))
    studio.api.failure = {'ok': False, 'message': '服务拒绝'}
    assert not paid_retry.offer_resubmit(studio) and studio.api.started == []


@pytest.mark.parametrize('change', ['line', 'media', 'pending', 'busy'])
def test_changed_project_never_resends_old_request(studio, monkeypatch, change):
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: pytest.fail('stale request must not be offered'))
    if change == 'line': studio.history.apply('改译文', lambda p: setattr(p.lines[0], 'translation', '改过'))
    elif change == 'media': studio.api.request['_studio_context']['media'] = {'path': 'other.wav'}
    elif change == 'pending': studio.pending = {'result': {'suggestions': [{}]}}
    else: studio.api.busy = True
    assert not paid_retry.offer_resubmit(studio) and studio.api.started == []
    assert '没有重新提交' in studio.messages[-1]


def test_job_keeps_the_failure_details(qapp, tmp_path):
    job = ApiJob(home=tmp_path); messages = []; job.failed.connect(messages.append)
    job.folder = tmp_path / 'task'; job.folder.mkdir(); job.result = job.folder / 'result.json'
    job.result.write_text(json.dumps({'ok': False, 'message': '已拦截自动重新提交', 'resubmit_required': RECORD}, ensure_ascii=False), encoding='utf-8')
    class Process:
        def readAllStandardError(self): pass
        def deleteLater(self): pass
    job.process = Process(); job.request = {'action': 'transcribe'}
    job.finish(0, None)
    assert messages == ['已拦截自动重新提交'] and paid_retry.blocked(job)['request_id'] == 'req-9'


def test_reused_stages_are_named_in_resume_dialog_and_progress(qapp):
    stages = [{'key': 'transcript', 'title': '联网识别音轨', 'state': 'completed', 'paid': True, 'reused_from': {'workflow': 'x'}},
              {'key': 'matching', 'title': '按原歌词匹配', 'state': 'completed', 'paid': False},
              {'key': 'readings', 'title': 'DeepSeek 读音建议', 'state': 'pending', 'paid': True}]
    state = {'id': 'a' * 32, 'status': 'paused', 'message': '', 'request': {'lines': [{'id': '1', 'text': '歌'}]}, 'stages': stages}
    dialog = ResumeDraftDialog(None, state)
    assert '复用此前结果' in dialog.table.item(0, 2).text() and dialog.table.item(2, 2).text() == '联网服务'
    dialog.deleteLater()

    class Progress(QWidget, DraftWorkflow):
        def __init__(self):
            super().__init__(); self.project = type('P', (), {'uid': 'p'})()
            from PySide6.QtWidgets import QLabel
            self.draft_status = QLabel()
    view = Progress()
    view.show_draft_progress({'context': {'project': 'p'}, 'status': 'running', 'stages': [
        {**{k: stages[0][k] for k in ('key', 'title', 'state', 'paid')}, 'reused': True}, stages[1]]})
    lines = view.draft_status.text().split('\n')
    assert '复用此前结果' in lines[0] and '复用' not in lines[1]
    view.deleteLater()
