"""Batch rendering: tasks run one after another, each with its own progress,
cancel and result record.

A task keeps its own project snapshot and options from the moment it was
added, so editing while the queue runs never changes a waiting video.  Every
state change is written to ``desktop-renders/<task id>.json``; a task is
written as running before the encoder starts, so a crash or forced quit
leaves a record that the next start turns into "未完成" (``RenderRecords.
recover``) and the unfinished temporary folder is removed.  Only an output
that the encoder verified and published is recorded as completed.
"""
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

STATES = {'waiting': '等待', 'running': '压制中', 'cancelling': '正在取消', 'completed': '完成', 'failed': '失败',
          'cancelled': '已取消', 'interrupted': '未完成', 'unverified': '待检查'}
FINISHED = {'completed', 'failed', 'cancelled', 'interrupted', 'unverified'}
STAGE_PREFIX = '.shengao-render-'


@dataclass
class RenderTask:
    project: object
    options: object
    label: str
    kind: str = 'full'
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = 'waiting'
    ratio: float = 0.
    remaining: object = None
    message: str = ''
    result: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    started: float = 0.
    finished: float = 0.
    stage: str = ''
    job: object = None

    @property
    def done(self): return self.state in FINISHED

    def line(self):
        name = Path(self.options.output).name
        text = f'[{STATES[self.state]}] {self.label} → {name}'
        if self.state == 'running':
            text += f' · {self.ratio:.0%}' + (f' · 预计剩余 {self.remaining:.0f} 秒' if self.remaining is not None else '')
        elif self.state in {'failed', 'interrupted', 'unverified'} and self.message:
            text += ' · ' + self.message.splitlines()[0][:80]
        return text

    def record(self):
        o = self.options
        value = {'kind': 'encode', 'id': self.id, 'state': self.state, 'created': self.created, 'started': self.started,
                 'finished': self.finished, 'title': self.project.title, 'label': self.label, 'sample': self.kind == 'sample',
                 'output': str(Path(o.output)), 'media': self.project.media, 'media_role': self.project.media_role,
                 'start': o.start, 'duration': o.duration, 'size': o.size, 'quality': o.quality, 'encoder': o.encoder,
                 'message': self.message}
        if self.state in {'running', 'cancelling'}: value.update(pid=os.getpid(), stage=self.stage)
        value.update({k: v for k, v in self.result.items() if k not in value or k in {'output', 'media', 'media_role'}})
        return value


class RenderQueue:
    """``start(task, done, failed, progress)`` launches one encode and returns a
    job whose ``cancel`` is a threading.Event.  Callbacks arrive on the caller's
    (GUI) thread; ``progress`` values may carry ``stage`` (the temporary folder)."""
    def __init__(self, start, records=None, changed=lambda task: None):
        self.start = start; self.records = records; self.changed = changed; self.tasks = []

    @property
    def running(self): return next((t for t in self.tasks if t.state in {'running', 'cancelling'}), None)

    @property
    def busy(self): return any(not t.done for t in self.tasks)

    def waiting(self): return [t for t in self.tasks if t.state == 'waiting']

    def find(self, task_id): return next((t for t in self.tasks if t.id == task_id), None)

    def add(self, project, options, label, kind='full'):
        task = RenderTask(project, options, label, kind)
        self.tasks.append(task); self._write(task); self.changed(task); self.pump()
        return task

    def pump(self):
        if self.running is not None: return None
        task = next(iter(self.waiting()), None)
        if task is None: return None
        task.state = 'running'; task.started = time.time(); task.ratio = 0.; task.remaining = None
        self._write(task); self.changed(task)
        try:
            task.job = self.start(task, lambda result, t=task: self._finish(t, 'completed', result=result),
                                  lambda message, t=task: self._finish(t, 'failed', message),
                                  lambda value, t=task: self._progress(t, value))
        except Exception as error:   # the encoder could not even start
            self._finish(task, 'failed', str(error))
        return task

    def _progress(self, task, value):
        if task.done or not isinstance(value, dict): return
        if value.get('stage'):
            task.stage = str(value['stage']); self._write(task)
        if 'ratio' in value:
            task.ratio = min(1., max(0., float(value['ratio']))); task.remaining = value.get('remaining')
        self.changed(task)

    def _finish(self, task, state, message='', result=None):
        if task.done: return
        if state == 'failed' and task.state == 'cancelling': state = 'cancelled'
        if state == 'cancelled' and not message: message = '已取消，未生成成品'
        task.state = state; task.message = message; task.result = dict(result or {}); task.finished = time.time(); task.job = None
        if state == 'completed': task.ratio = 1.; task.remaining = 0
        self._write(task); self.changed(task); self.pump()

    def cancel(self, task_id):
        task = self.find(task_id)
        if task is None or task.done: return False
        if task.state == 'waiting':
            self._finish(task, 'cancelled', '还没开始就已取消')
            return True
        if task.state == 'running':
            task.state = 'cancelling'
            if task.job is not None: task.job.cancel.set()
            self._write(task); self.changed(task)
        return True

    def cancel_all(self):
        for task in list(self.tasks):
            if task.state == 'waiting': self._finish(task, 'cancelled', '还没开始就已取消')
        if self.running is not None: self.cancel(self.running.id)

    def clear_finished(self):
        before = len(self.tasks); self.tasks = [t for t in self.tasks if not t.done]
        return before - len(self.tasks)

    def counts(self):
        result = {}
        for task in self.tasks: result[task.state] = result.get(task.state, 0) + 1
        return result

    def summary(self):
        counts = self.counts()
        return '，'.join(f'{STATES[k]} {v} 个' for k, v in counts.items()) if counts else '队列为空'

    def _write(self, task):
        if self.records is None: return
        try: self.records.write(task)
        except OSError: task.message = task.message or '任务记录无法保存，请记下输出位置'


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0: return False
    if pid == os.getpid(): return True
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle: return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally: kernel.CloseHandle(handle)
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    except PermissionError: return True
    except OSError: return False
    return True


