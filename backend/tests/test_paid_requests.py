"""A paid request that may have been billed is never sent again on its own."""
import asyncio
import copy
import json
import uuid

import pytest

from studio_backend import api, draft, paid_requests, worker
from studio_backend.model import LyricLine
from studio_backend.settings import Settings, atomic_json

KEY = 'a' * 64


def attempt(home, failure=None, confirmed=False, key=KEY, diagnostics=None):
    diagnostics = {} if diagnostics is None else diagnostics
    async def call():
        async with paid_requests.guard(home, key, 'transcribe', 'elevenlabs', diagnostics, confirmed):
            if failure: failure(diagnostics)
            return 'ok'
    return asyncio.run(call())


def timed_out(diagnostics):
    diagnostics.update(phase='waiting', request_id='req-77')
    raise api.failure('等待超时。', diagnostics)


def test_timeout_after_upload_blocks_the_next_attempt_until_confirmed(tmp_path):
    with pytest.raises(api.ApiError): attempt(tmp_path, timed_out)
    record = paid_requests.pending(tmp_path, KEY)
    assert record['state'] == 'unknown' and record['stage'] == 'waiting' and record['billing'] == 'possibly_billed'
    with pytest.raises(paid_requests.ResubmitRequired) as blocked: attempt(tmp_path)
    assert '等待服务处理' in str(blocked.value) and '已拦截自动重新提交' in str(blocked.value) and 'req-77' in str(blocked.value)
    assert blocked.value.record['request_id'] == 'req-77' and blocked.value.record['action'] == 'transcribe'
    assert attempt(tmp_path, confirmed=True) == 'ok'
    assert paid_requests.pending(tmp_path, KEY) is None and attempt(tmp_path) == 'ok'


@pytest.mark.parametrize('phase,status', [('connecting', None), ('uploading', None), ('reading_response', 401)])
def test_failures_the_service_never_billed_leave_no_record(tmp_path, phase, status):
    def failed(diagnostics):
        diagnostics['phase'] = phase
        if status: diagnostics['http_status'] = status
        raise api.failure('模拟失败。', diagnostics)
    with pytest.raises(api.ApiError): attempt(tmp_path, failed)
    assert paid_requests.pending(tmp_path, KEY) is None and attempt(tmp_path) == 'ok'


def test_local_failure_before_sending_leaves_no_record(tmp_path):
    def broken(diagnostics): raise ValueError('本机提取音轨失败')
    with pytest.raises(ValueError, match='提取'): attempt(tmp_path, broken)
    assert paid_requests.pending(tmp_path, KEY) is None


def test_killed_worker_record_counts_as_unknown(tmp_path):
    atomic_json(paid_requests.folder(tmp_path) / f'{KEY}.json',
                {'signature': KEY, 'action': 'align', 'label': '文字对齐', 'state': 'sent', 'started': 1})
    with pytest.raises(paid_requests.ResubmitRequired, match='未确认是否已发出'): attempt(tmp_path)
    (paid_requests.folder(tmp_path) / f'{KEY}.json').write_text('{broken', encoding='utf-8')
    with pytest.raises(paid_requests.ResubmitRequired): attempt(tmp_path)


def test_cancelled_while_waiting_is_recorded(tmp_path):
    def cancelled(diagnostics):
        diagnostics['phase'] = 'waiting'; raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError): attempt(tmp_path, cancelled)
    record = paid_requests.pending(tmp_path, KEY)
    assert record['cancelled'] and record['stage'] == 'waiting'


def test_same_request_running_elsewhere_is_refused(tmp_path):
    async def scenario():
        async with paid_requests.guard(tmp_path, KEY, 'transcribe', 'elevenlabs', {}):
            with pytest.raises(ValueError, match='另一个任务'):
                async with paid_requests.guard(tmp_path, KEY, 'transcribe', 'elevenlabs', {}, True): pass
            assert paid_requests.pending(tmp_path, KEY)['state'] == 'sent'
    asyncio.run(scenario())
    assert paid_requests.pending(tmp_path, KEY) is None


def test_stale_phase_from_an_earlier_batch_is_not_reused(tmp_path):
    diagnostics = {'phase': 'complete', 'stage': 'after_response'}
    def broken(values): raise ValueError('本机准备失败')
    with pytest.raises(ValueError): attempt(tmp_path, broken, diagnostics=diagnostics)
    assert paid_requests.pending(tmp_path, KEY) is None


