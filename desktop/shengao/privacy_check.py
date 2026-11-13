"""Privacy acceptance: no keys or private user material where others can see it.

Four places are checked, each on its own:

* Git: every tracked file (the working tree when there is no Git) has no API
  key, no key saved on this computer, no personal folder path; no project,
  settings, task record or cache from a person's own work is tracked; audio,
  video and subtitles are only the published demo and reference files.
* Release assets: every file inside the release archives (dist/*.zip by
  default) has no key, no key or home folder or user name of this computer and
  no private file. Other people's home folders are not failed there: the
  archives are mostly third-party files (upstream DLLs, package metadata, the
  standard library) that keep their authors' build and example paths, public
  and not ours to change; our own files are the tracked ones, already held to
  the full rule above. They are counted instead. A media file that is not
  byte-identical to a published one is listed for checking rather than failed
  outright, except upstream test files under a vendor folder.
* Diagnostics: a report built from a made-up home full of fake keys, lyrics,
  e-mail addresses and personal paths contains none of them; the report from
  this computer's own home contains none of its saved keys.
* Local records and projects: background task records, caches, workspace
  settings and the recently opened projects contain no saved key or key-shaped
  text. Lyrics and media paths there are the person's own and expected.

Findings never repeat a key: they name the kind and show at most its first
four characters. Toolkit independent; scripts/check-privacy.py prints it.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile

LIMIT = 64 * 1024 * 1024
MEDIA = {'.wav', '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma', '.mp4', '.mkv', '.mov', '.webm', '.avi',
         '.ass', '.ssa', '.srt', '.lrc', '.vtt'}
# Published files: each has a stated source in the repository.
PUBLIC_MEDIA = {
    'demo/demo.wav': '合成演示音（scripts/make-demo.py 生成）',
    'demo/rendered.ass': '演示字幕（scripts/make-demo.py 导出）',
    'desktop/assets/alignment-demo/pjs056_song.wav': 'PJS 公开歌声语料 PJS056，CC BY-SA 4.0（见同目录 ATTRIBUTION.txt）',
    'desktop/assets/demo/tutorial.mp4': '教程视频，合成画面加 demo.wav（scripts/make-desktop-demo.py 生成）',
    'docs/examples/shengao010-dual-row-demo.mp4': '8 秒合成音布局演示（docs/V010-ACCEPTANCE.md）',
}
# (kind, fixed anchors, pattern matched at each anchor, whether the anchor
# must start a word, whether anchors are searched case-insensitively).
# Anchors keep large media and release binaries fast to scan.
KEYS = [
    ('ElevenLabs 式密钥', [b'sk_'], re.compile(rb'sk_[0-9a-f]{48}(?![0-9a-f])'), True, False),
    ('DeepSeek 式密钥', [b'sk-'], re.compile(rb'sk-[0-9a-f]{32}(?![0-9a-f])'), True, False),
    ('OpenAI 式密钥', [b'sk-'], re.compile(rb'sk-(?:proj-)?[A-Za-z0-9_-]{40,}'), True, False),
    ('GitHub 令牌', [b'ghp_', b'gho_', b'ghu_', b'ghs_', b'ghr_', b'github_pat_'],
     re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})'), True, False),
    ('AWS 访问密钥', [b'AKIA'], re.compile(rb'AKIA[0-9A-Z]{16}(?![0-9A-Z])'), True, False),
    ('私钥', [b'-----BEGIN '], re.compile(rb'-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----'), False, False),
    ('服务请求头里的密钥', [b'xi-api-key', b'ocp-apim-subscription-key'],
     re.compile(rb'(?i)(?:xi-api-key|ocp-apim-subscription-key)["\']?\s*[:=]\s*["\']?[A-Za-z0-9]{20,}'), False, True),
    ('Bearer 令牌', [b'authorization'],
     re.compile(rb'(?i)authorization["\']?\s*[:=]\s*["\']?bearer\s+[A-Za-z0-9._~+/-]{24,}'), False, True),
]
PLACEHOLDERS = {'public', 'default', 'all users', 'default user', 'user', 'users', 'username', 'yourname', 'name', 'me',
                '用户', '用户名', '你的用户名', '〔用户〕'}
USER_NAME = re.compile(rb'[^\\/\s<>%{}"\'*?|:,;]+')
POSIX_NAME = re.compile(rb'([A-Za-z][\w.-]*)/')
# Synthetic personal paths that exist to prove they are redacted.
PATH_EXCEPTIONS = {'desktop/tests/test_diagnostics.py': '诊断脱敏测试用的虚构路径'}
PRIVATE_FOLDERS = {'desktop-tasks', 'desktop-recovery', 'desktop-renders', 'paid-requests', 'draft-workflows',
                   'chorus-workflows', 'vocal-cache', 'vocal-previews', 'wave-cache', 'version-history', 'readings'}
PRIVATE_FILES = {'workspace.json': '工作区设置', 'settings.json': '服务设置', '.env': '环境变量文件'}
SKIP_HOME = {'vocal-cache', 'vocal-previews', 'wave-cache'}


def mask(value):
    text = value.decode('utf-8', 'replace') if isinstance(value, bytes) else str(value)
    return text[:4] + '…'


def line_of(data, offset):
    return data.count(b'\n', 0, offset) + 1


def finding(where, what, line=None):
    return {'where': f'{where}:{line}' if line else str(where), 'what': what}


def saved_keys(home):
    """Keys this computer would send, as (service, key); empty when none can be read."""
    try:
        from studio_backend.settings import Settings
        settings = Settings(home)
    except (OSError, ValueError, ImportError):
        return []
    found = []
    for provider, title in (('elevenlabs', 'ElevenLabs'), ('mai', 'Microsoft AI'), ('deepseek', 'DeepSeek')):
        try:
            key = settings.key(provider)
        except Exception:  # DPAPI unavailable or damaged settings: patterns still apply
            key = ''
        if isinstance(key, str) and len(key) >= 8: found.append((title, key))
    return found


def personal(home=None):
    """This computer's own home folder and user name, as bytes to look for."""
    values = []
    user = os.getenv('USERNAME') or os.getenv('USER') or ''
    for path in {str(Path.home()), str(home) if home else ''}:
        if len(path) > 3 and path not in {'/root', 'C:\\', '/'}:
            values += [path.encode(), path.replace('\\', '/').encode(), path.replace('/', '\\').encode()]
    return sorted(set(values), key=len, reverse=True), user


