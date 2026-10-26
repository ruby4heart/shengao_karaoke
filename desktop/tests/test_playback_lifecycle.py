import time
from PySide6.QtCore import QThread
from PySide6.QtGui import QImage,QColor
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtTest import QTest
from shengao.playback import Playback


def test_paused_and_temporary_clocks_only_repaint_when_the_visible_time_changes(qapp,monkeypatch):
    p=Playback();p.timer.stop();calls=[];monkeypatch.setattr(p.canvas,'update',lambda:calls.append(p.canvas.position))
    try:
        p.on_position(1200);assert calls==[1200];calls.clear()
        p.on_position(1200)
        for _ in range(5):p.tick()
        assert not calls
        owner=object();p.begin_temporary(owner,lambda:None,1300);assert calls==[1300];calls.clear()
        p.tick();assert not calls;p.update_temporary_position(owner,1400);assert calls==[1400]
        calls.clear();p.canvas.video_frame(QVideoFrame(QImage(16,16,QImage.Format.Format_RGB32)));assert calls==[1400]
        calls.clear();p.clear();assert calls
    finally:p.clear();p.canvas.renderer.close();p.deleteLater();qapp.processEvents()


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
    qapp.processEvents();QTest.qWait(10);assert calls and all(thread==qapp.thread() for thread in calls)
    calls.clear()
    class EmitFromDecoder(QThread):
        def run(self):p.sink.videoFrameChanged.emit(frame)
    worker=EmitFromDecoder();worker.start();assert worker.wait(3000)
    assert calls==[]
    qapp.processEvents();QTest.qWait(10);assert calls and all(thread==qapp.thread() for thread in calls)
    p.clear();p.canvas.renderer.close();p.deleteLater();qapp.processEvents()


def test_clear_discards_queued_frame_and_cancels_preview_resume(qapp,video):
    from PySide6.QtMultimedia import QMediaPlayer
    p=Playback();p.audio.setMuted(True);p.open(video);ready(qapp,p)
    positions=[];durations=[];errors=[]
    p.positionChanged.connect(positions.append);p.durationChanged.connect(durations.append);p.error.connect(errors.append)
    image=QImage(16,16,QImage.Format.Format_RGB32);image.fill(QColor('red'))
    p.sink.videoFrameChanged.emit(QVideoFrame(image))
    p.player.positionChanged.emit(123);p.player.durationChanged.emit(999)
    p.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
    p.player.errorOccurred.emit(QMediaPlayer.Error.ResourceError,'late error')
    p.resume_on_load=True;p.restore_range=((100,200),True);p.pending_seek=100;p.range=(100,200)
    p.clear();qapp.processEvents()
    assert p.player.source().isEmpty() and p.canvas.frame.isNull()
    assert not p.resume_on_load and not p.preview_pending and p.pending_seek is None and p.restore_range is None and p.range is None
    assert positions==[0] and durations==[0] and errors==[]
    p.canvas.renderer.close();p.deleteLater();qapp.processEvents()


def test_player_notifications_exit_sender_before_touching_ui(qapp,video):
    from PySide6.QtMultimedia import QMediaPlayer
    p=Playback();p.audio.setMuted(True);p.open(video);ready(qapp,p);calls=[]
    p.positionChanged.connect(lambda value:calls.append(('position',QThread.currentThread())))
    p.durationChanged.connect(lambda value:calls.append(('duration',QThread.currentThread())))
    p.error.connect(lambda value:calls.append(('error',QThread.currentThread())))
    try:
        # Even a GUI-thread emission must unwind the backend's call before
        # Python queries player state or invokes another playback operation.
        p.player.positionChanged.emit(123);p.player.durationChanged.emit(999)
        assert calls==[], 'Player callbacks must not reenter a backend operation inline'
        qapp.processEvents();assert {name for name,thread in calls}>={'position','duration'}
        calls.clear()
        class EmitFromDecoder(QThread):
            def run(self):
                p.player.positionChanged.emit(456);p.player.durationChanged.emit(1000)
                p.player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PausedState)
                p.player.playbackRateChanged.emit(.75)
                p.player.errorOccurred.emit(QMediaPlayer.Error.ResourceError,'controlled test')
        worker=EmitFromDecoder();worker.start();assert worker.wait(3000)
        assert calls==[]
        qapp.processEvents();assert {name for name,thread in calls}>={'position','duration','error'}
        assert all(thread==qapp.thread() for name,thread in calls)
    finally:p.clear();p.canvas.renderer.close();p.deleteLater();qapp.processEvents()