def remove_stage(path):
    """Delete one unfinished encoder folder; never anything else."""
    path = Path(path) if path else None
    if path is None or not path.name.startswith(STAGE_PREFIX) or not path.is_dir() or path.is_symlink(): return False
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


# Files recover() has already inspected in this process; a second call must not
# re-report them (recovery is a one-shot per session).
_RECOVERED_FILES = set()


class RenderRecords:
    def __init__(self, home): self.root = Path(home) / 'desktop-renders'

    def write(self, task):
        from studio_backend.settings import atomic_json
        atomic_json(self.root / f'{task.id}.json', task.record())

    def recover(self, alive=pid_alive):
        """Records still marked running by a session that is gone: mark them
        unfinished, remove their temporary folder, and never call them done."""
        from studio_backend.settings import atomic_json
        result = []
        for file in sorted(self.root.glob('*.json')) if self.root.is_dir() else []:
            try: value = json.loads(file.read_text(encoding='utf-8'))
            except (OSError, ValueError): continue
            if os.path.normcase(str(file.resolve())) in _RECOVERED_FILES: continue
            if not isinstance(value, dict) or value.get('state') not in {'running', 'cancelling'} or alive(value.get('pid')):
                _RECOVERED_FILES.add(os.path.normcase(str(file.resolve())))
                continue
            removed = remove_stage(value.get('stage'))
            if not value.get('stage'):
                # The crash came before the folder was recorded: look beside the output.
                folder = Path(value.get('output', '')).parent if value.get('output') else None
                started = float(value.get('started') or value.get('created') or 0)
                for stage in folder.glob(STAGE_PREFIX + '*') if folder and folder.is_dir() else []:
                    try: fresh = stage.stat().st_mtime >= started - 2
                    except OSError: continue
                    if fresh: removed = remove_stage(stage) or removed
            output = Path(value['output']) if value.get('output') else None
            started = float(value.get('started') or value.get('created') or 0)
            try: written = bool(output and output.is_file() and output.stat().st_mtime >= started)
            except OSError: written = False
            if written:
                value['state'] = 'unverified'
                value['message'] = '上次压制在记录结果前中断，成品文件存在但未确认完整，请播放检查后再使用。'
            else:
                value['state'] = 'interrupted'
                value['message'] = '上次压制没有完成（软件被关闭或意外退出），没有生成成品。' + ('已清理残留的临时文件。' if removed else '')
            value['finished'] = time.time(); value.pop('pid', None)
            try: atomic_json(file, value)
            except OSError: continue
            _RECOVERED_FILES.add(os.path.normcase(str(file.resolve())))
            result.append(value)
        return result


def history_text(value):
    """One line for the task history list, from a saved record."""
    value = value if isinstance(value, dict) else {}
    state = value.get('state', '')
    kind = '视频样片' if value.get('sample') else '视频压制'
    text = f'{kind} · {STATES.get(state, state or "未知")}'
    output = str(value.get('output') or '')
    if state == 'completed':
        return text + (' · ' + output if output else '')
    if output: text += ' · ' + Path(output).name
    message = str(value.get('message') or '').strip()
    if message: text += ' · ' + message.splitlines()[0][:80]
    return text