def _anchors(data, anchors, lower=None):
    """Positions of fixed byte strings, in order."""
    text = data if lower is None else lower
    found = []
    for anchor in anchors:
        offset = text.find(anchor)
        while offset >= 0:
            found.append(offset); offset = text.find(anchor, offset + 1)
    return sorted(set(found))


def _word_start(data, offset):
    return offset == 0 or not data[offset - 1:offset].isalnum()


def secrets_in(data, where, keys=()):
    """Key-shaped text and saved keys in one file's bytes."""
    found = []; lower = None
    for title, anchors, pattern, word, folded in KEYS:
        if folded and lower is None: lower = data.lower()
        for offset in _anchors(data, anchors, lower if folded else None):
            if word and not _word_start(data, offset): continue
            match = pattern.match(data, offset)
            if match: found.append((offset, f'疑似{title}（{mask(match.group())}）'))
    for title, key in keys:
        offset = data.find(key.encode('utf-8'))
        if offset >= 0: found.append((offset, f'含本机保存的 {title} 密钥（{mask(key)}）'))
    # In file order, so a report reads top to bottom.
    return [finding(where, what, line_of(data, offset)) for offset, what in sorted(found)]


def users_in(data):
    """(offset, user name) for every Windows or POSIX home folder path in the bytes."""
    found = []; lower = data.lower()
    for anchor in (b':\\users\\', b':\\\\users\\\\', b':/users/'):
        for offset in _anchors(data, [anchor], lower):
            drive = offset - 1
            if drive < 0 or not data[drive:offset].isalpha() or (drive and data[drive - 1:drive].isalpha()): continue
            match = USER_NAME.match(data, offset + len(anchor))
            if match: found.append((drive, match.group()))
    for anchor in (b'/home/', b'/Users/'):
        for offset in _anchors(data, [anchor]):
            before = data[offset - 1:offset]
            if offset and (before.isalnum() or before in b'_./-:'): continue
            match = POSIX_NAME.match(data, offset + len(anchor))
            if match: found.append((offset, match.group(1)))
    return found


