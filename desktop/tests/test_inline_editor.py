import copy
from dataclasses import asdict
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QLineEdit
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.japanese import add_mora
from shengao.app import StudioWindow
from shengao.project import Project,History,save_project,load_project
from shengao.editor_model import segmentation_preview,boundary_preview,cuts_for,missing_mora_preview
from shengao.timing import set_time
from shengao.theme import STYLE

def lyric():
    return LyricLine('current','今日も歌う',3000,6000,[
        Unit('今日',3000,3900,'こんにち','konnichi','manual',highlights=[Highlight('こ',3000,3137,'manual'),Highlight('ん',3137,3300,'manual'),Highlight('に',3300,3600,'manual'),Highlight('ち',3600,3900,'manual')],reading_source='manual'),
        Unit('も',4000,4300,'も','mo','manual',highlights=[Highlight('も',4000,4300,'manual')],reading_source='manual'),
        Unit('歌う',4500,6000,'うたう','utau','manual',highlights=[Highlight('う',4500,4900,'manual'),Highlight('た',4900,5300,'manual'),Highlight('う',5300,6000,'manual')],reading_source='manual')
    ],kana='こんにちもうたう',romaji='konnichi mo utau',translation='今天也歌唱',reviewed=True)

def song():
    rows=[LyricLine('before','前の歌',1000,2000,[Unit('前の歌',1000,2000,'まえのうた','mae no uta','manual')],reviewed=True),lyric(),LyricLine('after','次の歌',6500,8000,[Unit('次の歌',6500,8000,'つぎのうた','tsugi no uta','manual')],reviewed=True)]
    for line in rows:
        for unit in line.units:
            add_mora(unit)
            for part in unit.highlights:part.source='manual'
    p=Project(duration=15000,lines=rows,checks={line.id:{'reading':True} for line in rows});p.validate();return p

def window(qapp,tmp_path,p=None):
    qapp.setStyle('Fusion');qapp.setStyleSheet(STYLE);w=StudioWindow(home=tmp_path/'home',test=True);w.playback.audio.setMuted(True);w.history=History(p or song());w.current=1 if len(w.project.lines)>1 else 0;w.refresh(True);w.set_stage(2);w.show();qapp.processEvents();return w

def click_anchor(qapp,browser,anchor,button=Qt.MouseButton.LeftButton):
    qapp.processEvents()
    for y in range(2,browser.viewport().height(),3):
        for x in range(2,browser.viewport().width(),3):
            if browser.anchorAt(QPoint(x,y))==anchor:
                QTest.mouseClick(browser.viewport(),button,pos=QPoint(x,y));qapp.processEvents();return
    raise AssertionError('Anchor not visible: '+anchor)

def test_cut_preview_preserves_manual_words_and_cancel_restores_exact_data():
    old=lyric();snapshot=old.to_dict();value=boundary_preview(old,4)
    assert [asdict(u) for u in value.line.units[:2]]==[asdict(u) for u in old.units[:2]]
    assert value.reestimated and all(u.highlights for u in value.line.units[2:]) and old.to_dict()==snapshot
    restored=segmentation_preview(old,cuts_for(old));assert restored.line.to_dict()==snapshot and not restored.affected

def test_merge_keeps_every_original_mora_and_real_audio_gap():
    old=lyric();value=boundary_preview(old,3)
    assert not value.reestimated and asdict(value.line.units[0])==asdict(old.units[0])
    assert [asdict(h) for h in value.line.units[1].highlights]==[asdict(h) for u in old.units[1:] for h in u.highlights]
    assert value.line.units[1].kana=='もうたう' and value.line.kana==''.join(u.kana for u in value.line.units)

def test_true_spaces_are_kept_but_never_become_blank_words():
    old=LyricLine('spaces','歌う  今日',1000,4000);first=boundary_preview(old,2).line
    with pytest.raises(ValueError,match='空格'):boundary_preview(first,3)
    assert ''.join(u.text for u in first.units)==old.text and all(u.text.strip() for u in first.units)

