"""Compatibility checks for the three online services, kept apart by kind of evidence.

模拟 (mock): each scenario replays a service's documented request and response
shapes (checked 2026-11-12; sources in docs/SERVICE-COMPATIBILITY.md) through
the real worker against a server on this computer. Request building, upload
limits, timeouts, error reading, the paid-request guard, caching and result
parsing all run exactly as in a real task. Nothing leaves the computer.

真实 (real): ``real_checks`` sends the bundled public PJS056 clip (16 s,
CC BY-SA 4.0) once to each service the person has a key for. It is only run
when the person asks for it, and its report says plainly that it was real.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import socket
import time

from aiohttp import web

from . import api, worker
from .model import LyricLine
from .settings import Settings

# Made-up keys: they only ever reach the local mock server.
MOCK_KEYS = {'elevenlabs': 'mock-eleven-not-a-real-key',
             'mai': 'mock-mai-not-a-real-key',
             'deepseek': 'mock-deepseek-not-a-real-key'}
KEY_HEADERS = {'elevenlabs': 'xi-api-key', 'mai': 'ocp-apim-subscription-key', 'deepseek': 'authorization'}
MAI_ENDPOINT = 'https://mock-speech.cognitiveservices.azure.com'


def fake_flac(path, seconds, size=None, rate=16000):
    """A FLAC header saying ``seconds`` long; a sparse file of ``size`` bytes if given."""
    samples = round(seconds * rate)
    packed = (rate << 44) | (0 << 41) | (15 << 36) | samples
    info = (4096).to_bytes(2, 'big') * 2 + bytes(6) + packed.to_bytes(8, 'big') + bytes(16)
    with open(path, 'wb') as stream:
        stream.write(b'fLaC' + bytes([0x80, 0, 0, 34]) + info + b'mock audio frames')
        if size: stream.truncate(size)


@contextmanager
def patched(*changes):
    """Temporarily set (object, name, value) attributes, restoring them afterwards."""
    saved = [(owner, name, getattr(owner, name)) for owner, name, _ in changes]
    try:
        for owner, name, value in changes: setattr(owner, name, value)
        yield
    finally:
        for owner, name, value in reversed(saved): setattr(owner, name, value)


def reply(status=200, body=None, headers=None, raw=None):
    async def respond(request, mock):
        return web.Response(status=status, body=raw if raw is not None else json.dumps(body, ensure_ascii=False).encode(),
                            headers={'Content-Type': 'application/json', **(headers or {})})
    return respond


def keepalive(body, beats=3):
    """DeepSeek's non-streaming wait: blank lines first, then the JSON."""
    async def respond(request, mock):
        response = web.StreamResponse(headers={'Content-Type': 'application/json'})
        await response.prepare(request)
        for _ in range(beats):
            await response.write(b'\n'); await asyncio.sleep(.05)
        await response.write(json.dumps(body, ensure_ascii=False).encode())
        await response.write_eof()
        return response
    return respond


def stall(seconds=5):
    """The service has the whole request and never answers in time."""
    async def respond(request, mock):
        try: await asyncio.wait_for(mock.release.wait(), seconds)
        except asyncio.TimeoutError: pass
        return web.json_response({'late': True})
    return respond