def personal_paths(data, where, own=((), '')):
    """(this computer's, other people's) home folder paths in one file's bytes."""
    if where.replace('\\', '/') in PATH_EXCEPTIONS: return [], []
    paths, user = own; mine = []; others = []
    for offset, raw in users_in(data):
        name = raw.decode('utf-8', 'replace').strip('.')
        if not name or name.lower() in PLACEHOLDERS: continue
        if len(user) >= 3 and name.lower() == user.lower():
            mine.append(finding(where, '含本机用户名路径', line_of(data, offset)))
        else:
            others.append(finding(where, f'含个人目录路径（用户名 {name}）', line_of(data, offset)))
    for path in paths:
        offset = data.find(path)
        if offset >= 0: mine.append(finding(where, '含本机个人目录路径', line_of(data, offset))); break
    if len(user) >= 3 and not mine:
        lower = data.lower(); name = user.lower().encode('utf-8')
        for anchor in (b'\\users\\', b'/users/', b'/home/', b'\\\\users\\\\'):
            offset = lower.find(anchor + name)
            end = offset + len(anchor + name)
            if offset >= 0 and not data[end:end + 1].isalnum():
                mine.append(finding(where, '含本机用户名路径', line_of(data, offset))); break
    return mine, others


def paths_in(data, where, own=((), '')):
    """Every home folder path in one of our own files, anyone's."""
    mine, others = personal_paths(data, where, own)
    return others + mine


def private_name(relative):
    parts = [x for x in relative.replace('\\', '/').split('/') if x]
    if not parts: return ''
    if parts[-1].lower().endswith('.sgproj'): return '声稿工程文件'
    if parts[-1].lower() in PRIVATE_FILES: return PRIVATE_FILES[parts[-1].lower()]
    if parts[-1].lower().startswith('.env.'): return '环境变量文件'
    folder = next((x for x in parts[:-1] if x.lower() in PRIVATE_FOLDERS), '')
    return f'个人数据目录 {folder}' if folder else ''


def tracked(root):
    """Tracked files, or every file outside build and environment folders without Git."""
    root = Path(root)
    try:
        output = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, check=True, timeout=60).stdout
        names = [x for x in output.decode('utf-8', 'replace').split('\0') if x]
        if names: return names, 'Git 跟踪文件'
    except (OSError, subprocess.SubprocessError):
        pass
    skip = {'.git', '.venv', '.venv-desktop', '.venv-align', '.venv-vocals', 'build', 'dist', 'tmp', '__pycache__',
            '.pytest_cache', 'vendor'}
    names = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        names += [str((Path(folder) / f).relative_to(root)).replace('\\', '/') for f in files]
    return sorted(names), '工作目录文件（没有 Git 记录）'


def check_repository(root, keys=(), own=None):
    root = Path(root); own = own or personal()
    names, label = tracked(root); problems = []; checked = 0
    for name in names:
        path = root / name
        kind = private_name(name)
        if kind: problems.append(finding(name, f'不应进入仓库的{kind}'))
        if Path(name).suffix.lower() in MEDIA and name not in PUBLIC_MEDIA:
            problems.append(finding(name, '未登记来源的音视频或字幕文件'))
        try:
            if not path.is_file() or path.stat().st_size > LIMIT: continue
            data = path.read_bytes()
        except OSError:
            continue
        checked += 1
        problems += secrets_in(data, name, keys) + paths_in(data, name, own)
    return {'title': 'Git 仓库', 'checked': f'{label} {len(names)} 个，读取内容 {checked} 个', 'problems': problems, 'warnings': []}


def public_hashes(root):
    hashes = {}
    for name in PUBLIC_MEDIA:
        try: hashes[hashlib.sha256((Path(root) / name).read_bytes()).hexdigest()] = name
        except OSError: pass
    return hashes


