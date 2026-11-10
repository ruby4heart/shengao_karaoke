"""Line-tail review: read-only check, explicit per-line choice, issue list entries and one-step undo."""
import copy
import threading
import time
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend import line_tails
from shengao.project import Project,History,file_stamp
from shengao.line_tail_dialog import LineTailDialog,LineTailOptions
from shengao.review_issues import collect,proposed_line
from shengao.app import StudioWindow
from shengao import sound_gap_audio

RATE=48000
BINDING={'audio_role':'vocals','source_sha256':'a'*64,'audio_sha256':'b'*64}


def lyric(uid,text,mora,end):
    hs=[Highlight(k,a,b,'acoustic') for a,b,k in mora]
    value=LyricLine(uid,text,mora[0][0],end,[Unit(text,mora[0][0],mora[-1][1],''.join(k for _,_,k in mora),'acoustic',highlights=hs)])
    value.timing_evidence={'edge_tags':'ap-ep-v1','runs':[{'window':[value.start,end],'edges':{'lead':True,'trail':True,'breath':None,'release':None}}]}
    return value


def project():
    # Both final syllables stop ~700 ms before the singing does.
    return Project(lines=[lyric('a','かなす',((400,800,'か'),(800,1200,'な'),(1200,1600,'す')),2400),
                          lyric('q','たま',((3000,3300,'た'),(3300,3500,'ま')),4400)])


def report_for(p,tmp_path):
    t=np.arange(RATE*5)/RATE;data=np.zeros_like(t)
    for a,b in ((400,2300),(3000,4300)):
        m=(t>=a/1000)&(t<b/1000);data[m]=np.sin(2*np.pi*220*t[m])*.4+np.sin(2*np.pi*440*t[m])*.15
    pcm=tmp_path/'voice.s16';np.round(data*32767).astype('<i2').tofile(pcm)
    return line_tails.analyze(p.lines,pcm,RATE,BINDING)


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


def test_dialog_keeps_every_tail_by_default_and_only_records_explicit_choices(qapp,tmp_path):
    p=project();before=p.to_dict();report=report_for(p,tmp_path);playback=Playback()
    assert [v['status'] for v in report['tails']]==['flagged','flagged']
    dialog=LineTailDialog(p,report,playback);dialog.show();qapp.processEvents()
    assert all(c.currentData()=='keep' for c in dialog.controls) and not dialog.apply_button.isEnabled()
    dialog.listen();a,b=playback.calls[-1];assert a==800 and b>=2300
    control=dialog.controls[0];control.setCurrentIndex(control.findData('release'));dialog.update_apply()
    assert dialog.apply_button.isEnabled();dialog.listen_to_choice()
    release=next(c['end'] for c in report['tails'][0]['candidates'] if c['name']=='release');assert playback.calls[-1]==(600,release)
    dialog.choose();assert dialog.choices=={report['tails'][0]['key']:'release'} and p.to_dict()==before


def test_only_the_changed_line_becomes_read_only(qapp,tmp_path):
    p=project();report=report_for(p,tmp_path);p.lines[0].translation='检查后改的译文'
    dialog=LineTailDialog(p,report,Playback());dialog.show();qapp.processEvents()
    assert not dialog.stale and not dialog.controls[0].isEnabled() and dialog.controls[1].isEnabled()
    assert '已修改' in dialog.table.item(0,0).text() and '1 句' in dialog.note.text()
    p.lines[1].translation='也改了';dialog.reject()
    dialog=LineTailDialog(p,report,Playback());assert dialog.stale and not dialog.apply_button.isEnabled();dialog.reject()


def test_scope_options_follow_the_shared_time_scope(qapp):
    p=project();options=LineTailOptions(p,1,[0,1],'original')
    assert options.indices()==[1];options.scope.setCurrentIndex(options.scope.findData('selected'));assert options.indices()==[0,1]
    options.scope.setCurrentIndex(options.scope.findData('all'));assert options.options()=={'indices':[0,1]};options.reject()


def window(qapp,tmp_path):
    media=tmp_path/'素材.mp4';media.write_bytes(b'not decoded in this test')
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    p=project();p.media=str(media);w.history=History(p);w.current=0;w.show();w.refresh();return w


def test_check_is_read_only_then_review_adopts_once_and_undo_restores(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);before=w.project.to_dict();controlled=report_for(w.project,tmp_path)
    assert w.line_tails_button.isEnabled() and w.line_tail_review.isHidden()
    monkeypatch.setattr(sound_gap_audio,'generate_tails',lambda *a,**k:copy.deepcopy(controlled))
    monkeypatch.setattr(sound_gap_audio,'verify',lambda source,*a,**k:file_stamp(source))
    assert w.run_line_tails({'indices':[0,1]})
    wait(qapp,lambda:w.source_job is None and w.pending is not None)
    assert w.project.to_dict()==before and w.pending["action"]=="line_tails" and not w.line_tail_review.isHidden()
    assert '2 句句尾' in w.review_button.text() and not w.line_tails_button.isEnabled()
    release=next(c['end'] for c in controlled['tails'][0]['candidates'] if c['name']=='release')
    def accept():
        dialog=next(d for d in w.findChildren(LineTailDialog) if d.isVisible())
        dialog.controls[0].setCurrentIndex(dialog.controls[0].findData('release'));dialog.update_apply();dialog.apply_button.click()
    QTimer.singleShot(20,accept);w.review_pending();wait(qapp,lambda:w.source_job is None and w.pending is None)
    h=w.project.lines[0].units[0].highlights[-1]
    assert h.end==release and h.start==1200 and w.project.lines[1].to_dict()==before['lines'][1] and len(w.history.undo_stack)==1
    assert 'sound_tail' in h.timing_origin['operations'] and not w.project.lines[0].reviewed
    w.undo();assert w.project.to_dict()==before;w.close()


