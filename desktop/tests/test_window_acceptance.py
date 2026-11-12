"""Window sizes of real screens, save and reopen, failure recovery and render
cancel, all in the test's own window (TODO group 10, item 8)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from shengao import window_acceptance
from shengao.window_size import DEFAULT, MINIMUM, available, startup_geometry

ROOT = Path(__file__).resolve().parents[2]


def test_start_size_fits_the_screen():
    assert startup_geometry(1920, 1032) == (MINIMUM, DEFAULT)                 # 1920×1080 at 100 %
    assert startup_geometry(1280, 672) == ((900, 620), (1256, 648))           # 1920×1080 at 150 %
    assert startup_geometry(910, 464) == ((886, 440), (886, 440))             # 1366×768 at 150 %: smaller than the usual minimum
    assert available(1920, 1080, 1.5) == (1280, 672) and available(3840, 2160, 1.5) == (2560, 1392)


def test_layout_cases_cover_every_screen_and_stay_inside_it():
    cases = window_acceptance.layout_cases(); keys = [key for key, *_ in cases]
    assert len(keys) == len(set(keys)) and keys[-1] == 'minimum'
    assert {'1366x768-150-start', '1920x1080-150-max', '3840x2160-150-max'} <= set(keys)
    for label, width, height, scale in window_acceptance.SCREENS:
        area = available(width, height, scale)
        for key, _, minimum, size in cases:
            if key.startswith(f'{width}x{height}-{round(scale * 100)}-'):
                assert size[0] <= area[0] and size[1] <= area[1] and minimum[0] <= size[0] and minimum[1] <= size[1]


def test_elided_title_keeps_the_whole_name(qapp):
    from shengao.widgets import ElidedLabel
    label = ElidedLabel('一个非常非常非常长的作品名字 · 今日も歌う · 第二版'); label.resize(60, 24)
    assert not label.grab().isNull() and label.text().endswith('第二版')


def test_export_page_never_scrolls_sideways_with_a_long_folder(qapp, tmp_path):
    from shengao.app import StudioWindow
    window = StudioWindow(home=tmp_path / 'home', test=True); window.setMinimumSize(*MINIMUM); window.resize(*MINIMUM); window.show()
    deep = tmp_path.joinpath(*['一个很长很长的文件夹名字_without_spaces_0123456789'] * 6)
    window.set_stage(4); window.show_output_folder(deep)          # after the step refreshed its own folder
    for _ in range(5): qapp.processEvents(); time.sleep(0.01)
    assert window.output_folder_label.text() == str(deep) and window.output_folder_label.toolTip() == str(deep)
    assert window_acceptance.inspect(window, 4) == []


def test_launcher_has_the_window_check():
    result = subprocess.run([sys.executable, str(ROOT / 'desktop' / 'main.py'), '--window-check'], capture_output=True, text=True,
                            timeout=60, env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert result.returncode == 2 and '--output' in result.stderr                  # reached its own argument check


def test_runner_reports_each_check_in_chinese(capsys):
    spec = importlib.util.spec_from_file_location('run_window_checks', ROOT / 'scripts' / 'run-window-checks.py')
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    assert runner.command(None, Path('o'))[1:] == [str(ROOT / 'desktop' / 'main.py'), '--window-check', '--output', 'o']
    assert runner.command(Path('pkg'), Path('o'))[0] == str(Path('pkg') / 'shengao-karaoke.exe')
    report = {'passed': False, 'device_pixel_ratio': 1.5, 'seconds': 3, 'groups': [{'title': '压制取消', 'completed': True}],
              'checks': [{'name': 'render_cancel_started', 'title': '压制任务开始后可以取消', 'passed': True},
                         {'name': 'layout_minimum', 'title': '', 'passed': False}],
              'layout': [{'label': '最小窗口 900×620', 'problems': ['第 5 步“导出”需要左右滚动 9 像素才能看全']}]}
    assert runner.show('150% 缩放', 1, report, Path('o')) is False
    text = capsys.readouterr().out
    assert '[通过] 压制任务开始后可以取消' in text and '[失败] 窗口尺寸：最小窗口 900×620' in text and '左右滚动 9 像素' in text
    assert [key for key, *_ in runner.RUNS] == ['normal', 'dpi150', 'basic']
    basic = runner.PREFERENCES['basic']; good = {'passed': True, 'checks': [{'name': 'x', 'title': '某项', 'passed': True}], 'groups': [],
                                                  'preview_gpu': False, 'worker_limit': 1, 'thread_limit': 1, 'light_preview': False}
    assert runner.show('关闭可选优化', 0, good, Path('o'), basic) is True
    assert 'GPU 预览关，后台任务并行数 1（线程上限 1），轻量预览关' in capsys.readouterr().out
    assert runner.show('关闭可选优化', 0, {**good, 'preview_gpu': True}, Path('o'), basic) is False      # settings were not read
    assert '[失败] 启动时读取了关闭可选优化的设置' in capsys.readouterr().out
    assert runner.show('正常缩放', 0, {**good, 'worker_limit': 0, 'thread_limit': 8, 'preview_gpu': True}, Path('o')) is True


class _SilentAudio:
    """Stand-in for the Windows waveform module: same calls, blank pictures."""
    def __init__(self, pcm, rate): self.rate = int(rate); self.handle = 1
    def rgb(self, start, width, height, pixel_ms, *args, **kwargs): return np.zeros((height, width, 3), np.uint8)
    def power(self, index, quality=1): return np.zeros(16, np.float32)
    def close(self): self.handle = None


@pytest.fixture
def window_class(monkeypatch):
    """The real window on Windows; elsewhere the Windows-only pieces (bundled
    ffmpeg, waveform module, Media Foundation encoder) get stand-ins."""
    from shengao.app import StudioWindow
    if os.name == 'nt': return StudioWindow
    found = shutil.which('ffmpeg')
    if not found: pytest.skip('needs a system ffmpeg with libx264')
    import shengao.media  # noqa: F401  (loads every module that starts ffmpeg)
    from shengao import paths, timeline
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
    original = paths.ffmpeg
    for name, module in list(sys.modules.items()):
        if name.startswith('shengao') and getattr(module, 'ffmpeg', None) is original:
            monkeypatch.setattr(module, 'ffmpeg', lambda: found)
    monkeypatch.setattr(timeline, 'AudioRenderer', _SilentAudio)

    class Window(StudioWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); self.encoder_capabilities = {'cpu': True, 'hardware': False, 'cpu_codec': 'libx264'}
    return Window


def _exercise(qapp, window_class, out, keys):
    from PySide6.QtTest import QTest
    checks = []
    def check(name, condition):
        checks.append(name); assert condition, window_acceptance.TITLES.get(name, name)
    def wait(fn, timeout=10000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            qapp.processEvents(); QTest.qWait(25)
            if fn(): return True
        return False
    cases = [c for c in window_acceptance.layout_cases() if c[0] in keys]
    window_acceptance.exercise(qapp, window_class, out, check, wait, cases)
    return checks


def test_save_reopen_recovery_cancel_and_sizes_in_own_window(qapp, window_class, tmp_path):
    checks = _exercise(qapp, window_class, tmp_path, {'minimum', '1366x768-150-start', '1920x1080-150-start'})
    assert set(window_acceptance.TITLES) <= set(checks) and len([c for c in checks if c.startswith('layout_')]) == 3


def test_whole_flow_works_with_every_optional_speed_up_off(qapp, window_class, tmp_path):
    """TODO 11.2: GPU preview off, one background task at a time, original video
    preview; saved the way the settings window saves them, read on start."""
    from PySide6.QtCore import QThreadPool
    pool = QThreadPool.globalInstance(); old = pool.maxThreadCount(); seen = []
    spec = importlib.util.spec_from_file_location('run_window_checks', ROOT / 'scripts' / 'run-window-checks.py')
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    (tmp_path / 'home').mkdir(); (tmp_path / 'home' / 'workspace.json').write_text(json.dumps(runner.PREFERENCES['basic']), encoding='utf-8')

    class Basic(window_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seen.append((self.playback.canvas.gpu_enabled, self.local_worker_limit, pool.maxThreadCount(), self.proxy_active))
    try: checks = _exercise(qapp, Basic, tmp_path, {'minimum'})
    finally: pool.setMaxThreadCount(old)
    assert set(window_acceptance.TITLES) <= set(checks)          # includes a render queue running on the single worker
    assert len(seen) >= 3 and set(seen) == {(False, 1, 1, False)}
