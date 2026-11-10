"""Samples, full videos and ASS from one set of timing, layout and font data;
visible sample range and destination; a batch queue with cancel and records;
fonts carried and reported; failures never published (TODO 9.1, 9.3-9.5)."""
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from shengao import encode as encode_module, paths, render_plan
from shengao.encode import EncodeOptions, capability_text, encode, encoder_args, video_filter
from shengao.fonts import bundled_fonts
from shengao.media_versions import MediaVersion
from shengao.project import Project, file_stamp
from shengao.render_plan import (font_report, font_warnings, output_folder, output_name, parse_probe, render_fonts,
                                 safe_name, sample_range, subtitle_fingerprint, unique_path, verify_output,
                                 version_snapshot)
from shengao.render_queue import RenderQueue, RenderRecords, history_text, remove_stage
from shengao.subtitle_files import export_subtitle
from shengao.subtitles import compose

SYSTEM_FFMPEG = shutil.which('ffmpeg') if os.name != 'nt' else None


# ---------------------------------------------------------------- sample range and names

def test_sample_range_is_exact_and_limited(project):
    project.duration = 20000
    value = sample_range(project, 'line', 0)
    assert (value['start'], value['duration']) == (0, 12000)
    assert value['text'] == '样片范围：00:00.0 – 00:12.0，共 12 秒（第 1 句前 1 秒起）'
    assert sample_range(project, 'playhead', playhead=15000)['duration'] == 5000         # cut at the end of the media
    assert sample_range(project, 'custom', custom_start=3000, length=500)['duration'] == 2000    # at least 2 s
    assert sample_range(project, 'custom', custom_start=0, length=90000)['duration'] == 20000   # at most 60 s / the media
    with pytest.raises(ValueError, match='超出素材时长'): sample_range(project, 'custom', custom_start=20000)
    with pytest.raises(ValueError, match='选项无效'): sample_range(project, 'everything')
    project.duration = 0
    with pytest.raises(ValueError, match='无法确定素材时长'): sample_range(project)


def test_default_names_are_safe_unique_and_say_what_they_are(project, tmp_path):
    assert safe_name('a/b:c?*') == 'a_b_c__' and safe_name(' .. ') == '声稿作品' and safe_name('CON') == '_CON'
    project.title = '夜/曲'
    assert output_name(project, True) == '夜_曲-试压.mp4'
    assert output_name(project, False, '720p', with_size=True) == '夜_曲-720p-字幕成品.mp4'
    assert output_name(project, False, role='instrumental') == '夜_曲-伴奏版-字幕成品.mp4'
    (tmp_path / 'x.mp4').write_bytes(b'old')
    assert unique_path(tmp_path, 'x.mp4').name == 'x (2).mp4'
    assert unique_path(tmp_path, 'x.mp4', [tmp_path / 'x (2).mp4']).name == 'x (3).mp4'      # already queued
    media = tmp_path / 'media' / 'a.mp4'; media.parent.mkdir(); media.write_bytes(b'v')
    assert output_folder(str(tmp_path / 'gone'), None, str(media)) == str(media.parent)
    assert output_folder(str(tmp_path), tmp_path / 'media' / 'p.shengao', str(media)) == str(tmp_path)


def test_output_check_refuses_files_players_cannot_use():
    log = ("  Duration: 00:00:02.04, start: 0.000000, bitrate: 1000 kb/s\n"
           "  Stream #0:0(und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 1280x720 [SAR 1:1 DAR 16:9], 25 fps\n"
           "  Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 192 kb/s\n")
    info = parse_probe(log)
    assert info == {'duration': 2040, 'video': 'h264', 'audio': 'aac', 'width': 1280, 'height': 720}
    assert verify_output('x', 2000, '720p', info=info) is info
    for change, words in [({'audio': ''}, '没有声音'), ({'video': 'mpeg4'}, '不是 H.264'), ({'duration': 900}, '时长只有'),
                          ({'duration': None}, '读不出时长'), ({'width': 1920, 'height': 1080}, '不是所选的 1280 × 720')]:
        with pytest.raises(ValueError, match=words) as error: verify_output('x', 2000, '720p', info={**info, **change})
        assert '未保存为成品' in str(error.value)
    assert verify_output('x', 2000, 'source', info={**info, 'audio': ''}, audio=False)     # silent source video


