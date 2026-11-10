"""What a render uses, decided in one place for preview, sample, full video and ASS.

* ``render_fonts`` is the exact list of font files the subtitles are drawn
  with.  The live preview loads these files, the encoder copies them into its
  private font folder and the ASS export carries them, so none of the three can
  silently pick a different font.
* ``subtitle_fingerprint`` identifies the timing, layout and font data a video
  was made from, so a full export can say whether it matches the last sample.
* ``sample_range`` turns the visible sample setting into an exact start and
  length; ``output_name``/``output_folder`` give a default destination.
* ``verify_output`` reads the finished file back before it is published: an
  output without H.264 video, AAC sound or with a cut-short duration is never
  reported as finished.
* ``font_report``/``font_warnings`` say which fonts are substituted, missing
  or lack characters, before export and when a project is opened.
"""
import hashlib
import os
import re
import subprocess
from pathlib import Path

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
ROLE_FONTS = [('font_file', 'font', '原文'), ('ruby_font_file', 'ruby_font', '假名'),
              ('translation_font_file', 'translation_font', '译文')]
SIZES = {'source': '分辨率跟随原视频', '1080p': '1920 × 1080', '720p': '1280 × 720'}
FRAME = {'1080p': (1920, 1080), '720p': (1280, 720)}
QUALITIES = {'standard': '标准画质', 'high': '较高画质'}
SAMPLE_MODES = {'line': '当前句前 1 秒起', 'playhead': '从播放点起', 'custom': '自定义起点'}
SAMPLE_MIN, SAMPLE_MAX, SAMPLE_DEFAULT = 2000, 60000, 12000
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


def clock(ms):
    ms = max(0, int(ms)); seconds, rest = divmod(ms, 1000); minutes, seconds = divmod(seconds, 60); hours, minutes = divmod(minutes, 60)
    return (f'{hours}:{minutes:02}:' if hours else f'{minutes:02}:') + f'{seconds:02}.{rest // 100}'


# ---------------------------------------------------------------- fonts

def render_fonts(project):
    """Every font file the subtitles of this project are drawn with, in a fixed order."""
    from .fonts import resolve_font, project_font_files
    paths = [resolve_font(getattr(project.style, name), getattr(project.style, family)) for name, family, _ in ROLE_FONTS]
    paths += [Path(value) for value in project_font_files(project) if Path(value).is_file()]
    result, seen = [], set()
    for path in paths:
        key = os.path.normcase(str(Path(path).resolve()))
        if key not in seen: seen.add(key); result.append(Path(path))
    return result


def _role_text(project, family):
    s = project.style; lines = project.lines
    if family == 'font':
        return ''.join(line.text + (line.romaji if s.show_romaji else '') for line in lines)
    if family == 'ruby_font':
        return ''.join(u.kana for line in lines for u in line.units) if s.show_ruby else ''
    return ''.join(line.translation for line in lines) if s.show_translation else ''


def font_report(project):
    """One row per font the subtitles need: what was chosen, what is used and what is missing."""
    from .fonts import resolve_font, find_font, missing, family_name
    rows = []
    if project.source_ass_active:
        from .subtitle_import import needed_fonts
        for family in needed_fonts(project.source_ass):
            asset = project.font_assets.get(family)
            found = bool(asset and Path(asset).is_file()) or find_font(family) is not None
            rows.append({'role': '原 ASS', 'family': family, 'chosen': asset or '', 'used': asset if asset and Path(asset).is_file() else '',
                         'state': 'ok' if found else 'missing', 'absent': ''})
        return rows
    s = project.style
    for name, family_attr, label in ROLE_FONTS:
        chosen = getattr(s, name); family = getattr(s, family_attr); text = _role_text(project, family_attr)
        if family_attr != 'font' and not text.strip(): continue
        used = resolve_font(chosen, family)
        if chosen and Path(chosen).is_file(): state = 'ok'
        elif chosen: state = 'missing_file'
        elif find_font(family) is not None: state = 'ok'
        else: state = 'substituted'
        try: used_family = family_name(str(used), family)
        except Exception: used_family = used.stem
        rows.append({'role': label, 'family': family, 'chosen': chosen, 'used': str(used), 'used_family': used_family,
                     'state': state, 'absent': missing(used, text, family) if text else ''})
    if project.song_info.get('enabled'):
        from .song_info import settings, font_path
        info = settings(project); chosen = info.get('font_file') or ''
        used = font_path(project)
        state = 'missing_file' if chosen and not Path(chosen).is_file() else 'ok'
        rows.append({'role': '歌曲信息', 'family': info.get('font') or s.font, 'chosen': chosen, 'used': str(used),
                     'used_family': used.stem, 'state': state, 'absent': ''})
    return rows


