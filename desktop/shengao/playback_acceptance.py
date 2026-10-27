"""Full-length local playback, real paint timestamps and five frame positions.

Explicit developer/packaged CLI, using only owned hidden Qt windows. Private
media, frame images and reports stay in the supplied local output directory.
This measures player-clock/render continuity, never acoustic or human accuracy.
"""
from pathlib import Path
import argparse
import json
import math
import os
import platform
import sys
import time
import traceback


def statistics(values):
    ordered = sorted(values)
    return {'values_ms': values, 'count': len(values),
            'p95_ms': ordered[max(0, math.ceil(len(values)*.95)-1)] if values else None,
            'max_ms': ordered[-1] if values else None}


def interval_lag(clock_ms, start_us, end_us):
    if start_us is None or end_us is None or start_us < 0 or end_us <= start_us:
        raise ValueError('Presented frame has no valid timing interval')
    return max(start_us/1000-clock_ms, clock_ms-end_us/1000, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--playback-continuity-test', action='store_true')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--proxy-cache', type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.output.resolve()
    if not source.is_file():
        parser.error('Local media does not exist')
    out.mkdir(parents=True, exist_ok=False)
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtTest import QTest
    from .app import StudioWindow
    from .project import Project, History, file_stamp
    from .proxy_video import prepare, digest
    from .paths import ffmpeg, RUNTIME
    from .process_memory import sample
    from .gui_gc import install
    from .native_slots import invoke_native_slot
    from .theme import STYLE
    from studio_backend.model import LyricLine, Unit
    from studio_backend.japanese import add_mora

    report = {'completed': False, 'passed': False, 'scope': __doc__,
              'computer_use': False, 'paid_api_calls': 0,
              'system_cache_flushed': False, 'proxy_cache': str(args.proxy_cache.resolve()),
              'source_stamp': file_stamp(source), 'source_sha256': digest(source),
              'ffmpeg_sha256': digest(ffmpeg()), 'frozen': bool(getattr(sys, 'frozen', False)),
              'python': sys.version, 'windows': platform.platform(),
              'cpu': platform.processor(), 'logical_processors': os.cpu_count(),
              'threads': {k: os.getenv(k) for k in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')},
              'measurements': {}, 'targets': {}, 'errors': [],
              'pending': ['Physical display and acoustic A/V judgment',
                          'Whole-song manual accuracy and newcomer acceptance']}
    before = None
    def phase(name):
        value = {'phase': name, 'monotonic_seconds': time.monotonic()}
        report.setdefault('phases', []).append(value)
        (out/'progress.json').write_text(json.dumps(value), encoding='utf-8')
        if sys.stdout is not None:
            print('phase', name, flush=True)
    if not report['frozen']:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
        from desktop_source_state import snapshot
        before = snapshot(Path(__file__).resolve().parents[2])
        report['source_snapshot'] = before
    else:
        report['package_manifest_sha256'] = digest(RUNTIME/'package-manifest.json')
    app = QApplication([])
    app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    policy = install(app)
    w = StudioWindow(out/'home', test=True)
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(1280, 800); w.playback.audio.setMuted(True); w.show()
    report['device_pixel_ratio'] = w.devicePixelRatioF()
    report['memory_before'] = sample()
    w.playback.error.connect(lambda message: report['errors'].append(str(message)))

    def wait(condition, seconds=30):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            app.processEvents(); QTest.qWait(2)
            if condition():
                return True
        return False

    def ready():
        c = w.playback.canvas
        return not w.playback.preview_pending and not c.frame.isNull() and c.painted_at_s is not None

    def frames_at_five_positions(label, path, edges):
        values = []
        report['measurements'][label+'_five_positions'] = values
        # Visit the middle first so returning to the first frame requires an
        # actual new decoder/painter result, rather than reusing its old image.
        for fraction in (.5, 0, .25, .75, 1):
            phase(label+' position '+str(fraction))
            target = round((edges['video_start_us']+(edges['video_last_us']-edges['video_start_us'])*fraction)/1000)
            c = w.playback.canvas; sequence = c.painted_sequence
            w.playback.open(path, position=target, preview=True, reference_size=(w.project.width, w.project.height))
            matched = wait(lambda: not w.playback.preview_pending and c.painted_sequence > sequence and c.painted_frame_start_us is not None
                           and c.painted_frame_end_us is not None and c.painted_frame_start_us <= target*1000+1000
                           and c.painted_frame_end_us > target*1000, 6)
            image_path = out/(label+'-position-'+str(fraction)+'.png')
            image = c.grab().toImage() if matched else None
            saved = image is not None and image.save(str(image_path))
            values.append({'fraction': fraction, 'target_ms': target, 'matched': matched,
                           'painted_start_us': c.painted_frame_start_us, 'painted_end_us': c.painted_frame_end_us,
                           'sequence': c.painted_sequence, 'private_image_saved': bool(saved),
                           'image_size': [image.width(), image.height()] if image is not None else None,
                           'reference_source_size': [w.playback.source_size.width(), w.playback.source_size.height()]})
        report['targets'][label+'_five_positions'] = all(v['matched'] and v['private_image_saved'] for v in values)

    def continuous(label, path, edges):
        phase(label+' continuous loading')
        w.playback.open(path, preview=True, reference_size=(w.project.width, w.project.height))
        assert wait(ready), 'Initial playback frame did not become ready'
        w.playback.player.setPlaybackRate(1.0)
        c = w.playback.canvas; player = w.playback.player
        sequence = c.painted_sequence; began = time.perf_counter(); previous = began
        last_frame = began; new_frames = []; beats = []; lags = []; observations = []
        value = {'player_duration_ms': player.duration(), 'video_edges': edges,
                 'playback_rate': player.playbackRate(), 'autosave_interval_ms': w.autosave.interval(),
                 'autosave_active': w.autosave.isActive(), 'unsaved_document': w.history.dirty,
                 'new_frames': new_frames, 'observations': observations, 'ended': False}
        report['measurements'][label+'_continuous'] = value
        timer = QTimer(w); timer.setInterval(20)

        def observe():
            nonlocal previous, sequence, last_frame
            now = time.perf_counter(); beats.append((now-previous)*1000); previous = now
            clock = player.position()
            try:
                lag = interval_lag(clock, c.painted_frame_start_us, c.painted_frame_end_us)
            except ValueError:
                lag = None
            if lag is not None:
                lags.append(lag)
            observations.append({'elapsed_ms': (now-began)*1000, 'clock_ms': clock, 'subtitle_clock_ms': c.position,
                                 'player_ms': player.position(), 'painted_sequence': c.painted_sequence,
                                 'painted_start_us': c.painted_frame_start_us,
                                 'painted_end_us': c.painted_frame_end_us, 'lag_ms': lag})
            if c.painted_sequence != sequence:
                painted = c.new_frame_painted_at_s
                new_frames.append({'sequence': c.painted_sequence, 'pts_us': c.painted_frame_start_us,
                                   'end_us': c.painted_frame_end_us, 'elapsed_ms': (painted-began)*1000,
                                   'interval_ms': (painted-last_frame)*1000})
                sequence = c.painted_sequence; last_frame = painted

        timer.timeout.connect(observe)
        phase(label+' continuous playing')
        timer.start(); invoke_native_slot(player, 'play')
        try:
            value['ended'] = wait(lambda: player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia,
                                  player.duration()/1000+15)
        finally:
            timer.stop(); timer.deleteLater()
        value['wall_ms'] = (time.perf_counter()-began)*1000
        value['wall_media_difference_ms'] = abs(value['wall_ms']-value['player_duration_ms'])
        value['heartbeat'] = statistics(beats); value['clock_frame_lag'] = statistics(lags)
        # Include the final gap up to real EndOfMedia; no slow final interval
        # is discarded just because no following video frame exists.
        value['new_frame_intervals'] = statistics([v['interval_ms'] for v in new_frames]+[(time.perf_counter()-last_frame)*1000])
        value['last_painted_start_us'] = c.painted_frame_start_us
        value['memory_after'] = sample()
        report['targets'][label+'_ended_at_1x'] = value['ended'] and player.playbackRate() == 1.0 and value['wall_media_difference_ms'] <= 2000
        report['targets'][label+'_all_frame_intervals'] = bool(new_frames) and value['new_frame_intervals']['p95_ms'] <= 150 and value['new_frame_intervals']['max_ms'] <= 500
        report['targets'][label+'_clock_frame_lag'] = bool(lags) and len(lags) == len(observations) and value['clock_frame_lag']['p95_ms'] <= 150 and value['clock_frame_lag']['max_ms'] <= 500
        report['targets'][label+'_final_video_frame'] = c.painted_frame_start_us is not None and abs(c.painted_frame_start_us-edges['video_last_us']) <= 1000
        report['targets'][label+'_normal_recovery_enabled'] = value['autosave_active'] and value['autosave_interval_ms'] == 15000 and value['unsaved_document']
        if sys.stdout is not None:
            print(label, json.dumps({k: value[k] for k in ('ended', 'wall_ms', 'wall_media_difference_ms', 'last_painted_start_us')}), flush=True)

    try:
        # Preparation/verification is outside the playback intervals. This
        # uses the same verified local cache implementation as the editor.
        from . import jobs
        phase('proxy verification')
        prepared = []; failures = []
        job = jobs.run(lambda cancel, progress: prepare(source, args.proxy_cache, cancel, progress),
                       prepared.append, failures.append)
        assert wait(lambda: bool(prepared or failures), 600), 'Proxy preparation timed out'
        assert prepared, failures
        base = prepared[0]; report['proxy_verification'] = base['verification']; report['proxy_reused'] = base['reused']
        phase('controlled 1000-line document and media analysis')
        lines = []
        for index in range(1000):
            start = index*260+50
            units = [Unit('明日', start, start+90, 'あした'), Unit('も', start+90, start+125, 'も'), Unit('歌う', start+125, start+220, 'うたう')]
            for unit in units:
                add_mora(unit)
            lines.append(LyricLine('continuous-'+str(index), '明日も歌う', start, start+220, units))
        project = Project(lines=lines); project.style.display_mode = 'alternating'; project.style.show_romaji = False; project.style.show_translation = False
        w.history = History(project); w.current = 0; w.refresh(); w.load_media(source, preview=True)
        assert wait(lambda: w.analysis_job is None and ready(), 90)
        w.history.apply_line('未保存播放验收', 0, lambda line: set_translation(line))
        w.finish_history_edit(render_now=True)
        w.view_choice.setCurrentIndex(2); w.reveal_center_widget(w.playback)
        assert wait(lambda: w.playback.visibleRegion().boundingRect().height() == w.playback.height())
        original = w.project.to_dict()
        for label, path in (('original', source), ('proxy', Path(base['path']))):
            edges = base['verification']['source' if label == 'original' else 'proxy']
            w.playback.open(path, preview=True, reference_size=(w.project.width, w.project.height))
            assert wait(ready)
            frames_at_five_positions(label, path, edges)
            continuous(label, path, edges)
            assert w.project.to_dict() == original, 'Playback changed document data'
            assert wait(lambda: w.recovery_writer.idle and not w.edited_recovery_timer.isActive() and w.recovery_path().is_file(), 8), 'Background recovery did not finish'
            recovered = json.loads(w.recovery_path().read_text(encoding='utf-8'))
            report['targets'][label+'_background_recovery_roundtrip'] = recovered['project'] == original and Project.from_dict(recovered['project']).to_dict() == original and recovered['pending'] is None
        report['targets']['no_player_errors'] = not report['errors']
        report['completed'] = True
        report['source_snapshot_unchanged'] = before is None or snapshot(Path(__file__).resolve().parents[2]) == before
        report['passed'] = all(report['targets'].values()) and report['source_snapshot_unchanged']
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        phase('finalizing local report')
        report['source_unchanged'] = file_stamp(source) == report['source_stamp'] and digest(source) == report['source_sha256']
        report['passed'] = report['passed'] and report['source_unchanged']
        report['gui_gc'] = policy.report() if policy else None
        report['frame_scaler'] = w.playback.canvas.frame_scaler_status()
        report['memory_after'] = sample()
        (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        w.close(); app.processEvents()
        if policy:
            policy.close()
    return 0 if report['passed'] else 1


def set_translation(line):
    line.translation = '受控字幕，指定MV仅用于本地播放性能。'
    return line
