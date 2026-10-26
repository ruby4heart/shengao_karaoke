import copy
import hashlib
import json
import time
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog,QDialogButtonBox
from shengao.app import StudioWindow
from shengao.project import Project,History,file_stamp,save_project,load_project
from shengao.recognition_workflow import RecognitionChoiceDialog,RecognitionDialog
from shengao.theme import STYLE
from studio_backend import recognition
from studio_backend.model import LyricLine,Unit


def raw():
    text='今日 も 歌う'
    return [LyricLine('raw',text,1000,2400,[Unit(c,1000+i*200,1200+i*200,source='recognition') for i,c in enumerate(text)]).to_dict()]


def wait(qapp,fn,seconds=15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        qapp.processEvents();QTest.qWait(20)
        if fn():return True
    return False


def window(qapp,tmp_path,project,with_draft=True):
    qapp.setStyleSheet(STYLE);p=copy.deepcopy(project);p.lines=[];p.checks={};p.source_ass='';p.source_ass_active=False
    p.transcript=raw();p.transcript_stamp=file_stamp(p.media);p.transcript_fingerprint=hashlib.sha256(__import__('pathlib').Path(p.media).read_bytes()).hexdigest()
    if with_draft:p.recognition_draft=recognition.create(p.transcript,p.transcript_stamp,p.transcript_fingerprint)
    w=StudioWindow(home=tmp_path/'home',test=True);w.history=History(p);w.current=-1;w.playback.audio.setMuted(True);w.show();w.refresh();w.set_stage(1);qapp.processEvents();return w


def choose(w,cls,callback):
    def active():
        d=next((d for d in w.findChildren(cls) if d.isVisible()),None);assert d is not None;callback(d)
    QTimer.singleShot(35,active)


def accept(dialog):dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()


def test_reuse_recognition_with_no_lyrics_is_local_and_preserves_original(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project,False);before=copy.deepcopy(w.project.transcript);calls=[];w.review_recognition=lambda:calls.append('review')
    def reuse(d):assert d.mode.currentData()=='reuse';accept(d)
    choose(w,RecognitionChoiceDialog,reuse);w.begin_recognition()
    assert not w.api.busy and not w.project.lines and w.project.recognition_draft and calls==['review']
    assert w.project.transcript==before and w.project.recognition_draft['rows'][0]['text']=='今日も歌う'
    assert '核对' in w.next_button.text() and '待确认' in w.current_text.text();w.close()


def test_new_recognition_request_allows_empty_lyrics_and_result_remains_unconfirmed(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project,False);w.project.transcript=[];w.project.transcript_stamp={};w.project.transcript_fingerprint='';calls=[]
    w.api.start=lambda request:calls.append(request)
    choose(w,RecognitionChoiceDialog,accept);w.begin_recognition();request=calls[0]
    assert request['action']=='transcribe' and request['lines']==[] and request['_recognition_entry']
    w.api.request=request;w.api_done({'ok':True,'suggestions':raw(),'media_fingerprint':hashlib.sha256(__import__('pathlib').Path(w.project.media).read_bytes()).hexdigest()})
    assert not w.project.lines and w.project.recognition_draft and w.pending is None
    assert w.recognition_generate_button.isVisible() and not w.draft_button.isVisible();w.close()


def test_original_lyrics_added_during_recognition_take_priority(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project,False);w.api.request={'action':'transcribe','_studio_context':{'project':w.project.uid,'media':file_stamp(w.project.media)}}
    w.edit('paste actual lyrics',lambda p:p.replace_lyrics('人が用意した 原詞'));original=[x.to_dict() for x in w.project.lines]
    w.api_done({'ok':True,'suggestions':raw()})
    assert [x.to_dict() for x in w.project.lines]==original and not w.project.recognition_draft and w.project.transcript==raw()
    assert '原歌词保持' in w.status.text();w.close()


def test_dialog_edit_split_merge_delete_and_undo_preserve_raw_evidence(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);source=copy.deepcopy(w.project.transcript);d=RecognitionDialog(w,w.project.recognition_draft,source,w.playback);d.show();qapp.processEvents()
    d.editor.setCursorPosition(2);d.split_button.click();assert [r['text'] for r in d.value['rows']]==['今日','も歌う']
    d.merge_button.click();assert d.value['rows'][0]['text']=='今日も歌う';d.undo_button.click();assert len(d.value['rows'])==2
    d.delete_button.click();assert len(d.value['rows'])==1;d.undo_button.click();assert len(d.value['rows'])==2
    d.add_button.click();assert len(d.value['rows'])==3 and not d.confirm_button.isEnabled()
    d.undo_button.click();assert len(d.value['rows'])==2 and d.confirm_button.isEnabled()
    assert recognition.source_text(d.value['rows'][0],source).startswith('今日') and source==raw();d.reject();w.close()


def test_partial_text_edits_persist_when_dialog_closes_and_project_reopens(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);source=copy.deepcopy(w.project.transcript)
    def edit_and_close(d):d.editor.setText('今日 も 歌おう ');d.editor.textEdited.emit(d.editor.text());d.reject()
    choose(w,RecognitionDialog,edit_and_close);w.review_recognition()
    assert not w.api.busy and not w.project.lines and w.project.recognition_draft['rows'][0]['text']=='今日 も 歌おう '
    w.path=tmp_path/'unconfirmed.sgproj';assert w.save();loaded=load_project(w.path)
    assert loaded.recognition_draft==w.project.recognition_draft and loaded.transcript==source and loaded.transcript_fingerprint==w.project.transcript_fingerprint
    assert loaded.to_dict()['version']==14;w.close()


def test_confirmed_text_enters_editable_rough_axis_one_undo_and_keeps_checks_separate(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);source=copy.deepcopy(w.project.transcript)
    def confirm(d):d.editor.setText('今日も歌おう');d.editor.textEdited.emit(d.editor.text());d.confirm()
    choose(w,RecognitionDialog,confirm);w.review_recognition()
    assert w.api.busy and w.project.recognition_draft and not w.project.lines
    assert wait(qapp,lambda:not w.api.busy and w.project.lines),w.status.text()
    assert w.line.text=='今日も歌おう' and w.line.match['text_confirmed'] and not w.line.reviewed
    assert w.playback.canvas.position==w.line.start
    assert not w.project.checks[w.line.id]['reading'] and all(u.highlights for u in w.line.units)
    assert not w.project.recognition_draft and w.project.transcript==source and w.stage==2
    w.undo();assert not w.project.lines and w.project.recognition_draft['rows'][0]['text']=='今日も歌おう'
    w.redo();assert w.line.text=='今日も歌おう';w.path=tmp_path/'confirmed.sgproj';assert w.save()
    assert load_project(w.path).lines[0].to_dict()==w.line.to_dict();w.close()


def test_manual_draft_change_while_local_worker_runs_cannot_be_overwritten(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.confirm_recognition()
    w.edit('late text correction',lambda p:p.recognition_draft['rows'][0].__setitem__('text','人工修正原文'))
    assert wait(qapp,lambda:not w.api.busy)
    assert not w.project.lines and w.project.recognition_draft['rows'][0]['text']=='人工修正原文'
    assert '没有覆盖' in w.status.text();w.close()


def test_restore_confirm_task_recovers_edited_wording_as_draft_without_cloud(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.project.recognition_draft['rows'][0]['text']='今日も歌おう';w.confirm_recognition()
    request=copy.deepcopy(w.api.request);assert wait(qapp,lambda:not w.api.busy and w.project.lines)
    result=json.loads(w.api.result.read_text(encoding='utf-8'))
    w.history=History(Project.from_dict({**w.project.to_dict(),'lines':[],'transcript':[],'recognition_draft':{},'transcript_fingerprint':'','checks':{}}));w.current=-1;w.refresh()
    captured=[]
    def review(d):captured.append(d.editor.text());d.reject()
    choose(w,RecognitionDialog,review);w.restore_recognition_result(request,result,w.api.folder)
    assert captured==['今日も歌おう'] and w.project.recognition_draft and not w.api.busy and not w.project.lines;w.close()


def test_new_result_does_not_replace_a_draft_already_being_edited(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);before=w.project.to_dict()
    req={'action':'transcribe','_studio_context':{'project':w.project.uid,'media':file_stamp(w.project.media)}}
    w.handle_recognition_result({'suggestions':raw()},req)
    assert w.project.to_dict()==before and '没有替换' in w.status.text();w.close()


def test_discard_is_reversible_and_keeps_raw_transcription_for_free_reuse(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);before=copy.deepcopy(w.project.recognition_draft);source=copy.deepcopy(w.project.transcript)
    w.discard_recognition();assert not w.project.recognition_draft and w.project.transcript==source
    w.undo();assert w.project.recognition_draft==before;w.close()


def test_audition_speed_and_loop_restore_without_confirming_lyrics(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.playback.open(w.project.media);assert wait(qapp,lambda:w.playback.player.duration()>0)
    d=RecognitionDialog(w,w.project.recognition_draft,w.project.transcript,w.playback);d.show();qapp.processEvents()
    d.speed.setCurrentIndex(1);d.loop.setChecked(True);d.context_button.click()
    assert w.playback.range==(650,2750) and w.playback.player.playbackRate()==.75
    d.reject();assert w.playback.range is None and w.playback.player.playbackRate()==1. and not w.playback.loop and not w.project.lines;w.close()


def test_pasting_correct_original_lyrics_clears_only_candidate_and_can_be_undone(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);before=w.project.to_dict();w.edit('paste correct lyrics',lambda p:p.replace_lyrics('確かな 原詞'))
    assert w.line.text=='確かな 原詞' and not w.project.recognition_draft and w.project.transcript==before['transcript']
    w.undo();assert w.project.to_dict()==before;w.close()


def test_project_accepts_old_schema_and_rejects_unknown_future_or_mismatched_draft(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);data=w.project.to_dict();assert Project.from_dict({**data,'version':4}).recognition_draft
    from shengao.project import SCHEMA
    with pytest.raises(ValueError):Project.from_dict({**data,'version':SCHEMA+1})
    bad=copy.deepcopy(data);bad['transcript_fingerprint']='a'*64
    with pytest.raises(ValueError,match='指纹不一致'):Project.from_dict(bad)
    old={**data,'version':4};old.pop('recognition_draft');old.pop('transcript_fingerprint')
    assert Project.from_dict(old).recognition_draft=={} and Project.from_dict(old).transcript_fingerprint==''
    w.close()


def test_dialog_keyboard_undo_redo_in_text_field_include_structural_changes(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);d=RecognitionDialog(w,w.project.recognition_draft,w.project.transcript,w.playback);d.show();qapp.processEvents()
    d.editor.setCursorPosition(2);d.split_button.click();assert len(d.value['rows'])==2
    d.editor.setFocus();QTest.keyClick(d.editor,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier)
    assert len(d.value['rows'])==1
    QTest.keyClick(d.editor,Qt.Key.Key_Y,Qt.KeyboardModifier.ControlModifier);assert len(d.value['rows'])==2
    d.reject();w.close()


def test_dialog_cursor_after_supplementary_character_splits_at_visual_position(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);source=[LyricLine('rare','𠮷野',1000,2000,[Unit('𠮷',1000,1500,source='recognition'),Unit('野',1500,2000,source='recognition')]).to_dict()]
    value=recognition.create(source,file_stamp(w.project.media));d=RecognitionDialog(w,value,source,w.playback);d.show();qapp.processEvents()
    d.editor.setCursorPosition(2);d.split_button.click();assert [r['text'] for r in d.value['rows']]==['𠮷','野']
    d.reject();w.close()


def test_late_recognition_result_for_other_media_never_enters_project(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project,False);before=w.project.to_dict()
    w.handle_recognition_result({'suggestions':raw()},{'action':'transcribe','_studio_context':{'project':w.project.uid,'media':{'path':'old'}}})
    assert w.project.to_dict()==before and '没有写入' in w.status.text();w.close()


def test_small_recognition_dialog_keeps_confirmation_reachable_without_side_scroll(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);d=RecognitionDialog(w,w.project.recognition_draft,w.project.transcript,w.playback);d.resize(760,520);d.show();qapp.processEvents()
    assert d.confirm_button.isVisible() and d.confirm_button.visibleRegion().boundingRect().height()>20
    assert d.controls_scroll.horizontalScrollBar().maximum()==0
    d.controls_scroll.ensureWidgetVisible(d.editor);qapp.processEvents();assert d.editor.visibleRegion().boundingRect().height()>15
    d.reject();w.close()
