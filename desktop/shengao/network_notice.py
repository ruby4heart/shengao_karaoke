"""What a background request sends over the network, said before it is sent.

Toolkit independent. ``describe`` reads a background request exactly as it
would be handed to the worker and returns one entry per online service it may
reach: which company and address, whether audio, text or both leave the
computer, how much of it, and which local records and caches it writes.
Requests that stay on this computer return an empty list and are never
interrupted. The entries mirror backend/studio_backend/worker.py and
draft.py; tests pin them to the request shapes those modules accept.
"""
from pathlib import Path
from urllib.parse import urlsplit

ELEVEN_HOST = 'api.elevenlabs.io'
DEEPSEEK_HOST = 'api.deepseek.com'
AUDIO_NOTE = '音轨先在本机转成 FLAC 再上传，视频画面不上传'
KEY_NOTE = 'API 密钥只用于这次请求的身份验证，不写入任务记录、工程或诊断报告。'


def _minutes(ms):
    if not isinstance(ms, (int, float)) or ms <= 0: return ''
    seconds = round(ms / 1000)
    return f'约 {seconds // 60} 分 {seconds % 60:02d} 秒' if seconds >= 60 else f'约 {seconds} 秒'


def _lines(request):
    return [x for x in request.get('lines', []) if isinstance(x, dict)]


def _characters(lines):
    return sum(len(x.get('text', '')) for x in lines)


def _media_name(request):
    media = request.get('media')
    return Path(str(media)).name if media else '当前素材'


LANGUAGES = {'ja': '日语', 'zh': '中文', 'en': '英语', 'ko': '韩语'}


def _language(request):
    code = request.get('language', 'ja')
    return '识别语言：' + LANGUAGES.get(code, str(code))


def _transcription(request, provider, services, duration):
    whole = f'「{_media_name(request)}」的整条音轨' + (f'（{_minutes(duration)}）' if _minutes(duration) else '')
    if provider == 'mai':
        endpoint = (services.get('mai') or {}).get('endpoint') or ''
        host = urlsplit(endpoint).hostname or '你在服务设置中填写的 Azure 资源地址'
        return {'id': 'mai:audio', 'short': 'Microsoft AI 转录（音频）', 'service': 'Microsoft AI 语音转文字（MAI-Transcribe-2，Azure Speech）', 'host': host,
                'kind': '音频', 'sends': [whole + '；' + AUDIO_NOTE, _language(request)],
                'keeps': ['歌词、译文和工程文件不发送']}
    return {'id': 'elevenlabs-stt:audio', 'short': 'ElevenLabs 转录（音频）', 'service': 'ElevenLabs 语音转文字（Scribe v2）', 'host': ELEVEN_HOST,
            'kind': '音频', 'sends': [whole + '；' + AUDIO_NOTE, _language(request)],
            'keeps': ['歌词、译文和工程文件不发送']}


def _alignment(request, lines, duration, whole):
    if whole or request.get('range_mode', 'full') != 'selection':
        audio = f'「{_media_name(request)}」的整条音轨' + (f'（{_minutes(duration)}）' if _minutes(duration) else '')
    else:
        starts = [x.get('start') for x in lines if isinstance(x.get('start'), (int, float))]
        ends = [x.get('end') for x in lines if isinstance(x.get('end'), (int, float))]
        span = max(ends) - min(starts) if starts and ends else None
        audio = '所选歌词时间范围内的一段音轨' + (f'（{_minutes(span)}）' if _minutes(span) else '')
    scope = '全部' if whole else '所选'
    text = (f'{scope} {len(lines)} 句歌词的原文（共 {_characters(lines)} 字）' if lines else '要对齐的歌词原文')
    return {'id': 'elevenlabs-align:audio+text', 'short': 'ElevenLabs 对齐（音频和歌词文字）', 'service': 'ElevenLabs 文字对齐（Forced Alignment）', 'host': ELEVEN_HOST,
            'kind': '音频和文字', 'sends': [audio + '；' + AUDIO_NOTE, text + '；不含假名、罗马音和译文'],
            'keeps': ['其他歌词、译文和工程文件不发送']}