# ---------------------------------------------------------------- fonts

def test_fonts_used_by_preview_encode_and_ass_are_one_list(project, tmp_path):
    first = Path(bundled_fonts()[0].path); second = Path(bundled_fonts()[2].path)
    assert render_fonts(project) == [first]                             # every role resolves to the bundled font
    project.font_assets = {'Copy': str(first)}
    assert render_fonts(project) == [first]                             # the same file is listed once
    project.style.ruby_font_file = str(second)
    assert render_fonts(project) == [first, second]


def test_font_report_names_missing_substituted_and_incomplete_fonts(project, tmp_path):
    assert font_warnings(project) == []
    project.style.font_file = str(tmp_path / '已删除.ttf')
    project.style.ruby_font = 'No Such Font For Test'
    project.lines[0].translation = 'sing '
    rows = {row['role']: row for row in font_report(project)}
    assert rows['原文']['state'] == 'missing_file' and rows['假名']['state'] == 'substituted'
    assert rows['译文']['absent'] == ''
    text = font_warnings(project)
    assert any('已删除.ttf 已找不到' in x for x in text) and any('No Such Font For Test」本机没有' in x for x in text)
    assert any('译文字体缺少 1 个字' in x for x in text)
    project.style.show_translation = False
    assert '译文' not in {row['role'] for row in font_report(project)}    # hidden text needs no font


def test_ass_export_carries_fonts_and_reports_the_missing(project, tmp_path):
    project.style.font_file = str(tmp_path / 'gone.ttf'); project.font_assets = {'Vanished': str(tmp_path / 'v.otf')}
    report = export_subtitle(project, tmp_path / 'out' / 'song-export.ass', 'ass')
    assert report['missing'] == ['gone.ttf', 'Vanished'] and report['fonts']
    carried = tmp_path / 'out' / 'song-export.assets' / 'fonts'
    assert sorted(x.name for x in carried.iterdir()) == sorted(set(report['fonts']))
    assert export_subtitle(project, tmp_path / 'out' / 'song-export.srt', 'srt')['fonts'] == []


def test_fingerprint_changes_only_with_what_is_drawn(project, tmp_path):
    fonts = render_fonts(project); text = compose(project)
    same = subtitle_fingerprint('; ShengaoProject: other\n' + text, fonts)
    assert subtitle_fingerprint(text, fonts) == same
    moved = Project.from_dict(project.to_dict()); moved.lines[0].start += 40; moved.lines[0].end += 40
    for unit in moved.lines[0].units:
        unit.start += 40; unit.end += 40
        for highlight in unit.highlights: highlight.start += 40; highlight.end += 40
    assert subtitle_fingerprint(compose(moved), fonts) != same
    assert subtitle_fingerprint(text, fonts + [Path(bundled_fonts()[2].path)]) != same


def test_each_version_renders_from_its_own_copy(project, tmp_path):
    a = tmp_path / 'vocal-mix.mp4'; b = tmp_path / 'backing-mix.mp4'; a.write_bytes(b'a' * 64); b.write_bytes(b'b' * 64)
    project.media = str(a); project.duration = 20000; project.media_stamp = file_stamp(a); project.has_video = True
    project.media_versions = {'original': MediaVersion(str(a), 20000, file_stamp(a)),
                              'instrumental': MediaVersion(str(b), 19000, file_stamp(b))}
    project.validate()
    copy = version_snapshot(project, 'instrumental')
    assert (copy.media, copy.media_role, copy.duration, copy.has_video) == (str(b), 'instrumental', 19000, None)
    assert project.media == str(a) and project.media_role == 'original'
    time.sleep(0.02); b.write_bytes(b'changed' * 20)
    with pytest.raises(ValueError, match='已变化'): version_snapshot(project, 'instrumental')
    b.unlink()
    with pytest.raises(ValueError, match='找不到'): version_snapshot(project, 'instrumental')


