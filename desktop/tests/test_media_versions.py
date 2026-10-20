import copy
import subprocess
import threading
import time
from pathlib import Path
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.project import Project,History,file_stamp,save_project,load_project
from shengao.media_versions import MediaVersion,apply_media_version,switch_warnings
from shengao.encode import encode,EncodeOptions
from shengao.paths import ffmpeg
from shengao.theme import STYLE

def wait(qapp,predicate,seconds=20):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        qapp.processEvents();QTest.qWait(20)
        if predicate():return
    assert predicate(),'source operation timed out'

@pytest.fixture(scope='module')
def accompaniment(tmp_path_factory):
    path=tmp_path_factory.mktemp('伴奏版')/'伴奏 source.mp4'
    result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i','color=c=0x773311:s=480x270:r=25:d=8','-f','lavfi','-i','sine=frequency=880:duration=8','-vf',"drawbox=color=0x117733:t=fill:enable='gte(t,2)'",'-c:v','h264_mf','-hw_encoding','0','-pix_fmt','nv12','-c:a','aac','-shortest',str(path)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr
    return path

def window(qapp,tmp_path,project,video):
    qapp.setStyle('Fusion');qapp.setStyleSheet(STYLE)
    w=StudioWindow(home=tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    p=copy.deepcopy(project);p.media=str(video);p.media_stamp=file_stamp(video);p.duration=8000;p.transcript=[p.lines[0].to_dict()];p.transcript_stamp=p.media_stamp.copy();p.lines[0].reviewed=True;p.checks[p.lines[0].id]={'reading':True};p.lines[0].locked=True
    w.history=History(p);w.current=0;w.refresh(True);w.show();w.load_media(video,False)
    wait(qapp,lambda:w.analysis_job is None and w.playback.player.duration()>0)
    w.api.start=lambda request:pytest.fail('Switching sources must not call an API')
    return w

def content(p):
    return {k:v for k,v in p.to_dict().items() if k not in {'media','media_stamp','duration','has_video','width','height','fps','media_role','media_versions'}}

def test_real_source_toggle_preserves_locked_timing_readings_and_transcript(qapp,tmp_path,project,video,accompaniment):
    w=window(qapp,tmp_path,project,video);before=content(w.project);old_pcm=str(w.timeline.audio.samples.filename);w.playback.seek(2400);w.playback.audio.setMuted(False)
    assert w.switch_media_source('instrumental',accompaniment)
    assert w.project.media==str(video) and content(w.project)==before
    wait(qapp,lambda:w.source_job is None)
    assert w.project.media_role=='instrumental' and w.project.media==str(accompaniment) and content(w.project)==before
    assert str(w.timeline.audio.samples.filename)!=old_pcm and w.project.width==480 and '原唱版' in w.source_switch.text()
    wait(qapp,lambda:Path(w.playback.player.source().toLocalFile())==accompaniment and abs(w.playback.canvas.position-2400)<120 and not w.playback.canvas.frame.isNull())
    assert not w.playback.audio.isMuted() and not w.playback.preview_started
    pixel=w.playback.canvas.frame.pixelColor(10,10);assert pixel.green()>pixel.red(), 'The preview must show the requested 2.4s frame, not the first frame'
    w.source_switch.click();wait(qapp,lambda:w.source_job is None)
    assert w.project.media==str(video) and content(w.project)==before and w.project.transcript_stamp==file_stamp(video)
    w.close()

def test_source_change_is_one_undo_step_and_roundtrips_relative_paths(qapp,tmp_path,project,video,accompaniment):
    w=window(qapp,tmp_path,project,video);before=w.project.to_dict();w.switch_media_source('instrumental',accompaniment);wait(qapp,lambda:w.source_job is None)
    changed=w.project.to_dict();assert len(w.history.undo_stack)==1
    path=tmp_path/'保存目录'/'两个版本.sgproj';path.parent.mkdir();save_project(w.project,path)
    assert load_project(path).to_dict()==changed
    w.undo();wait(qapp,lambda:w.analysis_job is None);assert w.project.to_dict()==before
    w.redo();wait(qapp,lambda:w.analysis_job is None);assert w.project.to_dict()==changed
    w.close()

def test_invalid_or_missing_source_keeps_current_player_and_all_data(qapp,tmp_path,project,video):
    w=window(qapp,tmp_path,project,video);before=w.project.to_dict();source=w.playback.player.source();bad=tmp_path/'损坏.mp4';bad.write_bytes(b'not a video')
    w.switch_media_source('instrumental',bad);wait(qapp,lambda:w.source_job is None)
    assert w.project.to_dict()==before and w.playback.player.source()==source and not w.history.undo_stack
    assert '保留' in w.status.text();assert not w.switch_media_source('instrumental',tmp_path/'不存在.mp4')
    assert w.project.to_dict()==before;w.close()

def test_cancel_candidate_keeps_live_source_and_subtitles(qapp,tmp_path,project,video,accompaniment,monkeypatch):
    from shengao import media
    w=window(qapp,tmp_path,project,video);before=w.project.to_dict()
    def slow(path,cache,cancel,report):
        while not cancel.wait(.02):pass
        raise ValueError('已取消')
    monkeypatch.setattr(media,'analyze',slow);w.switch_media_source('instrumental',accompaniment);w.cancel_task()
    wait(qapp,lambda:w.source_job is None);assert w.project.to_dict()==before and not w.history.undo_stack and Path(w.playback.player.source().toLocalFile())==video;w.close()

def test_different_duration_requires_review_and_never_stretches_axis(qapp,tmp_path,project,video,accompaniment,monkeypatch):
    from shengao import media
    w=window(qapp,tmp_path,project,video);original=media.analyze;before=w.project.to_dict();prompts=[]
    def shorter(*args,**kwargs):
        result=original(*args,**kwargs);result['duration']=4000;return result
    monkeypatch.setattr(media,'analyze',shorter);w.confirm_media_source=lambda notes:prompts.append(notes) or False
    w.switch_media_source('instrumental',accompaniment);wait(qapp,lambda:w.source_job is None)
    assert prompts and any('片尾' in s for s in prompts[0]) and w.project.to_dict()==before
    w.confirm_media_source=lambda notes:True;w.switch_media_source('instrumental',accompaniment);wait(qapp,lambda:w.source_job is None)
    assert w.project.duration==4000 and content(w.project)==content(Project.from_dict(before));w.close()

def test_reading_edit_during_analysis_survives_commit(qapp,tmp_path,project,video,accompaniment,monkeypatch):
    from shengao import media
    w=window(qapp,tmp_path,project,video);original=media.analyze;gate=threading.Event()
    def delayed(*args,**kwargs):
        result=original(*args,**kwargs);gate.wait(5);return result
    monkeypatch.setattr(media,'analyze',delayed);w.switch_media_source('instrumental',accompaniment)
    w.edit('人工备注',lambda p:setattr(p,'note','校对过程中修改'));gate.set();wait(qapp,lambda:w.source_job is None)
    assert w.project.media_role=='instrumental' and w.project.note=='校对过程中修改';w.close()

def test_each_export_contains_selected_video_and_audio(qapp,tmp_path,project,video,accompaniment):
    w=window(qapp,tmp_path,project,video);original=content(w.project);frequencies=[];colors=[]
    for role,path in [('original',video),('instrumental',accompaniment)]:
        if role!='original':w.switch_media_source(role,path);wait(qapp,lambda:w.source_job is None)
        output=tmp_path/(role+'.mp4');encode(w.project,EncodeOptions(str(output),0,500,'source'))
        audio=subprocess.run([ffmpeg(),'-v','error','-i',str(output),'-vn','-ac','1','-ar','16000','-f','f32le','-'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        samples=np.frombuffer(audio.stdout,dtype='<f4');assert len(samples)>4000
        frequencies.append(np.argmax(np.abs(np.fft.rfft(samples)))*16000/len(samples))
        frame=subprocess.run([ffmpeg(),'-v','error','-i',str(output),'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        colors.append(np.frombuffer(frame.stdout,dtype=np.uint8).astype(int))
        assert content(w.project)==original
    assert abs(frequencies[0]-440)<10 and abs(frequencies[1]-880)<10
    assert np.max(np.abs(colors[0]-colors[1]))>30;w.close()

def test_old_projects_migrate_without_dropping_lyrics_or_ass(project):
    data=project.to_dict();data['version']=3;data.pop('media_versions');data.pop('media_role')
    restored=Project.from_dict(data);assert restored.media_versions=={} and restored.media_role=='original'
    assert restored.lines[0].to_dict()==project.lines[0].to_dict()
    for value in [{'bogus':{'path':'a'}},{'original':{'path':42}}]:
        with pytest.raises(ValueError):Project.from_dict({**data,'version':4,'media_versions':value})


def test_candidate_modified_while_reading_is_not_committed(qapp,tmp_path,project,video,accompaniment,monkeypatch):
    from shengao import media
    import shutil
    w=window(qapp,tmp_path,project,video);before=w.project.to_dict();path=tmp_path/'候选.mp4';shutil.copy2(accompaniment,path);ready=threading.Event();gate=threading.Event();original=media.analyze
    def delayed(*args,**kwargs):
        result=original(*args,**kwargs);ready.set();gate.wait(5);return result
    monkeypatch.setattr(media,'analyze',delayed);w.switch_media_source('instrumental',path)
    wait(qapp,ready.is_set)
    with path.open('ab') as stream:stream.write(b'changed')
    gate.set();wait(qapp,lambda:w.source_job is None)
    assert w.project.to_dict()==before and not w.history.undo_stack and '变化' in w.status.text();w.close()


def test_export_cannot_overwrite_either_registered_source(project,video,accompaniment):
    p=copy.deepcopy(project);p.media_versions={'original':MediaVersion(str(video)),'instrumental':MediaVersion(str(accompaniment))}
    before=[file_stamp(path) for path in [video,accompaniment]]
    for role in ['original','instrumental']:
        p.media_role=role;p.media=p.media_versions[role].path
        for destination in [video,accompaniment]:
            with pytest.raises(ValueError,match='源'):
                encode(p,EncodeOptions(str(destination),0,500,'source'))
    assert [file_stamp(path) for path in [video,accompaniment]]==before


def test_reading_still_in_editor_is_committed_before_source_refresh(qapp,tmp_path,project,video,accompaniment,monkeypatch):
    from shengao import media
    from PySide6.QtWidgets import QLineEdit,QApplication
    w=window(qapp,tmp_path,project,video);w.project.lines[0].locked=False;w.refresh();original=media.analyze;gate=threading.Event()
    def delayed(*args,**kwargs):
        result=original(*args,**kwargs);gate.wait(5);return result
    monkeypatch.setattr(media,'analyze',delayed);w.switch_media_source('instrumental',accompaniment)
    assert w.progress.minimum()==w.progress.maximum()==0
    w.go_reading();item=w.units.item(0,1);old=w.line.units[0].kana;w.units.editItem(item);qapp.processEvents();editor=QApplication.focusWidget()
    assert isinstance(editor,QLineEdit);editor.setText('こんにち');assert w.line.units[0].kana==old
    gate.set();wait(qapp,lambda:w.source_job is None)
    assert w.project.media_role=='instrumental' and w.line.units[0].kana=='こんにち';w.close()

