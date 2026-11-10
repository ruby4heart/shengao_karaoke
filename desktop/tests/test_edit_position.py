"""Continue editing where the person stopped (TODO 9.6).

The place is compared with the same version check the unapplied drafts use,
so a changed line, media file or audition source is explained instead of
silently jumping somewhere else."""
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QComboBox, QWidget

from shengao import draft_recovery, edit_position
from shengao.edit_position import EditPositionWorkflow, PositionStore, capture, describe, resolve
from shengao.project import History, Project, file_stamp, load_project, save_project
from shengao.timing import merge_words
from tests.test_version_history import shifted


@pytest.fixture
def song(project, tmp_path):
    first = project.lines[0]
    project.lines = [first, shifted(first, 'b', 6000), shifted(first, 'c', 12000)]
    media = tmp_path / 'edit-position-source.wav'; media.write_bytes(b'RIFF' + bytes(4000))
    project.media = str(media); project.duration = 20000
    project.validate()
    return project


def taken(project, row=1, word=2, part=1, audition='original'):
    record = capture(project, row, word, part, 7300, 6100, 12, 'waveform', audition, 'mora', file_stamp(project.media), now=1)
    return json.loads(json.dumps(record))      # exactly as stored on disk


def test_unchanged_project_returns_to_the_exact_place(song):
    record = taken(song)
    place = resolve(record, song, file_stamp(song.media))
    assert place == {'row': 1, 'word': 2, 'part': 1, 'playhead': 7300, 'view': {'left': 6100, 'zoom': 12},
                     'display': 'waveform', 'granularity': 'mora', 'audition_role': 'original', 'notes': [], 'exact': True}
    assert describe(place, song) == '已回到上次编辑的位置：第 2 句「今日も歌う」。'


def test_deleted_line_moves_to_a_nearby_line_and_says_why(song):
    record = taken(song)
    gone = Project.from_dict(song.to_dict()); del gone.lines[1]; gone.lines[1].text = '別の歌詞'
    place = resolve(record, gone, file_stamp(song.media))
    assert place['row'] == 0 and not place['exact']            # the line with the same words
    assert place['notes'] == ['上次处理的那一句在当前工程里已不存在，改到第 1 句'] and place['playhead'] == 7300
    for x in gone.lines: x.text = '別の歌詞'
    assert resolve(record, gone, file_stamp(song.media))['row'] == 1   # no same words: the old row, clamped
    empty = Project.from_dict(song.to_dict()); empty.lines = []
    assert resolve(record, empty, file_stamp(song.media))['row'] == -1


def test_changed_line_keeps_the_syllable_only_while_it_still_exists(song):
    record = taken(song)
    retimed = Project.from_dict(song.to_dict()); h = retimed.lines[1].units[2].highlights[1]; h.start += 20
    place = resolve(record, retimed, file_stamp(song.media))
    assert (place['row'], place['word'], place['part']) == (1, 2, 1)
    assert '时间或读音与上次编辑时不同' in place['notes'][0]
    merged = Project.from_dict(song.to_dict()); merged.lines[1] = merge_words(merged.lines[1], 0, 1)
    place = resolve(record, merged, file_stamp(song.media))
    assert (place['word'], place['part']) == (0, 0) and '分词或音节' in place['notes'][0]
    whole = resolve(taken(song, word=-1, part=-1), merged, file_stamp(song.media))
    assert (whole['word'], whole['part']) == (0, -1)


def test_other_media_keeps_the_zoom_and_moves_to_the_line(song):
    record = taken(song)
    Path(song.media).write_bytes(b'RIFF' + bytes(9000))
    place = resolve(record, song, file_stamp(song.media))
    assert place['playhead'] == song.lines[1].start and place['view'] == {'left': None, 'zoom': 12}
    assert place['notes'] == ['素材文件已变化或尚未找到，播放点改到这一句开头'] and (place['word'], place['part']) == (2, 1)
    assert '素材' in resolve(record, song, {})['notes'][0]                       # file not found now
    role = Project.from_dict(song.to_dict()); role.media_role = 'instrumental'
    assert resolve(taken(song), role, file_stamp(song.media))['notes'] == ['上次编辑时使用的视频版本与现在不同']