# ---------------------------------------------------------------- encode settings

def test_subtitles_are_burned_onto_the_picture_before_letterboxing():
    text = video_filter('1080p', True)
    assert text.index('scale=1920:1080') < text.index('ass=lyrics.ass') < text.index('pad=1920:1080')
    assert 'pad=' not in video_filter('source', True) and video_filter('source', False) == 'ass=lyrics.ass:fontsdir=fonts'
    with pytest.raises(ValueError): video_filter('4k', True)
    args = encoder_args(EncodeOptions('x.mp4', codec='libx264'))
    assert args[:2] == ['-c:v', 'libx264'] and 'yuv420p' in args
    assert encoder_args(EncodeOptions('x.mp4'))[:2] == ['-c:v', 'h264_mf']
    assert 'libx264' in capability_text({'cpu': True, 'hardware': False, 'aac': True, 'cpu_codec': 'libx264'})
    assert '无法生成带声音的 MP4' in capability_text({'cpu': True, 'hardware': False, 'aac': False})


# ---------------------------------------------------------------- queue

class Starter:
    def __init__(self): self.calls = []; self.fail = False

    def __call__(self, task, done, failed, progress):
        if self.fail: raise RuntimeError('ffmpeg 无法启动')
        job = SimpleNamespace(cancel=threading.Event())
        self.calls.append(SimpleNamespace(task=task, done=done, failed=failed, progress=progress, job=job))
        return job


def saved(home, task):
    return json.loads((Path(home) / 'desktop-renders' / f'{task.id}.json').read_text(encoding='utf-8'))


def test_queue_runs_one_after_another_and_records_each_result(project, tmp_path):
    start = Starter(); seen = []
    queue = RenderQueue(start, RenderRecords(tmp_path), seen.append)
    first = queue.add(project, EncodeOptions(str(tmp_path / 'a.mp4')), '成品 · A')
    second = queue.add(project, EncodeOptions(str(tmp_path / 'b.mp4'), 1000, 4000), '样片 · B', 'sample')
    assert (first.state, second.state, len(start.calls)) == ('running', 'waiting', 1)
    record = saved(tmp_path, first)
    assert record['state'] == 'running' and record['pid'] == os.getpid()
    start.calls[0].progress({'stage': str(tmp_path / '.shengao-render-x')}); start.calls[0].progress({'ratio': .5, 'remaining': 3})
    assert saved(tmp_path, first)['stage'].endswith('.shengao-render-x') and '50%' in first.line()
    start.calls[0].done({'output': str(tmp_path / 'a.mp4'), 'fingerprint': 'f1'})
    assert first.state == 'completed' and second.state == 'running' and len(start.calls) == 2
    record = saved(tmp_path, first)
    assert record['state'] == 'completed' and record['fingerprint'] == 'f1' and 'pid' not in record and 'stage' not in record
    start.calls[1].failed('视频压制失败。xyz')
    assert second.state == 'failed' and saved(tmp_path, second)['message'] == '视频压制失败。xyz' and saved(tmp_path, second)['sample']
    assert not queue.busy and queue.summary() == '完成 1 个，失败 1 个'
    assert history_text(saved(tmp_path, first)) == '视频压制 · 完成 · ' + str(tmp_path / 'a.mp4')
    assert history_text(saved(tmp_path, second)) == '视频样片 · 失败 · b.mp4 · 视频压制失败。xyz'
    assert queue.clear_finished() == 2 and queue.tasks == []


