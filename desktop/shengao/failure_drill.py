"""Failure drills: damaged files, moved paths, full disks, forced exits, interrupted renders, failed model processes.

Toolkit independent and safe to run on the person's computer: every drill
works on copies inside its own temporary folder and never touches real
projects, settings or caches. A full disk is simulated by making the next
write fail with the operating system's own "disk full" error; a forced exit
runs a separate Python process that dies at the worst moment.

Each drill checks the same three things: the person's original file is
unchanged, work that can continue is recognised as such, and unfinished
output is never presented as finished. ``run()`` returns one record per
drill; ``scripts/run-failure-drills.py`` prints them and writes a report.
"""
from contextlib import contextmanager
from pathlib import Path
import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT/'demo'/'tutorial.json'
DRILLS = []


class Skip(Exception):
    """The drill cannot run in this environment; it is reported, not counted as passed."""


def drill(group, title):
    def register(fn):
        DRILLS.append((group, title, fn)); return fn
    return register


def disk_full():
    return OSError(errno.ENOSPC, '磁盘空间不足（演练）')


def sample_project(folder):
    """A small project with its own audio file and font copy inside folder."""
    from .project import load_project, MediaVersion, file_stamp
    folder = Path(folder); (folder/'素材').mkdir(parents=True, exist_ok=True)
    media = folder/'素材'/'练习.wav'; shutil.copy2(ROOT/'demo'/'demo.wav', media)
    project = load_project(DEMO)
    project.title = '演练作品'; project.media = str(media); project.media_role = 'original'
    project.media_versions = {'original': MediaVersion(str(media))}; project.media_stamp = file_stamp(media)
    project.duration = 8000; project.has_video = False
    return project


def files(folder, pattern='*'):
    return sorted(p.name for p in Path(folder).rglob(pattern) if p.is_file())


def python_ready():
    """Forced-exit drills need a plain Python interpreter, not the packaged app."""
    if getattr(sys, 'frozen', False): raise Skip('打包版没有独立的 Python，强制退出演练请在开发环境运行')


