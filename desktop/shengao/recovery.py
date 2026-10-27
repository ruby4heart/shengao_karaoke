"""Owned recovery snapshots, serialized off the GUI thread.

Only the GUI calls the public methods. A worker receives detached document
data and may publish only while its generation is current. Invalidation and
the final rename share a short lock; disk writes and retry waits do not.
"""
from pathlib import Path
import os,threading,uuid
from studio_backend.settings import atomic_json
from . import jobs
from .checkpoint_encoding import dumps as checkpoint_dumps


class RecoveryWriter:
    def __init__(self,path,on_error):
        self.path=Path(path);self.on_error=on_error;self._lock=threading.Lock()
        self._generation=0;self._closed=False;self._pending=None;self.active=None

    @property
    def idle(self):return self.active is None and self._pending is None

    def _invalidate(self,*,close=False,clear=False):
        self._pending=None
        with self._lock:
            self._generation+=1
            if close:self._closed=True
            if self.active is not None:self.active.cancel.set()
            if clear:self.path.unlink(missing_ok=True)
            return self._generation

    def clear(self):self._invalidate(clear=True)

    def close(self):self._invalidate(close=True)

    def write_now(self,owned):
        if self._closed:raise RuntimeError('自动恢复已关闭')
        self._invalidate();atomic_json(self.path,owned,compact=True)

    def queue_owned(self,owned):
        """Detached data may have other read-only readers; none may mutate it."""
        if self._closed:return False
        generation=self._invalidate();self._pending=(generation,owned);self._start_pending();return True

    def _start_pending(self):
        if self._closed or self.active is not None or self._pending is None:return
        generation,owned=self._pending;self._pending=None
        holder=[owned];del owned
        def work(cancel,progress):
            # Consume the payload here rather than retaining a full document
            # in Work.fn until its completion is dispatched on the GUI thread.
            value=holder.pop()
            return self._write(generation,value,cancel)
        self.active=jobs.run(work,
            lambda result:self._finished(generation),lambda error:self._finished(generation,error))

    def _finished(self,generation,error=None):
        self.active=None
        with self._lock:current=not self._closed and generation==self._generation
        if current and error:self.on_error(error)
        self._start_pending()

    def _write(self,generation,owned,cancel):
        prepared=self.path.with_name(self.path.stem+'.prepare-'+uuid.uuid4().hex+self.path.suffix)
        try:
            with self._lock:
                if self._closed or generation!=self._generation or cancel.is_set():return False
            atomic_json(prepared,owned,compact=True,dumps=checkpoint_dumps)
            for attempt in range(8):
                try:
                    with self._lock:
                        if self._closed or generation!=self._generation or cancel.is_set():return False
                        os.replace(prepared,self.path);return True
                except PermissionError:
                    if os.name!='nt' or attempt==7:raise
                    if cancel.wait(min(.01*2**attempt,.08)):return False
        finally:
            # This uniquely named staging file belongs to this worker only.
            try:prepared.unlink(missing_ok=True)
            except OSError:pass