def test_invalid_signature_is_refused(tmp_path):
    with pytest.raises(ValueError, match='编号无效'): attempt(tmp_path, key='../x')


def transcription_setup(tmp_path, monkeypatch, outcomes):
    media = tmp_path / 'source.wav'; media.write_bytes(b'synthetic input'); calls = []
    monkeypatch.setattr(Settings, 'key', lambda *args: 'test-never-sent')
    async def extract(source, target, *args): target.write_bytes(b'fLaC local fake')
    async def transcribe(audio, key, language, diagnostics):
        calls.append(1); outcome = outcomes.pop(0)
        if outcome == 'timeout':
            diagnostics.update(phase='waiting', uploaded_bytes=10, upload_size=10)
            raise api.failure('读取超时。', diagnostics)
        return {'words': [{'text': '今日', 'start': .1, 'end': 1.1}]}
    monkeypatch.setattr(worker, 'extract', extract); monkeypatch.setattr(api, 'eleven_transcribe', transcribe)
    return {'action': 'transcribe', 'media': str(media), 'lines': []}, calls


def execute(req, home, path):
    asyncio.run(worker.execute(req, home, path))
    return json.loads(path.read_text(encoding='utf-8'))


def test_worker_timeout_is_not_resubmitted_and_explicit_retry_is_cached(tmp_path, monkeypatch):
    req, calls = transcription_setup(tmp_path, monkeypatch, ['timeout', 'ok'])
    home = tmp_path / 'home'; out = tmp_path / 'task'; out.mkdir()
    first = execute(req, home, out / 'first.json')
    assert not first['ok'] and first['diagnostics']['billing'] == 'possibly_billed' and calls == [1]
    second = execute(req, home, out / 'second.json')
    assert not second['ok'] and calls == [1] and '已拦截自动重新提交' in second['message']
    assert second['resubmit_required']['action'] == 'transcribe' and second['resubmit_required']['stage'] == 'waiting'
    assert second['diagnostics']['billing'] == 'not_sent' and second['diagnostics']['resubmit_blocked']
    # The forced re-run of a cached result is a deliberate request; it is not the confirmation.
    third = execute({**req, 'force': True}, home, out / 'third.json')
    assert not third['ok'] and calls == [1]
    retried = execute({**req, 'confirm_resubmit': True}, home, out / 'retry.json')
    assert retried['ok'] and calls == [1, 1] and not retried['cached']
    again = execute(req, home, out / 'again.json')
    assert again['ok'] and again['cached'] and calls == [1, 1]


def test_refine_batch_interrupted_is_blocked_while_finished_batches_stay_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(worker.Settings, 'key', lambda *_: 'mock-key'); calls = []
    async def annotate(lines, key, model, diagnostics):
        calls.append(len(lines))
        if len(calls) == 2:
            diagnostics.update(phase='reading_response', http_status=200)
            raise api.failure('读取中断。', diagnostics)
        return [{'id': line['id'], 'kana': 'うた', 'romaji': 'uta', 'translation': '歌',
                 'groups': [{'text': '歌', 'kana': 'うた', 'romaji': 'uta', 'reason': 'mock'}]} for line in lines]
    monkeypatch.setattr(api, 'deepseek_annotate', annotate)
    lines = [LyricLine(str(i), '歌', i * 1000, i * 1000 + 900).to_dict() for i in range(31)]
    request = {'action': 'refine', 'lines': lines, 'use_llm': True, 'context': lines}
    first = asyncio.run(worker.operation(request, tmp_path, lambda *_: None))
    assert first['partial'] and calls == [30, 1]
    with pytest.raises(paid_requests.ResubmitRequired):
        asyncio.run(worker.operation(request, tmp_path, lambda *_: None))
    assert calls == [30, 1]
    done = asyncio.run(worker.operation({**request, 'confirm_resubmit': True}, tmp_path, lambda *_: None))
    assert not done.get('partial') and calls == [30, 1, 1] and len(done['suggestions']) == 31


