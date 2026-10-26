import copy,json,time
from pathlib import Path
import pytest
from PySide6.QtTest import QTest
from PySide6.QtCore import QThreadPool
from PySide6.QtMultimedia import QMediaPlayer
from shengao.app import StudioWindow
from shengao.project import History,Project,save_project,load_project,file_stamp
from shengao import proxy_video,vocal_audio
from shengao.encode import encode,EncodeOptions
from test_vocal_audio import track


def wait(app,fn,seconds=20):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        app.processEvents();QTest.qWait(10)
        if fn():return
    assert fn()


@pytest.fixture
def window(qapp,tmp_path,video,project):
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    project.media=str(video);w.history=History(project);w.current=0;w.refresh();w.show();w.load_media(video,edit=False,preview=True)
    wait(qapp,lambda:w.analysis_job is None and w.original_audio is not None and not w.playback.preview_pending)
    try:yield w
    finally:w.close();wait(qapp,lambda:QThreadPool.globalInstance().activeThreadCount()==0);qapp.processEvents()


def test_adoption_keeps_latest_edit_position_zoom_loop_and_original_document(window,qapp,tmp_path):
    w=window;w.playback.seek(1800);w.playback.set_zoom(.5);w.playback.player.setPlaybackRate(.75);w.playback.range=(1000,3500);w.playback.loop=True;before=w.project.to_dict();count=len(w.history.undo_stack)
    assert w.prepare_proxy();w.edit('任务期间人工译文',lambda p:setattr(p.lines[0],'translation','人工新译文'));w.playback.seek(2300)
    wait(qapp,lambda:w.proxy_active and w.proxy_job is None and not w.playback.preview_pending)
    assert w.project.media==before['media'] and w.line.translation=='人工新译文' and len(w.history.undo_stack)==count+1
    assert (w.playback.canvas.position,w.playback.zoom,w.playback.range,w.playback.loop)==(2300,.5,(1000,3500),True)
    assert w.playback.player.playbackRate()==.75 and w.audition_role=='original'
    assert Path(w.playback.player.source().toLocalFile())==Path(w.proxy_display_path) and w.timeline.audio is not None
    saved=tmp_path/'原片工程.sgproj';save_project(w.project,saved);loaded=load_project(saved)
    assert loaded.media==w.project.media and 'preview-cache' not in saved.read_text(encoding='utf-8')
    assert w.use_original_preview();wait(qapp,lambda:not w.playback.preview_pending)
    assert Path(w.playback.player.source().toLocalFile())==Path(w.project.media) and not w.proxy_active and w.line.translation=='人工新译文'


def test_proxy_choice_does_not_reset_current_playing_state(window,qapp):
    w=window;w.playback.seek(1000);w.playback.toggle();wait(qapp,lambda:w.playback.player.position()>1100)
    assert w.prepare_proxy();wait(qapp,lambda:w.proxy_active and not w.playback.preview_pending)
    assert w.playback.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState and w.playback.canvas.position>1100


def test_cancel_menu_stops_the_job_and_keeps_current_source(window,qapp):
    w=window;before=w.project.to_dict();w.prepare_proxy();w.proxy_action_sets[0]['cancel'].trigger()
    wait(qapp,lambda:QThreadPool.globalInstance().activeThreadCount()==0)
    assert w.proxy_job is None and not w.proxy_active and not w.cancel_button.isVisible()
    assert w.project.to_dict()==before and Path(w.playback.player.source().toLocalFile())==Path(w.project.media)


def test_late_project_replacement_discards_background_proxy(window,qapp):
    w=window;w.prepare_proxy();w.project.uid='different-project';after=w.project.to_dict()
    wait(qapp,lambda:w.proxy_job is None)
    assert not w.proxy_active and w.project.to_dict()==after and '已变化' in w.proxy_message


def test_ready_proxy_waits_for_fine_listening_to_finish(window,qapp):
    w=window;owner=object();stops=[];w.playback.begin_temporary(owner,lambda:stops.append(True),1900);source=w.playback.player.source()
    w.prepare_proxy();wait(qapp,lambda:w.proxy_job is None and w.proxy_pending is not None)
    assert w.playback.temporary_owner is owner and not stops and w.playback.player.source()==source and not w.proxy_active
    w.playback.end_temporary(owner);w.playback.seek(2500);wait(qapp,lambda:w.proxy_active and not w.playback.preview_pending)
    assert w.playback.canvas.position==2500 and not stops


