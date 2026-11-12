"""Recovery drills (11.3) and the pieces they rely on; no window or model is needed."""
from pathlib import Path
from unittest import mock
import errno
import json
import os
import sys
import time
import pytest
from shengao import failure_drill
from shengao.failure_drill import sample_project, Skip

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('name', [fn.__name__ for _, _, fn in failure_drill.DRILLS])
def test_drill(name, tmp_path):
    fn = next(fn for _, _, fn in failure_drill.DRILLS if fn.__name__ == name)
    try: detail = fn(tmp_path)
    except Skip as reason: pytest.skip(str(reason))
    assert isinstance(detail, str) and detail


def test_every_group_is_drilled_and_the_runner_reports_each(tmp_path):
    groups = {group for group, _, _ in failure_drill.DRILLS}
    assert groups == {'文件损坏', '路径移动', '磁盘不足', '强制退出', '压制中断', '模型进程失败'}
    rows = failure_drill.run({'damaged_task', 'moved_output'})
    assert [r['name'] for r in rows] == ['damaged_task', 'moved_output'] and all(r['state'] == 'passed' for r in rows)


def test_runner_reports_a_failed_drill_without_stopping(monkeypatch):
    def broken(base): raise AssertionError('原文件被改动')
    monkeypatch.setattr(failure_drill, 'DRILLS', [('文件损坏', '演练', broken), *failure_drill.DRILLS[:1]])
    rows = failure_drill.run()
    assert rows[0]['state'] == 'failed' and '原文件被改动' in rows[0]['detail'] and rows[1]['state'] == 'passed'