def test_annotate_timeout_is_blocked_until_confirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(worker.Settings, 'key', lambda *_: 'mock-key'); calls = []
    async def annotate(lines, key, model, diagnostics):
        calls.append(1)
        diagnostics.update(phase='waiting'); raise api.failure('等待超时。', diagnostics)
    monkeypatch.setattr(api, 'deepseek_annotate', annotate)
    request = {'action': 'annotate', 'lines': [LyricLine('1', '歌', 0, 900).to_dict()]}
    with pytest.raises(api.ApiError): asyncio.run(worker.operation(request, tmp_path, lambda *_: None))
    with pytest.raises(paid_requests.ResubmitRequired, match='注音和翻译'):
        asyncio.run(worker.operation(request, tmp_path, lambda *_: None))
    with pytest.raises(api.ApiError): asyncio.run(worker.operation({**request, 'confirm_resubmit': True}, tmp_path, lambda *_: None))
    assert calls == [1, 1]


# Draft stages record what they read and reuse identical finished work.

def draft_request(tmp_path, text='今日も歌う'):
    media = tmp_path / 'source.wav'
    if not media.exists(): media.write_bytes(b'local synthetic fixture, no API')
    return {'action': 'draft', 'workflow_id': uuid.uuid4().hex, 'media': str(media), 'language': 'ja',
            'draft_options': {'source': 'cloud', 'readings': 'deepseek', 'align': False},
            'lines': [LyricLine('line', text, 100, 2100).to_dict(), LyricLine('second', '明日も歌う', 2500, 4500).to_dict()],
            '_studio_context': {'project': 'test-project', 'media': {'path': str(media)}}}


def fake(monkeypatch):
    monkeypatch.setattr(Settings, 'key', lambda self, p: 'test-never-sent'); calls = []
    async def operation(req, root, report):
        calls.append((req['action'], req.get('confirm_resubmit', False)))
        if req['action'] == 'transcribe': return {'suggestions': [LyricLine('asr', '今日も歌う', 300, 2400).to_dict()]}
        return {'suggestions': copy.deepcopy(req['lines'])}
    return calls, operation


def run(req, home, operation, messages=None):
    def report(phase, message):
        if messages is not None: messages.append((phase, message))
    return asyncio.run(draft.run(req, home, report, operation))


def test_new_workflow_reuses_finished_stages_without_any_call(tmp_path, monkeypatch):
    home = tmp_path / 'home'; calls, operation = fake(monkeypatch)
    first = run(draft_request(tmp_path), home, operation)
    assert [a for a, _ in calls] == ['transcribe', 'match', 'refine'] and not first['partial']
    state = draft.load(home, first['workflow']['id'])
    assert all(s.get('inputs') for s in state['stages'] if s['state'] == 'completed')
    calls.clear(); messages = []
    second = run(draft_request(tmp_path), home, operation, messages)
    assert calls == [] and second['suggestions'] == first['suggestions'] and second['transcript'] == first['transcript']
    reused = [s for s in second['workflow']['stages'] if s.get('reused')]
    assert [s['key'] for s in reused] == ['transcript', 'matching', 'readings']
    assert any('没有重新提交' in m for p, m in messages if p == 'draft_cached')
    record = draft.load(home, second['workflow']['id'])['stages'][0]['reused_from']
    assert record['workflow'] == first['workflow']['id']


def test_changed_lyric_reruns_matching_but_reuses_transcription(tmp_path, monkeypatch):
    home = tmp_path / 'home'; calls, operation = fake(monkeypatch)
    run(draft_request(tmp_path), home, operation); calls.clear()
    changed = run(draft_request(tmp_path, '今日も笑う'), home, operation)
    assert [a for a, _ in calls] == ['match', 'refine'] and changed['suggestions'][0]['text'] == '今日も笑う'
    assert [s['key'] for s in changed['workflow']['stages'] if s.get('reused')] == ['transcript']


