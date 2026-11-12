"""Each service's documented requests, answers and failures, end to end through the worker.

The scenarios live in studio_backend.service_check so the same checks can be
run by hand (scripts/check-services.py --mock); every one runs against a local
server and sends nothing over the network.
"""
import asyncio
import json

import pytest

from studio_backend import api, service_check
from studio_backend.model import align_characters


@pytest.mark.parametrize('item', service_check.SCENARIOS, ids=lambda item: item.name)
def test_service_scenario(item, tmp_path):
    problems = asyncio.run(item.run(tmp_path / 'home', tmp_path / 'work'))
    assert not problems, f'{item.title}: ' + '；'.join(problems)


def test_every_service_has_success_failure_and_limit_scenarios():
    by_service = {}
    for item in service_check.SCENARIOS: by_service.setdefault(item.service, []).append(item.title)
    assert set(by_service) == {'elevenlabs', 'mai', 'deepseek'}
    for titles in by_service.values():
        assert any('成功' in t for t in titles) and any('429' in t for t in titles)
    assert len({item.name for item in service_check.SCENARIOS}) == len(service_check.SCENARIOS)


@pytest.mark.parametrize('seconds,rate', [(16, 16000), (7199.9, 16000), (3600 * 3, 44100), (0.5, 48000)])
def test_flac_duration_comes_from_the_streaminfo_header(tmp_path, seconds, rate):
    path = tmp_path / 'a.flac'
    service_check.fake_flac(path, seconds, rate=rate)
    assert api.flac_seconds(path) == pytest.approx(seconds, abs=1 / rate)


@pytest.mark.parametrize('data', [b'', b'fLaC', b'RIFF' + bytes(60), b'fLaC\x04' + bytes(60)])
def test_unreadable_flac_header_means_unknown_duration(tmp_path, data):
    path = tmp_path / 'a.flac'; path.write_bytes(data)
    assert api.flac_seconds(path) is None
    assert api.flac_seconds(tmp_path / 'missing.flac') is None


def test_size_limits_reject_at_the_documented_bound(tmp_path):
    audio = tmp_path / 'a.flac'
    service_check.fake_flac(audio, 10, size=100)
    diagnostics = {}
    api.too_large(audio, 101, 'x', diagnostics)
    with pytest.raises(api.ApiError, match='本机准备'):
        api.too_large(audio, 100, '过大。', diagnostics)
    assert diagnostics['stage'] == 'local' and diagnostics['billing'] == 'not_sent'
    assert (api.ELEVEN_STT_BYTES, api.ELEVEN_ALIGN_BYTES, api.MAI_BYTES, api.MAI_SECONDS) == (5_000_000_000, 1_000_000_000, 250_000_000, 7200)


def test_mai_under_two_hours_is_sent(tmp_path, monkeypatch):
    audio = tmp_path / 'a.flac'; service_check.fake_flac(audio, 7199)
    sent = []
    async def request_json(url, headers, data=None, diagnostics=None, upload_size=None):
        sent.append(url); return {'phrases': []}
    monkeypatch.setattr(api, 'request_json', request_json)
    asyncio.run(api.mai_transcribe(audio, 'k', service_check.MAI_ENDPOINT))
    service_check.fake_flac(audio, 7200)
    with pytest.raises(api.ApiError, match='2 小时'):
        asyncio.run(api.mai_transcribe(audio, 'k', service_check.MAI_ENDPOINT))
    assert len(sent) == 1


