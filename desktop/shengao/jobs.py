"""Nonblocking local tasks; signals are delivered on the Qt GUI thread."""
import threading
import traceback
from PySide6.QtCore import QObject,Signal,QRunnable,QThreadPool
from shiboken6 import isValid

class Signals(QObject):
    done=Signal(object)
    failed=Signal(str)
    progress=Signal(object)

class Work(QRunnable):
    def __init__(self,fn):
        super().__init__();self.fn=fn;self.signals=Signals();self.cancel=threading.Event()
    def run(self):
        try:value=self.fn(self.cancel,lambda value:self.emit('progress',value))
        except Exception as error:self.emit('failed',str(error))
        else:self.emit('done',value)
    def emit(self,name,value):
        if isValid(self.signals):
            try:getattr(self.signals,name).emit(value)
            except RuntimeError:
                if isValid(self.signals):raise

def run(fn,done,failed,progress=None):
    work=Work(fn);work.signals.done.connect(done);work.signals.failed.connect(failed)
    if progress:work.signals.progress.connect(progress)
    QThreadPool.globalInstance().start(work);return work