class Mock:
    """A local stand-in for the three services, recording every request it gets."""

    def __init__(self, home, work):
        self.home = Path(home); self.work = Path(work)
        self.requests = []; self.extracts = []; self.respond = reply(500, {})
        self.seconds = 16.0; self.size = None; self.runs = 0
        self.release = asyncio.Event(); self.received = asyncio.Event()
        self.media = self.work / 'song.wav'

    async def __aenter__(self):
        self.work.mkdir(parents=True, exist_ok=True); self.home.mkdir(parents=True, exist_ok=True)
        self.media.write_bytes(b'RIFF mock media for compatibility checks')
        (self.home / 'settings.json').write_text(json.dumps({'mai': {'endpoint': MAI_ENDPOINT}}), encoding='utf-8')
        app = web.Application(client_max_size=1 << 30)
        app.router.add_post('/{tail:.*}', self.handle)
        self.runner = web.AppRunner(app); await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0); await site.start()
        self.base = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
        real_azure = api.azure_url
        async def extract(media, target, start=None, end=None):
            self.extracts.append((start, end)); fake_flac(target, self.seconds, self.size)
        self.patch = patched((api, 'ELEVEN_STT', self.base + '/v1/speech-to-text'),
                             (api, 'ELEVEN_ALIGN', self.base + '/v1/forced-alignment'),
                             (api, 'DEEPSEEK', self.base + '/chat/completions'),
                             (api, 'azure_url', lambda endpoint: real_azure(endpoint).replace(MAI_ENDPOINT, self.base)),
                             (worker, 'extract', extract),
                             (Settings, 'key', lambda settings, provider: MOCK_KEYS.get(provider, '')))
        self.patch.__enter__()
        return self

    async def __aexit__(self, *error):
        self.release.set()
        self.patch.__exit__(*error)
        await self.runner.cleanup()

    async def handle(self, request):
        seen = {'path': request.path, 'query': dict(request.query),
                'keys': {name: request.headers.get(name, '') for name in KEY_HEADERS.values() if name in request.headers}}
        if request.content_type == 'multipart/form-data':
            form = {}
            for name, value in (await request.post()).items():
                if hasattr(value, 'file'):
                    form[name] = {'filename': value.filename, 'content_type': value.content_type, 'size': len(value.file.read())}
                else:
                    form[name] = value
            seen['form'] = form
        else:
            seen['json'] = await request.json()
        self.requests.append(seen); self.received.set()
        return await self.respond(request, self)

    def unused_url(self):
        """An address where nothing listens, for a connection that is refused."""
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        return f'http://127.0.0.1:{port}'

    async def run(self, request, cancel=False):
        self.runs += 1; self.received.clear()
        result_path = self.work / f'run-{self.runs}' / 'result.json'
        result_path.parent.mkdir(parents=True)
        task = asyncio.create_task(worker.execute(request, str(self.home), result_path))
        if cancel:
            await asyncio.wait_for(self.received.wait(), 10)
            await asyncio.sleep(.2)  # every byte is out: the service may be working now
            Path(str(result_path) + '.cancel').write_text('cancel', encoding='utf-8')
        await asyncio.wait_for(task, 30)
        return json.loads(result_path.read_text(encoding='utf-8'))

    def pending(self):
        folder = self.home / 'paid-requests'
        return [json.loads(p.read_text(encoding='utf-8')) for p in sorted(folder.glob('*.json'))] if folder.is_dir() else []

    def written(self):
        """Everything the app saved for this check, to look for leaked keys."""
        return '\n'.join(p.read_text(encoding='utf-8', errors='replace')
                         for root in (self.home, self.work) for p in root.rglob('*.json'))


# Documented response shapes (made-up values).
STT_OK = {'language_code': 'jpn', 'language_probability': 0.98, 'text': '今日も 歌う',
          'words': [{'text': '今日も', 'start': 0.12, 'end': 0.62, 'type': 'word', 'speaker_id': None, 'logprob': -0.1,
                     'characters': [{'text': '今', 'start': 0.12, 'end': 0.28}, {'text': '日', 'start': 0.28, 'end': 0.44},
                                    {'text': 'も', 'start': 0.44, 'end': 0.62}]},
                    {'text': ' ', 'start': 0.62, 'end': 0.70, 'type': 'spacing', 'speaker_id': None, 'logprob': 0},
                    {'text': '歌う', 'start': 0.70, 'end': 1.30, 'type': 'word', 'speaker_id': None, 'logprob': -0.2,
                     'characters': [{'text': '歌', 'start': 0.70, 'end': 1.00}, {'text': 'う', 'start': 1.00, 'end': 1.30}]},
                    {'text': '(拍手)', 'start': 1.30, 'end': 1.80, 'type': 'audio_event', 'speaker_id': None, 'logprob': 0}],
          'transcription_id': 'mock-transcription'}
MAI_OK = {'durationMilliseconds': 16000,
          'combinedPhrases': [{'text': '今日も歌う 遠くへ'}],
          'phrases': [{'offsetMilliseconds': 120, 'durationMilliseconds': 1180, 'text': '今日も歌う', 'locale': 'ja-JP',
                       'confidence': 0.91, 'words': [{'text': '今日も', 'offsetMilliseconds': 120, 'durationMilliseconds': 500},
                                                     {'text': '歌う', 'offsetMilliseconds': 700, 'durationMilliseconds': 600}]},
                      {'offsetMilliseconds': 2000, 'durationMilliseconds': 900, 'text': '遠くへ', 'locale': 'ja-JP',
                       'confidence': 0.88}]}
