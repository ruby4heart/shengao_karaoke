"""Optional speed-ups fall back reliably (TODO 11.2): GPU preview failures of any
kind give the regular picture, and damaged saved choices start with the defaults."""
import json

import pytest
from PySide6.QtCore import QThread, QThreadPool
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QLabel

from shengao.app import StudioWindow
from shengao.preview_preferences import PreviewPreferencesDialog


@pytest.fixture
def pool():
    pool = QThreadPool.globalInstance(); old = pool.maxThreadCount()
    yield pool
    pool.setMaxThreadCount(old)


def window(qapp, home):
    w = StudioWindow(home=home, test=True); w.resize(900, 620); return w


def frame(colour=0xff12ab34):
    image = QImage(40, 20, QImage.Format.Format_ARGB32); image.fill(colour); return QVideoFrame(image)


@pytest.mark.parametrize('error', [TypeError('driver returned nothing'), MemoryError(), KeyError('format'), ValueError('probe did not render')])
def test_any_gpu_failure_falls_back_to_the_regular_picture_and_says_so(qapp, tmp_path, monkeypatch, pool, error):
    import shengao.frame_scaler as module
    w = window(qapp, tmp_path / 'home'); canvas = w.playback.canvas; calls = []
    assert canvas.gpu_enabled
    monkeypatch.setattr(module, 'eligible', lambda *args: True)
    def broken(self): calls.append(1); raise error
    monkeypatch.setattr(module.GpuFrameScaler, '_initialize', broken)
    canvas.video_frame(frame())
    assert not canvas.frame.isNull() and canvas.frame.pixelColor(10, 10).rgb() == 0xff12ab34
    status = canvas.frame_scaler_status(); assert status['error'] and status['closed']
    canvas.video_frame(frame(0xff3456cd))                                   # later frames skip the failed GPU path
    assert canvas.frame.pixelColor(10, 10).rgb() == 0xff3456cd and calls == [1]
    dialog = PreviewPreferencesDialog(w)
    assert any('GPU不可用，已自动回退' in label.text() for label in dialog.findChildren(QLabel)) and dialog.gpu.isChecked()
    dialog.close()
    canvas.set_gpu_enabled(False); canvas.set_gpu_enabled(True)            # turning it off and on tries again
    canvas.video_frame(frame()); assert calls == [1, 1] and not canvas.frame.isNull()
    w.close(); qapp.processEvents()


@pytest.mark.parametrize('saved', [{'preview_gpu': 'yes', 'local_worker_limit': 3}, {'preview_gpu': False, 'local_worker_limit': -1},
                                   {'preview_gpu': 1, 'local_worker_limit': 2}])
def test_invalid_saved_choices_start_with_the_defaults(qapp, tmp_path, pool, saved):
    home = tmp_path / 'home'; home.mkdir(); (home / 'workspace.json').write_text(json.dumps(saved), encoding='utf-8')
    pool.setMaxThreadCount(1)
    w = window(qapp, home)
    assert w.playback.canvas.gpu_enabled is True and w.local_worker_limit == 0
    assert pool.maxThreadCount() == max(1, QThread.idealThreadCount())
    w.close(); qapp.processEvents()


def test_unreadable_settings_file_starts_with_the_defaults_and_is_kept(qapp, tmp_path, pool):
    home = tmp_path / 'home'; home.mkdir(); (home / 'workspace.json').write_text('{"preview_gpu": false, "local_wor', encoding='utf-8')
    w = window(qapp, home)
    assert w.playback.canvas.gpu_enabled is True and w.local_worker_limit == 0 and not w.proxy_active
    assert w.preferences.damaged and w.preferences.damaged.is_file()
    w.close(); qapp.processEvents()


def test_saved_choices_are_used_and_one_worker_still_finishes_queued_work(qapp, tmp_path, pool):
    from shengao import jobs
    home = tmp_path / 'home'; home.mkdir()
    (home / 'workspace.json').write_text(json.dumps({'preview_gpu': False, 'local_worker_limit': 1}), encoding='utf-8')
    w = window(qapp, home)
    assert w.playback.canvas.gpu_enabled is False and w.local_worker_limit == 1 and pool.maxThreadCount() == 1
    done = []
    work = [jobs.run(lambda cancel, report, n=n: n, done.append, lambda message: done.append(message)) for n in range(3)]
    assert pool.waitForDone(10000)
    for _ in range(20): qapp.processEvents()
    assert sorted(done) == [0, 1, 2] and len(work) == 3
    w.close(); qapp.processEvents()