def child(code, *args):
    """Run code in a fresh interpreter that can import the app; returns the exit code."""
    python_ready()
    path = os.pathsep.join([str(ROOT/'desktop'), str(ROOT/'backend')])
    environment = {**os.environ, 'PYTHONPATH': path + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')}
    result = subprocess.run([sys.executable, '-c', code, *map(str, args)], env=environment, capture_output=True, timeout=60,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.returncode, result.stderr.decode('utf-8', errors='replace')


# ------------------------------------------------------------------ damaged files

@drill('文件损坏', '工程文件损坏：原文件不动，可从本机版本记录打开')
def damaged_project(base):
    from .project import save_project, load_project, Project
    from .version_history import VersionHistory, find_for_path
    from .damage import reason
    home = base/'home'; project = sample_project(base/'作品'); path = base/'作品'/'演练.sgproj'
    save_project(project, path)
    VersionHistory(home/'version-history', project.uid).record(project.to_dict(), 'save', path=str(path))
    data = path.read_bytes(); path.write_bytes(data[:len(data)//2]); damaged = path.read_bytes()
    try: load_project(path)
    except ValueError as error: message = reason(error)
    else: raise AssertionError('损坏的工程居然能打开')
    assert '损坏' in message or '不完整' in message, message
    assert path.read_bytes() == damaged, '读取失败后原文件被改动'
    found = find_for_path(home/'version-history', path)
    assert found, '没有找到这个文件的版本记录'
    history, meta = found[0]; restored = Project.from_dict(history.load(meta['id']), path.parent)
    assert [x.text for x in restored.lines] == [x.text for x in project.lines]
    return f'提示「{message}」；原文件 {len(damaged)} 字节未改动；找到 {len(found)} 条版本记录并能打开'


@drill('文件损坏', '自动恢复记录损坏：另存一份，下次不再提示')
def damaged_recovery(base):
    from .recovery import RecoveryWriter, read_record
    project = sample_project(base/'作品'); path = base/'home'/'desktop-recovery.json'
    RecoveryWriter(path, lambda error: None).write_now({'project': project.to_dict(), 'path': '', 'pending': None, 'drafts': [], 'position': None})
    record, restored, problem, moved = read_record(path)
    assert record is not None and restored.title == project.title and not problem
    path.write_text('{"project": {"uid": "x", "lines": [', encoding='utf-8'); damaged = path.read_bytes()
    record, restored, problem, moved = read_record(path)
    assert record is None and problem and moved is not None, (problem, moved)
    assert moved.read_bytes() == damaged and not path.exists(), '损坏的记录没有原样另存'
    assert read_record(path) == (None, None, '', None), '另存后仍会再次提示'
    return f'提示「{problem}」；原记录另存为 {moved.name}'


@drill('文件损坏', '工作区设置损坏：改用默认设置，原文件另存')
def damaged_preferences(base):
    from .preferences import Preferences
    home = base/'home'; home.mkdir(); path = home/'workspace.json'
    path.write_text('{"recent": [{"path": "C:/作品/歌.sgproj"', encoding='utf-8'); damaged = path.read_bytes()
    preferences = Preferences(home)
    assert preferences.data == {} and preferences.damaged is not None
    assert preferences.damaged.read_bytes() == damaged
    preferences.set('stage', 2)
    assert json.loads(path.read_text(encoding='utf-8')) == {'stage': 2} and preferences.damaged.read_bytes() == damaged
    return f'原文件另存为 {preferences.damaged.name}；新设置可以正常保存'


@drill('文件损坏', '服务设置损坏：说明原因，重新填写后可保存')
def damaged_settings(base):
    from studio_backend.settings import Settings
    home = base/'home'; home.mkdir(); path = home/'settings.json'
    path.write_text('{"elevenlabs": {"secret": "', encoding='utf-8'); damaged = path.read_bytes()
    settings = Settings(home)
    try: settings.public()
    except ValueError as error: message = str(error)
    else: raise AssertionError('损坏的服务设置被当作有效')
    assert '损坏' in message, message
    settings.save('deepseek', model='deepseek-chat')
    assert settings.damaged is not None and settings.damaged.read_bytes() == damaged
    assert settings.public()['deepseek']['model'] == 'deepseek-chat'
    return f'提示「{message}」；原文件另存为 {settings.damaged.name}，重新保存成功'


@drill('文件损坏', '版本记录损坏：索引可重建，坏的检查点不会被打开')
def damaged_checkpoint(base):
    from .version_history import VersionHistory
    project = sample_project(base/'作品'); history = VersionHistory(base/'home'/'version-history', project.uid)
    first = history.record(project.to_dict(), 'save', now=1_800_000_000)
    project.title = '演练作品（第二版）'; second = history.record(project.to_dict(), 'save', now=1_800_000_060)
    history.index_path.write_text('{"entries": [', encoding='utf-8')
    assert [x['id'] for x in history.entries()] == [second['id'], first['id']], '索引损坏后丢了检查点'
    (history.folder/(second['id']+'.json')).write_text('{"meta":', encoding='utf-8')
    try: history.load(second['id'])
    except ValueError as error: message = str(error)
    else: raise AssertionError('损坏的检查点被打开')
    assert history.load(first['id'])['title'] == '演练作品'
    return f'索引损坏后仍列出 2 条；坏检查点提示「{message}」，较早的一条可用'


@drill('文件损坏', '后台任务结果损坏：显示为未完成，不当作可采用的建议')
def damaged_task(base):
    from .damage import read_task
    root = base/'home'/'desktop-tasks'
    def task(name, request, result=None):
        folder = root/name; folder.mkdir(parents=True)
        (folder/'request.json').write_text(request, encoding='utf-8')
        if result is not None: (folder/'result.json').write_text(result, encoding='utf-8')
        return folder
    broken = task('broken-result', json.dumps({'action': 'acoustic'}), '{"ok": true, "suggestions": [')
    request, value = read_task(broken)
    assert request['action'] == 'acoustic' and not value.get('ok') and not value.get('suggestions') and '损坏' in value['message']
    request, value = read_task(task('broken-request', '{"action": "acou'))
    assert request['action'] == 'damaged' and '保留' in value['message']
    request, value = read_task(task('no-result', json.dumps({'action': 'line_tails'})))
    assert not value.get('ok') and '没有最终结果' in value['message']
    assert read_task(task('configure', '{}').parent/'missing') is None
    assert broken.is_dir() and (broken/'result.json').is_file(), '任务目录被删除'
    return '损坏的结果、损坏的请求和没有结果的任务都显示为未完成，目录保留'


# ------------------------------------------------------------------ moved paths

@drill('路径移动', '整个作品文件夹搬走：素材按相对位置找到')
def moved_folder(base):
    from .project import save_project, load_project
    project = sample_project(base/'旧位置'/'作品'); path = base/'旧位置'/'作品'/'演练.sgproj'
    save_project(project, path); shutil.move(str(base/'旧位置'), str(base/'新位置'))
    moved = load_project(base/'新位置'/'作品'/'演练.sgproj')
    assert Path(moved.media).is_file() and Path(moved.media).parent.parent == (base/'新位置'/'作品').resolve()
    return '搬走后重开，素材路径自动指向新文件夹'


@drill('路径移动', '素材单独移动：按文件名、大小和时间找回')
def moved_media(base):
    from .project import save_project, load_project
    from .media_locate import missing_media, locate
    project = sample_project(base/'作品'); path = base/'作品'/'演练.sgproj'; old = Path(project.media)
    save_project(project, path); (base/'作品'/'整理后').mkdir(); shutil.move(str(old), str(base/'作品'/'整理后'/old.name))
    reopened = load_project(path); missing = missing_media(reopened)
    assert missing, '没有发现素材缺失'
    role, gone, stamp = missing[0]; candidates = locate(gone, stamp, path)
    assert candidates and candidates[0].same_file and Path(candidates[0].path).parent.name == '整理后'
    return f'发现缺失后在「整理后」找到同一文件（大小和时间一致）'


@drill('路径移动', '输出文件夹被移走：压制前拒绝，不留文件')
def moved_output(base):
    from .encode import encode, EncodeOptions
    project = sample_project(base/'作品'); output = base/'已删除的文件夹'/'成品.mp4'
    try: encode(project, EncodeOptions(str(output)))
    except ValueError as error: message = str(error)
    else: raise AssertionError('输出位置不存在却开始压制')
    assert '输出目录不存在' in message and not output.parent.exists()
    return f'提示「{message}」'


# ------------------------------------------------------------------ disk full

@drill('磁盘不足', '保存时磁盘满：上一次保存的工程不变，不留临时文件')
def full_on_save(base):
    from .project import save_project, load_project
    from .damage import reason, disk_full as is_full
    project = sample_project(base/'作品'); path = base/'作品'/'演练.sgproj'; save_project(project, path); before = path.read_bytes()
    project.title = '没能保存的修改'
    with mock.patch.object(os, 'fsync', side_effect=disk_full()):
        try: save_project(project, path)
        except OSError as error: message = reason(error); assert is_full(error)
        else: raise AssertionError('磁盘满时保存却成功了')
    assert path.read_bytes() == before and load_project(path).title == '演练作品'
    assert not [x for x in files(path.parent) if x.endswith('.tmp')], files(path.parent)
    return f'提示「{message}」；原工程未变，没有残留临时文件'


@drill('磁盘不足', '复制字体资源时磁盘满：不留半截字体，工程不变')
def full_on_asset(base):
    from .project import save_project
    project = sample_project(base/'作品'); path = base/'作品'/'演练.sgproj'; save_project(project, path); before = path.read_bytes()
    font = base/'字体'/'演练字体.ttf'; font.parent.mkdir(); font.write_bytes(os.urandom(64*1024))
    project.style.font_file = str(font)
    def partial(source, dest, **kwargs):
        with open(dest, 'wb') as stream: stream.write(Path(source).read_bytes()[:1000])
        raise disk_full()
    with mock.patch.object(shutil, 'copy2', partial):
        try: save_project(project, path)
        except OSError: pass
        else: raise AssertionError('磁盘满时复制字体却成功了')
    assets = path.parent/(path.stem+'.assets')
    assert not (assets.exists() and files(assets)), files(assets)
    assert path.read_bytes() == before
    return '没有留下半截字体或 .copying 文件；原工程未变'


@drill('磁盘不足', '导出字幕时磁盘满：上一次导出的文件不变')
def full_on_export(base):
    from .subtitle_files import export_subtitle
    project = sample_project(base/'作品'); output = base/'导出'/'演练.lrc'; output.parent.mkdir()
    export_subtitle(project, output, 'lrc'); before = output.read_bytes()
    line = project.lines[0]; line.start -= 100; line.end -= 100
    for unit in line.units: unit.start -= 100; unit.end -= 100
    real = os.fdopen
    class Full:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *error): self.stream.close()
        def write(self, text): self.stream.write(text[:10]); raise disk_full()
    with mock.patch.object(os, 'fdopen', lambda fd, *a, **k: Full(real(fd, *a, **k))):
        try: export_subtitle(project, output, 'lrc')
        except OSError: pass
        else: raise AssertionError('磁盘满时导出却成功了')
    assert output.read_bytes() == before and files(output.parent) == ['演练.lrc'], files(output.parent)
    return '上一次导出的字幕未变，没有残留临时文件'


@drill('磁盘不足', '写自动恢复和版本记录时磁盘满：报告失败，旧记录保留')
def full_on_records(base):
    from .recovery import RecoveryWriter, read_record
    from .version_history import VersionHistory
    project = sample_project(base/'作品'); path = base/'home'/'desktop-recovery.json'
    writer = RecoveryWriter(path, lambda error: None)
    writer.write_now({'project': project.to_dict()}); before = path.read_bytes()
    history = VersionHistory(base/'home'/'version-history', project.uid); history.record(project.to_dict(), 'save')
    project.title = '磁盘满时的修改'
    with mock.patch.object(os, 'fsync', side_effect=disk_full()):
        for action in (lambda: writer.write_now({'project': project.to_dict()}), lambda: history.record(project.to_dict(), 'auto')):
            try: action()
            except OSError: pass
            else: raise AssertionError('磁盘满时写入却成功了')
    assert path.read_bytes() == before and read_record(path)[1].title == '演练作品'
    assert len(history.entries()) == 1 and not [x for x in files(base/'home') if x.endswith('.tmp')]
    return '恢复记录仍是上一份，版本记录仍是 1 条，没有残留临时文件'


# ------------------------------------------------------------------ forced exit

DIE_ON_RENAME = '''
import os,sys
from pathlib import Path
os.replace=lambda *a,**k:os._exit(9)
'''


@drill('强制退出', '保存到一半被强制结束：原工程完好，可正常打开')
def exit_during_save(base):
    from .project import save_project, load_project
    project = sample_project(base/'作品'); path = base/'作品'/'演练.sgproj'; save_project(project, path); before = path.read_bytes()
    code, log = child(DIE_ON_RENAME + '''
from shengao.project import load_project,save_project
p=load_project(sys.argv[1]);p.title='强制结束前的修改';save_project(p,sys.argv[1])
''', path)
    assert code != 0, log
    assert path.read_bytes() == before and load_project(path).title == '演练作品'
    leftovers = [x for x in files(path.parent) if x.endswith('.tmp')]
    return f'进程在改名前退出（代码 {code}）；原工程完好' + (f'，留下 {len(leftovers)} 个无害的临时文件' if leftovers else '')


@drill('强制退出', '写自动恢复记录时被强制结束：上一份记录可用，残留文件下次清理')
def exit_during_recovery(base):
    from .recovery import RecoveryWriter, read_record, sweep
    project = sample_project(base/'作品'); path = base/'home'/'desktop-recovery.json'
    RecoveryWriter(path, lambda error: None).write_now({'project': project.to_dict()})
    code, log = child(DIE_ON_RENAME + '''
from shengao.recovery import RecoveryWriter
import threading
w=RecoveryWriter(sys.argv[1],print)
w._write(w._generation,{'project':{'broken':True}},threading.Event())
''', path)
    assert code != 0, log
    leftovers = [x for x in path.parent.iterdir() if x != path]
    assert read_record(path)[1].title == '演练作品'
    assert leftovers and sweep(path) == 0, '刚留下的暂存文件不应立刻删除（可能另一个窗口正在写）'
    removed = sweep(path, now=time.time() + 3600)
    assert [x for x in path.parent.iterdir()] == [path], list(path.parent.iterdir())
    return f'上一份恢复记录可用；{removed} 个残留暂存文件在下次启动时清理'


@drill('强制退出', '压制中被强制结束：标为未完成，清理临时文件，旧成品不动')
def exit_during_render(base):
    from .render_queue import RenderRecords, STAGE_PREFIX
    def case(name, newer):
        home = base/name; out = base/(name+'-输出'); out.mkdir(parents=True)
        output = out/'成品.mp4'; output.write_bytes(b'old render' * 100); old = time.time() - 3600
        os.utime(output, (old, old))
        stage = out/(STAGE_PREFIX+'abc123'); stage.mkdir(); (stage/'encoded.mp4').write_bytes(b'partial')
        started = time.time() - 60
        if newer: output.write_bytes(b'new but unchecked')
        record = {'kind': 'encode', 'id': name, 'state': 'running', 'started': started, 'created': started,
                  'output': str(output), 'pid': 999999, 'stage': str(stage)}
        (home/'desktop-renders').mkdir(parents=True); (home/'desktop-renders'/f'{name}.json').write_text(json.dumps(record), encoding='utf-8')
        found = RenderRecords(home).recover(alive=lambda pid: False)
        return found[0], output, stage
    value, output, stage = case('interrupted', False)
    assert value['state'] == 'interrupted' and not stage.exists() and output.read_bytes() == b'old render' * 100
    unverified, output, stage = case('unverified', True)
    assert unverified['state'] == 'unverified' and not stage.exists() and output.is_file()
    return '旧成品保持原样的记为「未完成」；成品已写出但未确认的记为「待检查」；临时文件夹都已清理'


@drill('强制退出', '付费请求中途退出：不会自动重新提交')
def exit_during_paid(base):
    from studio_backend import paid_requests
    home = base/'home'; key = 'a' * 64; folder = paid_requests.folder(home); folder.mkdir(parents=True)
    (folder/f'{key}.json').write_text(json.dumps({'signature': key, 'state': 'sent', 'action': 'transcribe'}), encoding='utf-8')
    assert paid_requests.pending(home, key)['state'] == 'sent'
    (folder/f'{key}.json').write_text('{"signature": "', encoding='utf-8')
    assert paid_requests.pending(home, key)['state'] == 'unknown'
    message = str(paid_requests.ResubmitRequired(paid_requests.pending(home, key)))
    assert '拦截' in message, message
    return '中断或记录损坏的付费请求都按「可能已计费」处理，需要确认后才会重发'


# ------------------------------------------------------------------ interrupted render

FAKE_ENCODER = r'''
import sys,time
stage=sys.argv[-1]
mode=sys.argv[1]
with open(stage,'wb') as out:out.write(b'\0'*(4096 if mode=='cancel' else 40))
if mode=='fail':sys.stderr.write('Error while encoding (drill)\n');sys.exit(1)
for i in range(600):
    print('out_time_us=%d'%(i*100000),flush=True);time.sleep(.05)
'''


def fake_render(base, mode, cancel_after_progress=False):
    """Run the real encode() with a stand-in encoder process; returns (error message, output, folder)."""
    from . import encode as module
    python_ready()
    project = sample_project(base/'作品'); out = base/'输出'; out.mkdir(); output = out/'成品.mp4'
    output.write_bytes(b'previous good render'); before = output.read_bytes()
    script = base/'fake_encoder.py'; script.write_text(FAKE_ENCODER, encoding='utf-8')
    source = Path(project.media).read_bytes(); cancel = threading.Event(); real = subprocess.Popen
    def popen(command, **kwargs): return real([sys.executable, str(script), mode, *command[1:]], **kwargs)
    def progress(value):
        if cancel_after_progress and isinstance(value, dict) and value.get('ratio', 0) > 0: cancel.set()
    with mock.patch.object(module, 'ffmpeg', lambda: 'ffmpeg'), mock.patch.object(module.subprocess, 'Popen', popen):
        try: module.encode(project, module.EncodeOptions(str(output), duration=4000), cancel, progress)
        except ValueError as error: message = str(error)
        else: raise AssertionError('中断的压制被当作完成')
    assert output.read_bytes() == before, '旧成品被覆盖'
    assert not [x for x in out.iterdir() if x.name.startswith('.shengao-render-')], list(out.iterdir())
    assert Path(project.media).read_bytes() == source
    return message


@drill('压制中断', '压制途中取消：不发布半成品，旧成品和素材不动')
def render_cancelled(base):
    message = fake_render(base, 'cancel', True)
    assert '压制已取消' in message, message
    return f'提示「{message}」；临时文件夹已删除'


@drill('压制中断', '编码器中途失败：不发布半成品，旧成品和素材不动')
def render_failed(base):
    message = fake_render(base, 'fail')
    assert message.startswith('视频压制失败'), message
    return f'提示「{message.splitlines()[0][:40]}…」；临时文件夹已删除'


# ------------------------------------------------------------------ model process failure

@drill('模型进程失败', '对齐模型内存不足退出：说明原因，结果不采用')
def model_memory(base):
    from .vocal_audio import run
    python_ready()
    code = 'import sys;sys.stderr.write("Traceback (most recent call last):\\nMemoryError: Unable to allocate 3.1 GiB\\n");sys.exit(1)'
    try: run([sys.executable, '-c', code], None, kind='alignment')
    except ValueError as error: message = str(error)
    else: raise AssertionError('失败的模型进程被当作成功')
    assert message.startswith('歌声对齐失败：本机内存不足') and '没有采用' in message and 'MemoryError' in message, message
    return f'提示「{message.splitlines()[0][:60]}…」'


@drill('模型进程失败', '人声模型进程崩溃：说明是意外退出，结果不采用')
def model_crash(base):
    from .vocal_audio import run
    python_ready()
    # Windows: the exit code of an access violation (0xC0000005 as a signed int); elsewhere: killed by the system.
    code = ('import os,sys\nif os.name=="nt":os._exit(-1073741819)\nimport signal;os.kill(os.getpid(),signal.SIGKILL)')
    try: run([sys.executable, '-c', code], None, kind='vocals')
    except ValueError as error: message = str(error)
    else: raise AssertionError('崩溃的模型进程被当作成功')
    assert message.startswith('人声处理失败：') and ('意外退出' in message or '被系统终止' in message), message
    return f'提示「{message.splitlines()[0][:60]}…」'


@drill('模型进程失败', '模型文件缺失：说明是运行包不完整')
def model_missing(base):
    from .vocal_audio import run
    python_ready()
    code = 'import sys;sys.stderr.write("FileNotFoundError: [Errno 2] No such file or directory: model.th\\n");sys.exit(2)'
    try: run([sys.executable, '-c', code], None, kind='alignment')
    except ValueError as error: message = str(error)
    else: raise AssertionError('缺模型时被当作成功')
    assert '找不到模型或输入文件' in message, message
    return f'提示「{message.splitlines()[0][:60]}…」'


# ------------------------------------------------------------------ runner

def run(selected=None):
    """Every drill in its own temporary folder; one record each."""
    results = []
    for group, title, fn in DRILLS:
        if selected and fn.__name__ not in selected: continue
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='shengao-drill-') as folder:
            try: detail = fn(Path(folder)); state = 'passed'
            except Skip as error: detail = str(error); state = 'skipped'
            except Exception as error:
                import traceback
                detail = f'{type(error).__name__}: {error}\n' + traceback.format_exc()[-1500:]; state = 'failed'
        results.append({'group': group, 'title': title, 'name': fn.__name__, 'state': state, 'detail': detail,
                        'seconds': round(time.monotonic() - started, 2)})
    return results
