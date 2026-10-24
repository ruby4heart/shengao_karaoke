import copy
import json
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from shengao import acoustic_audio
from shengao.project import History,save_project,load_project
from shengao.time_transform import transform_project,TimeTransform
from shengao.recalculation_dialog import RecalculationDialog
from shengao.dialogs import ReviewDialog
from studio_backend.provenance import create
from studio_backend.recalculation import prepare
from test_guided_alignment import window as original_window
from test_acoustic_workflow import result,wait


def window(qapp,tmp_path,video,reviewed=False):
    w=original_window(qapp,tmp_path,video)
    for h in w.line.units[0].highlights:h.timing_origin=create('estimated',h.start,h.end,method='text_distribution')
    manual=w.line.units[0].highlights[1];manual.source='manual';manual.timing_origin['operations']=['manual_boundary']
    w.line.units[0].highlights[3].fixed_edges=['start']
    w.history=History(transform_project(w.project,[0],TimeTransform(offset=500)).project)
    w.current=0;w.line.reviewed=reviewed;w.refresh();return w


def test_existing_button_explains_old_protection_and_cancel_is_readonly(qapp,tmp_path,video):
    w=window(qapp,tmp_path,video);before=w.project.to_dict();seen=[]
    def choose():
        d=QApplication.activeModalWidget();assert isinstance(d,RecalculationDialog)
        try:
            assert not d.release.isChecked() and not d.run.isEnabled()
            d.release.setChecked(True);assert d.run.isEnabled();seen.append(len(d.prepared['recalculation']['released']))
        finally:d.reject()
    QTimer.singleShot(0,choose);w.acoustic_button.click()
    assert seen==[3] and w.source_job is None and w.project.to_dict()==before;w.close()


def test_actual_bulk_shift_can_be_recalculated_then_adopted_once(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);before=w.project.to_dict();monkeypatch.setattr(acoustic_audio,'generate',result)
    def choose():
        d=QApplication.activeModalWidget();d.release.setChecked(True);d.accept()
    QTimer.singleShot(0,choose);w.acoustic_button.click();wait(qapp,lambda:w.source_job is None)
    assert w.project.to_dict()==before and w.pending['plan']['recalculation']['released']
    w.apply_suggestions(w.pending['result']['suggestions'])
    assert not w.pending and w.line.units[0].highlights[1].__dict__==before['lines'][0]['units'][0]['highlights'][1]|{'fixed_edges':[]}
    assert w.line.units[0].highlights[3].start==4500 and w.line.units[0].highlights[3].fixed_edges==['start']
    assert w.line.start==1500 and w.line.end==5500 and w.project.checks['guide']['reading']
    assert all(w.line.units[0].highlights[i].source=='acoustic' for i in (0,2,3))
    path=tmp_path/'重新计算.sgproj';save_project(w.project,path);assert load_project(path).to_dict()==w.project.to_dict()
    w.undo();assert w.project.to_dict()==before;w.close()


def test_confirmed_line_requires_both_meaningful_choices_and_only_resets_on_adoption(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video,True);before=w.project.to_dict();monkeypatch.setattr(acoustic_audio,'generate',result)
    def choose():
        d=QApplication.activeModalWidget();d.release.setChecked(True);assert not d.run.isEnabled()
        d.reviewed.setChecked(True);assert d.run.isEnabled();d.accept()
    QTimer.singleShot(0,choose);w.acoustic_button.click();wait(qapp,lambda:w.source_job is None)
    assert w.project.to_dict()==before and w.line.reviewed
    d=ReviewDialog(w.project,w.pending['result'],w.playback,w);d.check_all(True);assert d.apply_button.isEnabled()
    w.apply_suggestions(d.selected());d.reject();assert not w.line.reviewed and w.project.checks['guide']['reading']
    w.undo();assert w.project.to_dict()==before;w.close()