def test_playhead_past_the_end_and_vocals_that_are_gone(song):
    record = taken(song, audition='vocals'); record['playhead'] = 50000
    place = resolve(record, song, file_stamp(song.media), vocals_ready=False)
    assert place['playhead'] == 20000 and place['audition_role'] == 'original'
    assert any('人声辅助' in x for x in place['notes']) and any('结尾' in x for x in place['notes'])
    assert resolve(taken(song, audition='vocals'), song, file_stamp(song.media), vocals_ready=True)['audition_role'] == 'vocals'


def test_records_for_other_projects_or_broken_records_are_ignored(song):
    record = taken(song)
    other = Project.from_dict(song.to_dict()); other.uid = 'f' * 32
    assert resolve(record, other, file_stamp(song.media)) is None
    for key, value in (('kind', 'tap'), ('version', 9), ('playhead', '1'), ('view', {'left': 1})):
        broken = dict(record); broken[key] = value
        assert resolve(broken, song, file_stamp(song.media)) is None


def test_shared_version_check_gives_drafts_the_same_reasons(song):
    from shengao.tap_timing import TapDraft
    line = song.lines[0]; draft = TapDraft(line)
    for point in range(line.start, line.start + 120, 40): draft.add(point)
    stamp = file_stamp(song.media)
    tap = draft_recovery.tap_record(song, line, draft, stamp, 'original')
    edited = Project.from_dict(song.to_dict()); edited.lines[0].translation = '后来改过'
    assert draft_recovery.differences(tap, edited, stamp, 'vocals') == [
        ('line_changed', '这一句后来被修改过，草稿基于旧内容'), ('audition', '录制时使用原声试听，当前试听源不同')]
    assert draft_recovery.assess(tap, edited, stamp, 'vocals') == ('stale', '这一句后来被修改过，草稿基于旧内容')
    assert draft_recovery.differences(tap, song, stamp, 'original') == [] and draft_recovery.assess(tap, song, stamp, 'original')[0] == 'ready'


def test_store_keeps_one_file_per_project_and_prunes(song, tmp_path, monkeypatch):
    store = PositionStore(tmp_path / 'positions')
    assert store.path('../x') is None and store.read('../x') is None and not store.write({'project_uid': 'x'})
    record = taken(song)
    assert store.write(record) and store.read(song.uid) == record
    (store.root / (song.uid + '.json')).write_text('{broken', encoding='utf-8')
    assert store.read(song.uid) is None
    monkeypatch.setattr(edit_position, 'KEEP', 2)
    for n in range(4):
        other = dict(record); other['project_uid'] = f'{n:032x}'; store.write(other)
    assert len(list(store.root.glob('*.json'))) == 2


class FakeTimeline:
    """The parts of the Windows-only timeline the workflow uses."""
    def __init__(self):
        self.line = None; self.word = -1; self.part = -1; self.left = 0; self.zoom_level = 0; self.span = 8000
        self.show_spectrum = True; self.granularity = 'words'; self.duration = 0; self.updates = 0
    def set_zoom(self, level): self.zoom_level = level; self.span = 8000 * 2 ** (-level / 10)
    def invalidate(self):
        if self.duration: self.left = max(0, min(self.left, max(0, self.duration - self.span)))
        self.updates += 1


class FakePlayback:
    def __init__(self): self.canvas = type('Canvas', (), {'position': 0})()
    def seek(self, value): self.canvas.position = value


class Studio(QWidget, EditPositionWorkflow):
    def __init__(self, home, project):
        super().__init__(); self.home = Path(home); self.history = History(project); self.current = 0
        self.audition_role = 'original'; self.messages = []; self.vocal_requests = []
        self.timeline = FakeTimeline(); self.playback = FakePlayback()
        self.audio_view = QComboBox(); self.audio_view.addItem('频谱', 'spectrum'); self.audio_view.addItem('波形', 'waveform')
        self.audio_view.currentIndexChanged.connect(lambda: setattr(self.timeline, 'show_spectrum', self.audio_view.currentData() == 'spectrum'))
        self.granularity = QComboBox()
        for label, mode in (('词组', 'words'), ('音节', 'mora'), ('整句', 'line')): self.granularity.addItem(label, mode)
        self.granularity.currentIndexChanged.connect(lambda: setattr(self.timeline, 'granularity', self.granularity.currentData()))
    @property
    def project(self): return self.history.project
    def refresh(self, focus=False): self.timeline.line = self.project.lines[self.current]; self.timeline.word = 0; self.timeline.part = -1
    def select_target(self, word, part): self.timeline.word = word; self.timeline.part = part
    def select_vocal_audition(self, role): self.vocal_requests.append(role); self.audition_role = role; return True
    def message(self, text): self.messages.append(text)