ALIGN_TEXT = ['今日も', '歌う']
ALIGN_OK = {'characters': [{'text': '今', 'start': 0.12, 'end': 0.28}, {'text': '日', 'start': 0.28, 'end': 0.44},
                           {'text': 'も', 'start': 0.44, 'end': 0.62}, {'text': '\n', 'start': 0.62, 'end': 0.70},
                           {'text': '歌', 'start': 0.70, 'end': 1.00}, {'text': 'う', 'start': 1.00, 'end': 1.30}],
            'words': [{'text': '今日も', 'start': 0.12, 'end': 0.62, 'loss': 0.4},
                      {'text': '歌う', 'start': 0.70, 'end': 1.30, 'loss': 0.5}],
            'loss': 0.45}
ANNOTATION = {'lines': [{'id': '1', 'kana': 'きょうも', 'romaji': 'kyou mo', 'translation': '今天也',
                         'groups': [{'text': '今日', 'kana': 'きょう', 'romaji': 'kyou'}, {'text': 'も', 'kana': 'も', 'romaji': 'mo'}]}]}


def chat(content, finish='stop'):
    return {'id': 'mock-chat', 'object': 'chat.completion', 'created': 0, 'model': 'deepseek-flash',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': finish}],
            'usage': {'prompt_tokens': 300, 'completion_tokens': 80, 'total_tokens': 380}}


def transcribe(mock, provider, language='ja'):
    return {'action': 'transcribe', 'provider': provider, 'media': str(mock.media), 'language': language, 'lines': []}


def align(mock):
    lines = [LyricLine(str(i + 1), text, i * 1000, i * 1000 + 900).to_dict() for i, text in enumerate(ALIGN_TEXT)]
    return {'action': 'align', 'media': str(mock.media), 'lines': lines, 'range_mode': 'full'}


def annotate(mock):
    return {'action': 'annotate', 'lines': [LyricLine('1', '今日も', 0, 900).to_dict()]}


class Check:
    """Collects failed expectations, so one report lists every problem."""

    def __init__(self): self.problems = []

    def __call__(self, condition, what):
        if not condition: self.problems.append(what)
        return condition

    def failed(self, result, mock, stage, billing, sent, kept):
        d = result.get('diagnostics', {})
        self(result.get('ok') is False, f'应失败，实际 ok={result.get("ok")}')
        self(d.get('stage') == stage, f'阶段应为 {stage}，实际 {d.get("stage")}')
        self(d.get('billing') == billing, f'计费判断应为 {billing}，实际 {d.get("billing")}')
        self(len(mock.requests) == sent, f'应只发出 {sent} 次请求，实际 {len(mock.requests)} 次')
        self(bool(mock.pending()) == kept, '应保留付费未知登记' if kept else '不应留下付费未知登记')
        return d


@dataclass
class Scenario:
    name: str
    service: str
    title: str
    body: object

    async def run(self, home, work):
        check = Check()
        async with Mock(home, work) as mock:
            await self.body(mock, check)
            for provider, key in MOCK_KEYS.items():
                check(key not in mock.written(), f'{provider} 密钥出现在本机保存的文件里')
        return check.problems


SCENARIOS = []


def scenario(service, title):
    def register(body):
        SCENARIOS.append(Scenario(body.__name__, service, title, body)); return body
    return register


@scenario('elevenlabs', '识别成功：按文档字段上传，逐字时间、空格和声音事件解析正确，再次识别读缓存不重发')
async def eleven_transcribe_ok(mock, check):
    mock.respond = reply(200, STT_OK, {'request-id': 'mock-req-1'})
    result = await mock.run(transcribe(mock, 'elevenlabs'))
    sent = mock.requests[0] if mock.requests else {}
    form = sent.get('form', {})
    check(result.get('ok') is True, f'应成功：{result.get("message")}')
    check(sent.get('path') == '/v1/speech-to-text', '接口路径应为 /v1/speech-to-text')
    check(sent.get('keys', {}).get('xi-api-key') == MOCK_KEYS['elevenlabs'], '应以 xi-api-key 头发送密钥')
    check({k: form.get(k) for k in ('model_id', 'language_code', 'timestamps_granularity', 'diarize', 'tag_audio_events')}
          == {'model_id': 'scribe_v2', 'language_code': 'ja', 'timestamps_granularity': 'character',
              'diarize': 'false', 'tag_audio_events': 'false'}, f'表单字段不符：{ {k: v for k, v in form.items() if k != "file"} }')
    check(form.get('file', {}).get('filename') == 'audio.flac' and form['file'].get('content_type') == 'audio/flac',
          '音频应以 audio.flac（audio/flac）上传')
    units = [u for line in result.get('suggestions', []) for u in line['units']]
    check(''.join(line['text'] for line in result.get('suggestions', [])) == '今日も 歌う', '识别文字应为“今日も 歌う”，声音事件不计入')
    check([(u['start'], u['end']) for u in units][:3] == [(120, 280), (280, 440), (440, 620)], '逐字时间应换算为毫秒')
    check(result.get('diagnostics', {}).get('request_id') == 'mock-req-1', '应记录服务返回的请求编号')
    again = await mock.run(transcribe(mock, 'elevenlabs'))
    check(again.get('ok') and again.get('cached') and len(mock.requests) == 1, '同一音轨再次识别应读缓存，不再发请求')


