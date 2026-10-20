import copy
import json
from pathlib import Path
import subprocess
import threading
import time
import numpy as np
import pytest
from PySide6.QtTest import QTest
from shengao import vocal_audio as vocal
from shengao.app import StudioWindow
from shengao.project import Project,History,file_stamp,save_project,load_project
from shengao.media_versions import apply_media_version
from shengao.encode import encode,EncodeOptions
from shengao.paths import ffmpeg
from vocal_engine import MODEL_SHA256,ENGINE_VERSION

def wait(app,fn,seconds=25):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        app.processEvents();QTest.qWait(20)
        if fn():return
    assert fn()

@pytest.fixture
def track(tmp_path,video):
    path=tmp_path/'人声.wav'
    result=subprocess.run([ffmpeg(),'-v','error','-nostdin','-y','-f','lavfi','-i','sine=frequency=880:duration=8:sample_rate=44100','-ac','2','-c:a','pcm_f32le',str(path)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0
    return {'path':str(path),'source_path':str(video),'source_stamp':file_stamp(video),'source_sha256':vocal.digest(video),'sha256':vocal.digest(path),'frames':8*44100,'sample_rate':44100,'model_sha256':MODEL_SHA256,'engine':ENGINE_VERSION}

def window(app,tmp_path,project,video,track=None):
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True);w.history=History(copy.deepcopy(project));w.current=0;w.show();w.load_media(video)
    wait(app,lambda:w.analysis_job is None and w.original_audio is not None)
    if track:w.project.vocal_track=copy.deepcopy(track)
    w.history.mark_saved();w.refresh();return w

def content(p):return {k:v for k,v in p.to_dict().items() if k!='vocal_track'}

def test_real_mux_ab_keeps_position_speed_range_axis_and_export_source(qapp,tmp_path,project,video,track):
    w=window(qapp,tmp_path,project,video,track);before=w.project.to_dict();oldpcm=str(w.timeline.audio.samples.filename)
    w.playback.seek(2400);w.playback.player.setPlaybackRate(.75);w.playback.set_zoom(.5);w.timeline.left=800;left=w.timeline.left;scale=w.timeline.pixel_ms
    w.vocal_tools.click();wait(qapp,lambda:w.source_job is None and w.audition_role=='vocals')
    wait(qapp,lambda:not w.playback.canvas.frame.isNull() and not w.playback.preview_pending)
    assert w.project.to_dict()==before and w.project.media==str(video)
    assert str(w.timeline.audio.samples.filename)!=oldpcm and abs(w.playback.canvas.position-2400)<120
    assert w.playback.audio.isMuted() and w.playback.player.playbackRate()==.75 and w.playback.zoom==.5
    assert w.timeline.left==left and w.timeline.pixel_ms==scale
    assert '人声' in w.vocal_tools.text() and w.playback.player.source().toLocalFile()!=str(video)
    result=subprocess.run([ffmpeg(),'-v','error','-i',w.playback.player.source().toLocalFile(),'-vn','-ac','1','-ar','16000','-t','1','-f','f32le','-'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    samples=np.frombuffer(result.stdout,dtype='<f4');frequency=np.argmax(abs(np.fft.rfft(samples)))*16000/len(samples);assert abs(frequency-880)<5
    output=tmp_path/'export-original.mp4';encode(w.project,EncodeOptions(str(output),0,500,'source'))
    result=subprocess.run([ffmpeg(),'-v','error','-i',str(output),'-vn','-ac','1','-ar','16000','-f','f32le','-'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    samples=np.frombuffer(result.stdout,dtype='<f4');frequency=np.argmax(abs(np.fft.rfft(samples)))*16000/len(samples);assert abs(frequency-440)<10
    w.playback.audition(2000,4000,True);wait(qapp,lambda:w.playback.player.position()>2100)
    w.vocal_tools.click();wait(qapp,lambda:Path(w.playback.player.source().toLocalFile())==video and w.playback.player.position()>2200)
    assert w.audition_role=='original' and w.playback.range==(2000,4000) and w.playback.loop and w.project.to_dict()==before
    w.close()

def test_portable_stem_roundtrip_and_corrupt_save_never_overwrites(tmp_path,project,track):
    project.vocal_track=track;path=tmp_path/'保存'/'工程.sgproj';path.parent.mkdir();save_project(project,path)
    value=json.loads(path.read_text(encoding='utf-8'));assert not Path(value['vocal_track']['path']).is_absolute()
    restored=load_project(path);assert vocal.digest(restored.vocal_track['path'])==track['sha256'];assert content(restored)==content(project)
    before=path.read_bytes();Path(track['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='变化'):save_project(project,path)
    assert path.read_bytes()==before

@pytest.mark.parametrize('name,value',[('sha256','bad'),('frames',0),('frames',True),('sample_rate',0),('source_stamp',[]),('path',''),('model_sha256',None)])
def test_reject_malformed_track(project,track,name,value):
    project.vocal_track={**track,name:value}
    with pytest.raises(ValueError):project.validate()

def test_previous_project_without_aux_track_reads(project):
    value=project.to_dict();value['version']=5;value.pop('vocal_track');assert Project.from_dict(value).vocal_track=={}

def test_cancel_preserves_old_audition_and_late_lyrics(qapp,tmp_path,project,video,monkeypatch):
    w=window(qapp,tmp_path,project,video);before=w.project.to_dict();source=w.playback.player.source()
    def slow(source,home,cancel,report):
        cancel.wait(10);vocal.cancelled(cancel)
    monkeypatch.setattr(vocal,'generate',slow)
    w.generate_vocals();w.edit('人工译文',lambda p:setattr(p.lines[0],'translation','保留'));w.cancel_task();wait(qapp,lambda:w.source_job is None)
    assert w.playback.player.source()==source and w.project.vocal_track=={} and w.project.lines[0].translation=='保留'
    assert '取消' in w.status.text() and w.audition_role=='original';w.undo();assert w.project.to_dict()==before;w.close()

def test_late_manual_edit_survives_stem_apply_and_one_undo(qapp,tmp_path,project,video,track,monkeypatch):
    w=window(qapp,tmp_path,project,video);gate=threading.Event()
    def local(source,home,cancel,report):gate.wait(10);return track.copy()
    monkeypatch.setattr(vocal,'generate',local);w.generate_vocals();w.edit('人工改字',lambda p:setattr(p.lines[0],'translation','人工翻译'));before=w.project.to_dict();gate.set()
    wait(qapp,lambda:w.source_job is None);assert w.audition_role=='vocals' and w.project.lines[0].translation=='人工翻译'
    w.undo();assert w.project.to_dict()==before and w.audition_role=='original';w.close()

def test_corrupt_or_changed_source_does_not_change_audition(qapp,tmp_path,project,video,track,monkeypatch):
    w=window(qapp,tmp_path,project,video,track);before=w.project.to_dict();source=w.playback.player.source();Path(track['path']).write_bytes(b'bad')
    def failure(*args,**kwargs):raise ValueError('分离失败')
    monkeypatch.setattr(vocal,'generate',failure);w.generate_vocals();wait(qapp,lambda:w.source_job is None)
    assert w.project.to_dict()==before and w.playback.player.source()==source and w.audition_role=='original';w.close()

def test_prepare_cancel_never_publishes_preview(tmp_path,video,track):
    cancel=threading.Event();cancel.set()
    with pytest.raises(ValueError,match='取消'):vocal.prepare(track,video,tmp_path,cancel)
    assert not list(tmp_path.glob('vocal-previews/*.mkv'))

def test_same_size_timestamp_source_change_rejects_old_stem(tmp_path,video,track):
    import os,shutil
    source=tmp_path/'copied.mp4';shutil.copy2(video,source);stat=source.stat();track.update(source_path=str(source),source_stamp=file_stamp(source))
    data=bytearray(source.read_bytes());data[-1]^=1;source.write_bytes(data);os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    assert vocal.bound(track,source)
    with pytest.raises(ValueError,match='内容'):vocal.prepare(track,source,tmp_path,threading.Event())

def test_stem_generation_uses_model_exact_frames_and_cache(tmp_path,video):
    # A real local inference, not a paid service or a fake separation response.
    updates=[];cancel=threading.Event();track=vocal.generate(video,tmp_path,cancel,updates.append)
    assert track['frames']>7.9*44100 and track['model_sha256']==MODEL_SHA256
    assert vocal.digest(track['path'])==track['sha256'] and vocal.bound(track,video)
    modified=Path(track['path']).stat().st_mtime_ns
    again=vocal.generate(video,tmp_path,cancel,updates.append)
    assert again==track and Path(track['path']).stat().st_mtime_ns==modified
    assert any('复用' in str(s) for s in updates)
