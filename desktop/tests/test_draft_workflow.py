import copy
import json
import time
import uuid
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QDialog,QDialogButtonBox
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.project import History,file_stamp,save_project,load_project
from shengao.theme import STYLE
from shengao.draft_workflow import DraftDialog,ResumeDraftDialog
from studio_backend import draft
from studio_backend.model import LyricLine,Unit
from studio_backend.settings import atomic_json


def wait(qapp,fn,seconds=15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        qapp.processEvents();QTest.qWait(20)
        if fn():return True
    return False


def window(qapp,tmp_path,project):
    qapp.setStyleSheet(STYLE);p=copy.deepcopy(project)
    for line in p.lines:
        line.reviewed=False
        for unit in line.units:
            unit.source='estimated'
            for part in unit.highlights:part.source='estimated'
    w=StudioWindow(home=tmp_path/'home',test=True);w.history=History(p);w.current=0;w.playback.audio.setMuted(True);w.show();w.refresh();w.set_stage(1);qapp.processEvents();return w


def choose(w,cls,callback):
    def active():
        dialog=next((d for d in w.findChildren(cls) if d.isVisible()),None)
        assert dialog is not None;callback(dialog)
    QTimer.singleShot(30,active)


def accept(dialog):dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()


def test_real_offline_process_stage_results_review_undo_and_reopen(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);before=w.project.to_dict();seen=[]
    w.api.workflowChanged.connect(lambda state:seen.append(state))
    choose(w,DraftDialog,accept);w.draft_button.click()
    assert w.api.busy and w.project.to_dict()==before
    assert wait(qapp,lambda:not w.api.busy and w.pending),w.status.text()
    result=w.pending['result'];assert not result['partial'] and len(result['workflow']['stages'])==6
    assert w.project.to_dict()==before and '准备审核' in w.draft_status.text()
    w.apply_suggestions(result['suggestions']);assert w.project.lines[0].units[0].highlights and not w.line.reviewed
    w.path=tmp_path/'workflow.sgproj';assert w.save();assert load_project(w.path).lines[0].to_dict()==w.line.to_dict()
    w.undo();assert w.project.to_dict()==before;w.close()


def test_late_manual_changes_remain_protected_and_other_suggestions_stay_reviewable(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);choose(w,DraftDialog,accept);w.start_draft()
    w.edit('manual input',lambda p:setattr(p.lines[0],'translation','人工译文'))
    assert wait(qapp,lambda:not w.api.busy and w.pending),w.status.text()
    w.apply_suggestions(w.pending['result']['suggestions'])
    assert w.line.translation=='人工译文' and w.pending and '保留' in w.status.text();w.close()


def test_complete_workflow_resumes_after_reopen_without_keys_and_uses_original_snapshots(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);choose(w,DraftDialog,accept);w.start_draft()
    assert wait(qapp,lambda:not w.api.busy and w.pending)
    workflow_id=w.pending['result']['workflow']['id'];save_project(w.project,tmp_path/'original.sgproj');home=w.home;w.close();qapp.processEvents()
    reopened=StudioWindow(home=home,test=True);reopened.history=History(load_project(tmp_path/'original.sgproj'));reopened.current=0;reopened.show();reopened.refresh();reopened.set_stage(1)
    original=reopened.line.to_dict();choose(reopened,ResumeDraftDialog,accept);reopened.resume_draft()
    assert wait(qapp,lambda:not reopened.api.busy and reopened.pending)
    assert reopened.pending['result']['workflow']['id']==workflow_id and reopened.pending['snapshots'][original['id']]==original
    assert not reopened.pending['result']['partial'];reopened.close()


def test_resume_never_attaches_old_workflow_to_replaced_source(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);choose(w,DraftDialog,accept);w.start_draft();assert wait(qapp,lambda:not w.api.busy and w.pending)
    workflow_id=w.pending['result']['workflow']['id'];w.project.media=str(tmp_path/'another.wav');w.resume_draft(workflow_id)
    assert not w.api.busy and '另一工程或素材' in w.status.text();w.close()


def test_unknown_paid_stage_requires_explicit_retry_and_partial_review_stays_available(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project)
    state={'id':uuid.uuid4().hex,'version':1,'status':'paused','request':{'lines':[w.line.to_dict()]},'message':'模拟网络中断','stages':[
        {'key':'matching','title':'按原歌词匹配','paid':False,'state':'completed','result':{'suggestions':[w.line.to_dict()]}},
        {'key':'readings','title':'生成读音建议','paid':True,'state':'running'}]}
    dialog=ResumeDraftDialog(w,state,1);dialog.show();qapp.processEvents()
    assert dialog.retry_stage=='readings' and not dialog.continue_button.isEnabled() and dialog.review_button.isEnabled()
    dialog.retry.click();assert dialog.continue_button.isEnabled();dialog.retry.click();assert not dialog.continue_button.isEnabled()
    dialog.review_button.click();assert dialog.review_only and dialog.result()==QDialog.DialogCode.Accepted
    w.close()


def test_draft_configuration_makes_uploads_optional_and_disables_stale_transcript(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);dialog=DraftDialog(w,1,2,False);dialog.show();qapp.processEvents()
    assert dialog.options()=={'source':'offline','provider':'elevenlabs','readings':'dictionary','align':False}
    assert not dialog.source.model().item(1).isEnabled()
    dialog.source.setCurrentIndex(2);assert dialog.provider.isVisible();dialog.llm.click();dialog.align.click()
    assert dialog.options()['readings']=='deepseek' and dialog.options()['align'];dialog.close();w.close()


def test_protected_lines_are_excluded_before_any_worker_submission(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.line.units[0].source='manual'
    calls=[];w.api.start=lambda request:calls.append(request)
    def reject(dialog):
        assert not dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).isEnabled();dialog.reject()
    choose(w,DraftDialog,reject);w.start_draft();assert calls==[];w.close()


def test_confirmed_reading_survives_adopting_time_only_workflow_draft(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.project.checks[w.line.id]={'reading':True}
    choose(w,DraftDialog,accept);w.start_draft();assert wait(qapp,lambda:not w.api.busy and w.pending)
    assert w.pending['result']['suggestions'][0]['kana']==w.line.kana
    w.apply_suggestions(w.pending['result']['suggestions']);assert w.project.checks[w.line.id]['reading'] and not w.line.reviewed;w.close()


def test_partial_edit_preview_blocks_both_workflow_entry_points(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.set_stage(2);w.resegment_current();w.inline_segment.whole.click()
    assert w.inline_segment.pending and not w.draft_button.isEnabled() and not w.draft_resume_button.isEnabled()
    calls=[];w.api.start=lambda request:calls.append(request);w.start_draft();w.resume_draft();assert not calls;w.close()


def test_reading_confirmation_during_background_job_blocks_stale_adoption(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);choose(w,DraftDialog,accept);w.start_draft()
    w.confirm_reading(True);assert wait(qapp,lambda:not w.api.busy and w.pending)
    old=w.line.to_dict();w.apply_suggestions(w.pending['result']['suggestions'])
    assert w.line.to_dict()==old and w.project.checks[w.line.id]['reading'] and w.pending and '保留' in w.status.text();w.close()


def test_pending_without_suggestions_is_recoverable_flow_not_empty_review(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.api.request={'action':'draft','_studio_context':{'project':w.project.uid,'media':file_stamp(w.project.media)}}
    w.api_done({'ok':True,'suggestions':[],'partial':True,'message':'先设置 DeepSeek 再继续','workflow':{
        'id':uuid.uuid4().hex,'status':'paused','context':w.api.request['_studio_context'],'stages':[],'message':'先设置 DeepSeek 再继续'}})
    assert w.pending is None and not w.review_button.isVisible() and 'DeepSeek' in w.draft_status.text();w.close()


def test_missing_final_ipc_result_recovers_completed_checkpoint_after_process_finished(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);choose(w,DraftDialog,accept);w.start_draft()
    assert wait(qapp,lambda:not w.api.busy and w.pending),w.status.text()
    from shengao.api_jobs import ApiJob
    job=ApiJob(home=w.home);job.request=copy.deepcopy(w.api.request);job.result=tmp_path/'never-written-result.json';received=[]
    job.completed.connect(received.append)
    class TerminatedProcess:
        def readAllStandardError(self):return b''
        def deleteLater(self):pass
    job.process=TerminatedProcess();job.finish(1,None)
    assert received and received[0]['workflow']['status']=='completed' and received[0]['suggestions'];w.close()