@scenario('elevenlabs', '中文与自动语言：language_code 原样传 zh；不选语言时不发送该字段，由服务自动判断')
async def eleven_language(mock, check):
    mock.respond = reply(200, STT_OK)
    await mock.run(transcribe(mock, 'elevenlabs', 'zh'))
    await mock.run(transcribe(mock, 'elevenlabs', ''))
    forms = [r.get('form', {}) for r in mock.requests]
    check(len(forms) == 2, f'应发出 2 次请求（语言不同不共用缓存），实际 {len(forms)} 次')
    check(forms[:1] and forms[0].get('language_code') == 'zh', '中文应传 language_code=zh')
    check(len(forms) == 2 and 'language_code' not in forms[1], '不选语言时不应发送 language_code')


@scenario('elevenlabs', '401 密钥无效（detail 为对象）：只发一次，判为服务拒绝、不计费，记录错误代码，不留付费登记')
async def eleven_401(mock, check):
    mock.respond = reply(401, {'detail': {'status': 'invalid_api_key', 'message': 'Invalid API key'}})
    result = await mock.run(transcribe(mock, 'elevenlabs'))
    d = check.failed(result, mock, 'service_rejected', 'rejected', 1, False)
    check(d.get('error_code') == 'invalid_api_key', f'错误代码应为 invalid_api_key，实际 {d.get("error_code")}')
    check('401' in result.get('message', '') and '密钥' in result.get('message', ''), '提示应说明 401 密钥问题')


@scenario('elevenlabs', '422 参数错误（detail 为列表）：读出第一项的 type 作为错误代码')
async def eleven_422(mock, check):
    mock.respond = reply(422, {'detail': [{'loc': ['body', 'language_code'], 'msg': 'Invalid language code', 'type': 'value_error'}]})
    result = await mock.run(transcribe(mock, 'elevenlabs', 'xx'))
    d = check.failed(result, mock, 'service_rejected', 'rejected', 1, False)
    check(d.get('error_code') == 'value_error', f'错误代码应为 value_error，实际 {d.get("error_code")}')


@scenario('elevenlabs', '429 限流：只发一次不自动重试，提示限流')
async def eleven_429(mock, check):
    mock.respond = reply(429, {'detail': {'status': 'too_many_concurrent_requests', 'message': 'busy'}})
    result = await mock.run(transcribe(mock, 'elevenlabs'))
    check.failed(result, mock, 'service_rejected', 'rejected', 1, False)
    check('限流' in result.get('message', ''), '提示应说明限流')


@scenario('elevenlabs', '等待结果时超时：判为可能已计费，保留登记；再点一次被拦下不发送，确认后才重发')
async def eleven_timeout(mock, check):
    mock.respond = stall()
    request = transcribe(mock, 'elevenlabs')
    with patched((api, 'TIMEOUT', api.aiohttp.ClientTimeout(total=None, connect=5, sock_read=.4))):
        result = await mock.run(request)
    check.failed(result, mock, 'waiting', 'possibly_billed', 1, True)
    blocked = await mock.run(request)
    check(blocked.get('resubmit_required', {}).get('stage') == 'waiting' and len(mock.requests) == 1,
          '再次提交应被拦下且不发请求')
    mock.respond = reply(200, STT_OK)
    retried = await mock.run({**request, 'confirm_resubmit': True})
    check(retried.get('ok') and len(mock.requests) == 2 and not mock.pending(), '确认后应重发一次并清除登记')


