"""Controlled sound responses exercise actual Qt review and adoption paths."""
import copy
import threading
import time
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.sound_gaps import analyze
from shengao.project import Project,History,file_stamp
from shengao.sound_gap_dialog import SoundGapDialog,SoundGapOptions
from shengao.app import StudioWindow
from shengao import sound_gap_audio
import numpy as np


def project():
    return Project(lines=[LyricLine('a','かな',400,1600,[Unit('かな',400,1600,'かな',highlights=[Highlight('か',400,900),Highlight('な',1000,1600)])])])


def report_for(p,tmp_path):
    t=np.arange(96000)/48000;pcm=tmp_path/'voice.s16'
    ((np.sin(t*2*np.pi*220)*.4+np.sin(t*2*np.pi*440)*.15)*32767).astype('<i2').tofile(pcm)
    return analyze(p.lines,pcm,48000,{'audio_role':'vocals','source_sha256':'a'*64,'audio_sha256':'b'*64})


class Playback:
    def __init__(self):self.calls=[]
    def audition(self,a,b):self.calls.append((a,b))
    def stop(self):pass


def wait(qapp,predicate,seconds=10):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        qapp.processEvents();QTest.qWait(10)
        if predicate():return
    assert predicate()


def test_dialog_is_read_only_auditions_and_exposes_explicit_manual_choice(qapp,tmp_path):
    p=project();before=p.to_dict();report=report_for(p,tmp_path);playback=Playback()
    dialog=SoundGapDialog(p,report,playback);dialog.show();qapp.processEvents()
    assert dialog.apply_button.isEnabled();dialog.listen();assert playback.calls==[(650,1250)]
    dialog.controls[0].setCurrentIndex(dialog.controls[0].findData('manual'));dialog.choose()
    assert dialog.selected==dialog.manual==[report['gaps'][0]['key']] and p.to_dict()==before
    assert not dialog.timer.isActive()


def test_changed_project_is_read_only_and_empty_filter_disables_listen(qapp,tmp_path):
    p=project();report=report_for(p,tmp_path);p.lines[0].translation='新译文'
    dialog=SoundGapDialog(p,report,Playback());dialog.show();qapp.processEvents()
    assert dialog.stale and not dialog.apply_button.isEnabled() and not dialog.controls[0].isEnabled()
    dialog.filter.setCurrentIndex(dialog.filter.findData('protected'));assert not dialog.listen_button.isEnabled()
    dialog.choose();assert not dialog.selected;dialog.reject()


def test_nonadjacent_selection_does_not_connect_over_intervening_lyrics(qapp):
    p=project()
    for i in range(1,3):
        v=copy.deepcopy(p.lines[0]);v.id=str(i);v.start+=i*2000;v.end+=i*2000
        for u in v.units:
            u.start+=i*2000;u.end+=i*2000
            for h in u.highlights:h.start+=i*2000;h.end+=i*2000
        p.lines.append(v)
    options=SoundGapOptions(p,0,[0,2],'original');options.scope.setCurrentIndex(options.scope.findData('selected'))
    assert options.indices()==[0,2]
    from studio_backend.sound_gaps import targets
    assert all(v['kind']!='line' for v in targets(p.lines,5000,True,options.indices()))
    options.reject()


def window(qapp,tmp_path,video):
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    p=project();p.media=str(video);w.history=History(p);w.current=0;w.show();w.refresh();return w


def test_real_review_command_adopts_once_and_undo_restores_input(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);before=w.project.to_dict();controlled=report_for(w.project,tmp_path)
    monkeypatch.setattr(sound_gap_audio,'generate',lambda *a,**k:copy.deepcopy(controlled))
    monkeypatch.setattr(sound_gap_audio,'verify',lambda source,*a,**k:file_stamp(source))
    assert w.run_sound_gaps({'indices':[0],'maximum':2000,'join_lines':True})
    wait(qapp,lambda:w.source_job is None and w.pending is not None)
    assert w.project.to_dict()==before
    def accept():
        dialog=next(d for d in w.findChildren(SoundGapDialog) if d.isVisible());dialog.apply_button.click()
    QTimer.singleShot(20,accept);w.review_pending();wait(qapp,lambda:w.source_job is None)
    assert w.pending is None and w.line.units[0].highlights[0].end==1000 and len(w.history.undo_stack)==1
    assert not w.line.reviewed and w.line.text=='かな';w.undo();assert w.project.to_dict()==before;w.close()


def test_edit_during_analysis_is_kept_and_report_is_stale(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);controlled=report_for(w.project,tmp_path);gate=threading.Event()
    def generate(*args,**kwargs):gate.wait(5);return controlled
    monkeypatch.setattr(sound_gap_audio,'generate',generate)
    assert w.run_sound_gaps({'indices':[0],'maximum':2000,'join_lines':True})
    w.edit('人工译文',lambda p:setattr(p.lines[0],'translation','不要覆盖'));before=w.project.to_dict();gate.set()
    wait(qapp,lambda:w.source_job is None and w.pending is not None)
    assert not w.adopt_sound_gaps(controlled,[controlled['gaps'][0]['key']],[])
    assert w.project.to_dict()==before and w.pending is not None;w.close()


def test_delayed_audition_does_not_start_after_dialog_closed(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);report=report_for(w.project,tmp_path);callbacks=[];calls=[]
    monkeypatch.setattr(w,'generate_vocals',lambda after_ready=None:callbacks.append(after_ready))
    monkeypatch.setattr(w.playback,'audition',lambda a,b:calls.append((a,b)))
    w._gap_listen_serial=1;w.audition_sound_gap(600,1200,report,1);assert len(callbacks)==1
    w._gap_listen_serial=2;callbacks[0]();assert calls==[];w.close()


def test_review_handoff_reaches_exact_leaf_without_adoption(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);before=w.project.to_dict();controlled=report_for(w.project,tmp_path)
    monkeypatch.setattr(sound_gap_audio,'generate',lambda *a,**k:controlled)
    w.run_sound_gaps({'indices':[0],'maximum':2000,'join_lines':True})
    wait(qapp,lambda:w.source_job is None and w.pending is not None)
    QTimer.singleShot(20,lambda:next(d for d in w.findChildren(SoundGapDialog) if d.isVisible()).calibrate_button.click())
    w.review_pending()
    assert w.pending is None and (w.timeline.word,w.timeline.part)==(0,0) and w.project.to_dict()==before
    assert w.granularity.currentData()=='mora' and w.selected_times()==(400,900)
    assert list((w.home/'desktop-tasks').glob('*/result.json'));w.close()