def test_locked_word_allows_other_word_edits_but_not_shared_boundary_changes():
    old=lyric();old.units[0].locked=True
    assert asdict(boundary_preview(old,4).line.units[0])==asdict(old.units[0])
    with pytest.raises(ValueError,match='锁定'):boundary_preview(old,1)
    changed=set_time(old,1,4050,4300);assert asdict(changed.units[0])==asdict(old.units[0])
    old.units[0].end=old.units[1].start;snapshot=old.to_dict()
    with pytest.raises(ValueError,match='锁定'):set_time(old,1,4050,4300)
    assert old.to_dict()==snapshot

def test_missing_mora_preserves_katakana_manual_mora_and_locked_words():
    old=lyric();old.units[0].kana='キョウ';old.units[0].romaji='kyou';old.units[0].highlights=[];old.units[2].highlights=[];old.units[2].locked=True;snapshot=old.to_dict()
    value=missing_mora_preview(old)
    assert value.kind=='mora' and value.skipped==1 and [h.kana for h in value.line.units[0].highlights]==['キョ','ウ']
    assert value.line.units[0].kana=='キョウ' and (value.line.units[0].start,value.line.units[0].end)==(3000,3900)
    assert [asdict(u) for u in value.line.units[1:]]==[asdict(u) for u in old.units[1:]] and old.to_dict()==snapshot

def test_missing_mora_is_previewed_then_applied_without_resetting_reading_review(qapp,tmp_path):
    p=song();p.lines[1].units[0].highlights=[];w=window(qapp,tmp_path,p);before=w.project.to_dict()
    w.fill_mora_button.click();assert w.inline_segment.pending and w.project.to_dict()==before and '估算' in w.inline_segment.status.text()
    w.inline_segment.apply.click();assert w.line.units[0].highlights and w.project.checks['current']['reading'] and not w.line.reviewed
    w.undo();assert w.project.to_dict()==before;w.close()

