"""Verify the frozen Qt binding's GIL behaviour, before any media tasks."""
import json
import threading
import time
import PySide6
from PySide6.QtCore import QThread,QTimer,qVersion
from PySide6.QtWidgets import QDialog
from PySide6.QtMultimedia import QMediaPlayer
from .native_slots import invoke_native_slot


def exercise(app,out,check):
    dialog=QDialog();gate=threading.Event();progress=threading.Event();observed=[];binding_calls=[]
    def binding():binding_calls.append(True);raise AssertionError('Unexpected ordinary binding call')
    def work():gate.wait();time.sleep(.03);progress.set()
    worker=threading.Thread(target=work);worker.start()
    def end():observed.append(progress.is_set() and QThread.currentThread()==dialog.thread());dialog.accept()
    QTimer.singleShot(250,end);gate.set()
    try:invoke_native_slot(dialog,'exec')
    finally:worker.join(2);dialog.deleteLater();app.processEvents()
    player=QMediaPlayer();player.stop=binding
    try:invoke_native_slot(player,'stop')
    finally:player.deleteLater();app.processEvents()
    passed=observed==[True] and not binding_calls and not worker.is_alive()
    (out/'native-slot-audit.json').write_text(json.dumps({'passed':passed,'pyside':PySide6.__version__,'qt':qVersion(),
        'python_worker_finished_before_native_slot_returned':observed==[True],'ordinary_binding_bypassed':not binding_calls,
        'scope':'Public synchronous meta-call stays on receiver thread and releases GIL; actual media stop paths run separately.'},indent=2),encoding='utf-8')
    check('native_controls_release_gil_inside_actual_cpp_slot',passed)
