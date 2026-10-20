import copy
from pathlib import Path
from PySide6.QtWidgets import QApplication,QLineEdit,QDialogButtonBox
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.project import History,file_stamp
from shengao.draft_workflow import DraftDialog
from shengao.dialogs import ReviewDialog

def test_api_completion_keeps_unsubmitted_editor_and_time_with_paid_transcript(qapp,tmp_path,project):
    w=StudioWindow(tmp_path/'home',test=True);w.history=History(project);w.current=0;w.show();w.refresh();w.set_stage(2);qapp.processEvents()
    w.begin.setValue(1234);w.units.editItem(w.units.item(0,1));qapp.processEvents()
    editor=next(e for e in w.units.findChildren(QLineEdit) if e.isVisible());editor.setText('てすと')
    w.snapshots={v.id:v.to_dict() for v in project.lines};w.api.request={'action':'draft','_studio_context':{'project':project.uid,'media':file_stamp(project.media)}}
    result={'suggestions':[v.to_dict() for v in project.lines],'transcript':[project.lines[0].to_dict()],'media_fingerprint':'a'*64,'workflow':{'id':'a'*32,'status':'completed','stages':[],'context':w.api.request['_studio_context']}}
    w.api_done(result)
    assert editor.text()=='てすと' and w.begin.value()==1234 and w.project.transcript and w.pending
    w.close()


def test_user_can_revert_active_reading_after_background_persistence(qapp,tmp_path,project,monkeypatch):
    w=StudioWindow(tmp_path/'home',test=True);w.history=History(project);w.current=0;w.show();w.refresh();w.set_stage(2);qapp.processEvents()
    previous=w.line.units[0].kana;w.quick_reading.click();editor=QApplication.focusWidget()
    assert isinstance(editor,QLineEdit) and w.units.isAncestorOf(editor)
    # Captured from full-suite Qt row selection: column 0 is current even
    # while the live delegate editor belongs to the kana cell in column 1.
    monkeypatch.setattr(w.units,'currentColumn',lambda:0)
    editor.setText('てすと');editor.setCursorPosition(1)
    w.keep_background_reading();assert editor.cursorPosition()==1 and w.line.units[0].kana=='てすと'
    editor.setText(previous);assert w.flush_edits() and w.line.units[0].kana==previous;w.close()

def test_pipeline_dialog_footer_is_reachable_and_source_summary_is_explicit(qapp,tmp_path,project,video):
    w=StudioWindow(tmp_path/'home',test=True);w.history=History(project);w.project.media=str(video)
    d=DraftDialog(w,1,0,False);d.resize(620,420);d.show();qapp.processEvents()
    assert not d.acoustic.isChecked();d.source.setCurrentIndex(2);assert d.acoustic.isChecked() and '使用额度' in d.overview.text() and '歌声音节' in d.overview.text()
    buttons=d.findChild(QDialogButtonBox);assert buttons.isVisible() and buttons.geometry().bottom()<=d.height()
    assert d.options()['acoustic_audio']=='auto' and d.options()['fit_range']
    d.acoustic.setChecked(False);assert 'acoustic' not in d.options();d.reject();w.close()

def test_batch_review_distinguishes_failed_and_unfinished_rows(qapp,tmp_path,project):
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    values=[v.to_dict() for v in project.lines]
    result={'suggestions':values,'acoustic':{'lines':{values[0]['id']:{'status':'needs_manual','reason':'假名缺失'}}}}
    d=ReviewDialog(project,result,w.playback,w)
    assert d.table.columnCount()==5 and '需手工' in d.table.item(0,4).text()
    assert '假名缺失' in d.details.toPlainText() and not d.acoustic_mora.isVisible()
    d.reject();w.close()

def test_manual_handoff_persists_suggestions_before_opening_same_editor(qapp,tmp_path,project):
    import json
    w=StudioWindow(tmp_path/'home',test=True);w.history=History(project);w.current=0;w.refresh();before=w.project.to_dict()
    uid=project.lines[0].id;values=[v.to_dict() for v in project.lines]
    w.pending={'action':'draft','result':{'suggestions':values,'acoustic':{'lines':{uid:{'status':'needs_manual','reason':'假名缺失'}}}},'snapshots':{v['id']:v for v in values},'context':{},'checks':copy.deepcopy(project.checks)}
    w.shelve_for_manual(uid)
    assert w.pending is None and w.stage==2 and w.line.id==uid and w.project.to_dict()==before and w.acoustic_button.isEnabled()==bool(project.media)
    folder=next((w.home/'desktop-tasks').iterdir());req=json.loads((folder/'request.json').read_text(encoding='utf-8'));saved=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    assert req['_studio_origin_action']=='draft' and saved['suggestions']==values and req['_studio_snapshots'][uid]==values[0];w.close()
