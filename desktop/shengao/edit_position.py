"""Continue editing where the person stopped.

The remembered position is the line and word/syllable being worked on, the
playhead, the visible part of the timeline and its zoom, spectrum or waveform,
the selection mode and the audition source.  It is kept per project in the
user data folder (never inside the .sgproj, so moving the playhead does not
mark the work as changed) and in the crash-recovery record.

On reopen the record is compared with the same version check the unapplied
drafts use (``draft_recovery.differences``).  When nothing changed, the exact
place comes back.  When the line, media or audition source changed, a usable
place is chosen instead and every difference is explained.
"""
import copy
import re
import time
from pathlib import Path

from . import draft_recovery

VERSION = 1
DISPLAYS = {'spectrum', 'waveform'}
MODES = {'words', 'mora', 'line'}
KEEP = 200
_UID = re.compile(r'[0-9a-f]{32}')


def capture(project, row, word, part, playhead, left, zoom, display, audition_role, granularity, media_stamp, now=None):
    line = project.lines[row] if 0 <= row < len(project.lines) else None
    return {'version': VERSION, 'kind': 'edit_position', 'project_uid': project.uid,
            'line_id': line.id if line else '', 'line_index': row if line else -1, 'text': line.text if line else '',
            'original': line.to_dict() if line else {}, 'word': int(word), 'part': int(part),
            'playhead': max(0, int(playhead)), 'view': {'left': max(0, int(left)), 'zoom': int(zoom)},
            'display': display, 'granularity': granularity, 'audition_role': audition_role,
            'media': project.media, 'media_stamp': copy.deepcopy(media_stamp or {}), 'media_role': project.media_role,
            'saved': int((time.time() if now is None else now) * 1000)}


def valid(record):
    if not isinstance(record, dict) or record.get('kind') != 'edit_position' or record.get('version') != VERSION: return False
    view = record.get('view')
    return (isinstance(record.get('project_uid'), str) and isinstance(record.get('line_id'), str)
            and isinstance(record.get('original'), dict) and isinstance(record.get('media_stamp'), dict)
            and all(type(record.get(k)) is int for k in ('line_index', 'word', 'part', 'playhead'))
            and isinstance(view, dict) and type(view.get('left')) is int and type(view.get('zoom')) is int)


def _shape(line):
    return [(u.text, len(u.highlights)) for u in line.units]


def _target(line, word, part):
    """The recorded word/syllable if it still exists on this line, else None."""
    if word < 0: return -1, -1
    if word >= len(line.units): return None
    if part < 0: return word, -1
    return (word, part) if part < len(line.units[word].highlights) else None


def resolve(record, project, media_stamp, vocals_ready=False):
    """A usable position and the plain-language differences, or None."""
    if not valid(record) or record['project_uid'] != project.uid: return None
    changed = dict(draft_recovery.differences(record, project, media_stamp))
    notes = []
    lines = project.lines; row = -1; line = None
    if record['line_id']:
        row = next((i for i, x in enumerate(lines) if x.id == record['line_id']), -1)
        if row < 0 and lines:
            same = [i for i, x in enumerate(lines) if x.text == record.get('text')]
            row = min(same, key=lambda i: abs(i - record['line_index'])) if same else min(max(record['line_index'], 0), len(lines) - 1)
            notes.append(f'上次处理的那一句在当前工程里已不存在，改到第 {row + 1} 句')
    elif lines:
        row = 0
    line = lines[row] if row >= 0 else None
    word, part = -1, -1
    if line is not None:
        target = _target(line, record['word'], record['part'])
        if 'line_changed' in changed and record['original'].get('units') is not None:
            from studio_backend.model import LyricLine
            try: before = _shape(LyricLine.from_dict(record['original']))
            except (ValueError, KeyError, TypeError): before = None
            if before != _shape(line): target = None
        if target is None:
            word = 0 if line.units else -1
            part = 0 if word >= 0 and record['part'] >= 0 and line.units[0].highlights else -1
            if 'line_missing' not in changed: notes.append('这一句的分词或音节与上次编辑时不同，回到这一句开头')
        else:
            word, part = target
            if 'line_changed' in changed: notes.append('这一句的时间或读音与上次编辑时不同，仍停在同一个词组／音节')
    same_media = 'media' not in changed
    duration = max(0, int(project.duration or 0))
    if same_media:
        playhead = record['playhead']; left = record['view']['left']
        if duration and playhead > duration:
            playhead = duration; notes.append('播放点超出当前素材长度，已移到结尾')
    else:
        playhead = line.start if line is not None else 0; left = None
        notes.append('素材文件已变化或尚未找到，播放点改到这一句开头' if line is not None else '素材文件已变化或尚未找到，播放点回到开头')
    if 'media_role' in changed: notes.append('上次编辑时使用的视频版本与现在不同')
    audition = record.get('audition_role') if record.get('audition_role') in {'original', 'vocals'} else 'original'
    if audition == 'vocals' and not vocals_ready:
        audition = 'original'; notes.append('上次用人声辅助试听，当前没有可用的人声辅助，改用原声')
    return {'row': row, 'word': word, 'part': part, 'playhead': playhead,
            'view': {'left': left, 'zoom': record['view']['zoom']},
            'display': record.get('display') if record.get('display') in DISPLAYS else None,
            'granularity': record.get('granularity') if record.get('granularity') in MODES else None,
            'audition_role': audition, 'notes': notes, 'exact': not notes}


