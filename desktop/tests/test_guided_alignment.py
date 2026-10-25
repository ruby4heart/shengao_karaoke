import copy
import json
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QDialog
from shengao.app import StudioWindow
from shengao.project import Project,History,file_stamp,save_project,load_project,SCHEMA
from shengao.guide_dialog import GuideDialog
from shengao import acoustic_audio
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.acoustic_guides import prepare
from test_acoustic_workflow import result,wait


def window(qapp,tmp_path,video):
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    highlights=[Highlight(c,1000+i*1000,2000+i*1000) for i,c in enumerate('あいうえ')]
    line=LyricLine('guide','合言葉',1000,5000,[Unit('合言葉',1000,5000,'あいうえ',highlights=highlights)],kana='あいうえ')
    w.history=History(Project(media=str(video),media_stamp=file_stamp(video),duration=8000,lines=[line],checks={'guide':{'reading':True}}));w.current=0;w.refresh()
    return w


def points():return [dict(unit=0,highlight=1,edge='start',time=2400),dict(unit=0,highlight=2,edge='end',time=3800)]


def test_dialog_uses_original_axis_point_controls_and_cancel_is_readonly(qapp,tmp_path,video):
    w=window(qapp,tmp_path,video);before=w.project.to_dict();saved=[]
    d=GuideDialog(w.line,w.playback,w,save=lambda value:saved.append(copy.deepcopy(value)))
    d.show();qapp.processEvents();assert not d.run.isEnabled()
    old_time=d.time.value();w.playback.canvas.position=6000;d.use_playhead.click()
    assert d.time.value()==old_time and '超出本句' in d.status.text()
    d.mora.setCurrentIndex(1);d.edge.setCurrentIndex(0);d.time.setValue(2400);d.add.click()
    assert len(d.points)==1 and not d.run.isEnabled()
    d.mora.setCurrentIndex(2);d.edge.setCurrentIndex(1);d.time.setValue(3800);d.add.click()
    assert d.run.isEnabled() and len(d.prepared['jobs'])==1
    d.mode.setCurrentIndex(1);assert not d.timeline.show_spectrum
    assert d.timeline.view_renderer and not d.timeline.editing_enabled
    assert d.buttons.geometry().bottom()<=d.height()
    d.reject();assert saved[-1]['points']==points() and w.project.to_dict()==before
    w.close()


def test_entry_saves_draft_and_reopens_without_touching_project(qapp,tmp_path,video):
    w=window(qapp,tmp_path,video);before=w.project.to_dict();seen=[]
    def first():
        d=QApplication.activeModalWidget();assert isinstance(d,GuideDialog)
        try:
            for p in points():
                d.mora.setCurrentIndex(p['highlight']);d.edge.setCurrentIndex(0 if p['edge']=='start' else 1);d.time.setValue(p['time']);d.add.click()
        finally:d.reject()
    QTimer.singleShot(0,first);assert not w.open_acoustic_guides()
    def reopen():
        d=QApplication.activeModalWidget()
        try:seen.append(copy.deepcopy(d.points));assert d.run.isEnabled()
        finally:d.reject()
    QTimer.singleShot(0,reopen);w.guide_button.click()
    assert seen==[points()] and w.project.to_dict()==before
    stored=json.loads(w.guide_draft_path().read_text(encoding='utf-8'))
    assert stored['line']==w.line.to_dict() and stored['draft']['points']==points();w.close()


def test_guided_proposal_review_save_undo_and_release_fixed_points(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);before=w.project.to_dict();monkeypatch.setattr(acoustic_audio,'generate',result)
    p=prepare(w.line,points());assert w.align_acoustic(p);wait(qapp,lambda:w.source_job is None)
    assert w.project.to_dict()==before and w.pending['plan']==p
    w.apply_suggestions(w.pending['result']['suggestions'])
    assert not w.pending and w.line.units[0].highlights[1].start==2400
    assert w.line.units[0].highlights[2].end==3800 and w.project.checks['guide']['reading']
    target=tmp_path/'固定点.sgproj';save_project(w.project,target)
    assert load_project(target).to_dict()==w.project.to_dict() and SCHEMA==13
    with pytest.raises(ValueError,match='11'):Project.from_dict({**w.project.to_dict(),'version':10})
    w.select_target(0,1);times=w.selected_times();assert w.release_acoustic_guide()
    assert not w.line.units[0].highlights[1].fixed_edges and w.selected_times()==times
    w.undo();assert w.line.units[0].highlights[1].fixed_edges==['start']
    w.undo();assert w.project.to_dict()==before;w.close()


