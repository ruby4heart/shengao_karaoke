import time
import wave,io
import pytest
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QMediaPlayer
from shengao.fine_listening import selected_range
from studio_backend.model import LyricLine,Unit
from test_reading_candidates_workflow import reading_window


def wait(qapp,condition,timeout=12000):
    end=time.monotonic()+timeout/1000
    while time.monotonic()<end:
        qapp.processEvents()
        if condition():return True
        QTest.qWait(15)
    return bool(condition())


@pytest.fixture
def fine_window(reading_window,qapp):
    w=reading_window;w.playback.audio.setMuted(True);w.load_media(w.project.media,False)
    assert wait(qapp,lambda:w.analysis_job is None and w.original_audio is not None and w.playback.player.duration()>0)
    w.select_editor_mora(0,2);w.open_inline_listening();yield w
    w.fine_listener.stop()


def test_context_range_uses_actual_previous_mora_and_unmatched_line_is_listenable(reading_window):
    line=reading_window.line
    assert selected_range(line,0,2)==(1110,1900,1400) and selected_range(line,0,2,False)==(1400,1800,1400)
    plain=LyricLine('unmatched','未匹配',1000,3000)
    assert selected_range(plain,-1,-1)==(850,3150,1000)
    plain.units=[Unit('未匹配',1000,3000)]
    assert selected_range(plain,0,-1,False)==(1000,3000,1000)


def test_top_tail_action_opens_inline_controls_without_a_modal(reading_window,qapp):
    w=reading_window;w.quick_tail.click();qapp.processEvents()
    assert w.fine_listening.toggle.isChecked() and w.fine_listener.context_button.isVisible() and qapp.activeModalWidget() is None


def test_normal_context_slow_play_loops_and_restores_regular_settings(fine_window,qapp):
    w=fine_window;f=w.fine_listener;before=w.project.to_dict();rate=w.playback.player.playbackRate();loop=w.playback.loop
    assert f.listen(True) and w.playback.range==(1110,1900)
    assert wait(qapp,lambda:w.playback.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState)
    assert w.playback.temporary_owner is f and w.playback.player.playbackRate()==.75 and w.playback.loop
    QTest.qWait(1250);qapp.processEvents();assert f.mode=='normal' and w.playback.range==(1110,1900)
    f.stop_button.click();assert f.mode is None and w.playback.temporary_owner is None and w.playback.player.playbackRate()==rate and w.playback.loop==loop and w.project.to_dict()==before


def test_real_filtered_waveform_moves_main_playhead_and_stops_on_regular_seek(fine_window,qapp):
    w=fine_window;f=w.fine_listener;before=w.project.to_dict();rate=w.playback.player.playbackRate();loop=w.playback.loop
    f.enhance.setChecked(True);assert f.listen(True)
    assert wait(qapp,lambda:f.filtered_player.playbackState()==QMediaPlayer.PlaybackState.PlayingState)
    assert w.playback.temporary_owner is f and w.playback.temporary_position is not None and f.filtered_audio.isMuted()
    data=bytes(f.current_buffer.data())
    with wave.open(io.BytesIO(data),'rb') as clip:
        assert clip.getnchannels()==1 and clip.getsampwidth()==2 and clip.getnframes()>100 and clip.getframerate()==w.timeline.audio.rate
    assert '定位静帧' in f.status.text() and wait(qapp,lambda:w.playback.canvas.position>f.filtered_start+70)
    assert w.play_time.text() and w.timeline.position==w.playback.canvas.position
    w.playback.audio.setVolume(.2);assert abs(f.filtered_audio.volume()-.2)<.001
    w.playback.seek(2400);qapp.processEvents()
    assert f.mode is None and w.playback.temporary_owner is None and w.playback.temporary_position is None and w.playback.canvas.position==2400
    assert f.filtered_player.playbackState()!=QMediaPlayer.PlaybackState.PlayingState and w.playback.player.playbackRate()==rate and w.playback.loop==loop and w.project.to_dict()==before


def test_main_play_button_stops_enhanced_audition_and_returns_to_regular_label(fine_window,qapp):
    w=fine_window;f=w.fine_listener;f.enhance.setChecked(True);assert f.listen(False)
    assert wait(qapp,lambda:f.filtered_player.playbackState()==QMediaPlayer.PlaybackState.PlayingState)
    assert w.play_button.text()=='停止细听';w.play_button.click();qapp.processEvents()
    assert f.mode is None and w.playback.temporary_owner is None and w.play_button.text()=='播放'


def test_turn_off_enhancement_and_original_compare_keeps_project(fine_window,qapp):
    w=fine_window;f=w.fine_listener;before=w.project.to_dict();f.enhance.setChecked(True);assert f.listen(False)
    f.compare.click();assert not f.enhance.isChecked() and f.mode=='normal' and w.audition_role=='original' and w.project.to_dict()==before
    assert wait(qapp,lambda:w.playback.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState)


def test_changing_selection_or_source_stops_temporary_sound(fine_window,qapp):
    w=fine_window;f=w.fine_listener;f.enhance.setChecked(True);assert f.listen(True)
    assert wait(qapp,lambda:f.filtered_player.playbackState()==QMediaPlayer.PlaybackState.PlayingState)
    w.select_target(1,-1);assert f.mode is None and w.playback.temporary_owner is None
    w.select_target(0,2);assert f.listen(True);w.playback.open(w.project.media)
    assert f.mode is None and f.filtered_player.playbackState()!=QMediaPlayer.PlaybackState.PlayingState


def test_regular_speed_change_interrupts_fine_play_and_applies_requested_speed(fine_window,qapp):
    w=fine_window;f=w.fine_listener;assert f.listen(True)
    w.speed.setCurrentIndex(w.speed.findData(.5));qapp.processEvents()
    assert f.mode is None and w.playback.temporary_owner is None and w.playback.player.playbackRate()==.5


def test_no_enhancement_audio_keeps_original_project_and_reports_recovery(reading_window):
    w=reading_window;f=w.fine_listener;before=w.project.to_dict();f.enhance.setChecked(True)
    assert not f.listen(True) and f.mode is None and '波形尚未就绪' in f.status.text() and w.project.to_dict()==before


def test_repeated_stop_releases_devices_and_disposal_stops_all_sound(fine_window,qapp):
    w=fine_window;f=w.fine_listener;f.enhance.setChecked(True);before=w.project.to_dict()
    for _ in range(6):
        assert f.listen(False);assert wait(qapp,lambda:f.filtered_player.playbackState()==QMediaPlayer.PlaybackState.PlayingState)
        f.stop();qapp.processEvents();assert not f.buffers and w.playback.temporary_owner is None
    assert f.listen(False);w.close();qapp.processEvents()
    assert f.closed and not f.timer.isActive() and f.filtered_player.source().isEmpty() and w.playback.temporary_owner is None and w.project.to_dict()==before