def test_cancel_stops_one_task_and_never_marks_it_finished(project, tmp_path):
    start = Starter(); queue = RenderQueue(start, RenderRecords(tmp_path))
    tasks = [queue.add(project, EncodeOptions(str(tmp_path / f'{n}.mp4')), str(n)) for n in range(3)]
    assert queue.cancel(tasks[1].id) and tasks[1].state == 'cancelled' and len(start.calls) == 1   # never started
    assert queue.cancel(tasks[0].id) and tasks[0].state == 'cancelling' and start.calls[0].job.cancel.is_set()
    assert tasks[2].state == 'waiting'                                    # waits until the encoder has stopped
    start.calls[0].failed('压制已取消；原素材和工程未改动')
    assert tasks[0].state == 'cancelled' and saved(tmp_path, tasks[0])['state'] == 'cancelled'
    assert tasks[2].state == 'running'
    queue.cancel_all(); start.calls[1].failed('压制已取消')
    assert [t.state for t in tasks] == ['cancelled'] * 3 and not queue.cancel(tasks[0].id)
    start.fail = True
    broken = queue.add(project, EncodeOptions(str(tmp_path / 'x.mp4')), 'x')
    assert broken.state == 'failed' and 'ffmpeg 无法启动' in broken.message


def test_start_after_a_crash_marks_running_records_unfinished_and_cleans_up(tmp_path):
    root = tmp_path / 'desktop-renders'; root.mkdir(); out = tmp_path / 'videos'; out.mkdir()
    now = time.time()
    stage = out / '.shengao-render-abc'; stage.mkdir(); (stage / 'encoded.mp4').write_bytes(b'half')
    loose = out / '.shengao-render-def'; loose.mkdir()
    keep = out / 'my-folder'; keep.mkdir()
    finished = out / 'done.mp4'; finished.write_bytes(b'v' * 200)
    records = {
        'gone': {'state': 'running', 'pid': 11, 'stage': str(stage), 'output': str(out / 'a.mp4'), 'started': now - 5},
        'loose': {'state': 'running', 'pid': 12, 'stage': '', 'output': str(out / 'b.mp4'), 'started': now - 5},
        'written': {'state': 'cancelling', 'pid': 13, 'stage': '', 'output': str(finished), 'started': now - 5},
        'odd': {'state': 'running', 'pid': 14, 'stage': str(keep), 'output': str(out / 'c.mp4'), 'started': now + 60},
        'alive': {'state': 'running', 'pid': 15, 'stage': '', 'output': str(out / 'd.mp4'), 'started': now - 5},
        'done': {'state': 'completed', 'output': str(out / 'e.mp4'), 'started': now - 5},
    }
    for key, value in records.items(): (root / f'{key}.json').write_text(json.dumps(value), encoding='utf-8')
    found = RenderRecords(tmp_path).recover(alive=lambda pid: pid == 15)
    states = {key: json.loads((root / f'{key}.json').read_text(encoding='utf-8'))['state'] for key in records}
    assert states == {'gone': 'interrupted', 'loose': 'interrupted', 'written': 'unverified', 'odd': 'interrupted',
                      'alive': 'running', 'done': 'completed'}
    assert len(found) == 4 and not stage.exists() and not loose.exists() and keep.is_dir() and finished.is_file()
    gone = json.loads((root / 'gone.json').read_text(encoding='utf-8'))
    assert '没有生成成品' in gone['message'] and '已清理' in gone['message'] and 'pid' not in gone
    assert '请播放检查' in json.loads((root / 'written.json').read_text(encoding='utf-8'))['message']
    assert RenderRecords(tmp_path).recover(alive=lambda pid: False) == []        # already handled
    assert not remove_stage(keep) and not remove_stage('')


# ---------------------------------------------------------------- real encode

needs_ffmpeg = pytest.mark.skipif(not SYSTEM_FFMPEG, reason='needs a system ffmpeg with libx264')


@pytest.fixture
def system_ffmpeg(monkeypatch):
    monkeypatch.setattr(encode_module, 'ffmpeg', lambda: SYSTEM_FFMPEG)
    monkeypatch.setattr(paths, 'ffmpeg', lambda: SYSTEM_FFMPEG)
    return SYSTEM_FFMPEG


def make_source(path, sound=True, size='320x240', seconds=4):
    command = [SYSTEM_FFMPEG, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
               f'color=c=0x2266aa:s={size}:r=25:d={seconds}']
    if sound: command += ['-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}', '-c:a', 'aac', '-shortest']
    result = subprocess.run(command + ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], capture_output=True)
    if result.returncode: pytest.skip('system ffmpeg cannot make a test video: ' + result.stderr.decode(errors='replace')[-200:])
    return path


