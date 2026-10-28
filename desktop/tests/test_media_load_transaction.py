"""Probing may overlap editing, but rejected edits must not leave live media."""
import time
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.project import Project,History
from studio_backend.model import LyricLine,Unit


def test_first_media_load_keeps_manual_lyrics_and_one_undo_step(qapp,tmp_path,video):
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    line=LyricLine('manual','歌',100,700,[Unit('歌',100,700,'うた',source='manual')])
    w.history=History(Project(lines=[line]));w.current=0;w.refresh()
    lyrics=w.project.to_dict()['lines']
    w.load_media(video,preview=True)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline and (w.analysis_job is not None or w.playback.preview_pending):
        qapp.processEvents();QTest.qWait(5)
    assert w.analysis_job is None and not w.playback.preview_pending
    assert w.project.media==str(video.resolve()) and w.project.duration>0
    assert not w.playback.canvas.frame.isNull() and w.project.to_dict()['lines']==lyrics
    assert len(w.history.undo_stack)==1
    w.undo();assert not w.project.media and w.project.to_dict()['lines']==lyrics


def test_rejected_media_edit_clears_started_probe_without_analysis_or_undo(qapp,tmp_path,video):
    w=StudioWindow(tmp_path/'home',test=True)
    w.history=History(Project(lines=[LyricLine('bad','歌',100,700)]));w.current=0;w.refresh()
    w.project.lines[0].end=-1;before=w.project.to_dict()
    w.load_media(video,preview=True)
    qapp.processEvents();QTest.qWait(10)
    assert w.project.to_dict()==before and not w.history.undo_stack
    assert w.analysis_job is None and w.playback.player.source().isEmpty()
    assert not w.playback.preview_pending and w.playback.canvas.frame.isNull()
    assert w.playback.player.mediaStatus()==QMediaPlayer.MediaStatus.NoMedia
    assert w.validation_error and w.status.text()==w.validation_error
