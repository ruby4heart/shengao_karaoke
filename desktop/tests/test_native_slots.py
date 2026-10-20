"""A native blocking slot must not prevent a Python worker from finishing."""
import threading
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog
from shengao.native_slots import invoke_native_slot


def test_native_slot_releases_gil_during_the_synchronous_call(qapp):
    dialog=QDialog();gate=threading.Event();progress=threading.Event();observed=[]
    def work():gate.wait();time.sleep(.03);progress.set()
    worker=threading.Thread(target=work);worker.start()
    def end():observed.append(progress.is_set());dialog.accept()
    QTimer.singleShot(250,end);gate.set()
    try:
        invoke_native_slot(dialog,'exec')
        # Observation happens inside the C++ event loop, before the call
        # returns; checking afterwards could hide a worker blocked on GIL.
        assert observed==[True]
    finally:worker.join(2);dialog.deleteLater();qapp.processEvents()


def test_native_slot_rejects_foreign_thread_before_touching_player(qapp):
    dialog=QDialog();errors=[]
    def work():
        try:invoke_native_slot(dialog,'reject')
        except RuntimeError as error:errors.append(str(error))
    worker=threading.Thread(target=work);worker.start();worker.join(2)
    assert not worker.is_alive() and len(errors)==1 and '界面线程' in errors[0]
    dialog.deleteLater();qapp.processEvents()


def test_media_stop_uses_native_slot_instead_of_the_ordinary_binding(qapp,monkeypatch):
    from PySide6.QtMultimedia import QMediaPlayer
    player=QMediaPlayer()
    def binding():raise AssertionError('Ordinary stop binding entered')
    monkeypatch.setattr(player,'stop',binding)
    invoke_native_slot(player,'stop')
    assert player.playbackState()==QMediaPlayer.PlaybackState.StoppedState
    player.deleteLater();qapp.processEvents()