def describe(place, project):
    row = place['row']
    where = f'第 {row + 1} 句' if 0 <= row < len(project.lines) else '作品开头'
    if 0 <= row < len(project.lines):
        text = project.lines[row].text; where += '「' + (text if len(text) <= 16 else text[:15] + '…') + '」'
    if place['exact']: return f'已回到上次编辑的位置：{where}。'
    return f'已回到上次编辑附近：{where}。' + '；'.join(place['notes']) + '。'


class PositionStore:
    """One small JSON file per project uid in the user data folder."""
    def __init__(self, root): self.root = Path(root)

    def path(self, uid):
        if not isinstance(uid, str) or not _UID.fullmatch(uid): return None
        return self.root / f'{uid}.json'

    def read(self, uid):
        path = self.path(uid)
        if path is None: return None
        import json
        try: data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError): return None
        return data if valid(data) and data['project_uid'] == uid else None

    def write(self, record):
        path = self.path(record.get('project_uid'))
        if path is None or not valid(record): return False
        from studio_backend.settings import atomic_json
        atomic_json(path, record); self.prune(); return True

    def prune(self):
        try: files = sorted(self.root.glob('*.json'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        except OSError: return
        for old in files[KEEP:]:
            try: old.unlink()
            except OSError: pass


class EditPositionWorkflow:
    """Mixed into the studio window."""
    def position_store(self): return PositionStore(self.home / 'edit-positions')

    def capture_edit_position(self):
        p = self.project
        if not p.lines and not p.media: return None
        from .project import file_stamp
        tl = self.timeline
        return capture(p, self.current, tl.word, tl.part, self.playback.canvas.position, tl.left, tl.zoom_level,
                       'spectrum' if tl.show_spectrum else 'waveform', self.audition_role, tl.granularity, file_stamp(p.media))

    def position_snapshot(self):
        """For the crash-recovery record; never stops the record being written."""
        try: return self.capture_edit_position()
        except (OSError, ValueError, TypeError, AttributeError): return None

    def remember_edit_position(self):
        """Quietly keep the current place; unchanged places are not rewritten
        and a failure never interrupts editing."""
        record = self.position_snapshot()
        if record is None: return False
        key = {k: v for k, v in record.items() if k != 'saved'}
        if key == getattr(self, '_remembered_place', None): return True
        try: written = self.position_store().write(record)
        except (OSError, ValueError): return False
        if written: self._remembered_place = key
        return written

    def restore_edit_position(self, record=None, lead=''):
        """Put back the line, selection, display and selection mode now; the
        playhead, visible range, zoom and audition source follow as soon as the
        waveform of this project is ready (``apply_pending_place``)."""
        p = self.project; self._pending_place = None
        if record is None: record = self.position_store().read(p.uid)
        if not record: return None
        from .project import file_stamp
        stamp = file_stamp(p.media)
        ready = False
        if stamp and record.get('audition_role') == 'vocals':
            from . import vocal_audio
            ready = vocal_audio.bound(p.vocal_track, p.media)
        place = resolve(record, p, stamp, ready)
        if place is None: return None
        if place['display'] and self.audio_view.findData(place['display']) >= 0:
            self.audio_view.setCurrentIndex(self.audio_view.findData(place['display']))
        if place['granularity'] and self.granularity.findData(place['granularity']) >= 0:
            self.granularity.setCurrentIndex(self.granularity.findData(place['granularity']))
        if place['row'] >= 0:
            self.current = place['row']; self.refresh(True)
            if place['word'] >= 0: self.select_target(place['word'], place['part'])
        text = describe(place, p)
        if stamp: self._pending_place = {'uid': p.uid, 'media': p.media, 'text': text, **place}
        self.message(lead + (' ' if lead else '') + text)
        return place

    def apply_pending_place(self):
        """Called once the timeline audio is ready; ignores another project or media."""
        place = getattr(self, '_pending_place', None)
        if not place or place['uid'] != self.project.uid or place['media'] != self.project.media: return False
        self._pending_place = None
        tl = self.timeline
        tl.set_zoom(place['view']['zoom'])
        left = place['view']['left']
        if left is None:   # other media: keep the zoom, centre the chosen line
            line = tl.line; left = max(0, (line.start + line.end - tl.span) / 2) if line else 0
        tl.left = left; tl.invalidate()
        self.playback.seek(place['playhead'])
        if place['audition_role'] == 'vocals' and self.audition_role != 'vocals': self.select_vocal_audition('vocals')
        self.message('音频波形已就绪。' + place['text'])
        return True