def test_cache_changed_while_waiting_for_fine_listening_is_rejected(window,qapp):
    w=window;owner=object();w.playback.begin_temporary(owner,lambda:None,1900);w.prepare_proxy();wait(qapp,lambda:w.proxy_pending is not None)
    result=w.proxy_pending[1];Path(result['display']['path']).write_bytes(b'changed');w.playback.end_temporary(owner);qapp.processEvents()
    assert not w.proxy_active and w.proxy_pending is None and '已变化' in w.proxy_message


def test_original_file_missing_does_not_claim_a_successful_switch(window,qapp,tmp_path):
    import shutil
    w=window;source=tmp_path/'可移动原片.mp4';shutil.copy2(w.project.media,source);w.load_media(source,edit=False)
    # Use an independent project source record while preserving the current
    # analysis callback's identity, exactly as relocation does.
    w.project.media=str(source);wait(qapp,lambda:w.analysis_job is None and w.original_audio is not None)
    w.prepare_proxy();wait(qapp,lambda:w.proxy_active and not w.playback.preview_pending);current=w.playback.player.source()
    source.unlink();assert not w.use_original_preview() and w.proxy_active and w.playback.player.source()==current and '不存在' in w.proxy_message


def test_proxy_and_vocal_audition_combine_without_replacing_the_voice_or_waveform(window,qapp,track):
    w=window;w.project.vocal_track=track;w.prepare_proxy();wait(qapp,lambda:w.proxy_active and not w.playback.preview_pending)
    before=w.project.to_dict();w.select_vocal_audition('vocals')
    wait(qapp,lambda:w.audition_role=='vocals' and w.source_job is None and w.proxy_job is None and not w.playback.preview_pending and bool(w.proxy_display_path))
    human=w.playback.player.source().toLocalFile();assert w.proxy_active and human!=w._proxy_vocal_path
    assert proxy_video.audio_digest(human)==proxy_video.audio_digest(track['path']) and w.project.to_dict()==before
    assert w.original_audio is not None and w.timeline.audio is not None
    w.select_vocal_audition('original');wait(qapp,lambda:not w.playback.preview_pending)
    assert w.audition_role=='original' and w.proxy_active and Path(w.playback.player.source().toLocalFile())==Path(w.proxy_base['path'])


def test_proxy_playback_failure_recovers_existing_vocal_source(window,qapp,track):
    w=window;w.project.vocal_track=track;w.select_vocal_audition('vocals');wait(qapp,lambda:w.source_job is None and w.audition_role=='vocals' and not w.playback.preview_pending)
    w.prepare_proxy();wait(qapp,lambda:w.proxy_active and not w.playback.preview_pending);original_voice=w._proxy_vocal_path;before=w.project.to_dict()
    w.vocal_play_error('受控代理播放失败');wait(qapp,lambda:not w.playback.preview_pending)
    assert not w.proxy_active and w.audition_role=='vocals' and Path(w.playback.player.source().toLocalFile())==Path(original_voice) and w.project.to_dict()==before


def test_switching_media_clears_proxy_choice_without_overwriting_shared_lyrics(window,qapp):
    w=window;w.prepare_proxy();wait(qapp,lambda:w.proxy_active and not w.playback.preview_pending);before=[v.to_dict() for v in w.project.lines]
    w.reload_media_source();wait(qapp,lambda:w.analysis_job is None and not w.playback.preview_pending)
    assert not w.proxy_active and w.proxy_base is None and Path(w.playback.player.source().toLocalFile())==Path(w.project.media) and [v.to_dict() for v in w.project.lines]==before


def test_final_encode_still_uses_original_source_with_proxy_active(window,qapp,tmp_path):
    w=window;w.prepare_proxy();wait(qapp,lambda:w.proxy_active and not w.playback.preview_pending)
    result=encode(w.project,EncodeOptions(str(tmp_path/'原片输出.mp4'),start=1500,duration=400))
    assert result['media']==w.project.media and result['media']!=w.proxy_display_path and Path(result['output']).is_file()


def test_player_retains_original_zoom_dimensions_after_proxy_frame_size_arrives(qapp):
    from shengao.playback import Playback
    p=Playback();p.reference_size=(3840,2160);p.set_zoom(.5);p.set_frame_size(1280,720)
    assert (p.source_size.width(),p.source_size.height())==(3840,2160) and (p.canvas.width(),p.canvas.height())==(1920,1080)
    p.clear();assert p.reference_size is None;p.canvas.renderer.close();p.deleteLater();qapp.processEvents()