@scenario('elevenlabs', '等待结果时取消：提示云端可能仍计费，登记标为已取消；下次提交需确认')
async def eleven_cancel(mock, check):
    mock.respond = stall(10)
    request = transcribe(mock, 'elevenlabs')
    result = await mock.run(request, cancel=True)
    check(result.get('cancelled') is True, '应记为已取消')
    check('可能仍会计费' in result.get('message', ''), '取消提示应说明已提交的请求可能仍计费')
    records = mock.pending()
    check(records and records[0].get('cancelled') is True and records[0].get('stage') == 'waiting', '付费登记应标为等待中取消')
    blocked = await mock.run(request)
    check('resubmit_required' in blocked and len(mock.requests) == 1, '取消后再次提交应先确认，不自动重发')


@scenario('elevenlabs', '连不上服务：判为未发出、不计费，不留登记')
async def eleven_refused(mock, check):
    with patched((api, 'ELEVEN_STT', mock.unused_url() + '/v1/speech-to-text')):
        result = await mock.run(transcribe(mock, 'elevenlabs'))
    check.failed(result, mock, 'not_connected', 'not_sent', 0, False)


@scenario('elevenlabs', '返回不是 JSON（如代理网页）：判为解析失败、通常已计费，保留登记')
async def eleven_not_json(mock, check):
    mock.respond = reply(200, raw=b'<html>proxy sign-in page</html>', headers={'Content-Type': 'text/html'})
    result = await mock.run(transcribe(mock, 'elevenlabs'))
    check.failed(result, mock, 'parsing', 'likely_billed', 1, True)


@scenario('elevenlabs', '返回结构异常（时间倒序）：原始返回存入任务目录，不应用结果')
async def eleven_bad_times(mock, check):
    broken = {**STT_OK, 'words': [{'text': '歌', 'start': 2.0, 'end': 1.0, 'type': 'word'}]}
    mock.respond = reply(200, broken)
    result = await mock.run(transcribe(mock, 'elevenlabs'))
    d = check.failed(result, mock, 'parsing', 'likely_billed', 1, True)
    check(d.get('response_saved') == 'api-response.json' and (mock.work / f'run-{mock.runs}' / 'api-response.json').is_file(),
          '原始返回应保存在任务目录')


@scenario('elevenlabs', '识别上限 5 GB：达到上限的音轨在本机拦下，不上传')
async def eleven_size(mock, check):
    mock.size = 4096; mock.respond = reply(200, STT_OK)
    with patched((api, 'ELEVEN_STT_BYTES', 4096)):
        result = await mock.run(transcribe(mock, 'elevenlabs'))
    check.failed(result, mock, 'local', 'not_sent', 0, False)
    check('5 GB' in result.get('message', ''), '提示应写明 5 GB 上限')


@scenario('elevenlabs', '对齐成功：上传歌词原文与音频，按行拆回逐字时间并合并成词')
async def eleven_align_ok(mock, check):
    mock.respond = reply(200, ALIGN_OK)
    result = await mock.run(align(mock))
    sent = mock.requests[0] if mock.requests else {}
    check(result.get('ok') is True, f'应成功：{result.get("message")}')
    check(sent.get('path') == '/v1/forced-alignment', '接口路径应为 /v1/forced-alignment')
    check(sent.get('form', {}).get('text') == '\n'.join(ALIGN_TEXT), '应按行上传歌词原文')
    lines = result.get('suggestions', [])
    check([line['text'] for line in lines] == ALIGN_TEXT, '应按原分行返回')
    check([(line['start'], line['end']) for line in lines] == [(120, 620), (700, 1300)], '每行起止应取自逐字时间（毫秒）')
    check(lines and lines[0]['units'][0]['start'] == 120 and lines[0]['units'][-1]['end'] == 620, '逐字时间合并成词后首尾不变')


@scenario('elevenlabs', '对齐结果省略换行或以空格代替：按原分行补回，不判为歌词不一致')
async def eleven_align_breaks(mock, check):
    dropped = {**ALIGN_OK, 'characters': [c for c in ALIGN_OK['characters'] if c['text'] != '\n']}
    mock.respond = reply(200, dropped)
    result = await mock.run(align(mock))
    check(result.get('ok') is True and [l['text'] for l in result.get('suggestions', [])] == ALIGN_TEXT,
          f'省略换行时应仍能按行拆分：{result.get("message")}')


