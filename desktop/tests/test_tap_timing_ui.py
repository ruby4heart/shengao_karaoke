import copy
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.project import History
from shengao.tap_timing_dialog import TapButton


@pytest.fixture
def studio(qapp,tmp_path,project):
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True);w.history=History(project);w.current=0;w.show();w.refresh();w.set_stage(2);qapp.processEvents()
    yield w
    w.close();qapp.processEvents()


def fill(d):
    # Exercise the existing project data, without pretending a simulated
    # clock is a decoder/heard-audio precision measurement.
    for _,_,h in d.draft.notes:
        d.draft.add(h.start+10);d.draft.add(h.end)
    d.render()


def test_cancel_keeps_project_and_default_keys(studio,qapp):
    w=studio;before=w.project.to_dict();profile=w.audio_profile.to_data();d=w.open_tap_timing()
    assert d is not None and not d.isModal()
    d.draft.add(d.draft.notes[0][2].start);d.back();assert not d.draft.points
    d.reject();qapp.processEvents()
    assert w.project.to_dict()==before and w.audio_profile.to_data()==profile and w.playback.temporary_owner is None


def test_apply_is_one_undo_and_does_not_confirm_reading_or_time(studio,qapp):
    w=studio;before=w.project.to_dict();d=w.open_tap_timing();fill(d);d.allow_manual.setChecked(True);d.apply()
    assert d.applied and w.project.to_dict()!=before and not w.line.reviewed
    assert w.project.checks==before['checks'] and w.line.text==before['lines'][0]['text']
    w.undo();assert w.project.to_dict()==before


@pytest.mark.parametrize('change',['line','source','audition','project'])
def test_late_changes_preserve_draft_and_reject_apply(studio,change):
    w=studio;d=w.open_tap_timing();fill(d);points=list(d.draft.points)
    if change=='line':w.project.lines[0].translation='late edit'
    elif change=='source':w.project.media='moved.mp4'
    elif change=='audition':w.audition_role='vocals'
    else:w.history=History(copy.deepcopy(w.project));w.project.uid='new uid'
    before=w.project.to_dict();d.apply()
    assert d.stale and not d.applied and d.draft.points==points and w.project.to_dict()==before
    d.reject()


def test_space_is_scoped_and_held_key_does_not_record_twice(qapp):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    button=TapButton('记录');button.setAutoDefault(False);values=[];button.clicked.connect(lambda:values.append(1));button.show();button.setFocus()
    QTest.keyClick(button,Qt.Key.Key_Space)
    QApplication.sendEvent(button,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Space,Qt.KeyboardModifier.NoModifier,' ',True,1))
    assert values==[1];button.close()


def test_mode_change_preserves_existing_draft_until_explicit_restart(studio):
    d=studio.open_tap_timing();d.draft.add(d.draft.notes[0][2].start);old=d.draft
    d.mode.setCurrentIndex(1);assert d.draft is old and d.draft.points
    d.gaps.setChecked(True);d.restart();assert not d.draft.points and d.draft.mode=='continuous'
    d.reject()


def test_real_player_pause_resume_and_external_seek_keep_draft(studio,video,qapp):
    import time
    from PySide6.QtMultimedia import QMediaPlayer
    w=studio;w.load_media(str(video))
    def until(predicate):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            qapp.processEvents()
            if predicate():return
            QTest.qWait(20)
        assert predicate()
    until(lambda:not w.source_job and not w.analysis_job and not w.playback.player.source().isEmpty() and
          not w.playback.preview_pending and w.playback.pending_seek is None and w.playback.player.duration()>0)
    w.current=0;w.refresh();before=w.project.to_dict();d=w.open_tap_timing();assert d is not None
    d.start();until(lambda:d.recording and w.playback.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState and w.playback.canvas.position>=w.line.start+30)
    QTest.keyClick(d.capture,Qt.Key.Key_Space);assert len(d.draft.points)==1
    d.pause();first=list(d.draft.points);QTest.keyClick(d.capture,Qt.Key.Key_Space);assert d.draft.points==first
    d.stop_at_start();assert w.playback.canvas.position==w.line.start and d.draft.points==first
    d.start();until(lambda:d.recording and w.playback.canvas.position>=first[-1]+50)
    QTest.keyClick(d.capture,Qt.Key.Key_Space);assert len(d.draft.points)==2 and d.draft.points[-1]>d.draft.points[0]
    points=list(d.draft.points);w.playback.seek(w.line.start)
    assert not d.recording and d.draft.points==points and w.playback.temporary_owner is None
    d.reject();assert w.project.to_dict()==before
