"""Synchronous GUI-thread Qt calls that release the Python GIL while waiting.

PySide6 6.12 marks QMetaObject.invokeMethod as allow-thread. QMediaPlayer's
ordinary stop binding does not: a Qt disconnect/destruction mutex can then
wait for a worker that needs the GIL for Shiboken's virtual notification.
"""
from PySide6.QtCore import QMetaObject,QThread,Qt


def invoke_native_slot(receiver,name):
    if QThread.currentThread()!=receiver.thread():
        raise RuntimeError('播放控制必须在界面线程执行')
    if not QMetaObject.invokeMethod(receiver,name,Qt.ConnectionType.DirectConnection):
        raise RuntimeError('无法完成播放控制：'+name)