def ready(project, source):
    project.media = str(source); project.duration = 4000; project.has_video = True
    project.width, project.height, project.fps = 320, 240, 25
    return project


def frame(path, at=0.5):
    result = subprocess.run([SYSTEM_FFMPEG, '-v', 'error', '-ss', str(at), '-i', str(path), '-frames:v', '1', '-f', 'rawvideo',
                             '-pix_fmt', 'rgb24', 'pipe:1'], capture_output=True)
    return np.frombuffer(result.stdout, np.uint8)


@needs_ffmpeg
def test_real_sample_and_full_video_are_checked_and_match(project, tmp_path, system_ffmpeg):
    source = make_source(tmp_path / 'four-three-source.mp4'); ready(project, source)
    sample = encode(project, EncodeOptions(str(tmp_path / 'out-sample.mp4'), 1000, 2000, '720p', codec='libx264'))
    full = encode(project, EncodeOptions(str(tmp_path / 'out-full.mp4'), 0, 0, '720p', codec='libx264'))
    assert sample['checked']['width'] == 1280 and sample['checked']['height'] == 720
    assert (sample['checked']['video'], sample['checked']['audio'], sample['codec']) == ('h264', 'aac', 'libx264')
    assert abs(sample['checked']['duration_ms'] - 2000) < 200 and abs(full['checked']['duration_ms'] - 4000) < 200
    assert sample['fingerprint'] == full['fingerprint'] and sample['fonts'] == [Path(bundled_fonts()[0].path).name]
    pixels = frame(tmp_path / 'out-full.mp4').reshape(720, 1280, 3)
    assert pixels[:, :150].max() < 40                                    # the side bars stay empty: subtitles sit on the picture
    assert pixels[100, 640, 2] > 120                                     # the picture itself (blue)
    assert not list(tmp_path.glob('.shengao-render-*'))
    project.lines[0].text = '明日も歌う'; project.lines[0].units = []
    changed = encode(project, EncodeOptions(str(tmp_path / 'out-changed.mp4'), 1000, 2000, '720p', codec='libx264'))
    assert changed['fingerprint'] != sample['fingerprint']


@needs_ffmpeg
def test_silent_source_video_still_gives_a_checked_mp4(project, tmp_path, system_ffmpeg):
    ready(project, make_source(tmp_path / 'silent-source.mp4', sound=False))
    result = encode(project, EncodeOptions(str(tmp_path / 'silent-out.mp4'), 0, 2000, codec='libx264'))
    assert result['checked']['audio'] == '' and result['checked']['video'] == 'h264'


@needs_ffmpeg
def test_cancelled_or_rejected_render_leaves_no_half_file(project, tmp_path, system_ffmpeg, monkeypatch):
    ready(project, make_source(tmp_path / 'cancel-source.mp4'))
    output = tmp_path / 'keep.mp4'; output.write_bytes(b'previous video')
    cancel = threading.Event(); stages = []
    def progress(value):
        if 'stage' in value: stages.append(value['stage']); cancel.set()
    with pytest.raises(ValueError, match='取消'):
        encode(project, EncodeOptions(str(output), codec='libx264'), cancel, progress)
    assert stages and not Path(stages[0]).exists() and output.read_bytes() == b'previous video'
    def reject(*args, **kwargs): raise ValueError('成品检查未通过：时长只有 0.1 秒。未保存为成品，原素材和工程未改动。')
    monkeypatch.setattr(encode_module, 'verify_output', reject)
    with pytest.raises(ValueError, match='成品检查未通过'):
        encode(project, EncodeOptions(str(output), 0, 2000, codec='libx264'))
    assert output.read_bytes() == b'previous video' and not list(tmp_path.glob('.shengao-render-*'))


# ---------------------------------------------------------------- export page

class Preferences:
    def __init__(self): self.data = {}
    def set(self, key, value): self.data[key] = value