def test_failure_retains_permission_request_and_manual_resume(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);before=w.project.to_dict()
    def fail(*_):raise ValueError('fixture model failure')
    monkeypatch.setattr(acoustic_audio,'generate',fail);assert w.align_acoustic(prepare(w.line));wait(qapp,lambda:w.source_job is None)
    assert not w.pending and w.project.to_dict()==before
    request=json.loads(next((w.home/'desktop-tasks').glob('*/request.json')).read_text(encoding='utf-8'))
    def manual():
        d=QApplication.activeModalWidget();assert isinstance(d,RecalculationDialog) and d.release.isChecked();d.go_manual()
    QTimer.singleShot(0,manual);assert w.resume_acoustic_recalculation(request)
    assert w.stage==2 and w.project.to_dict()==before;w.close()


def test_late_edit_and_missing_permission_do_not_overwrite_current_content(qapp,tmp_path,video,monkeypatch):
    w=window(qapp,tmp_path,video);monkeypatch.setattr(acoustic_audio,'generate',result)
    w.align_acoustic(prepare(w.line));wait(qapp,lambda:w.source_job is None)
    before=w.project.to_dict();saved=copy.deepcopy(w.pending);w.pending.pop('plan')
    w.apply_suggestions(w.pending['result']['suggestions']);assert w.project.to_dict()==before and w.pending
    w.pending=saved;w.edit('人工译文',lambda p:setattr(p.lines[0],'translation','保留修改'));before=w.project.to_dict()
    w.apply_suggestions(w.pending['result']['suggestions']);assert w.project.to_dict()==before and w.pending;w.close()


def test_corrupt_saved_choices_do_not_open_or_mutate(qapp,tmp_path,video):
    w=window(qapp,tmp_path,video);before=w.project.to_dict()
    assert not w.resume_acoustic_recalculation({'plan':True,'_studio_context':{}})
    assert not w.open_acoustic_recalculation({'release_old_protection':'true'})
    assert w.project.to_dict()==before and w.source_job is None;w.close()


def test_partial_return_states_scope_and_preserves_failed_interval(qapp,tmp_path,video,monkeypatch):
    from test_recalculation_cache import inference
    from studio_backend.acoustic import propose
    from shengao.vocal_audio import digest
    w=window(qapp,tmp_path,video);before=w.project.to_dict()
    def partial(plan,source,*_):
        raw=inference(plan);raw['jobs'][0]={'index':0,'error':'fixture failure'};fingerprint=digest(source)
        new=propose(plan,raw,fingerprint,'b'*64,'original')
        return {'ok':True,'action':'acoustic','suggestions':[new.to_dict()],'source_sha256':fingerprint}
    monkeypatch.setattr(acoustic_audio,'generate',partial);w.align_acoustic(prepare(w.line));wait(qapp,lambda:w.source_job is None)
    assert w.pending['result']['partial'] and '2/3' in w.pending['result']['message'] and '部分' in w.status.text()
    w.apply_suggestions(w.pending['result']['suggestions'])
    assert w.line.units[0].highlights[0].__dict__==before['lines'][0]['units'][0]['highlights'][0]|{'fixed_edges':[]}
    w.undo();assert w.project.to_dict()==before;w.close()


def test_manual_mora_can_bound_guided_range_without_changing_it(qapp,tmp_path,video):
    from shengao.guide_dialog import GuideDialog
    w=original_window(qapp,tmp_path,video);w.line.start=900;w.line.end=5600;u=w.line.units[0];u.start=900;u.end=5600;u.source='manual'
    u.highlights[0].fixed_edges=['start'];u.highlights[2].source='manual';before=w.project.to_dict()
    d=GuideDialog(w.line,w.playback,w);d.mora.setCurrentIndex(2);d.edge.setCurrentIndex(1)
    assert d.time.isReadOnly() and not d.use_playhead.isEnabled() and d.add.isEnabled()
    d.add.click();assert d.run.isEnabled() and len(d.prepared['jobs'])==1
    assert d.prepared['jobs'][0]['start']==1000 and d.prepared['baseline']['units'][0]['highlights'][2].get('fixed_edges',[])==[]
    d.reject();assert w.project.to_dict()==before;w.close()