def check_archives(paths, root, keys=(), own=None):
    own = own or personal(); known = public_hashes(root)
    problems = []; warnings = []; entries = 0; skipped = 0; names = []; others = 0; other_files = 0; upstream = 0
    for archive in paths:
        archive = Path(archive); names.append(archive.name)
        try:
            with zipfile.ZipFile(archive) as bundle:
                for info in bundle.infolist():
                    if info.is_dir(): continue
                    entries += 1; where = f'{archive.name}!{info.filename}'
                    kind = private_name(info.filename)
                    if kind: problems.append(finding(where, f'不应进入发行包的{kind}'))
                    if info.file_size > LIMIT:
                        skipped += 1; continue
                    data = bundle.read(info)
                    if Path(info.filename).suffix.lower() in MEDIA and hashlib.sha256(data).hexdigest() not in known:
                        if 'vendor' in Path(info.filename).parts[:-1]: upstream += 1
                        else: warnings.append(finding(where, '音视频或字幕与公开演示文件不一致，请确认来源'))
                    mine, theirs = personal_paths(data, where, own)
                    problems += secrets_in(data, where, keys) + mine
                    others += len(theirs); other_files += bool(theirs)
        except (OSError, zipfile.BadZipFile) as error:
            problems.append(finding(archive, f'发行包无法读取（{error}）'))
    checked = (f'{len(names)} 个发行包（{"、".join(names)}），文件 {entries} 个' +
               (f'，超过 64 MB 未读内容 {skipped} 个' if skipped else '') +
               (f'；第三方文件里别人的目录路径 {others} 处（{other_files} 个文件，上游构建或示例留下的，不计为问题）' if others else '') +
               (f'；vendor 里上游源码自带的测试音视频或字幕 {upstream} 个' if upstream else '')) if names else '没有找到发行包，跳过'
    return {'title': '发行资产', 'checked': checked, 'problems': problems, 'warnings': warnings}


class _Settings:
    """Stand-in service settings holding made-up keys."""
    def __init__(self, keys, endpoint):
        self.keys = keys; self.endpoint = endpoint

    def public(self):
        return {name: {'has_key': True, **({'endpoint': self.endpoint} if name == 'mai' else {})} for name in self.keys}

    def key(self, provider):
        return self.keys.get(provider, '')


class _Line:
    def __init__(self, text):
        self.text = text; self.translation = '誰も知らない訳'; self.kana = 'ひみつ'; self.romaji = 'himitsu'; self.units = []


class _Project:
    def __init__(self, texts, media):
        self.lines = [_Line(x) for x in texts]; self.duration = 8000; self.media = media
        self.media_role = 'original'; self.media_versions = {}; self.source_ass_active = False


