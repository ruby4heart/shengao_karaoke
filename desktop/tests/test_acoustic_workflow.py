import copy
import threading
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.project import Project,History,save_project,load_project,file_stamp,SCHEMA
from shengao.dialogs import ReviewDialog
from shengao import acoustic_audio
from studio_backend.model import LyricLine,Unit
from studio_backend.acoustic import plan,propose
import time

def wait(app,fn):
    end=time.monotonic()+15
    while time.monotonic()<end:
        app.processEvents();QTest.qWait(20)
        if fn():return
    assert fn()

def window(qapp,tmp_path,video):
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    line=LyricLine('a','君を抱きしめて',1000,6000,[Unit('君を',1000,2500,'きみを','kimio',locked=True),Unit('抱きしめて',2500,6000,'だきしめて','dakishimete')],kana='きみをだきしめて')
    w.history=History(Project(media=str(video),media_stamp=file_stamp(video),duration=8000,lines=[line],checks={'a':{'reading':True}}));w.current=0;w.refresh();return w

def result(prepared,*args):
    outputs=[]
    for i,job in enumerate(prepared['jobs']):
        step=(job['end']-job['start'])//len(job['mora']);rows=[]
        for j,m in enumerate(job['mora']):
            a=job['start']+j*step;b=a+step-20
            rows.append({**m,'start':a,'end':b,'phones':[{'phone':'fixture','start':a,'end':b}]})
        outputs.append({'index':i,'mora':rows,'agreement':.5})
    raw={'engine':'test','model_sha256':'a'*64,'timestep_ms':10,'jobs':outputs}
    from shengao.vocal_audio import digest
    fingerprint=digest(args[0]) if args else 'b'*64
    new=propose(prepared,raw,fingerprint,'c'*64,'original')
    return {'ok':True,'action':'acoustic','suggestions':[new.to_dict()],'source_sha256':fingerprint}

def test_review_real_changes_preserves_reading_lock_undo_and_saved_evidence(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);before=w.project.to_dict();monkeypatch.setattr(acoustic_audio,'generate',result)
    assert w.align_acoustic();wait(qapp,lambda:w.source_job is None)
    assert w.pending and w.project.to_dict()==before
    dialog=ReviewDialog(w.project,w.pending['result'],w.playback,w)
    assert '人工' in dialog.details.toPlainText() and dialog.acoustic_mora.count()==5 and not dialog.candidates.isEnabled()
    assert not dialog.apply_button.isEnabled();dialog.check_all(True);w.apply_suggestions(dialog.selected());dialog.reject()
    assert w.pending is None and w.project.checks['a']['reading'] and w.line.units[0].locked
    assert not w.line.reviewed and w.line.units[1].highlights[0].source=='acoustic'
    target=tmp_path/'project.sgproj';save_project(w.project,target);restored=load_project(target)
    assert restored.to_dict()==w.project.to_dict() and restored.to_dict()['version']==SCHEMA
    w.undo();assert w.project.to_dict()==before;w.close()

def test_late_manual_edit_rejected_and_result_recoverable(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);gate=threading.Event()
    def slow(prepared,*args):gate.wait(8);return result(prepared,*args)
    monkeypatch.setattr(acoustic_audio,'generate',slow);w.align_acoustic();w.edit('人工译文',lambda p:setattr(p.lines[0],'translation','保留我'));before=w.project.to_dict();gate.set();wait(qapp,lambda:w.source_job is None)
    folder=w.pending['folder'];w.apply_suggestions(w.pending['result']['suggestions'])
    assert w.project.to_dict()==before and w.pending and '保留' in w.status.text()
    from pathlib import Path
    assert (Path(folder)/'result.json').is_file();w.close()

def test_cancel_keeps_original_and_manual_edits(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video)
    def slow(prepared,source,track,home,cancel,progress):cancel.wait(8);raise ValueError('已取消')
    monkeypatch.setattr(acoustic_audio,'generate',slow);w.align_acoustic();w.edit('人工译文',lambda p:setattr(p.lines[0],'translation','保留我'));before=w.project.to_dict();w.cancel_task();wait(qapp,lambda:w.source_job is None)
    assert w.project.to_dict()==before and not w.pending and '取消' in w.status.text();w.close()

def test_arrival_keeps_unsubmitted_time_field_and_table_editor(qapp,tmp_path,video,monkeypatch):
    from PySide6.QtWidgets import QLineEdit
    w=window(qapp,tmp_path,video);w.show();w.set_stage(2);gate=threading.Event()
    def slow(prepared,*args):gate.wait(8);return result(prepared,*args)
    monkeypatch.setattr(acoustic_audio,'generate',slow);w.align_acoustic()
    w.begin.setValue(1234);w.units.editItem(w.units.item(1,1));qapp.processEvents()
    editor=next(e for e in w.units.findChildren(QLineEdit) if e.isVisible());editor.setText('だきしめた');gate.set();wait(qapp,lambda:w.source_job is None)
    assert editor.text()=='だきしめた' and w.begin.value()==1234
    w.apply_suggestions(w.pending['result']['suggestions'])
    assert w.line.units[1].kana=='だきしめた' and w.pending;w.close()