def test_script_prints_report_and_exit_code(tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location('run_failure_drills', ROOT/'scripts/run-failure-drills.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    out = tmp_path/'report.json'
    assert module.main(['--only', 'damaged_preferences', 'full_on_save', '--out', str(out)]) == 0
    printed = capsys.readouterr().out
    assert '【文件损坏】' in printed and '【磁盘不足】' in printed and '通过 2，失败 0' in printed
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['summary'] == {'passed': 2, 'failed': 0, 'skipped': 0} and len(report['drills']) == 2
    assert module.main(['--only', 'no_such_drill', '--out', str(out)]) == 2


def test_forced_exit_drills_skip_in_packaged_app(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    with pytest.raises(Skip): failure_drill.exit_during_save(tmp_path)


# ------------------------------------------------------------------ damage.py

class WinError(OSError):
    def __init__(self, code): super().__init__(None, 'drill'); self.winerror = code


def test_reasons_are_plain_and_name_the_cause():
    from shengao.damage import reason, disk_full
    assert disk_full(OSError(errno.ENOSPC, 'x')) and disk_full(WinError(112)) and disk_full(WinError(39))
    assert not disk_full(OSError(errno.EACCES, 'x')) and not disk_full(ValueError('x'))
    assert reason(OSError(errno.ENOSPC, 'x')) == '磁盘空间不足，请清理出空间后重试'
    assert '占用' in reason(PermissionError(errno.EACCES, 'x')) and '占用' in reason(WinError(32))
    assert '移动' in reason(FileNotFoundError(errno.ENOENT, 'x'))
    try: json.loads('{\n"a": [')
    except ValueError as error: assert reason(error) == '文件内容不完整或已损坏（第 2 行附近）'
    assert '损坏' in reason(UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'bad'))
    assert reason(ValueError('歌词为空')) == '歌词为空'


@pytest.mark.parametrize('kind,code,log,expected', [
    ('alignment', 1, 'MemoryError: Unable to allocate', '歌声对齐失败：本机内存不足'),
    ('vocals', 0xC0000017, '', '人声处理失败：本机内存不足'),
    ('vocals', 1, 'OSError: [Errno 28] No space left on device', '人声处理失败：磁盘空间不足'),
    ('alignment', 0xC0000005, '', '歌声对齐失败：本地模型进程意外退出（内存访问错误，代码 0xC0000005）'),
    ('alignment', -1073741819, '', '歌声对齐失败：本地模型进程意外退出（内存访问错误，代码 0xC0000005）'),
    ('vocals', -9, '', '人声处理失败：本地模型进程被系统终止（信号 9）'),
    ('vocals', 3, 'something else', '人声处理失败：本地模型进程异常结束（代码 3）'),
    ('audio', 1, 'demo.wav: No such file or directory', '声音准备失败：找不到素材文件'),
    ('audio', 0xC000013A, '', '声音准备失败：声音转换进程意外退出（被关闭'),
])
def test_process_failure_names_the_cause(kind, code, log, expected):
    from shengao.damage import process_failure
    message = process_failure(kind, code, log)
    assert message.startswith(expected), message
    assert '原素材和工程没有改动，这次未完成的结果没有采用。' in message
    assert ('详细记录' in message) == bool(log.strip())


def test_process_failure_keeps_only_the_end_of_a_long_log():
    from shengao.damage import process_failure
    message = process_failure('alignment', 1, 'x' * 5000 + 'END')
    assert message.endswith('END') and len(message) < 1400


def test_ffmpeg_failures_are_not_called_model_failures(monkeypatch):
    from shengao import vocal_audio
    real = vocal_audio.subprocess.Popen
    monkeypatch.setattr(vocal_audio.subprocess, 'Popen', lambda command, **k: real([sys.executable, '-c', 'import sys;sys.exit(1)'], **k))
    with pytest.raises(ValueError) as found: vocal_audio.run(['C:/app/ffmpeg.exe', '-i', 'x'], None)
    assert str(found.value).startswith('声音准备失败：声音转换进程异常结束（代码 1）')
    with pytest.raises(ValueError) as found: vocal_audio.run(['worker.exe'], None, kind='alignment')
    assert str(found.value).startswith('歌声对齐失败：本地模型进程异常结束')


def test_read_task_never_offers_a_damaged_result(tmp_path):
    from shengao.damage import read_task
    assert read_task(tmp_path) is None
    (tmp_path/'request.json').write_text('[1]', encoding='utf-8')
    assert read_task(tmp_path)[0] == {'action': 'damaged'}
    (tmp_path/'request.json').write_text('{"action": "acoustic"}', encoding='utf-8'); (tmp_path/'result.json').write_text('[]', encoding='utf-8')
    request, value = read_task(tmp_path)
    assert request == {'action': 'acoustic'} and '损坏' in value['message'] and 'suggestions' not in value
    (tmp_path/'result.json').write_text('{"ok": true, "suggestions": []}', encoding='utf-8')
    assert read_task(tmp_path)[1] == {'ok': True, 'suggestions': []}


# ------------------------------------------------------------------ moved-aside copies

def test_damaged_copies_are_dated_and_only_the_newest_five_kept(tmp_path):
    from studio_backend.settings import preserve_damaged
    path = tmp_path/'settings.json'; moved = []
    for i in range(7):
        path.write_text(f'broken {i}', encoding='utf-8')
        moved.append(preserve_damaged(path, now=time.mktime((2026, 11, 12, 10, 0, i // 2, 0, 0, -1))))
    assert not path.exists() and len({p.name for p in moved}) == 7
    kept = sorted(tmp_path.glob('settings.damaged-*.json'))
    assert len(kept) == 5 and {p.read_text(encoding='utf-8') for p in kept} == {f'broken {i}' for i in range(2, 7)}
    assert moved[0].name == 'settings.damaged-20261112-100000.json' and moved[1].name == 'settings.damaged-20261112-100000-1.json'
    assert preserve_damaged(tmp_path/'missing.json') is None


def test_settings_with_wrong_shape_are_damaged_but_reported_only_when_written(tmp_path):
    from studio_backend.settings import Settings
    (tmp_path/'settings.json').write_text('{"deepseek": "key"}', encoding='utf-8')
    settings = Settings(tmp_path)
    with pytest.raises(ValueError, match='已损坏'): settings.read()
    assert (tmp_path/'settings.json').exists() and settings.damaged is None
    settings.forget('deepseek')
    assert settings.damaged.read_text(encoding='utf-8') == '{"deepseek": "key"}'


def test_preferences_with_wrong_shape_start_fresh(tmp_path):
    from shengao.preferences import Preferences
    (tmp_path/'workspace.json').write_text('[1, 2]', encoding='utf-8')
    preferences = Preferences(tmp_path)
    assert preferences.data == {} and preferences.damaged.read_text(encoding='utf-8') == '[1, 2]'
    assert Preferences(tmp_path).damaged is None


# ------------------------------------------------------------------ recovery record

def test_sweep_removes_only_old_app_owned_staging_files(tmp_path):
    from shengao.recovery import sweep
    path = tmp_path/'desktop-recovery.json'; path.write_text('{}', encoding='utf-8')
    names = ['desktop-recovery.prepare-ab12.json', 'desktop-recovery.prepare-ab12.tmp', 'desktop-recovery.x1y2.tmp',
             'desktop-recovery.damaged-20261112-100000.json', 'workspace.abc.tmp', 'project.sgproj']
    for name in names: (tmp_path/name).write_text('x', encoding='utf-8')
    assert sweep(path) == 0
    assert sweep(path, now=time.time() + 601) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(['desktop-recovery.json', *names[3:]])
    assert sweep(tmp_path/'missing'/'desktop-recovery.json') == 0


def test_read_record_rejects_records_without_a_usable_project(tmp_path):
    from shengao.recovery import read_record
    path = tmp_path/'desktop-recovery.json'
    assert read_record(path) == (None, None, '', None)
    for text in ('[]', '{"path": "x"}', '{"project": "x"}'):
        path.write_text(text, encoding='utf-8')
        record, project, problem, moved = read_record(path)
        assert record is None and problem and moved.read_text(encoding='utf-8') == text and not path.exists()
    path.write_text(json.dumps({'project': sample_project(tmp_path/'p').to_dict()}), encoding='utf-8')
    record, project, problem, moved = read_record(path)
    assert project.title == '演练作品' and problem == '' and moved is None


class Window:
    """Just enough of the main window for the recovery and open paths."""
    def __init__(self, home):
        self.home = Path(home); self.messages = []; self.calls = []
    def recovery_path(self): return self.home/'desktop-recovery.json'
    def version_root(self): return self.home/'version-history'
    def message(self, text): self.messages.append(text)
    def __getattr__(self, name):
        if name.startswith('_'): raise AttributeError(name)
        return lambda *a, **k: self.calls.append(name)
    @property
    def project(self): return self.history.project


def test_damaged_recovery_record_is_reported_once_without_asking(tmp_path):
    from shengao.app import StudioWindow
    window = Window(tmp_path); window.recovery_path().write_text('{"project": {', encoding='utf-8')
    with mock.patch('shengao.app.QMessageBox.question') as question:
        StudioWindow.offer_recovery(window); StudioWindow.offer_recovery(window)
    question.assert_not_called()
    assert len(window.messages) == 1 and '无法读取' in window.messages[0] and '不会再提示' in window.messages[0]
    assert len(list(tmp_path.glob('desktop-recovery.damaged-*.json'))) == 1


# ------------------------------------------------------------------ damaged project file

def damaged_project(tmp_path, record=True):
    from shengao.project import save_project
    from shengao.version_history import VersionHistory
    project = sample_project(tmp_path/'作品'); path = tmp_path/'作品'/'演练.sgproj'; save_project(project, path)
    if record: VersionHistory(tmp_path/'home'/'version-history', project.uid).record(project.to_dict(), 'save', path=str(path))
    data = path.read_bytes(); path.write_bytes(data[:len(data)//3])
    return project, path, path.read_bytes()


def test_find_for_path_matches_only_that_file(tmp_path):
    from shengao.version_history import VersionHistory, find_for_path
    project, path, _ = damaged_project(tmp_path)
    root = tmp_path/'home'/'version-history'
    other = sample_project(tmp_path/'别的'); other.uid = 'other-project'
    VersionHistory(root, other.uid).record(other.to_dict(), 'save', path=str(tmp_path/'别的.sgproj'))
    found = find_for_path(root, path)
    assert [h.uid for h, _ in found] == [project.uid]
    (root/project.uid.replace('/', '_')/'index.json').write_text('{', encoding='utf-8')
    assert [h.uid for h, _ in find_for_path(root, path)] == [project.uid]
    assert find_for_path(tmp_path/'none', path) == []


def test_damaged_project_opens_its_checkpoint_as_unsaved_work(tmp_path):
    from PySide6.QtWidgets import QMessageBox
    from shengao.version_history_dialog import VersionWorkflow
    from shengao.project import load_project
    project, path, damaged = damaged_project(tmp_path)
    try: load_project(path)
    except ValueError as error: problem = error
    window = Window(tmp_path/'home'); window.path = path
    with mock.patch('shengao.version_history_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes) as question:
        assert VersionWorkflow.open_damaged_project(window, path, problem)
    assert '无法读取' in question.call_args.args[2] and '1 句' in question.call_args.args[2]
    assert window.path is None and window.history.project.title == '演练作品' and window.history.saved == {}
    assert 'load_media' in window.calls and '未改动' in window.messages[-1]
    assert path.read_bytes() == damaged


def test_damaged_project_without_checkpoint_or_when_declined_is_left_alone(tmp_path):
    from PySide6.QtWidgets import QMessageBox
    from shengao.version_history_dialog import VersionWorkflow
    _, path, damaged = damaged_project(tmp_path, record=False)
    window = Window(tmp_path/'home')
    with mock.patch('shengao.version_history_dialog.QMessageBox.question') as question:
        assert not VersionWorkflow.open_damaged_project(window, path, ValueError('x'))
        assert not VersionWorkflow.open_damaged_project(window, tmp_path/'歌.lrc', ValueError('x'))
    question.assert_not_called()
    _, path, damaged = damaged_project(tmp_path/'second')
    window = Window(tmp_path/'second'/'home')
    with mock.patch('shengao.version_history_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        assert not VersionWorkflow.open_damaged_project(window, path, ValueError('x'))
    assert 'history' not in vars(window) and window.calls == [] and path.read_bytes() == damaged


def test_open_failure_says_why_and_that_the_file_was_not_changed(tmp_path):
    from shengao.app import StudioWindow
    _, path, damaged = damaged_project(tmp_path, record=False)
    window = Window(tmp_path/'home'); window.open_damaged_project = lambda path, error: False
    assert not StudioWindow.open_path(window, path, guard=False)
    assert window.messages[-1].startswith('打开失败：文件内容不完整或已损坏') and window.messages[-1].endswith('；原文件未改动。')
    assert not StudioWindow.open_path(window, tmp_path/'不存在.sgproj', guard=False)
    assert window.messages[-1] == '打开失败：文件或文件夹不存在，可能已被移动、改名或删除。'


# ------------------------------------------------------------------ whole-file copies

def test_copy_whole_keeps_the_old_file_when_the_check_fails(tmp_path):
    from shengao.project import copy_whole, _font_check
    source = tmp_path/'new.ttf'; source.write_bytes(b'new font'); dest = tmp_path/'aaaaaaaaaaaa.ttf'; dest.write_bytes(b'old font')
    with pytest.raises(ValueError, match='发生变化'): copy_whole(source, dest, _font_check(dest.stem))
    assert dest.read_bytes() == b'old font' and sorted(p.name for p in tmp_path.iterdir()) == ['aaaaaaaaaaaa.ttf', 'new.ttf']
    import hashlib
    good = tmp_path/(hashlib.sha256(b'new font').hexdigest()[:12]+'.ttf')
    copy_whole(source, good, _font_check(good.stem))
    assert good.read_bytes() == b'new font' and not list(tmp_path.glob('*.copying'))


def test_save_on_full_disk_keeps_the_file_and_the_window_contents(tmp_path):
    from shengao.app import StudioWindow
    from shengao.project import History, save_project
    project = sample_project(tmp_path/'作品'); path = tmp_path/'作品'/'演练.sgproj'; save_project(project, path); before = path.read_bytes()
    project.title = '没能保存的修改'
    window = Window(tmp_path/'home'); window.path = path; window.history = History(project); window.flush_edits = lambda: True
    with mock.patch.object(os, 'fsync', side_effect=OSError(errno.ENOSPC, 'full')):
        assert not StudioWindow.save(window)
    assert window.messages[-1] == '保存失败：磁盘空间不足，请清理出空间后重试；原工程文件未改动。当前修改仍在窗口中，可另存到其他位置。'
    assert path.read_bytes() == before and window.history.project.title == '没能保存的修改' and 'record_version' not in window.calls
