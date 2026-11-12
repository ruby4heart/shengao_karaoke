"""Multi-plan timing comparison: read-only check, explicit per-line choice, issue list entries and one-step undo."""
import copy
import threading
import time
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.provenance import create
from studio_backend import timing_plans
from shengao.project import Project,History
from shengao.timing_plan_dialog import TimingPlanDialog,TimingPlanOptions
from shengao.review_issues import collect
from shengao.app import StudioWindow
from shengao import acoustic_batch,timing_plan_sources


def lyric(uid,text,mora):
    hs=[Highlight(k,a,b,'acoustic',timing_origin=create('acoustic',a,b,'tifa','tifa_mora',k)) for a,b,k in mora]
    unit=Unit(text,mora[0][0],mora[-1][1],''.join(k for _,_,k in mora),'acoustic',highlights=hs,timing_origin=create('acoustic',mora[0][0],mora[-1][1],'tifa','tifa_mora'))
    return LyricLine(uid,text,mora[0][0],mora[-1][1],[unit],kana=unit.kana)


def project():
    return Project(lines=[lyric('a','かなす',((400,800,'か'),(800,1200,'な'),(1200,1600,'す'))),
                          lyric('q','たま',((3000,3300,'た'),(3300,3500,'ま')))])


def moved(value,deltas):
    """The model's alternative: syllable onsets move by ``deltas`` ms, the line keeps its tail."""
    out=copy.deepcopy(value);hs=out.units[0].highlights
    for h,d in zip(hs,deltas):h.start+=d
    for a,b in zip(hs,hs[1:]):a.end=b.start
    out.units[0].start=hs[0].start;out.start=min(out.start,hs[0].start)
    for h in hs:h.timing_origin=create('acoustic',h.start,h.end,'tifa','tifa_mora',h.kana)
    out.validate();return out


def fake_generate(calls,shift={'a':[0,200,0]},gate=None):
    def generate(rows,source,track,home,cancel,progress=lambda x:None,audio_choice='auto',neighbors=None,**kwargs):
        if gate is not None:gate.wait(5)
        calls.append({'rows':copy.deepcopy(rows),'choice':audio_choice,'track':track})
        out=[];states={}
        for raw in rows:
            value=LyricLine.from_dict(raw);deltas=shift.get(value.id)
            out.append((moved(value,deltas) if deltas else value).to_dict());states[value.id]={'status':'aligned','reason':'测试用歌声候选。'}
        return {'suggestions':out,'acoustic':{'lines':states}}
    return generate


def report_for(p):
    a=p.lines[0]
    return timing_plans.analyze(p.lines,{'local_original':{0:{'line':moved(a,[0,200,0]),'note':'原声'},1:{'line':copy.deepcopy(p.lines[1]),'note':'原声'}},
                                         'local_vocals':{0:{'line':copy.deepcopy(a),'note':'人声'}}})


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


def test_options_disable_unavailable_sources_and_require_one(qapp):
    p=project();notes={'scribe':'本工程没有保存的 Scribe 转录。','alignment':'没有初稿流程。','local_original':'','local_vocals':'还没有人声辅助。','reading':'','chorus':''}
    options=TimingPlanOptions(p,1,[0,1],notes)
    assert not options.boxes['scribe'].isEnabled() and '没有保存的 Scribe' in options.boxes['scribe'].text()
    assert options.options()=={'indices':[1],'sources':['local_original','reading','chorus']}
    options.scope.setCurrentIndex(options.scope.findData('all'));assert options.indices()==[0,1]
    for kind in ('local_original','reading','chorus'):options.boxes[kind].setChecked(False)
    assert not options.ok.isEnabled() and '至少' in options.count.text();options.reject()