def test_edit_during_check_is_kept_and_that_line_cannot_be_adopted(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);controlled=report_for(w.project,tmp_path);gate=threading.Event()
    def generate(*args,**kwargs):gate.wait(5);return copy.deepcopy(controlled)
    monkeypatch.setattr(sound_gap_audio,'generate_tails',generate)
    assert w.run_line_tails({'indices':[0,1]})
    w.edit('人工译文',lambda p:setattr(p.lines[0],'translation','不要覆盖'));before=w.project.to_dict();gate.set()
    wait(qapp,lambda:w.source_job is None and w.pending is not None)
    first=controlled['tails'][0]
    assert not w.adopt_line_tails(controlled,{first['key']:first['candidates'][0]['name']})
    assert w.project.to_dict()==before and w.pending is not None;w.close()


def test_handoff_reaches_the_last_syllable_without_changing_time(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);before=w.project.to_dict();controlled=report_for(w.project,tmp_path)
    monkeypatch.setattr(sound_gap_audio,'generate_tails',lambda *a,**k:copy.deepcopy(controlled))
    w.run_line_tails({'indices':[0,1]});wait(qapp,lambda:w.source_job is None and w.pending is not None)
    def handoff():
        dialog=next(d for d in w.findChildren(LineTailDialog) if d.isVisible());dialog.table.setCurrentCell(1,0);dialog.calibrate_button.click()
    QTimer.singleShot(20,handoff);w.review_pending()
    assert w.pending is None and w.current==1 and (w.timeline.word,w.timeline.part)==(0,1) and w.project.to_dict()==before
    assert list((w.home/'desktop-tasks').glob('*/result.json'));w.close()


def test_issue_list_lists_checked_tails_and_adopts_one_at_a_time(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);before=w.project.to_dict();controlled=report_for(w.project,tmp_path)
    monkeypatch.setattr(sound_gap_audio,'generate_tails',lambda *a,**k:copy.deepcopy(controlled))
    w.run_line_tails({'indices':[0,1]});wait(qapp,lambda:w.source_job is None and w.pending is not None)
    items=[v for v in collect(w.project,False,w.pending) if v.kind=='tail']
    assert [v.row for v in items]==[0,1] and all(v.severity=='warning' and v.proposal['kind']=='tail' for v in items)
    assert not [v for v in collect(w.project,False,w.pending) if v.kind=='proposal']
    first=items[0];preview=proposed_line(w.project,first,w.pending)
    assert w.project.to_dict()==before and preview.units[0].highlights[-1].end>1600
    expected={'line':w.project.lines[0].to_dict(),'checks':{},'preview':preview.to_dict()}
    assert w.adopt_review_issue(first,expected)
    assert w.project.lines[0].to_dict()==preview.to_dict() and w.project.review_states[first.id]['decision']=='adopted'
    left=[v for v in collect(w.project,False,w.pending) if v.kind=='tail']
    assert [v.row for v in left]==[1] and proposed_line(w.project,left[0],w.pending).units[0].highlights[-1].end>3500
    w.undo();assert w.project.to_dict()==before;w.close()


def test_timing_only_tail_warning_opens_the_tail_check(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path)
    w.edit('压缩句尾',lambda p:(setattr(p.lines[1].units[0].highlights[-1],'start',3460),setattr(p.lines[1].units[0].highlights[-2],'end',3460)))
    items=[v for v in collect(w.project,False,None) if v.kind=='tail']
    assert [(v.row,v.severity,v.part) for v in items]==[(1,'notice',1)] and not items[0].proposal and '未听声音' in items[0].why
    calls=[];monkeypatch.setattr(w,'start_line_tails',lambda:calls.append(w.current))
    w.manual_review_issue(items[0],specific=True);assert calls==[1];w.close()


def test_task_record_and_cancel_wording_name_the_tail_check(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);controlled=report_for(w.project,tmp_path);gate=threading.Event()
    def generate(*args,**kwargs):gate.wait(5);return copy.deepcopy(controlled)
    monkeypatch.setattr(sound_gap_audio,'generate_tails',generate)
    w.run_line_tails({'indices':[0]});w.cancel_task();assert '句尾检查' in w.status.text();gate.set()
    wait(qapp,lambda:w.source_job is None)
    assert w.pending is None and '取消' in w.status.text();w.close()