def test_guided_failure_retains_request_draft_and_manual_handoff(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);before=w.project.to_dict()
    def fail(*_):raise ValueError('fixture 模型失败')
    monkeypatch.setattr(acoustic_audio,'generate',fail)
    assert w.align_acoustic(prepare(w.line,points()));wait(qapp,lambda:w.source_job is None)
    assert w.project.to_dict()==before and not w.pending
    folders=list((w.home/'desktop-tasks').iterdir());assert len(folders)==1
    request=json.loads((folders[0]/'request.json').read_text(encoding='utf-8'))
    assert request['plan']['guide_points']==points()
    def manual():
        d=QApplication.activeModalWidget()
        assert isinstance(d,GuideDialog) and d.points==points();d.mora.setCurrentIndex(2);d.go_manual()
    QTimer.singleShot(0,manual);assert w.resume_acoustic_guides(request)
    assert w.current==0 and w.timeline.part==2 and w.project.to_dict()==before;w.close()


def test_late_manual_change_blocks_guided_adoption(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);monkeypatch.setattr(acoustic_audio,'generate',result)
    w.align_acoustic(prepare(w.line,points()));wait(qapp,lambda:w.source_job is None)
    w.edit('人工译文',lambda p:setattr(p.lines[0],'translation','人工保留'));before=w.project.to_dict()
    w.apply_suggestions(w.pending['result']['suggestions'])
    assert w.project.to_dict()==before and w.pending;w.close()


def test_shelved_review_retains_exact_guide_request(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);monkeypatch.setattr(acoustic_audio,'generate',result)
    prepared=prepare(w.line,points());w.align_acoustic(prepared);wait(qapp,lambda:w.source_job is None)
    assert w.shelve_for_manual('guide')
    saved=[json.loads(p.read_text(encoding='utf-8')) for p in (w.home/'desktop-tasks').glob('*/request.json')]
    assert any(v['action']=='review_saved' and v['plan']==prepared and v['_studio_origin_action']=='acoustic' for v in saved)
    w.close()


def test_missing_request_rejects_guided_suggestion_without_modifying_project(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);monkeypatch.setattr(acoustic_audio,'generate',result)
    before=w.project.to_dict();w.align_acoustic(prepare(w.line,points()));wait(qapp,lambda:w.source_job is None)
    w.pending.pop('plan');w.apply_suggestions(w.pending['result']['suggestions'])
    assert w.project.to_dict()==before and w.pending and '缺少原始固定点' in w.status.text();w.close()


def test_unwritable_draft_never_starts_model_or_reports_saved(qapp,tmp_path,video):
    w=window(qapp,tmp_path,video);before=w.project.to_dict()
    def fail(_):raise OSError('fixture disk unavailable')
    d=GuideDialog(w.line,w.playback,w,{'points':points(),'scope':'between'},fail)
    assert not d.run.isEnabled() and not d.draft_saved and '无法保存' in d.status.text()
    d.accept();assert d.result()!=QDialog.DialogCode.Accepted
    d.reject();assert w.source_job is None and w.project.to_dict()==before;w.close()


def test_normal_model_result_cannot_label_new_human_fixed_edge(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);before=w.project.to_dict();monkeypatch.setattr(acoustic_audio,'generate',result)
    w.align_acoustic();wait(qapp,lambda:w.source_job is None)
    w.pending['result']['suggestions'][0]['units'][0]['highlights'][0]['fixed_edges']=['start']
    w.apply_suggestions(w.pending['result']['suggestions'])
    assert w.project.to_dict()==before and w.pending and '不能新建人工固定点' in w.status.text();w.close()


def test_existing_fixed_point_is_not_duplicated_when_restoring_task_draft(qapp,tmp_path,video):
    w=window(qapp,tmp_path,video);w.line.units[0].highlights[1].fixed_edges=['start']
    p=points();p[0]['time']=2000
    d=GuideDialog(w.line,w.playback,w,{'points':p,'scope':'between'})
    assert len(d.entries)==2 and len(d.points)==1 and d.run.isEnabled()
    d.reject();w.close()
