import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from shengao.project import save_project,load_project,file_stamp
from shengao.review_issues import state,progress,collect
from test_reading_candidates_workflow import reading_window


def open_issues(w,qapp):
    assert w.open_review_issues();qapp.processEvents();d=w.issue_dialog
    assert not d.isModal() and QApplication.activeModalWidget() is None
    return d


def choose(d,kind):
    d.kind.setCurrentIndex(d.kind.findData(kind))
    assert d.filtered and all(v.kind==kind for v in d.filtered)
    d.table.setCurrentCell(0,0);return d.selected()


def test_real_list_filters_orders_search_and_readonly_comparison(reading_window,qapp):
    w=reading_window;before=w.project.to_dict();d=open_issues(w,qapp)
    assert d.items and d.table.rowCount()==len(d.filtered) and '不会自动确认' in d.summary.text()
    item=choose(d,'missing');assert item.word==1 and '缺少' in d.title.text() and d.adopt.isEnabled()
    assert d.current.toPlainText() and '估算' in d.why.text() and d.suggested.toPlainText()
    d.severity.setCurrentIndex(d.severity.findData('error'));assert not d.filtered
    d.severity.setCurrentIndex(0);d.kind.setCurrentIndex(0);d.order.setCurrentIndex(d.order.findData('severity'))
    ranks={'error':0,'warning':1,'notice':2};assert [ranks[v.severity] for v in d.filtered]==sorted(ranks[v.severity] for v in d.filtered)
    d.search.setText('does not exist');assert not d.filtered;d.search.clear();assert d.filtered
    assert w.project.to_dict()==before


def test_keep_and_defer_are_saved_without_confirmation_and_undo_is_one_step(reading_window,qapp,tmp_path):
    w=reading_window;before=w.project.to_dict();d=open_issues(w,qapp);item=choose(d,'missing');d.keep.click()
    assert state(item,w.project.review_states)=='keep' and w.line.to_dict()==before['lines'][0] and w.project.checks==before['checks']
    d.status_filter.setCurrentIndex(d.status_filter.findData('keep'));assert d.filtered and d.selected().id==item.id
    path=tmp_path/'保留疑点.sgproj';save_project(w.project,path);assert load_project(path).review_states==w.project.review_states
    w.undo();assert w.project.to_dict()==before;d.refresh();d.status_filter.setCurrentIndex(d.status_filter.findData('pending'));choose(d,'missing');d.defer.click()
    assert state(item,w.project.review_states)=='defer' and d.filtered and not w.project.review_states[item.id]['decision']=='adopted'


def test_adopt_one_missing_word_and_record_in_same_undo_without_touching_manual_neighbor(reading_window,qapp):
    w=reading_window;d=open_issues(w,qapp);item=choose(d,'missing');before=w.project.to_dict();d.adopt.click()
    assert w.line.units[1].highlights and all(h.source=='estimated' for h in w.line.units[1].highlights)
    assert w.line.to_dict()['units'][0]==before['lines'][0]['units'][0] and w.project.checks==before['checks'] and not w.line.reviewed
    assert w.project.review_states[item.id]['decision']=='adopted' and len(w.history.undo_stack)==1
    assert '已直接采用 1' in d.summary.text();w.undo();assert w.project.to_dict()==before


def test_changed_basis_reopens_old_keep_and_displays_previous_values(reading_window,qapp):
    w=reading_window;d=open_issues(w,qapp);old=choose(d,'missing');d.keep.click()
    w.line.units[1].kana='のがい';d.refresh();d.status_filter.setCurrentIndex(d.status_filter.findData('changed'))
    assert d.filtered and d.selected().id==old.id and d.old.isVisible() and '上次决定' in d.old.toPlainText() and old.current in d.old.toPlainText()
    assert state(d.selected(),w.project.review_states)=='changed'


def test_late_manual_edit_rejects_old_adoption_and_keeps_latest_value(reading_window,qapp):
    w=reading_window;d=open_issues(w,qapp);item=choose(d,'missing');expected=copy.deepcopy(d.adoption)
    w.project.checks['line']['reading']=False;before=w.project.to_dict()
    assert not w.adopt_review_issue(item,expected) and w.project.to_dict()==before and '确认已变化' in w.status.text()


def test_locked_unit_can_be_listened_and_kept_but_not_overwritten(reading_window,qapp):
    w=reading_window;w.line.units[1].locked=True;w.refresh();d=open_issues(w,qapp);choose(d,'missing')
    assert not d.adopt.isEnabled() and d.keep.isEnabled() and d.locate.isEnabled()
    before=w.line.to_dict();d.keep.click();assert w.line.to_dict()==before