@scenario('elevenlabs', '对齐上限 1 GB：达到上限在本机拦下，不上传')
async def eleven_align_size(mock, check):
    mock.size = 4096; mock.respond = reply(200, ALIGN_OK)
    with patched((api, 'ELEVEN_ALIGN_BYTES', 4096)):
        result = await mock.run(align(mock))
    check.failed(result, mock, 'local', 'not_sent', 0, False)


@scenario('mai', '识别成功：definition 按文档填写（MAI-Transcribe-2、逐词时间、locales=ja），带 api-version；无逐词时间的句子按句均分')
async def mai_ok(mock, check):
    mock.respond = reply(200, MAI_OK, {'apim-request-id': 'mock-apim-1'})
    result = await mock.run(transcribe(mock, 'mai'))
    sent = mock.requests[0] if mock.requests else {}
    form = sent.get('form', {})
    check(result.get('ok') is True, f'应成功：{result.get("message")}')
    check(sent.get('path') == '/speechtotext/transcriptions:transcribe' and sent.get('query') == {'api-version': '2025-10-15'},
          f'接口应为 transcriptions:transcribe?api-version=2025-10-15，实际 {sent.get("path")} {sent.get("query")}')
    check(sent.get('keys', {}).get('ocp-apim-subscription-key') == MOCK_KEYS['mai'], '应以 Ocp-Apim-Subscription-Key 头发送密钥')
    try: definition = json.loads(form.get('definition', '{}'))
    except ValueError: definition = {}
    check(definition.get('enhancedMode') == {'enabled': True, 'model': 'MAI-Transcribe-2', 'modelOptions': {'timestamps': 'word'}},
          f'enhancedMode 不符：{definition.get("enhancedMode")}')
    check(definition.get('locales') == ['ja'], f'locales 应为 ["ja"]，实际 {definition.get("locales")}')
    check(form.get('audio', {}).get('filename') == 'audio.flac', '音频应放在 audio 字段')
    lines = result.get('suggestions', [])
    check([line['text'] for line in lines] == ['今日も歌う', '遠くへ'], '应按句返回两行')
    check(lines and [(u['start'], u['end']) for u in lines[0]['units']] == [(120, 620), (700, 1300)], '逐词时间应原样换算')
    check(len(lines) == 2 and lines[1]['start'] == 2000 and lines[1]['end'] == 2900, '无逐词时间的句子应保留句首句尾')
    check(result.get('diagnostics', {}).get('request_id') == 'mock-apim-1', '应记录 apim-request-id')


@scenario('mai', '中文与自动语言：locales 原样传 ["zh"]；不选语言时不发送 locales')
async def mai_language(mock, check):
    mock.respond = reply(200, MAI_OK)
    await mock.run(transcribe(mock, 'mai', 'zh'))
    await mock.run(transcribe(mock, 'mai', ''))
    definitions = [json.loads(r.get('form', {}).get('definition', '{}')) for r in mock.requests]
    check(len(definitions) == 2 and definitions[0].get('locales') == ['zh'], '中文应传 locales=["zh"]')
    check(len(definitions) == 2 and 'locales' not in definitions[1], '不选语言时不应发送 locales')


@scenario('mai', '400 音频超长（innerError）：读出内层错误代码 AudioLengthLimitExceeded 并在提示中说明')
async def mai_inner_error(mock, check):
    mock.respond = reply(400, {'error': {'code': 'InvalidRequest', 'message': 'Audio too long.',
                                         'innerError': {'code': 'AudioLengthLimitExceeded', 'message': 'Audio too long.'}}},
                         {'apim-request-id': 'mock-apim-2'})
    result = await mock.run(transcribe(mock, 'mai'))
    d = check.failed(result, mock, 'service_rejected', 'rejected', 1, False)
    check(d.get('error_code') == 'AudioLengthLimitExceeded', f'错误代码应为 AudioLengthLimitExceeded，实际 {d.get("error_code")}')
    check('时长限制' in result.get('message', ''), '提示应说明超过时长限制')
    check(d.get('request_id') == 'mock-apim-2', '应记录 apim-request-id')