def font_warnings(project, report=None):
    """Plain sentences for every substituted, missing or incomplete font."""
    result = []
    for row in font_report(project) if report is None else report:
        if row['state'] == 'missing':
            result.append(f'{row["role"]}字体「{row["family"]}」找不到，播放器会用其他字体代替')
        elif row['state'] == 'missing_file':
            result.append(f'{row["role"]}字体文件 {Path(row["chosen"]).name} 已找不到，改用「{row["used_family"]}」')
        elif row['state'] == 'substituted':
            result.append(f'{row["role"]}字体「{row["family"]}」本机没有，改用「{row["used_family"]}」')
        if row.get('absent'):
            result.append(f'{row["role"]}字体缺少 {len(row["absent"])} 个字：{row["absent"][:12]}')
    return result


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1024 * 1024): digest.update(data)
    return digest.hexdigest()


def subtitle_fingerprint(text, fonts):
    """Same value exactly when the drawn subtitles (timing, layout, fonts) are the same."""
    digest = hashlib.sha256()
    for row in text.splitlines():
        if not row.startswith('; ShengaoProject: '): digest.update(row.encode('utf-8') + b'\n')
    for value in sorted(file_digest(path) for path in fonts): digest.update(value.encode())
    return digest.hexdigest()[:16]


# ---------------------------------------------------------------- sample and destination

def sample_range(project, mode='line', row=-1, playhead=0, custom_start=0, length=SAMPLE_DEFAULT):
    total = int(project.duration or 0)
    if total <= 0: raise ValueError('无法确定素材时长，请等待素材读取完成')
    length = max(SAMPLE_MIN, min(SAMPLE_MAX, int(length)))
    if mode == 'line':
        lines = project.lines
        index = row if 0 <= row < len(lines) else (0 if lines else -1)
        start = max(0, lines[index].start - 1000) if index >= 0 else 0
        where = f'第 {index + 1} 句前 1 秒起' if index >= 0 else '作品开头'
    elif mode == 'playhead':
        start = max(0, int(playhead)); where = '从播放点起'
    elif mode == 'custom':
        start = max(0, int(custom_start)); where = '自定义起点'
    else:
        raise ValueError('样片范围选项无效')
    if start >= total: raise ValueError(f'样片起点 {clock(start)} 超出素材时长 {clock(total)}')
    duration = min(length, total - start)
    return {'start': start, 'duration': duration, 'mode': mode,
            'text': f'样片范围：{clock(start)} – {clock(start + duration)}，共 {duration / 1000:g} 秒（{where}）'}


def safe_name(text):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(text or '')).strip(' .')[:120].strip(' .')
    if not value: value = '声稿作品'
    if value.split('.')[0].upper() in _RESERVED: value = '_' + value
    return value


def output_name(project, sample, size='source', role=None, with_size=False):
    from .media_versions import ROLES
    role = role or project.media_role
    parts = [safe_name(project.title)]
    if len(project.media_versions) > 1 or role != project.media_role: parts.append(ROLES.get(role, role))
    if with_size and size in FRAME: parts.append(size)
    parts.append('试压' if sample else '字幕成品')
    return '-'.join(parts) + '.mp4'


def unique_path(folder, name, taken=()):
    folder = Path(folder); stem, suffix = os.path.splitext(name)
    taken = {os.path.normcase(str(Path(x).resolve())) for x in taken}
    candidate = folder / name; number = 2
    while candidate.exists() or os.path.normcase(str(candidate.resolve())) in taken:
        candidate = folder / f'{stem} ({number}){suffix}'; number += 1
    return candidate