def test_filtered_tail_notifications_are_queued_and_ignored_after_close(qapp,project,monkeypatch):
    from PySide6.QtMultimedia import QMediaPlayer
    from shengao.tail_dialog import TailDialog
    from shengao.timeline import Timeline
    p=Playback();p.audio.setMuted(True);source=Timeline();dialog=TailDialog(project.lines[0],p,source);calls=[]
    original_follow=dialog.timeline.follow_position
    monkeypatch.setattr(dialog.timeline,'follow_position',lambda value:calls.append(QThread.currentThread()))
    dialog.filtered_player.positionChanged.emit(123);assert calls==[]
    qapp.processEvents();assert calls and all(thread==qapp.thread() for thread in calls)
    monkeypatch.setattr(dialog.timeline,'follow_position',original_follow);dialog.reject()
    monkeypatch.setattr(dialog.timeline,'follow_position',lambda value:calls.append(QThread.currentThread()))
    before=dialog.status.text();calls.clear()
    dialog.filtered_player.positionChanged.emit(456)
    dialog.filtered_player.errorOccurred.emit(QMediaPlayer.Error.ResourceError,'late failure')
    dialog.filtered_player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)
    qapp.processEvents()
    assert calls==[] and dialog.status.text()==before and dialog.filtered_player.playbackState()==QMediaPlayer.PlaybackState.StoppedState
    p.clear();p.canvas.renderer.close();dialog.deleteLater();p.deleteLater();source.deleteLater();qapp.processEvents()


def test_old_queued_position_never_overwrites_a_newer_seek(qapp,video):
    p=Playback();p.audio.setMuted(True);p.open(video);ready(qapp,p)
    p.seek(2000);qapp.processEvents();p.player.positionChanged.emit(123)
    qapp.processEvents();assert p.canvas.position==p.player.position()==2000
    p.pending_seek=3500;p.on_position(3500);p.player.positionChanged.emit(0)
    p.tick();qapp.processEvents();assert p.canvas.position==3500 and p.pending_seek==3500
    p.clear();p.canvas.renderer.close();p.deleteLater();qapp.processEvents()


def test_preview_waits_for_target_frame_and_keeps_exact_seek(qapp,video,monkeypatch):
    p=Playback();p.audio.setMuted(True);p.open(video);ready(qapp,p);p.seek(2000)
    p.preview_pending=p.preview_started=True;p.preview_target=2000;p.preview_muted=True;pauses=[]
    from shengao.native_slots import invoke_native_slot
    def observe(player,action):
        if action=='pause':pauses.append(True)
        return invoke_native_slot(player,action)
    monkeypatch.setattr('shengao.playback.invoke_native_slot',observe)
    frame=QVideoFrame(QImage(16,16,QImage.Format.Format_RGB32));frame.setStartTime(1500000);frame.setEndTime(1540000)
    p.receive_frame(frame);assert p.preview_started and pauses==[]
    p.preview_target=2400;p.tick();assert p.canvas.position==2400
    p.seek(2400);frame.setStartTime(2000000);frame.setEndTime(2040000);p.receive_frame(frame)
    assert p.preview_target==2400 and pauses==[]
    frame.setStartTime(2400000);frame.setEndTime(2440000);p.receive_frame(frame)
    assert pauses==[]
    qapp.processEvents();QTest.qWait(10)
    assert pauses==[True] and not p.preview_pending and p.preview_target is None and p.canvas.position==p.player.position()==2400
    p.clear();p.canvas.renderer.close();p.deleteLater();qapp.processEvents()


def test_busy_gui_presents_latest_frame_once_and_clear_discards_pending_image(qapp,video,monkeypatch):
    p=Playback();p.audio.setMuted(True);p.open(video);ready(qapp,p);calls=[];original=p.canvas.video_frame
    def present(frame):calls.append(frame.startTime());original(frame)
    monkeypatch.setattr(p.canvas,'video_frame',present)
    try:
        for index in range(50):
            image=QImage(16,16,QImage.Format.Format_RGB32);image.fill(QColor('blue' if index==49 else 'red'))
            frame=QVideoFrame(image);frame.setStartTime(index*40000);frame.setEndTime((index+1)*40000);p.receive_frame(frame)
        assert not calls
        qapp.processEvents();QTest.qWait(10)
        assert calls==[49*40000] and p.canvas.frame.pixelColor(3,3)==QColor('blue')
        p.receive_frame(frame);p.clear();qapp.processEvents();QTest.qWait(10)
        assert calls==[49*40000] and p.canvas.frame.isNull() and not p.frame_timer.isActive()
    finally:p.clear();p.canvas.renderer.close();p.deleteLater();qapp.processEvents()


def test_new_seek_replaces_pending_request_before_loaded_notification(qapp,video):
    p=Playback();p.audio.setMuted(True);p.open(video);ready(qapp,p)
    # Metadata is already loaded, but the queued handler has not consumed an
    # older request yet. A new user seek must replace that request as well.
    p.pending_seek=0;p.seek(2400);assert p.pending_seek==2400
    p.loaded(p.player.mediaStatus());qapp.processEvents()
    assert p.pending_seek is None and p.canvas.position==p.player.position()==2400
    p.clear();p.canvas.renderer.close();p.deleteLater();qapp.processEvents()