def test_locate_and_manual_work_on_unmatched_missing_group(reading_window,qapp):
    w=reading_window;w.line.units=[];w.line.kana='';w.refresh();d=open_issues(w,qapp);item=choose(d,'missing')
    d.manual.click();assert not d.isVisible() and w.stage==2 and w.inline_segment.mode.isChecked() and w.line.text=='人気の街'
    assert w.timeline.word==-1 and w.timeline.part==-1


def test_gap_context_listens_to_actual_selected_part_and_stop_restores_settings(reading_window,qapp):
    # This checks the shared location; the real media/clock path is exercised
    # with loaded synthetic audio in test_fine_listening.py.
    w=reading_window;d=open_issues(w,qapp);item=choose(d,'gap');before=w.project.to_dict();d.locate.click()
    assert w.timeline.word==item.word and w.timeline.part==item.part and w.project.to_dict()==before


def test_stale_background_suggestion_stays_comparable_without_direct_adoption(reading_window,qapp):
    w=reading_window;original=w.line.to_dict();proposal=copy.deepcopy(original);proposal['start']-=50
    w.pending={'action':'align','context':{'project':w.project.uid,'media':file_stamp(w.project.media)},'snapshots':{'line':original},'result':{'suggestions':[proposal]}}
    w.line.start-=10;before=w.project.to_dict();d=open_issues(w,qapp);item=choose(d,'proposal')
    assert '当前已变化' in item.title and not d.adopt.isEnabled() and d.pending.isEnabled()
    assert str(w.line.start) in d.current.toPlainText() and str(proposal['start']) in d.suggested.toPlainText() and w.project.to_dict()==before
    d.keep.click();assert w.pending and w.pending['result']['suggestions'][0]==proposal and w.line.to_dict()==before['lines'][0]


def test_recording_adopted_requires_actual_success_and_unrelated_fake_preview_is_rejected(reading_window,qapp):
    w=reading_window;d=open_issues(w,qapp);item=choose(d,'missing');before=w.project.to_dict()
    assert not w.decide_review_issue(item,'adopted') and w.project.to_dict()==before
    bad=copy.deepcopy(d.adoption);bad['preview']['units'][0]['highlights'][0]['start']+=10
    assert not w.adopt_review_issue(item,bad) and w.project.to_dict()==before


def test_medusa_keys_do_not_escape_modeless_issue_search_into_main_audio_commands(reading_window,qapp):
    w=reading_window;w.timeline.medusa_hotkeys=True;before=w.project.to_dict();d=open_issues(w,qapp)
    assert d.window() is d and w.fine_listener.window() is w
    d.search.setFocus();QTest.keyClicks(d.search,'sdf');qapp.processEvents()
    assert d.search.text()=='sdf' and w.project.to_dict()==before and w.playback.range is None


def test_missing_background_result_is_visible_without_crashing_or_resubmitting(reading_window,qapp):
    w=reading_window;w.pending={'action':'align','result':None};before=w.project.to_dict();d=open_issues(w,qapp)
    item=choose(d,'proposal');assert '没有可用建议' in item.title and not d.adopt.isEnabled()
    d.pending.click();assert '不自动重复提交' in d.message.text() and w.project.to_dict()==before and w.pending['result'] is None


def test_search_enter_does_not_adopt_and_workbench_undo_restores_one_operation(reading_window,qapp):
    w=reading_window;d=open_issues(w,qapp);choose(d,'missing');before=w.project.to_dict()
    d.adopt.setFocus();d.search.setFocus();QTest.keyClick(d.search,Qt.Key.Key_Return);qapp.processEvents();assert w.project.to_dict()==before
    d.adopt.click();assert w.project.to_dict()!=before and d.undo_button.isEnabled()
    d.undo_button.click();assert w.project.to_dict()==before


def test_missing_mora_returning_after_actual_adoption_reopens_with_old_comparison(reading_window,qapp):
    w=reading_window;d=open_issues(w,qapp);item=choose(d,'missing');d.adopt.click();assert w.line.units[1].highlights
    w.line.units[1].highlights=[];w.refresh();d.refresh();d.kind.setCurrentIndex(d.kind.findData('missing'))
    assert d.selected().id==item.id and state(d.selected(),w.project.review_states)=='changed' and '再次出现' in d.old.toPlainText()