@pytest.mark.parametrize('body,code', [
    ({'detail': {'status': 'invalid_api_key', 'message': 'm', 'request_id': 'r1'}}, 'invalid_api_key'),
    ({'detail': [{'loc': ['body'], 'msg': 'm', 'type': 'missing'}]}, 'missing'),
    ({'detail': ['text only']}, None),
    ({'error': {'code': 'InvalidRequest', 'innerError': {'code': 'InvalidLocale'}}}, 'InvalidLocale'),
    ({'error': {'code': 'InvalidRequest', 'innererror': {}}}, 'InvalidRequest'),
    ({'error': {'message': 'm', 'type': 'server_error', 'code': None}}, 'server_error'),
    ({'error': 'plain text'}, None),
    ({'error': {'code': 'x' * 500}}, 'x' * 100),
])
def test_error_bodies_give_a_short_code(body, code):
    diagnostics = {}
    api.error_details(body, diagnostics)
    assert diagnostics.get('error_code') == code
    assert 'm' not in json.dumps({k: v for k, v in diagnostics.items() if k != 'error_code'}).replace('"', '')
    if code == 'invalid_api_key': assert diagnostics['request_id'] == 'r1'


def test_alignment_restores_dropped_or_spaced_line_breaks():
    chars = [{'text': c, 'start': i / 10, 'end': (i + 1) / 10} for i, c in enumerate('ab')]
    for returned in (chars, [chars[0], {'text': ' ', 'start': .1, 'end': .1}, chars[1]]):
        units = align_characters('a\nb', returned)
        assert [u.text for u in units] == ['a', '\n', 'b'] and units[1].start == units[1].end == 100
    with pytest.raises(ValueError, match='不一致'): align_characters('a\nb', [chars[0]])
    with pytest.raises(ValueError, match='不一致'): align_characters('ab', [chars[0], {'text': 'x', 'start': 0, 'end': 0}])
    with pytest.raises(ValueError, match='不一致'): align_characters('a\nb', chars + [{'text': 'c', 'start': 0, 'end': 0}])