@pytest.mark.parametrize('change', ['media', 'model', 'provider'])
def test_changed_service_or_media_does_not_reuse_transcription(tmp_path, monkeypatch, change):
    home = tmp_path / 'home'; calls, operation = fake(monkeypatch)
    run(draft_request(tmp_path), home, operation); calls.clear(); req = draft_request(tmp_path)
    if change == 'media': (tmp_path / 'source.wav').write_bytes(b'different audio')
    elif change == 'model': atomic_json(home / 'settings.json', {'deepseek': {'model': 'different-test-model'}})
    else: req['draft_options']['provider'] = 'mai'
    data = run(req, home, operation)
    # The fake service returns the same words, so the text-only later stages
    # legitimately reuse; transcription itself must run again.
    expected = ['refine'] if change == 'model' else ['transcribe']
    assert [a for a, _ in calls] == expected
    reused = [s['key'] for s in data['workflow']['stages'] if s.get('reused')]
    assert reused == (['transcript', 'matching'] if change == 'model' else ['matching', 'readings'])


def test_corrupted_or_foreign_stage_cache_is_ignored(tmp_path, monkeypatch):
    home = tmp_path / 'home'; calls, operation = fake(monkeypatch)
    run(draft_request(tmp_path), home, operation)
    for path in (Settings(home).root / 'draft-stages').glob('transcript-*.json'):
        data = json.loads(path.read_text(encoding='utf-8')); data['result']['suggestions'][0]['text'] = '改过'
        atomic_json(path, data)
    for path in (Settings(home).root / 'draft-stages').glob('matching-*.json'):path.write_text('{', encoding='utf-8')
    calls.clear(); run(draft_request(tmp_path), home, operation)
    assert [a for a, _ in calls] == ['transcribe', 'match']


def test_partial_stage_is_not_offered_to_other_workflows(tmp_path, monkeypatch):
    home = tmp_path / 'home'; calls, operation = fake(monkeypatch)
    async def partial(req, root, report):
        if req['action'] == 'refine':
            calls.append(('refine', False)); rows = copy.deepcopy(req['lines'])
            return {'suggestions': rows[:1] + copy.deepcopy(req['lines'][1:]), 'partial': True, 'message': '后续批次失败'}
        return await operation(req, root, report)
    run(draft_request(tmp_path), home, partial)
    assert not list((Settings(home).root / 'draft-stages').glob('readings-*.json'))
    calls.clear(); run(draft_request(tmp_path), home, operation)
    assert [a for a, _ in calls] == ['refine']


def test_only_the_explicit_stage_retry_confirms_a_resubmit(tmp_path, monkeypatch):
    home = tmp_path / 'home'; calls, operation = fake(monkeypatch)
    async def blocked(req, root, report):
        if req['action'] == 'transcribe' and not req.get('confirm_resubmit'):
            calls.append(('transcribe', False))
            raise paid_requests.ResubmitRequired({'action': 'transcribe', 'label': '音频识别', 'stage': 'waiting'})
        return await operation(req, root, report)
    req = draft_request(tmp_path); data = run(req, home, blocked)
    assert data['partial'] and '已拦截自动重新提交' in data['workflow']['message']
    assert draft.load(home, req['workflow_id'])['stages'][0]['state'] == 'failed'
    calls.clear(); run({**req, 'resume': True}, home, blocked)
    assert calls == []
    done = run({**req, 'resume': True, 'retry_stage': 'transcript'}, home, blocked)
    assert not done['partial'] and calls == [('transcribe', True), ('match', False), ('refine', False)]


def test_failed_paid_stage_uses_identical_result_finished_by_another_workflow(tmp_path, monkeypatch):
    home = tmp_path / 'home'; calls, operation = fake(monkeypatch)
    async def timeout(req, root, report):
        calls.append((req['action'], False))
        raise api.ApiError('模拟等待中断', {'phase': 'waiting'})
    stuck = draft_request(tmp_path); run(stuck, home, timeout)
    assert draft.load(home, stuck['workflow_id'])['stages'][0]['state'] == 'failed'
    run(draft_request(tmp_path), home, operation); calls.clear()
    resumed = run({**stuck, 'resume': True}, home, timeout)
    assert calls == [] and not resumed['partial']


def test_changed_signature_message_mentions_reuse(tmp_path, monkeypatch):
    home = tmp_path / 'home'; calls, operation = fake(monkeypatch)
    req = draft_request(tmp_path); run(req, home, operation)
    altered = copy.deepcopy(req); altered['lines'][0]['text'] = '明日も歌う'
    with pytest.raises(ValueError, match='复用输入未变'): run({**altered, 'resume': True}, home, operation)