@scenario('mai', '401 订阅密钥无效：只发一次，判为服务拒绝')
async def mai_401(mock, check):
    mock.respond = reply(401, {'error': {'code': '401', 'message': 'Access denied due to invalid subscription key.'}})
    result = await mock.run(transcribe(mock, 'mai'))
    check.failed(result, mock, 'service_rejected', 'rejected', 1, False)


@scenario('mai', '429 限流（带 Retry-After）：只发一次不自动重试')
async def mai_429(mock, check):
    mock.respond = reply(429, {'error': {'code': 'TooManyRequests', 'message': 'Rate limit exceeded.'}}, {'Retry-After': '30'})
    result = await mock.run(transcribe(mock, 'mai'))
    d = check.failed(result, mock, 'service_rejected', 'rejected', 1, False)
    check(d.get('error_code') == 'TooManyRequests', f'错误代码应为 TooManyRequests，实际 {d.get("error_code")}')


@scenario('mai', '时长上限 2 小时：本机读 FLAC 头判断，超过即拦下不上传')
async def mai_duration(mock, check):
    mock.seconds = 2.5 * 3600; mock.respond = reply(200, MAI_OK)
    result = await mock.run(transcribe(mock, 'mai'))
    check.failed(result, mock, 'local', 'not_sent', 0, False)
    check('2 小时' in result.get('message', '') and 'ElevenLabs' in result.get('message', ''), '提示应写明 2 小时上限并建议改用 ElevenLabs')


@scenario('mai', '大小上限 250 MB：达到上限在本机拦下，不上传')
async def mai_size(mock, check):
    mock.size = 4096; mock.respond = reply(200, MAI_OK)
    with patched((api, 'MAI_BYTES', 4096)):
        result = await mock.run(transcribe(mock, 'mai'))
    check.failed(result, mock, 'local', 'not_sent', 0, False)
    check('250 MB' in result.get('message', ''), '提示应写明 250 MB 上限')


@scenario('deepseek', '注音成功：等待期间先收到空行保活，再收到 JSON；请求为 JSON 输出、关闭思考、不流式')
async def deepseek_ok(mock, check):
    mock.respond = keepalive(chat(json.dumps(ANNOTATION, ensure_ascii=False)))
    result = await mock.run(annotate(mock))
    sent = mock.requests[0] if mock.requests else {}
    payload = sent.get('json', {})
    check(result.get('ok') is True, f'应成功：{result.get("message")}')
    check(sent.get('path') == '/chat/completions', '接口路径应为 /chat/completions')
    check(sent.get('keys', {}).get('authorization') == 'Bearer ' + MOCK_KEYS['deepseek'], '应以 Bearer 头发送密钥')
    check(payload.get('model') == 'deepseek-flash' and payload.get('response_format') == {'type': 'json_object'}
          and payload.get('thinking') == {'type': 'disabled'} and payload.get('stream') is False,
          '请求应为 deepseek-flash、JSON 输出、关闭思考、不流式')
    check(json.loads(payload.get('messages', [{}, {'content': '{}'}])[1]['content']) == {'lines': [{'id': '1', 'text': '今日も'}]},
          '只发送歌词文字和行号')
    check(result.get('annotations', [{}])[0].get('kana') == 'きょうも', '应解析出假名')


@scenario('deepseek', '402 余额不足：只发一次，判为服务拒绝，不留登记')
async def deepseek_402(mock, check):
    mock.respond = reply(402, {'error': {'message': 'Insufficient Balance', 'type': 'unknown_error', 'param': None,
                                         'code': 'invalid_request_error'}})
    result = await mock.run(annotate(mock))
    check.failed(result, mock, 'service_rejected', 'rejected', 1, False)
    check('余额不足' in result.get('message', ''), '提示应说明余额不足')


@scenario('deepseek', '429 并发超限：只发一次不自动重试')
async def deepseek_429(mock, check):
    mock.respond = reply(429, {'error': {'message': 'Rate limit reached', 'type': 'rate_limit_error', 'code': 'rate_limit_exceeded'}})
    result = await mock.run(annotate(mock))
    d = check.failed(result, mock, 'service_rejected', 'rejected', 1, False)
    check(d.get('error_code') == 'rate_limit_exceeded', f'错误代码应为 rate_limit_exceeded，实际 {d.get("error_code")}')