def output_folder(saved='', project_path=None, media=''):
    for value in (saved, Path(project_path).parent if project_path else None, Path(media).parent if media else None):
        if value and Path(value).is_dir(): return str(Path(value))
    videos = Path.home() / 'Videos'
    return str(videos if videos.is_dir() else Path.home())


def version_snapshot(project, role):
    """An independent copy of the project that renders the named video version."""
    from .project import Project, file_stamp
    from .media_versions import ROLES
    snapshot = Project.from_dict(project.to_dict())
    if role == snapshot.media_role: return snapshot
    entry = snapshot.media_versions.get(role)
    name = ROLES.get(role, role)
    if entry is None: raise ValueError(f'工程里没有{name}')
    if not Path(entry.path).is_file(): raise ValueError(f'{name}文件找不到：{Path(entry.path).name}')
    if entry.stamp and file_stamp(entry.path) != entry.stamp: raise ValueError(f'{name}文件在加入工程后已变化，请重新添加该版本')
    snapshot.media = entry.path; snapshot.media_role = role; snapshot.media_stamp = dict(entry.stamp)
    snapshot.duration = entry.duration or snapshot.duration; snapshot.has_video = None
    return snapshot


def describe_options(options, role_name=''):
    parts = [role_name] if role_name else []
    parts += [SIZES.get(options.size, options.size), QUALITIES.get(options.quality, options.quality)]
    if options.duration: parts.append(f'样片 {clock(options.start)} 起 {options.duration / 1000:g} 秒')
    return ' · '.join(parts)


# ---------------------------------------------------------------- output check

def probe_output(path, ffmpeg_path=None):
    from .paths import ffmpeg
    result = subprocess.run([ffmpeg_path or ffmpeg(), '-hide_banner', '-nostdin', '-i', str(path)],
                            capture_output=True, timeout=60, creationflags=NO_WINDOW)
    return parse_probe(result.stderr.decode('utf-8', errors='replace'))


def parse_probe(log):
    duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', log)
    video = next((x for x in log.splitlines() if 'Stream #' in x and 'Video:' in x and 'attached pic' not in x.lower()), '')
    audio = next((x for x in log.splitlines() if 'Stream #' in x and 'Audio:' in x), '')
    size = re.search(r', (\d{2,5})x(\d{2,5})', video)
    codec = lambda line, kind: (re.search(kind + r': (\w+)', line) or [None, ''])[1]
    return {'duration': round((int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])) * 1000) if duration else None,
            'video': codec(video, 'Video'), 'audio': codec(audio, 'Audio'),
            'width': int(size[1]) if size else 0, 'height': int(size[2]) if size else 0}


def verify_output(path, expected_ms, size='source', ffmpeg_path=None, info=None, audio=True):
    """Raise unless the file is an MP4 that common players can play from start to end.

    ``audio=False`` only for a source video that has no sound track itself."""
    info = probe_output(path, ffmpeg_path) if info is None else info
    problems = []
    if not info['video']: problems.append('没有视频画面')
    elif info['video'] != 'h264': problems.append(f'视频编码是 {info["video"]}，不是 H.264')
    if not info['audio']:
        if audio: problems.append('没有声音')
    elif info['audio'] != 'aac': problems.append(f'音频编码是 {info["audio"]}，不是 AAC')
    if info['duration'] is None: problems.append('读不出时长')
    elif expected_ms and info['duration'] < expected_ms - max(1000, expected_ms * 0.03):
        problems.append(f'时长只有 {info["duration"] / 1000:.1f} 秒，应约为 {expected_ms / 1000:.1f} 秒')
    if size in FRAME and info['video'] and (info['width'], info['height']) != FRAME[size]:
        problems.append(f'画面是 {info["width"]}×{info["height"]}，不是所选的 {SIZES[size]}')
    if problems: raise ValueError('成品检查未通过：' + '；'.join(problems) + '。未保存为成品，原素材和工程未改动。')
    return info