def test_window_remembers_and_restores_every_part_of_the_place(qapp, song, tmp_path, monkeypatch):
    home = tmp_path / 'home'; studio = Studio(home, song)
    studio.current = 2; studio.refresh(); studio.select_target(2, 1)
    studio.audio_view.setCurrentIndex(1); studio.granularity.setCurrentIndex(1)
    studio.timeline.set_zoom(14); studio.timeline.left = 11800; studio.playback.seek(12450); studio.audition_role = 'vocals'
    assert studio.remember_edit_position()
    written = (home / 'edit-positions' / (song.uid + '.json')).stat().st_mtime_ns
    assert studio.remember_edit_position() and (home / 'edit-positions' / (song.uid + '.json')).stat().st_mtime_ns == written
    path = tmp_path / 'song.sgproj'; save_project(song, path)

    monkeypatch.setattr('shengao.vocal_audio.bound', lambda track, media: True)
    again = Studio(home, load_project(path))
    place = again.restore_edit_position(lead='已打开工程。')
    assert place['exact'] and again.current == 2 and (again.timeline.word, again.timeline.part) == (2, 1)
    assert again.timeline.show_spectrum is False and again.timeline.granularity == 'mora'
    assert again.messages[-1] == '已打开工程。 已回到上次编辑的位置：第 3 句「今日も歌う」。'
    assert again.playback.canvas.position == 0 and again.timeline.zoom_level == 0      # waits for the waveform
    again.timeline.duration = again.project.duration
    assert again.apply_pending_place() and not again.apply_pending_place()
    assert again.playback.canvas.position == 12450 and again.timeline.zoom_level == 14 and again.timeline.left == 11800
    assert again.vocal_requests == ['vocals'] and again.messages[-1].startswith('音频波形已就绪。已回到上次编辑的位置')


def test_window_explains_changes_and_never_applies_a_stale_view(qapp, song, tmp_path):
    home = tmp_path / 'home'; studio = Studio(home, song)
    studio.current = 1; studio.refresh(); studio.select_target(1, 0); studio.timeline.set_zoom(8); studio.timeline.left = 5000
    studio.playback.seek(6500); studio.audition_role = 'vocals'; studio.remember_edit_position()
    changed = Project.from_dict(song.to_dict()); changed.lines[1] = merge_words(changed.lines[1], 0, 1)
    Path(song.media).write_bytes(b'RIFF' + bytes(100))
    again = Studio(home, changed)
    place = again.restore_edit_position()
    assert not place['exact'] and again.current == 1 and (again.timeline.word, again.timeline.part) == (0, 0)
    text = again.messages[-1]
    assert text.startswith('已回到上次编辑附近：第 2 句') and '分词或音节' in text and '素材' in text and '人声辅助' in text
    again.history = History(Project.from_dict(song.to_dict())); again.history.project.uid = 'e' * 32
    assert not again.apply_pending_place()                          # another project is open now
    again.history = History(changed); again.restore_edit_position(); again.timeline.duration = 20000
    assert again.apply_pending_place()
    line = changed.lines[1]
    assert again.playback.canvas.position == line.start and again.timeline.zoom_level == 8
    assert again.timeline.left == pytest.approx(max(0, (line.start + line.end - again.timeline.span) / 2))
    assert again.vocal_requests == []


def test_window_without_lines_or_with_unreadable_state_stays_quiet(qapp, song, tmp_path):
    studio = Studio(tmp_path / 'home', Project())
    assert studio.capture_edit_position() is None and not studio.remember_edit_position()
    assert studio.restore_edit_position() is None and studio.messages == []
    broken = Studio(tmp_path / 'home', song); broken.timeline = None
    assert broken.position_snapshot() is None and not broken.remember_edit_position()
    (tmp_path / 'home').mkdir(); (tmp_path / 'home' / 'edit-positions').write_text('not a folder', encoding='utf-8')
    assert not Studio(tmp_path / 'home', song).remember_edit_position()      # cannot write: editing goes on