def _deepseek(lines, services, transcript, neighbours, protected, at_most=False):
    model = (services.get('deepseek') or {}).get('model') or 'deepseek-flash'
    sends = [(('最多 ' if at_most else '') + f'{len(lines)} 句歌词原文' +
              (f'（共 {_characters(lines)} 字）' if lines else '') + '，以及每个词现有的读音和本机词典读音')]
    if neighbours: sends.append('每句的上一句和下一句歌词，帮助判断读法')
    if transcript: sends.append('与这些句子时间相近的转录文字（最多 4 段），作为实际唱法的参考')
    return {'id': 'deepseek:text', 'short': 'DeepSeek（歌词文字）', 'service': f'DeepSeek 文字模型（{model}）', 'host': DEEPSEEK_HOST,
            'kind': '文字', 'sends': sends,
            'keeps': ['不发送任何音频'] + (['读音已锁定或已人工确认的句子会跳过，不发送'] if protected else []) + ['已有译文和工程文件不发送']}


def describe(request, services=None, duration=None):
    """Online services a background request may reach, in the order they would be used."""
    services = services or {}
    if not isinstance(request, dict): return []
    action = request.get('action'); lines = _lines(request)
    if action in {'transcribe', 'transcribe_match'}:
        return [_transcription(request, request.get('provider', 'elevenlabs'), services, duration)]
    if action == 'align':
        return [_alignment(request, lines, duration, False)]
    if action == 'annotate':
        return [_deepseek(lines, services, False, False, False)]
    if action == 'refine' and request.get('use_llm'):
        return [_deepseek(lines, services, bool(request.get('transcript')), True, True)]
    if action == 'draft':
        options = request.get('draft_options') or {}; found = []
        if options.get('source') == 'cloud':
            found.append(_transcription(request, options.get('provider', 'elevenlabs'), services, duration))
        if options.get('readings') == 'deepseek':
            found.append(_deepseek(lines, services, options.get('source') in {'cloud', 'reuse'}, True, True, True))
        if options.get('align'):
            found.append(_alignment(request, lines, duration, True))
        return found
    return []


def caches(request, home):
    """Local records this request writes, as plain sentences with their folders."""
    home = Path(home); action = request.get('action')
    rows = [f'任务记录：{home / "desktop-tasks" / "<任务编号>"}（请求里的歌词、素材位置和选项，以及服务返回的结果；不含密钥）',
            f'付费请求登记：{home / "paid-requests"}（只记请求指纹和进行到哪一步，用来防止中断后自动重发）']
    audio = any(item['kind'] != '文字' for item in describe(request))
    if audio:
        rows.append(f'识别和对齐结果缓存：{home / "cache"}（服务返回的原始结果；同一音轨和设置再次使用时直接读取，不再上传）')
        rows.append(f'临时音轨：在 {home} 下的临时文件夹中转成 FLAC，上传结束后删除')
    if action == 'refine' or (action == 'draft' and (request.get('draft_options') or {}).get('readings') == 'deepseek'):
        rows.append(f'读音建议缓存：{home / "readings"}（每批 DeepSeek 结果；同样的内容再次复核时直接读取）')
    if action == 'draft': rows.append(f'初稿流程进度：{home / "draft-workflows"}（每一步完成后保存，继续时已完成的步骤不再发送）')
    rows.append('结果先进入审核，采用后才写入工程；工程文件本身不会发送。')
    return rows


def text(request, home, services=None, duration=None):
    """The explanation shown before sending, or '' when nothing goes online."""
    found = describe(request, services, duration)
    if not found: return ''
    rows = ['这次操作会联网，并使用你的服务额度：', '']
    for number, item in enumerate(found, 1):
        rows.append(f'{number}. {item["service"]}')
        rows.append(f'   发送到：{item["host"]}（{item["kind"]}）')
        rows += [f'   · 发送：{x}' for x in item['sends']]
        rows += [f'   · {x}' for x in item['keeps']]
        rows.append('')
    rows.append('本机会保存：')
    rows += [f'   · {x}' for x in caches(request, home)]
    rows += ['', KEY_NOTE]
    return '\n'.join(rows)


def keys(request, services=None):
    """Identifiers of the kinds of sending in this request, for “do not ask again”."""
    return sorted({item['id'] for item in describe(request, services)})


def summary(request, services=None):
    """One status-line sentence naming where this request sends data, or ''."""
    found = describe(request, services)
    return '联网发送到 ' + '、'.join(item['short'] for item in found) + '；' if found else ''


def remembered(value):
    """The saved “do not ask again” list, ignoring anything malformed."""
    return {x for x in value if isinstance(x, str)} if isinstance(value, list) else set()


def pending(request, saved, services=None):
    """Kinds of sending in this request the person has not chosen to stop being asked about."""
    return [x for x in keys(request, services) if x not in remembered(saved)]
