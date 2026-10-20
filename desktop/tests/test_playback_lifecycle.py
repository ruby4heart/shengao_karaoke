import time
from PySide6.QtCore import QThread
from PySide6.QtGui import QImage,QColor
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtTest import QTest
from shengao.playback import Playback


def ready(qapp,playback):
    deadline=time.monotonic()+10
    while not playback.player.duration() and time.monotonic()<deadline:
        qapp.processEvents();QTest.qWait(10)
    assert playback.player.duration()>0


def test_frame_delivery_exits_emitter_and_runs_on_gui_thread(qapp,video,monkeypatch):
    p=Playback();p.audio.setMuted(True);p.open(video);ready(qapp,p)
    calls=[];monkeypatch.setattr(p.canvas,'video_frame',lambda frame:calls.append(QThread.currentThread()))
    frame=QVideoFrame(QImage(16,16,QImage.Format.Format_RGB32))
    p.sink.videoFrameChanged.emit(frame)
    assert calls==[], 'Decoder signals must not map images or pause the player inline'
    qapp.processEvents();assert calls and all(thread==qapp.thread() for thread in calls)
    calls.clear()
    class EmitFromDecoder(QThread):
        def run(self):p.sink.videoFrameChanged.emit(frame)
    worker=EmitFromDecoder();worker.start();assert worker.wait(3000)
    assert calls==[]
    qapp.processEvents();assert calls and all(thread==qapp.thread() for thread in calls)
    p.clear();p.canvas.renderer.close();p.deleteLater();qapp.processEvents()


def test_clear_discards_queued_frame_and_cancels_preview_resume(qapp,video):
    p=Playback();p.audio.setMuted(True);p.open(video);ready(qapp,p)
    image=QImage(16,16,QImage.Format.Format_RGB32);image.fill(QColor('red'))
    p.sink.videoFrameChanged.emit(QVideoFrame(image))
    p.resume_on_load=True;p.restore_range=((100,200),True);p.pending_seek=100;p.range=(100,200)
    p.clear();qapp.processEvents()
    assert p.player.source().isEmpty() and p.canvas.frame.isNull()
    assert not p.resume_on_load and not p.preview_pending and p.pending_seek is None and p.restore_range is None and p.range is None
    p.canvas.renderer.close();p.deleteLater();qapp.processEvents()