def test_dialog_keeps_current_by_default_marks_the_odd_syllable_and_records_choices(qapp):
    p=project();before=p.to_dict();report=report_for(p);playback=Playback()
    assert [v['status'] for v in report['lines']]==['conflict','agree']
    dialog=TimingPlanDialog(p,report,playback);dialog.show();qapp.processEvents()
    assert all(c.currentData()=='current' for c in dialog.controls) and not dialog.apply_button.isEnabled()
    assert not dialog.table.isRowHidden(0) and dialog.table.isRowHidden(1)
    col=[v['id'] for v in dialog.columns].index('local_original')
    assert dialog.grid.item(1,col).text().startswith('△') and not dialog.grid.item(0,col).text().startswith('△')
    assert dialog.grid.verticalHeaderItem(3).text()=='句尾'
    dialog.grid.setCurrentCell(1,col);dialog.listen_syllable();assert playback.calls[-1]==(850,1350)
    dialog.listen_plan();assert playback.calls[-1]==(100,1900)
    control=dialog.controls[0];assert control.findData('local_vocals')<0
    control.setCurrentIndex(control.findData('local_original'));dialog.update_apply()
    assert dialog.apply_button.isEnabled() and '1 句' in dialog.summary.text()
    dialog.choose();assert dialog.choices=={'a':'local_original'} and p.to_dict()==before


def test_only_the_changed_line_becomes_read_only(qapp):
    p=project();report=report_for(p);p.lines[1].translation='比对后改的译文'
    dialog=TimingPlanDialog(p,report,Playback());dialog.filter.setCurrentIndex(dialog.filter.findData('all'));dialog.show();qapp.processEvents()
    assert not dialog.stale and dialog.controls[0].isEnabled() and not dialog.controls[1].isEnabled()
    assert '已修改' in dialog.table.item(1,0).text() and '1 句' in dialog.note.text()
    p.lines[0].translation='也改了';dialog.reject()
    dialog=TimingPlanDialog(p,report,Playback());assert dialog.stale and not dialog.apply_button.isEnabled();dialog.reject()


def test_collect_reads_only_local_and_saved_sources_and_tries_other_readings(qapp,tmp_path,monkeypatch):
    p=project();calls=[];monkeypatch.setattr(acoustic_batch,'generate',fake_generate(calls))
    variant=copy.deepcopy(p.lines[0]);variant.units[0].kana='かなず';variant.units[0].highlights[-1].kana='ず';variant.kana='かなず'
    monkeypatch.setattr(timing_plans,'reading_variants',lambda line,*a,**k:[{'line':variant,'word':0,'text':'かなす','kana':'かなず','before':'かなす','source':'dictionary_entry','note':'第 1 词改读。'}] if line.id=='a' else [])
    data=timing_plan_sources.inputs(tmp_path,p);before=p.to_dict()
    report=timing_plan_sources.collect(p.lines,{'indices':[0,1],'sources':list(timing_plan_sources.SOURCES)},data,tmp_path,threading.Event())
    assert p.to_dict()==before and [c['choice'] for c in calls]==['original','original'] and all(c['track'] is None for c in calls)
    assert [r['id'] for r in calls[1]['rows']]==['a'] and calls[1]['rows'][0]['kana']=='かなず'
    entry=report['lines'][0];reading=next(v for v in entry['plans'] if v['kind']=='reading')
    assert reading['changes_reading'] and reading['reading']=='かなず'
    sources=report['sources']
    assert not sources['scribe']['available'] and 'Scribe' in sources['scribe']['note'] and not sources['alignment']['available'] and not sources['local_vocals']['available']
    assert sources['local_original']['available']


def window(qapp,tmp_path):
    media=tmp_path/'素材.mp4';media.write_bytes(b'not decoded in this test')
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    p=project();p.media=str(media);w.history=History(p);w.current=0;w.show();w.refresh();return w


OPTIONS={'indices':[0,1],'sources':['local_original','chorus']}