def check_diagnostics(home=None, keys=()):
    """A report from made-up private data, then this computer's own report."""
    from . import diagnostics
    problems = []
    fake = {'elevenlabs': 'sk_' + '3c' * 24, 'mai': 'f00dfeed' * 4, 'deepseek': 'sk-' + 'ab12' * 8}
    lyric = '誰にも言えない秘密の歌詞'; user = 'shengaoprivacy'
    with tempfile.TemporaryDirectory(prefix='shengao-privacy-') as folder:
        base = Path(folder) / 'Users' / user; private_home = base / 'AppData' / 'Roaming' / 'ShengaoKaraoke'
        media = base / 'Music' / '秘密の新曲デモ.wav'; media.parent.mkdir(parents=True); media.write_bytes(b'0' * 64)
        task = private_home / 'desktop-tasks' / ('e' * 32); task.mkdir(parents=True)
        request = {'action': 'transcribe', 'provider': 'elevenlabs', 'media': str(media), 'language': 'ja',
                   'lines': [{'id': '1', 'text': lyric, 'start': 0, 'end': 10, 'units': [], 'translation': '没人知道的歌词'}]}
        result = {'ok': False, 'exception': 'ApiError',
                  'message': (f'上传失败：{lyric}；xi-api-key: {fake["elevenlabs"]}；Authorization: Bearer {fake["deepseek"]}；'
                              f'{media}；C:\\Users\\{user}\\Desktop\\a.ass；联系 someone@example.com'),
                  'original_api_result': {'text': lyric}, 'transcript': [{'text': lyric}],
                  'diagnostics': {'stage': 'waiting', 'request_id': 'req-privacy', 'headers': {'Ocp-Apim-Subscription-Key': fake['mai']}}}
        (task / 'request.json').write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
        (task / 'result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        saved_user = os.environ.get('USERNAME')
        os.environ['USERNAME'] = user
        try:
            text, _ = diagnostics.report(private_home, _Project([lyric, '二行目の秘密'], str(media)),
                                         _Settings(fake, 'https://privacy-test.cognitiveservices.azure.com/speechtotext'))
        finally:
            if saved_user is None: os.environ.pop('USERNAME', None)
            else: os.environ['USERNAME'] = saved_user
        for label, value in [('ElevenLabs 测试密钥', fake['elevenlabs']), ('Microsoft 测试密钥', fake['mai']),
                             ('DeepSeek 测试密钥', fake['deepseek']), ('歌词', lyric), ('第二句歌词', '二行目の秘密'),
                             ('译文', '没人知道的歌词'), ('素材文件名', '秘密の新曲デモ'), ('邮箱', 'someone@example.com'),
                             ('用户名', user), ('个人目录', str(private_home))]:
            if value in text: problems.append(finding('诊断报告（虚构数据）', f'泄露了{label}'))
        if 'req-privacy' not in text: problems.append(finding('诊断报告（虚构数据）', '没有保留排查需要的请求编号'))
    checked = '用虚构的密钥、歌词、邮箱和个人路径生成一份报告'
    if home is not None and Path(home).is_dir():
        try:
            from studio_backend.settings import Settings
            real, _ = diagnostics.report(home, None, Settings(home))
            data = real.encode('utf-8')
            problems += secrets_in(data, '诊断报告（本机）', keys)
            if str(home) in real: problems.append(finding('诊断报告（本机）', '含本机个人目录路径'))
            checked += '；再用本机设置和任务记录生成一份核对'
        except (OSError, ValueError) as error:
            problems.append(finding('诊断报告（本机）', f'无法生成（{error}）'))
    return {'title': '诊断报告', 'checked': checked, 'problems': problems, 'warnings': []}


def recent_projects(home):
    try:
        value = json.loads((Path(home) / 'workspace.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    recent = value.get('recent', []) if isinstance(value, dict) else []
    return [Path(x['path']) for x in recent if isinstance(x, dict) and isinstance(x.get('path'), str)]


def check_home(home, keys=()):
    """Task records, caches, workspace settings and recent projects hold no keys."""
    home = Path(home); problems = []; files = 0
    if not home.is_dir():
        return {'title': '本机记录与工程', 'checked': f'没有找到本机数据目录 {home}，跳过', 'problems': [], 'warnings': []}
    for folder, dirs, names in os.walk(home):
        dirs[:] = [d for d in dirs if d not in SKIP_HOME]
        for name in names:
            path = Path(folder) / name
            if path.suffix.lower() in MEDIA: continue
            try:
                if path.stat().st_size > LIMIT: continue
                data = path.read_bytes()
            except OSError:
                continue
            files += 1; problems += secrets_in(data, str(path.relative_to(home)), keys)
    projects = 0
    for path in recent_projects(home):
        try: data = path.read_bytes()
        except OSError: continue
        projects += 1; problems += secrets_in(data, f'工程 {path.name}', keys)
    return {'title': '本机记录与工程', 'checked': f'本机数据目录文件 {files} 个，最近打开的工程 {projects} 个',
            'problems': problems, 'warnings': []}


def run(root, home=None, archives=None):
    """Every check; ``archives`` None means dist/*.zip under root."""
    root = Path(root)
    keys = saved_keys(home) if home is not None else []; own = personal(home)
    if archives is None: archives = sorted((root / 'dist').glob('*.zip')) if (root / 'dist').is_dir() else []
    sections = [check_repository(root, keys, own), check_archives(archives, root, keys, own), check_diagnostics(home, keys)]
    if home is not None: sections.append(check_home(home, keys))
    return {'keys_checked': [title for title, _ in keys], 'sections': sections,
            'problems': sum(len(s['problems']) for s in sections), 'warnings': sum(len(s['warnings']) for s in sections)}


def text(report, limit=40):
    rows = ['声稿隐私检查', '']
    keys = report['keys_checked']
    rows.append('本机已保存的密钥：' + ('、'.join(keys) + '（逐字比对，报告中不显示）' if keys else '没有读到，只按密钥格式检查'))
    for section in report['sections']:
        state = '通过' if not section['problems'] else f'发现 {len(section["problems"])} 处问题'
        rows += ['', f'【{section["title"]}】{state}', f'  检查范围：{section["checked"]}']
        for item in section['problems'][:limit]: rows.append(f'  ✗ {item["where"]}：{item["what"]}')
        if len(section['problems']) > limit: rows.append(f'  …另有 {len(section["problems"]) - limit} 处')
        for item in section['warnings'][:limit]: rows.append(f'  ？ {item["where"]}：{item["what"]}')
    rows += ['', f'合计：问题 {report["problems"]} 处，待核对 {report["warnings"]} 处。']
    return '\n'.join(rows)
