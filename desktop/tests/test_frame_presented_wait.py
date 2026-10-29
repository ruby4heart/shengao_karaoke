"""Actual paint completion and native event-loop waiting contracts."""
import pytest
from PySide6.QtCore import QObject,Signal,QTimer
from PySide6.QtGui import QImage,QColor
from PySide6.QtMultimedia import QVideoFrame
from shengao.event_wait import wait_for_signal
from shengao.playback import VideoCanvas


class Emitter(QObject):
    changed=Signal()


def test_already_ready_does_not_enter_loop_or_retain_observer(qapp):
    emitter=Emitter();calls=[]
    def ready():calls.append('checked');return True
    assert wait_for_signal(emitter.changed,ready,100)
    emitter.changed.emit();assert calls==['checked']


def test_nonmatching_notification_does_not_complete_and_other_events_continue(qapp):
    emitter=Emitter();state=[];other=[]
    emitter.changed.connect(lambda:other.append('observed'))
    def first():
        state.append('not ready');emitter.changed.emit();QTimer.singleShot(0,second)
    def second():state.append('ready');emitter.changed.emit()
    QTimer.singleShot(0,first)
    assert wait_for_signal(emitter.changed,lambda:state==['not ready','ready'],200)
    assert other==['observed','observed']


def test_timeout_is_false_and_disconnects_only_its_own_observer(qapp):
    emitter=Emitter();calls=[];other=[]
    emitter.changed.connect(lambda:other.append('preserved'))
    def not_ready():calls.append('check');return False
    QTimer.singleShot(0,emitter.changed.emit)
    assert not wait_for_signal(emitter.changed,not_ready,20)
    count=len(calls);emitter.changed.emit()
    assert len(calls)==count and other==['preserved','preserved']


def test_async_predicate_exception_is_propagated_after_cleanup(qapp):
    emitter=Emitter();state=[]
    def predicate():
        if state:raise ValueError('controlled failure')
        return False
    def fail():state.append(True);emitter.changed.emit()
    QTimer.singleShot(0,fail)
    with pytest.raises(ValueError,match='controlled failure'):wait_for_signal(emitter.changed,predicate,100)
    # A leaked observer would raise again through Qt instead of this returning.
    emitter.changed.emit()


def test_deleted_sender_times_out_without_cleanup_error(qapp):
    emitter=Emitter();signal=emitter.changed
    QTimer.singleShot(0,emitter.deleteLater)
    assert not wait_for_signal(signal,lambda:False,20)


@pytest.fixture
def canvas(qapp):
    value=VideoCanvas();value.resize(320,180);value.show();qapp.processEvents()
    yield value
    value.close_frame_scaler();value.renderer.close();value.close();value.deleteLater();qapp.processEvents()


def frame(start=100000,end=140000):
    image=QImage(160,90,QImage.Format.Format_ARGB32);image.fill(QColor('#2d73b5'))
    value=QVideoFrame(image);value.setStartTime(start);value.setEndTime(end);return value


def test_notification_occurs_only_after_pixels_and_metadata_are_painted(qapp,canvas):
    observations=[]
    canvas.framePainted.connect(lambda:observations.append((canvas.painted_sequence,canvas.painted_frame_start_us,canvas.painted_frame_end_us,canvas.new_frame_painted_at_s,canvas.painted_at_s)))
    canvas.video_frame(frame());assert observations==[]
    assert wait_for_signal(canvas.framePainted,lambda:canvas.painted_sequence==1,200)
    sequence,start,end,new_time,paint_time=observations[0]
    assert (sequence,start,end)==(1,100000,140000) and new_time<=paint_time
    assert canvas.grab().toImage().pixelColor(20,20)==QColor('#2d73b5')


def test_repaint_resize_and_subtitle_clock_do_not_invent_new_frames(qapp,canvas):
    seen=[];canvas.framePainted.connect(lambda:seen.append(canvas.painted_sequence))
    canvas.video_frame(frame());assert wait_for_signal(canvas.framePainted,lambda:bool(seen),200)
    canvas.position=120;canvas.update();canvas.resize(340,191);qapp.processEvents();canvas.grab()
    assert seen==[1]


def test_fresh_frame_with_same_pts_gets_its_own_completion(qapp,canvas):
    seen=[];canvas.framePainted.connect(lambda:seen.append(canvas.painted_sequence))
    canvas.video_frame(frame());assert wait_for_signal(canvas.framePainted,lambda:canvas.painted_sequence==1,200)
    canvas.video_frame(frame());assert wait_for_signal(canvas.framePainted,lambda:canvas.painted_sequence==2,200)
    assert seen==[1,2]


def test_cleared_or_invalid_frame_does_not_emit_completion(qapp,canvas):
    seen=[];canvas.framePainted.connect(lambda:seen.append(canvas.painted_sequence))
    canvas.video_frame(QVideoFrame());canvas.update();qapp.processEvents();assert seen==[]
    canvas.video_frame(frame());assert wait_for_signal(canvas.framePainted,lambda:canvas.painted_sequence==1,200)
    canvas.clear_frame();canvas.update();qapp.processEvents();assert seen==[1]