@scenario('deepseek', '503 服务繁忙：是否计费未知，保留登记，下次需确认')
async def deepseek_503(mock, check):
    mock.respond = reply(503, {'error': {'message': 'Server overloaded', 'type': 'server_error', 'code': None}})
    result = await mock.run(annotate(mock))
    check.failed(result, mock, 'service_error', 'unknown', 1, True)
    blocked = await mock.run(annotate(mock))
    check('resubmit_required' in blocked and len(mock.requests) == 1, '再次提交应先确认，不自动重发')


@scenario('deepseek', '输出被截断（finish_reason=length）：判为解析失败，提示减少行数')
async def deepseek_truncated(mock, check):
    mock.respond = reply(200, chat('{"lines": [', 'length'))
    result = await mock.run(annotate(mock))
    check.failed(result, mock, 'parsing', 'likely_billed', 1, True)
    check('截断' in result.get('message', ''), '提示应说明输出被截断')


@scenario('deepseek', '改动了原歌词：校验拒绝、不应用结果，并如实记为已返回（通常已计费）而非未发出')
async def deepseek_changed_lyrics(mock, check):
    changed = {'lines': [{**ANNOTATION['lines'][0], 'groups': [{'text': '明日', 'kana': 'あした', 'romaji': 'ashita'},
                                                               {'text': 'も', 'kana': 'も', 'romaji': 'mo'}]}]}
    mock.respond = reply(200, chat(json.dumps(changed, ensure_ascii=False)))
    result = await mock.run(annotate(mock))
    check.failed(result, mock, 'parsing', 'likely_billed', 1, True)
    check('原歌词' in result.get('message', ''), f'应说明结果改动了原歌词：{result.get("message")}')


async def run_mock(folder, names=None, progress=None):
    """Run the mock scenarios in ``folder``; returns [(scenario, problems, seconds)]."""
    results = []
    for item in SCENARIOS:
        if names and item.name not in names: continue
        started = time.monotonic()
        try: problems = await item.run(Path(folder) / item.name / 'home', Path(folder) / item.name / 'work')
        except Exception as error: problems = [f'检查本身出错：{type(error).__name__}: {error}']
        results.append((item, problems, time.monotonic() - started))
        if progress: progress(item, problems)
    return results


# --- 真实 (real) checks, only when the person runs them ---------------------

REAL_SAMPLE = Path(__file__).resolve().parents[2] / 'desktop' / 'assets' / 'alignment-demo'


async def real_check(name, request, home, folder):
    """One real task through the normal worker; returns a short, key-free summary."""
    path = Path(folder) / name / 'result.json'; path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    await worker.execute({**request, 'force': True}, str(home) if home else None, path)
    result = json.loads(path.read_text(encoding='utf-8'))
    d = result.get('diagnostics', {})
    summary = {'check': name, 'ok': bool(result.get('ok')), 'seconds': round(time.monotonic() - started, 1),
               'stage': d.get('stage'), 'billing': d.get('billing'), 'http_status': d.get('http_status'),
               'error_code': d.get('error_code'), 'request_id': d.get('request_id'),
               'message': '' if result.get('ok') else result.get('message', '')}
    lines = result.get('suggestions', [])
    if lines:
        summary['lines'] = len(lines)
        summary['text'] = ''.join(line.get('text', '') for line in lines)[:120]
        summary['span_ms'] = [lines[0].get('start'), lines[-1].get('end')]
    if result.get('annotations'):
        summary['kana'] = result['annotations'][0].get('kana', '')[:120]
    return summary


def real_requests(language='ja'):
    """The real checks for each service: the 16 s PJS056 clip, or one short lyric line."""
    sample = json.loads((REAL_SAMPLE / 'sample.json').read_text(encoding='utf-8'))
    media = str(REAL_SAMPLE / 'pjs056_song.wav')
    text = sample['text']
    line = LyricLine('1', text, round(sample['mora'][0]['start']), round(sample['mora'][-1]['end'])).to_dict()
    return {'elevenlabs': [('elevenlabs-transcribe', {'action': 'transcribe', 'provider': 'elevenlabs', 'media': media,
                                                      'language': language, 'lines': []}),
                           ('elevenlabs-align', {'action': 'align', 'media': media, 'lines': [line], 'range_mode': 'full'})],
            'mai': [('mai-transcribe', {'action': 'transcribe', 'provider': 'mai', 'media': media, 'language': language, 'lines': []})],
            'deepseek': [('deepseek-annotate', {'action': 'annotate', 'lines': [LyricLine('1', '遠くの空に今日も歌う', 0, 3000).to_dict()]})]}