def test_check_is_read_only_then_review_adopts_once_and_undo_restores(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);before=w.project.to_dict();calls=[]
    assert w.timing_plans_button.isEnabled() and w.timing_plan_review.isHidden()
    monkeypatch.setattr(acoustic_batch,'generate',fake_generate(calls))
    assert w.run_timing_plans(OPTIONS)
    wait(qapp,lambda:w.source_job is None and w.pending is not None)
    assert w.project.to_dict()==before and w.pending['action']=='timing_plans' and not w.timing_plan_review.isHidden()
    assert '2 句时间方案' in w.review_button.text() and not w.timing_plans_button.isEnabled() and len(calls)==1
    def accept():
        dialog=next(d for d in w.findChildren(TimingPlanDialog) if d.isVisible())
        dialog.controls[0].setCurrentIndex(dialog.controls[0].findData('local_original'));dialog.update_apply();dialog.apply_button.click()
    QTimer.singleShot(20,accept);w.review_pending()
    line=w.project.lines[0];h=line.units[0].highlights
    assert [v.start for v in h]==[400,1000,1200] and w.project.lines[1].to_dict()==before['lines'][1] and len(w.history.undo_stack)==1
    assert line.timing_evidence['timing_plans'][-1]['plan']=='local_original' and not line.reviewed and line.translation==before['lines'][0]['translation']
    assert w.pending is None and '一步撤销' in w.status.text()
    w.undo();assert w.project.to_dict()==before;w.close()


def test_edit_during_comparison_is_kept_and_that_line_cannot_be_adopted(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);gate=threading.Event();calls=[]
    monkeypatch.setattr(acoustic_batch,'generate',fake_generate(calls,gate=gate))
    assert w.run_timing_plans(OPTIONS)
    w.edit('人工译文',lambda p:setattr(p.lines[0],'translation','不要覆盖'));before=w.project.to_dict();gate.set()
    wait(qapp,lambda:w.source_job is None and w.pending is not None)
    report=w.pending['result']['plan_report']
    assert not w.adopt_timing_plans(report,{'a':'local_original'}) and '已修改' in w.status.text()
    assert w.project.to_dict()==before and w.pending is not None;w.close()


def test_handoff_reaches_the_differing_syllable_without_changing_time(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);before=w.project.to_dict()
    monkeypatch.setattr(acoustic_batch,'generate',fake_generate([]))
    w.run_timing_plans(OPTIONS);wait(qapp,lambda:w.source_job is None and w.pending is not None)
    def handoff():
        dialog=next(d for d in w.findChildren(TimingPlanDialog) if d.isVisible());dialog.grid.setCurrentCell(1,0);dialog.calibrate_button.click()
    QTimer.singleShot(20,handoff);w.review_pending()
    assert w.pending is None and w.current==0 and (w.timeline.word,w.timeline.part)==(0,1) and w.project.to_dict()==before
    assert list((w.home/'desktop-tasks').glob('*/result.json'));w.close()


def test_issue_list_lists_disagreeing_lines_without_choosing_and_opens_the_comparison(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);before=w.project.to_dict()
    calls=[];monkeypatch.setattr(w,'start_timing_plans',lambda:calls.append('start'))
    monkeypatch.setattr(acoustic_batch,'generate',fake_generate([]))
    w.run_timing_plans(OPTIONS);wait(qapp,lambda:w.source_job is None and w.pending is not None)
    items=[v for v in collect(w.project,False,w.pending) if v.kind=='timing']
    assert [(v.row,v.word,v.part,v.severity) for v in items]==[(0,0,1,'warning')] and items[0].proposal=={}
    assert '本机模型 · 原声' in items[0].suggested and '200 ms' in items[0].title
    assert not [v for v in collect(w.project,False,w.pending) if v.kind=='proposal']
    opened=[];monkeypatch.setattr(w,'review_timing_plans',lambda:opened.append(w.current))
    w.manual_review_issue(items[0],specific=True);assert opened==[0] and not calls
    w.pending=None;w.manual_review_issue(items[0],specific=True);assert calls==['start']
    assert w.project.to_dict()==before;w.close()


def test_task_record_and_cancel_wording_name_the_comparison(qapp,tmp_path,monkeypatch):
    w=window(qapp,tmp_path);gate=threading.Event()
    monkeypatch.setattr(acoustic_batch,'generate',fake_generate([],gate=gate))
    w.run_timing_plans({'indices':[0],'sources':['local_original']});w.cancel_task();assert '多方案比对' in w.status.text();gate.set()
    wait(qapp,lambda:w.source_job is None)
    assert w.pending is None and '取消' in w.status.text();w.close()
