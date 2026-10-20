"""Cancelable process isolation for the already-tested transcription backend."""
from pathlib import Path
import json
import os
import sys
import uuid
import shutil
from PySide6.QtCore import QObject,QProcess,QTimer,Signal
from studio_backend.settings import default_home,atomic_json

class ApiJob(QObject):
    progress=Signal(str)
    completed=Signal(dict)
    failed=Signal(str)
    changed=Signal()
    workflowChanged=Signal(dict)
    def __init__(self,parent=None,home=None):
        super().__init__(parent);self.home=Path(home) if home else default_home();self.process=None
        self.folder=None;self.result=None;self.request={};self.stopping=False
        self.child_job=None;self.start_error=''
        self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.poll)

    @property
    def busy(self):return self.process is not None

    def start(self,request):
        if self.busy:raise ValueError('已有任务正在执行，请等待或取消')
        self.folder=self.home/'desktop-tasks'/uuid.uuid4().hex;self.folder.mkdir(parents=True)
        self.result=self.folder/'result.json';self.request=request;self.stopping=False;self.start_error=''
        # Config keys are stdin only. No key or environment snapshot is persisted.
        if request.get('action')!='configure':atomic_json(self.folder/'request.json',request)
        args=['--worker','--request','-','--result',str(self.result),'--home',str(self.home)]
        if sys.platform=='win32':
            try:
                from .process_tree import ProcessTree
                self.child_job=ProcessTree();args+=['--owner-job',self.child_job.name]
            except OSError:self.failed.emit('无法建立后台进程管理，尚未发送请求。');return
        if not getattr(sys,'frozen',False):args=[str(Path(__file__).resolve().parents[1]/'main.py')]+args
        process=QProcess(self);self.process=process;process.setProgram(sys.executable);process.setArguments(args)
        process.finished.connect(self.finish)
        process.errorOccurred.connect(self.error)
        process.started.connect(lambda:self.send(request))
        process.start();self.timer.start();self.changed.emit()

    def send(self,request):
        if sys.platform=='win32':
            try:
                self.child_job.assign(self.process.processId())
            except OSError:
                self.start_error='无法建立后台进程管理，尚未发送请求；请检查本机进程权限后重试。'
                if self.child_job:self.child_job.close();self.child_job=None
                self.process.kill();return
        self.process.write(json.dumps(request,ensure_ascii=False).encode());self.process.closeWriteChannel()

    def poll(self):
        if self.result:
            progress=Path(str(self.result)+'.progress.json')
            if progress.is_file():
                try:self.progress.emit(json.loads(progress.read_text(encoding='utf-8')).get('message',''))
                except (OSError,ValueError):pass
        if self.request.get('action')=='draft':
            try:
                from studio_backend.draft import load_summary
                self.workflowChanged.emit(load_summary(self.home,self.request['workflow_id']))
            except (OSError,ValueError,KeyError,TypeError):pass

    def finish(self,code,status):
        if not self.process:return
        process=self.process;self.process=None;self.timer.stop()
        if self.child_job:self.child_job.close();self.child_job=None
        if self.folder:
            folder=self.folder.resolve();base=(self.home/'desktop-tasks').resolve();work=folder/'acoustic-work'
            if folder.is_relative_to(base) and folder!=base and work.resolve().parent==folder and not work.is_symlink():
                try:shutil.rmtree(work)
                except OSError:pass
        # Never display raw stderr, which could come from a third-party HTTP library.
        process.readAllStandardError();process.deleteLater()
        try:
            if self.start_error:self.failed.emit(self.start_error);return
            recovery={}
            if self.request.get('action')=='draft':
                from studio_backend.draft import mark_stopped,saved_result
                try:mark_stopped(self.home,self.request['workflow_id'])
                except (OSError,ValueError,KeyError,TypeError):pass
                recovery=saved_result(self.request,self.home);self.poll()
            if self.result and self.result.exists():
                try:data=json.loads(self.result.read_text(encoding='utf-8'))
                except (OSError,ValueError):self.failed.emit('后台结果文件不完整，请查看任务记录');return
                if data.get('ok'):self.completed.emit(data)
                else:self.failed.emit(data.get('message','后台任务未完成'))
            elif recovery:self.completed.emit({'ok':True,**recovery})
            else:self.failed.emit('后台进程结束但未返回结果；任务目录保留，可从任务记录检查')
        finally:self.changed.emit()

    def error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            if self.child_job:self.child_job.close();self.child_job=None
            self.timer.stop();self.process=None;self.changed.emit();self.failed.emit('无法启动后台进程，请检查完整运行包')

    def cancel(self):
        if self.busy:
            Path(str(self.result)+'.cancel').touch();self.stopping=True;self.progress.emit('正在取消；已经提交的云端任务可能仍由服务端处理')

    def abandon(self):
        self.cancel()
        process=self.process
        if process:
            if self.child_job:
                try:self.child_job.terminate()
                except OSError:self.child_job.close();self.child_job=None
            process.kill();process.waitForFinished(3000)