def export_page(qapp, project, tmp_path):
    from PySide6.QtWidgets import QComboBox, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget
    from shengao.render_workflow import RenderWorkflow

    class Page(QWidget, RenderWorkflow):
        def message(self, text): self.status.setText(text); self.messages.append(text)
        def flush_edits(self): return True
        def busy_changed(self): self.busy_calls += 1

    page = Page(); page.home = tmp_path / 'home'; page.preferences = Preferences(); page.project = project
    page.path = None; page.current = 0; page.playback = SimpleNamespace(canvas=SimpleNamespace(position=3000))
    page.test = True; page.encoder_capabilities = {'cpu_codec': 'libx264'}; page.source_job = None; page.local_job = None
    page.messages = []; page.busy_calls = 0; page.status = QLabel(); page.output_label = QLabel(); page.progress = QProgressBar()
    page.sample_button = QPushButton()
    page.output_size = QComboBox(); [page.output_size.addItem(t, k) for k, t in render_plan.SIZES.items()]
    page.quality = QComboBox(); [page.quality.addItem(t, k) for k, t in render_plan.QUALITIES.items()]
    page.encoder = QComboBox(); page.encoder.addItem('CPU', 'cpu')
    page.init_render_workflow(); layout = QVBoxLayout(page)
    page.build_render_controls(layout); page.build_render_queue(layout)
    return page


def test_export_page_shows_range_folder_and_queue(qapp, project, tmp_path, monkeypatch):
    media = tmp_path / 'clip' / 'page-source.mp4'; media.parent.mkdir(); media.write_bytes(b'v' * 64)
    project.media = str(media); project.duration = 30000
    page = export_page(qapp, project, tmp_path)
    page.refresh_sample_range()
    assert page.sample_label.text() == '样片范围：00:00.0 – 00:12.0，共 12 秒（第 1 句前 1 秒起）'
    assert page.output_folder_label.text() == str(media.parent) and page.sample_button.text() == '先看 12 秒样片'
    page.sample_mode.setCurrentIndex(page.sample_mode.findData('custom')); page.sample_start.setValue(20); page.sample_length.setValue(5)
    assert page.sample_label.text().startswith('样片范围：00:20.0 – 00:25.0') and page.sample_start.isVisibleTo(page)
    assert page.preferences.data['sample'] == {'mode': 'custom', 'length': 5000}
    calls = []
    def run(fn, done, failed, progress):
        job = SimpleNamespace(cancel=threading.Event()); calls.append(SimpleNamespace(done=done, failed=failed, progress=progress, job=job))
        return job
    monkeypatch.setattr('shengao.render_workflow.jobs.run', run)
    options = page.encode_settings(True)
    assert (options.start, options.duration, options.codec) == (20000, 5000, 'libx264')
    options.output = str(tmp_path / 'clip' / 's.mp4'); first = page.encode_to(options, 'sample')
    added = page.queue_batch(['original'], ['720p', '1080p'])
    assert page.local_job is calls[0].job and [t.state for t in page.render_queue.tasks] == ['running', 'waiting', 'waiting']
    assert [Path(t.options.output).name for t in added] == ['未命名作品-720p-字幕成品.mp4', '未命名作品-1080p-字幕成品.mp4']
    assert page.render_list.count() == 3 and page.render_list.item(0).text().startswith('[压制中] 样片')
    calls[0].done({'output': options.output, 'fingerprint': 'same', 'checked': {'duration_ms': 5000}})
    assert page._last_sample['fingerprint'] == 'same' and '已读回检查' in page.output_label.text()
    calls[1].done({'output': added[0].options.output, 'fingerprint': 'same'})
    assert '与上次样片使用同一份时间、排版和字体' in page.messages[-1] and added[0].result['matches_sample']
    page.render_list.setCurrentRow(2); page.cancel_selected_render()
    assert added[1].state == 'cancelling' and calls[2].job.cancel.is_set()
    calls[2].failed('压制已取消；原素材和工程未改动')
    assert added[1].state == 'cancelled' and page.local_job is None and not page.render_queue.busy
    assert page.render_list.item(2).text().startswith('[已取消]')
    record = json.loads((page.home / 'desktop-renders' / f'{first.id}.json').read_text(encoding='utf-8'))
    assert record['state'] == 'completed' and record['sample'] and record['start'] == 20000