def test_real_original_click_previews_then_applies_as_one_undo(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();w.quick_segment.click();assert QApplication.activeModalWidget() is None
    click_anchor(qapp,w.inline_segment.text,'char:4');assert w.inline_segment.pending and w.project.to_dict()==before
    assert '重估' in w.inline_segment.status.text() and not w.timeline.editing_enabled
    w.inline_segment.apply.click();assert len(w.line.units)==4 and len(w.history.undo_stack)==1 and w.timeline.editing_enabled
    assert [asdict(u) for u in w.line.units[:2]]==[asdict(u) for u in lyric().units[:2]]
    w.undo();assert w.project.to_dict()==before;w.redo();assert len(w.line.units)==4;w.close()

def test_multiple_preview_toggles_restore_manual_data_without_history(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();w.quick_segment.click()
    for position in [3,4,3,4]:click_anchor(qapp,w.inline_segment.text,'char:'+str(position))
    assert not w.inline_segment.pending and w.project.to_dict()==before and not w.history.undo_stack;w.close()

def test_selection_follows_the_same_word_when_an_earlier_word_is_split(qapp,tmp_path):
    w=window(qapp,tmp_path);w.select_editor_mora(2,2);selected=asdict(w.line.units[2].highlights[2]);w.quick_segment.click()
    click_anchor(qapp,w.inline_segment.text,'char:1');w.inline_segment.apply.click()
    assert (w.timeline.word,w.timeline.part)==(3,2) and asdict(w.line.units[3].highlights[2])==selected
    assert (w.begin.value(),w.end.value())==(selected['start'],selected['end']);w.close()

def test_pending_segmentation_blocks_navigation_and_save_until_resolved(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();w.quick_segment.click();w.inline_segment.whole.click();w.move_line(1)
    assert w.current==1 and not w.save() and w.project.to_dict()==before
    w.timeline.setFocus();QTest.keyClick(w.timeline,Qt.Key.Key_Plus,Qt.KeyboardModifier.KeypadModifier);w.delete_current()
    assert w.project.to_dict()==before and not w.optional_reading.isEnabled() and w.inline_segment.pending
    w.inline_segment.cancel.click();w.move_line(1);assert w.current==2 and not w.history.undo_stack;w.close()

def test_click_word_edits_kana_inline_and_preserves_other_manual_mora(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();w.show_editor_widget(w.inline_segment)
    click_anchor(qapp,w.inline_segment.text,'char:1');assert QApplication.activeModalWidget() is None
    editor=QApplication.focusWidget();assert isinstance(editor,QLineEdit);editor.setText('きょう');w.quick_timing.click()
    assert w.line.units[0].kana=='きょう' and w.line.units[0].romaji=='kyou'
    assert [asdict(u) for u in w.line.units[1:]]==[asdict(u) for u in lyric().units[1:]]
    assert not w.project.checks[w.line.id]['reading'] and w.calibration_tabs.currentIndex()==0
    w.undo();assert w.project.to_dict()==before;w.close()

@pytest.mark.filterwarnings('ignore:.*setActiveWindow.*:DeprecationWarning')
def test_edit_buffer_commits_even_when_main_window_is_not_active(qapp,tmp_path):
    w=window(qapp,tmp_path);QApplication.setActiveWindow(None);w.units.setCurrentCell(0,1);w.units.editItem(w.units.item(0,1));qapp.processEvents()
    editor=next(widget for widget in w.units.findChildren(QLineEdit) if widget.isVisible());editor.setText('きょう')
    assert QApplication.focusWidget() is None and w.line.units[0].kana=='こんにち'
    assert w.flush_edits() and w.line.units[0].kana=='きょう';w.close()

def backend_result(w,tmp_path):
    old=w.line.to_dict();context={'project':w.project.uid,'media':{}}
    w.api.request={'action':'segment','_studio_context':context};w.api.folder=tmp_path;w.snapshots={old['id']:old}
    return {'suggestions':[old],'transcript':[LyricLine('recognition',old['text'],old['start'],old['end']).to_dict()]}

def test_background_result_commits_input_and_cannot_overwrite_it(qapp,tmp_path):
    w=window(qapp,tmp_path);result=backend_result(w,tmp_path);w.quick_reading.click();editor=QApplication.focusWidget();assert isinstance(editor,QLineEdit);editor.setText('きょう')
    w.api_done(result);assert w.line.units[0].kana=='きょう' and w.project.transcript==result['transcript']
    w.apply_suggestions(result['suggestions']);assert w.line.units[0].kana=='きょう' and w.pending;w.close()

def test_background_transcript_does_not_discard_segmentation_draft(qapp,tmp_path):
    w=window(qapp,tmp_path);result=backend_result(w,tmp_path);w.quick_segment.click();w.inline_segment.whole.click();draft=w.inline_segment.preview.line.to_dict()
    w.api_done(result);assert w.inline_segment.pending and w.inline_segment.preview.line.to_dict()==draft
    w.inline_segment.apply.click();assert len(w.line.units)==1 and w.project.transcript==result['transcript'];w.close()

def test_unmatched_phrase_can_set_range_and_segment_without_transcription(qapp,tmp_path):
    raw=LyricLine('unmatched','真夜中の ネオンサイン',0,5000,match={'status':'unmatched'});w=window(qapp,tmp_path,Project(duration=20000,lines=[raw]))
    w.range_button.click();w.begin.setValue(10000);w.end.setValue(16000);w.apply_spins();assert (w.line.start,w.line.end)==(10000,16000)
    w.quick_segment.click();w.inline_segment.dictionary.click();assert w.inline_segment.pending and not w.line.units
    w.inline_segment.apply.click();assert w.line.units and w.line.text==raw.text and all(u.text.strip() for u in w.line.units)
    assert w.mora_strip.toPlainText().strip() and QApplication.activeModalWidget() is None;w.close()

def test_word_without_reading_can_be_timed_then_filled_inline(qapp,tmp_path):
    p=song();p.lines[1].units[1].kana='';p.lines[1].units[1].romaji='';p.lines[1].units[1].highlights=[];w=window(qapp,tmp_path,p)
    untouched=[asdict(w.line.units[i]) for i in [0,2]];w.select_editor_mora(1,-1)
    assert (w.begin.value(),w.end.value())==(4000,4300)
    w.edit_selected_reading();editor=QApplication.focusWidget();assert isinstance(editor,QLineEdit);editor.setText('も');assert w.flush_edits()
    assert w.line.units[1].highlights and w.line.units[1].highlights[0].kana=='も'
    assert [asdict(w.line.units[i]) for i in [0,2]]==untouched;w.close()

def test_mora_click_and_right_audition_share_timeline_and_time_fields(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();calls=[];w.playback.audition=lambda *args:calls.append(args);w.show_editor_widget(w.mora_strip)
    click_anchor(qapp,w.mora_strip,'mora:0:2');part=w.line.units[0].highlights[2]
    assert (w.timeline.word,w.timeline.part)==(0,2) and w.units.currentRow()==0 and (w.begin.value(),w.end.value())==(part.start,part.end)
    assert w.playback.canvas.position==part.start
    w.show_editor_widget(w.mora_strip);click_anchor(qapp,w.mora_strip,'mora:0:2',Qt.MouseButton.RightButton);assert calls[-1][:2]==(part.start,part.end)
    w.end.setValue(part.end+10);w.apply_spins();assert w.line.units[0].highlights[2].end==part.end+10
    w.undo();assert w.project.to_dict()==before;w.close()

def test_both_neighbour_lanes_use_same_time_coordinates_and_open_exact_mora(qapp,tmp_path):
    w=window(qapp,tmp_path);t=w.timeline;t.left=0;t.span=10000;t.invalidate();qapp.processEvents();view=(t.left,t.span)
    assert w.previous_context.isVisible() and w.next_context.isVisible() and t.width()==w.previous_context.lane.width()==w.next_context.lane.width()
    part=w.project.lines[2].units[0].highlights[0]
    QTest.mouseClick(w.next_context.lane,Qt.MouseButton.LeftButton,pos=QPoint(round(t.tx((part.start+part.end)//2)),10))
    assert w.current==2 and (t.word,t.part)==(0,0) and (t.left,t.span)==view
    part=w.project.lines[1].units[-1].highlights[-1]
    QTest.mouseClick(w.previous_context.lane,Qt.MouseButton.LeftButton,pos=QPoint(round(t.tx((part.start+part.end)//2)),10))
    assert w.current==1 and (t.word,t.part)==(2,2) and (t.left,t.span)==view;w.close()

def test_aeg_enter_confirms_time_only_even_when_reading_is_selected(qapp,tmp_path):
    p=song();p.lines[1].reviewed=False;p.checks['current']['reading']=False;w=window(qapp,tmp_path,p);w.calibration_tabs.setCurrentIndex(1);w.timeline.setFocus();QTest.keyClick(w.timeline,Qt.Key.Key_Return)
    assert w.project.lines[1].reviewed and not w.project.checks['current']['reading'] and w.current==2;w.close()

def test_video_playhead_locates_the_matching_line_and_mora_without_retiming(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();w.playback.seek(7000);w.locate_lyric_button.click()
    assert w.current==2 and (w.timeline.word,w.timeline.part)==(0,1) and w.playback.canvas.position==7000
    assert (w.begin.value(),w.end.value())==(6800,7100) and w.project.to_dict()==before
    w.playback.seek(6200);w.locate_lyric_button.click();assert w.current==1 and (w.timeline.word,w.timeline.part)==(2,2);w.close()

def test_inline_edits_save_reopen_and_optional_romaji_preference(qapp,tmp_path):
    w=window(qapp,tmp_path);w.show_editor_romaji.setChecked(True);w.units.item(0,1).setText('きょう');path=tmp_path/'本句.sgproj';save_project(w.project,path);expected=w.project.to_dict();w.close()
    w=window(qapp,tmp_path,load_project(path));assert w.project.to_dict()==expected and not w.units.isColumnHidden(2);w.close()

@pytest.mark.parametrize('width,height',[(960,620),(960,680),(1280,800),(1460,940)])
def test_unified_editor_does_not_clip_timeline_or_need_sideways_scroll(qapp,tmp_path,width,height):
    w=window(qapp,tmp_path);w.resize(width,height);w.set_stage(2);qapp.processEvents()
    assert w.height()==height and w.width()==width
    assert w.timeline.height()>=180 and w.timeline.visibleRegion().boundingRect().height()==w.timeline.height()
    assert w.pages.widget(2).horizontalScrollBar().maximum()==0 and w.calibrate_footer.visibleRegion().boundingRect().height()>=30
    w.close()
