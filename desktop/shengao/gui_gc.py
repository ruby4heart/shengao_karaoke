"""Keep CPython's full collection away from editing gestures.

Generation 0/1 remain automatic. Full collections run on the GUI thread when
idle, with a bounded wait during continuous activity. Applies to bundled 3.12;
future Python GC generations must be reviewed before enabling this policy.
"""
from collections import deque
import gc,sys,time
from PySide6.QtCore import QObject,QEvent,QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

_INPUT_EVENTS=frozenset((QEvent.Type.KeyPress,QEvent.Type.KeyRelease,QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonRelease,QEvent.Type.MouseMove,QEvent.Type.Wheel,QEvent.Type.InputMethod,QEvent.Type.TouchBegin,QEvent.Type.TouchUpdate,QEvent.Type.Drop))


class GuiGcPolicy(QObject):
    def __init__(self,app,*,clock=None,collector=None,counter=None,dragging=None):
        super().__init__(app);self.app=app;self.clock=clock or time.monotonic;self.collector=collector or gc.collect;self.counter=counter or gc.get_count
        self.dragging=dragging or (lambda:QApplication.mouseButtons()!=Qt.MouseButton.NoButton)
        self.previous=gc.get_threshold();self.threshold=(*self.previous[:2],1_000_000_000);self.closed=False;self.running=False;self.in_collection=0
        self.last_activity=self.last_full=self.clock();self.records=deque(maxlen=256)
        gc.set_threshold(*self.threshold);gc.callbacks.append(self.collection_phase)
        self.app.installEventFilter(self);self.app.aboutToQuit.connect(self.close)
        self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.maybe_collect);self.timer.start()

    def collection_phase(self,phase,info):
        self.in_collection=max(0,self.in_collection+(1 if phase=='start' else -1))

    def activity(self):self.last_activity=self.clock()

    def eventFilter(self,obj,event):
        if event.type() in _INPUT_EVENTS:self.activity()
        return False

    def maybe_collect(self):
        if self.closed or self.running or self.in_collection or not gc.isenabled() or self.dragging():return
        now=self.clock()
        if self.counter()[2]<self.previous[2]:return
        forced=now-self.last_full>=60
        if not forced and now-self.last_activity<1:return
        self.running=True;began=time.perf_counter()
        try:
            collected=self.collector(2);self.last_full=self.clock()
            self.records.append({'duration_ms':(time.perf_counter()-began)*1000,'collected':collected,'forced_after_60s':forced})
        finally:self.running=False

    def report(self):
        return {'python':sys.version.split()[0],'automatic_generations':[0,1],'original_thresholds':self.previous,'active_thresholds':gc.get_threshold(),'full_idle_after_ms':1000,'full_max_wait_seconds':60,'held_mouse_defers_full_collection':True,'collections':list(self.records),'automatic_gc_enabled':gc.isenabled()}

    def close(self):
        if self.closed:return
        self.closed=True;self.timer.stop();self.app.removeEventFilter(self)
        try:gc.callbacks.remove(self.collection_phase)
        except ValueError:pass
        if gc.get_threshold()==self.threshold:gc.set_threshold(*self.previous)


def install(app):
    if sys.implementation.name!='cpython' or sys.version_info[:2]!=(3,12):return None
    policy=getattr(app,'_shengao_gc_policy',None)
    if policy is None or policy.closed:policy=GuiGcPolicy(app);app._shengao_gc_policy=policy
    return policy


def activity():
    app=QApplication.instance();policy=getattr(app,'_shengao_gc_policy',None) if app is not None else None
    if policy is not None and not policy.closed:policy.activity()