def load_script():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'check-services.py'
    spec = importlib.util.spec_from_file_location('check_services', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_mock_report_is_labelled_mock(tmp_path, capsys):
    script = load_script()
    out = tmp_path / 'mock.json'
    assert script.main(['--only-scenarios', 'eleven_401', 'deepseek_ok', '--out', str(out)]) == 0
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['evidence'] == '模拟' and [s['name'] for s in report['scenarios']] == ['eleven_401', 'deepseek_ok']
    assert '【模拟】' in capsys.readouterr().out


class Services:
    """Stand-in for the real services on a background thread, for the --real flow."""

    def __init__(self, wrong):
        import threading
        self.wrong = wrong; self.seen = []; self.ready = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def serve(self):
        from aiohttp import web
        sample = json.loads((service_check.REAL_SAMPLE / 'sample.json').read_text(encoding='utf-8'))
        text = sample['text']; step = 0.3
        alignment = {'characters': [{'text': c, 'start': 4.38 + i * step, 'end': 4.38 + (i + 1) * step} for i, c in enumerate(text)],
                     'words': [], 'loss': 0.3}
        groups = [('遠く', 'とおく', 'tooku'), ('の', 'の', 'no'), ('空', 'そら', 'sora'), ('に', 'に', 'ni'),
                  ('今日', 'きょう', 'kyou'), ('も', 'も', 'mo'), ('歌う', 'うたう', 'utau')]
        annotation = {'lines': [{'id': '1', 'kana': ''.join(g[1] for g in groups), 'romaji': ' '.join(g[2] for g in groups),
                                 'translation': '在远方的天空今天也歌唱',
                                 'groups': [{'text': t, 'kana': k, 'romaji': r} for t, k, r in groups]}]}
        answers = {'/v1/speech-to-text': service_check.STT_OK, '/v1/forced-alignment': alignment,
                   '/speechtotext/transcriptions:transcribe': service_check.MAI_OK,
                   '/chat/completions': service_check.chat(json.dumps(annotation, ensure_ascii=False))}
        async def handle(request):
            body = await request.read()
            keys = [request.headers.get(h, '') for h in service_check.KEY_HEADERS.values()]
            self.seen.append((request.path, len(body)))
            if any(self.wrong in k for k in keys):
                return web.json_response({'detail': {'status': 'invalid_api_key'}}, status=401)
            return web.json_response(answers[request.path], headers={'request-id': 'r-' + str(len(self.seen))})
        async def main():
            app = web.Application(client_max_size=1 << 28); app.router.add_post('/{tail:.*}', handle)
            runner = web.AppRunner(app); await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
            self.base = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
            self.stop = asyncio.Event(); self.ready.set()
            await self.stop.wait(); await runner.cleanup()
        self.loop = asyncio.new_event_loop(); self.loop.run_until_complete(main())

    def __enter__(self):
        self.thread.start(); self.ready.wait(10); return self

    def __exit__(self, *error):
        self.loop.call_soon_threadsafe(self.stop.set); self.thread.join(10)


@pytest.mark.skipif(not __import__('shutil').which('ffmpeg'), reason='needs FFmpeg to extract the sample')
def test_real_flow_runs_every_check_and_labels_the_report_real(tmp_path, monkeypatch, capsys):
    from studio_backend.settings import Settings
    script = load_script()
    home = tmp_path / 'home'; home.mkdir()
    (home / 'settings.json').write_text(json.dumps({'mai': {'endpoint': service_check.MAI_ENDPOINT}}), encoding='utf-8')
    monkeypatch.setattr(Settings, 'key', lambda self, provider: 'stand-in-key-' + provider)
    with Services(script.WRONG_KEY) as services:
        real_azure = api.azure_url
        for name, path in (('ELEVEN_STT', '/v1/speech-to-text'), ('ELEVEN_ALIGN', '/v1/forced-alignment'), ('DEEPSEEK', '/chat/completions')):
            monkeypatch.setattr(api, name, services.base + path)
        monkeypatch.setattr(api, 'azure_url', lambda endpoint: real_azure(endpoint).replace(service_check.MAI_ENDPOINT, services.base))
        code = script.main(['--real', '--yes', '--home', str(home)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    reports = list((home / 'service-checks').glob('*-real/report.json'))
    report = json.loads(reports[0].read_text(encoding='utf-8'))
    assert report['evidence'] == '真实'
    checks = {row['check']: row for row in report['checks']}
    assert set(checks) == {'elevenlabs-transcribe', 'elevenlabs-align', 'mai-transcribe', 'deepseek-annotate',
                           'elevenlabs-wrong-key', 'mai-wrong-key', 'deepseek-wrong-key'}
    assert all(row['passed'] for row in checks.values())
    assert checks['elevenlabs-align']['start_error_ms'] == 4380 - checks['elevenlabs-align']['reference_span_ms'][0]
    assert checks['mai-wrong-key']['http_status'] == 401 and checks['mai-wrong-key']['billing'] == 'rejected'
    # The 16 s sample was really extracted and uploaded (FLAC, far more than a header).
    assert all(size > 50_000 for path, size in services.seen if path != '/chat/completions')
    saved = '\n'.join(p.read_text(encoding='utf-8') for p in home.rglob('*.json'))
    assert 'stand-in-key' not in saved and script.WRONG_KEY not in saved


def test_real_flow_asks_first_and_sends_nothing_when_declined(tmp_path, monkeypatch, capsys):
    from studio_backend.settings import Settings
    script = load_script()
    monkeypatch.setattr(Settings, 'key', lambda self, provider: 'stand-in-key' if provider == 'deepseek' else '')
    monkeypatch.setattr('builtins.input', lambda prompt: 'n')
    sent = []
    monkeypatch.setattr(service_check, 'real_check', lambda *a: sent.append(a))
    assert script.main(['--real', '--home', str(tmp_path)]) == 2
    printed = capsys.readouterr().out
    assert '跳过 ElevenLabs' in printed and '跳过 Microsoft AI' in printed and '已取消，没有发送任何请求' in printed
    assert not sent and not (tmp_path / 'service-checks').exists()
