import copy
import asyncio
import pytest
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox
from studio_backend.model import LyricLine, Unit, Highlight
from shengao.project import Project, History, save_project, load_project
from shengao.time_transform import scope_indices, TimeTransform, transform_project, shift_limits
from shengao.time_correction_dialog import TimeCorrectionDialog
from shengao.app import StudioWindow
from shengao.theme import STYLE
from shengao.presentation import display_windows
from shengao.match_range_dialog import MatchRangeDialog


def song():
    p = Project(duration=15000)
    for i, start in enumerate([1000, 2500, 5000, 7500]):
        p.lines.append(LyricLine(str(i), '歌う', start, start+800, [Unit('歌', start, start+400, 'うた', 'uta', 'manual', highlights=[Highlight('う', start, start+200, 'manual'), Highlight('た', start+200, start+400, 'manual')], reading_source='manual'), Unit('う', start+400, start+800, 'う', 'u', 'manual', highlights=[Highlight('う', start+400, start+800, 'manual')], reading_source='manual')], kana='うたう', romaji='utau', translation='歌唱', reviewed=True))
        p.checks[str(i)] = {'reading': True}
    p.validate(); return p


def times(line):
    return [line.start, line.end, *[t for u in line.units for t in [u.start, u.end, *[v for h in u.highlights for v in [h.start, h.end]]]]]


def window(qapp, tmp_path):
    qapp.setStyle('Fusion'); qapp.setStyleSheet(STYLE)
    w = StudioWindow(home=tmp_path/'home', test=True); w.playback.audio.setMuted(True); w.history=History(song()); w.current=0; w.refresh(True); w.set_stage(2); w.show(); qapp.processEvents(); return w


def test_scope_is_explicit_and_does_not_confuse_suffix_with_visible_filter():
    p=song()
    assert scope_indices(p,'all',2)==[0,1,2,3]
    assert scope_indices(p,'following',2)==[2,3]
    assert scope_indices(p,'current',2)==[2]
    assert scope_indices(p,'selected',2,[3,1,1])==[1,3]
    with pytest.raises(ValueError):scope_indices(p,'selected',2,[])


def test_batch_shift_keeps_every_relative_time_and_reading_and_is_atomic():
    p=song(); before=p.to_dict(); result=transform_project(p,[0,1,3],TimeTransform(offset=137))
    assert p.to_dict()==before and len(result.rows)==3
    for i in [0,1,3]:
        assert [b-a for a,b in zip(times(p.lines[i]),times(result.project.lines[i]))]==[137]*len(times(p.lines[i]))
        assert result.project.lines[i].text==p.lines[i].text and result.project.lines[i].kana==p.lines[i].kana
        assert result.project.lines[i].translation==p.lines[i].translation and not result.project.lines[i].reviewed
    assert result.project.lines[2].to_dict()==p.lines[2].to_dict() and result.project.checks==p.checks
    p.lines[3].units[0].locked=True; locked=copy.deepcopy(p.to_dict())
    with pytest.raises(ValueError,match='4'):transform_project(p,[0,1,3],TimeTransform(offset=100))
    assert p.to_dict()==locked


def test_shift_rejects_out_of_media_instead_of_individually_clamping_lines():
    p=song(); assert shift_limits(p,[0,3])==(-1000,6700)
    for delta in [-1001,6701]:
        with pytest.raises(ValueError):transform_project(p,[0,3],TimeTransform(offset=delta))
    unchanged=transform_project(p,[0,3],TimeTransform()); assert not unchanged.rows and unchanged.project.to_dict()==p.to_dict()


def test_two_points_correct_drift_and_multiple_points_fix_piecewise_drift():
    p=song(); points=((1000,1100),(5000,5200),(8300,10300)); mapping=TimeTransform(anchors=points)
    assert all(mapping.at(x)==y for x,y in points) and mapping.at(500)==600 and mapping.at(9000)==11000
    result=transform_project(p,range(4),mapping)
    for old,new in zip(p.lines,result.project.lines):assert times(new)==[mapping.at(t) for t in times(old)]
    assert result.project.lines[0].units[0].end==result.project.lines[0].units[1].start
    with pytest.raises(ValueError,match='倒序'):TimeTransform(anchors=((1000,1000),(1000,2000)))
    with pytest.raises(ValueError,match='倒序'):TimeTransform(anchors=((1000,2000),(3000,1000)))
    with pytest.raises(ValueError,match='压缩'):transform_project(p,[0],TimeTransform(anchors=((1000,1000),(1800,1001))))


def test_new_overlap_is_a_reviewable_warning_without_rewriting_other_lines():
    p=song(); result=transform_project(p,[1],TimeTransform(offset=-1000))
    assert result.warnings and '重叠' in result.warnings[0]
    assert result.project.lines[0].to_dict()==p.lines[0].to_dict()


def test_multi_select_uses_real_shift_click_and_one_history_step(qapp,tmp_path):
    w=window(qapp,tmp_path); before=w.project.to_dict(); viewport=w.lyrics.viewport()
    QTest.mouseClick(viewport,Qt.MouseButton.LeftButton,pos=w.lyrics.visualItemRect(w.lyrics.item(0)).center())
    QTest.mouseClick(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,w.lyrics.visualItemRect(w.lyrics.item(2)).center())
    w.time_scope.setCurrentIndex(w.time_scope.findData('selected')); assert w.timing_indices()==[0,1,2]
    assert '3' in w.time_scope_summary.text()
    def edit():
        d=qapp.activeModalWidget(); assert isinstance(d,TimeCorrectionDialog)
        d.set_shift(250); assert w.project.to_dict()==before and len(d.preview_result.rows)==3
        d.apply_button.click()
    QTimer.singleShot(20,edit); w.offset_button.click()
    assert [line.start for line in w.project.lines]==[1250,2750,5250,7500] and len(w.history.undo_stack)==1
    assert w.timing_indices()==[0,1,2]
    w.undo(); assert w.project.to_dict()==before; w.redo(); assert w.project.lines[2].start==5250; w.close()


def test_all_scope_pin_and_drag_move_the_whole_song_and_escape_is_atomic(qapp,tmp_path):
    w=window(qapp,tmp_path); before=w.project.to_dict(); w.time_scope.setCurrentIndex(w.time_scope.findData('all'))
    w.playback.seek(2000); w.move_to_playhead.click(); assert [l.start for l in w.project.lines]==[2000,3500,6000,8500]
    w.undo(); assert w.project.to_dict()==before
    t=w.timeline; t.duration=15000; t.left=0; t.span=10000; w.drag_line.click(); y=t.audio_top+30
    QTest.mousePress(t,Qt.MouseButton.LeftButton,pos=QPoint(round(t.tx(1200)),y)); QTest.mouseMove(t,QPoint(round(t.tx(1800)),y))
    assert t.moving is not None and w.project.to_dict()==before
    QTest.keyClick(t,Qt.Key.Key_Escape); QTest.mouseRelease(t,Qt.MouseButton.LeftButton,pos=QPoint(round(t.tx(1800)),y)); assert w.project.to_dict()==before
    QTest.mousePress(t,Qt.MouseButton.LeftButton,pos=QPoint(round(t.tx(1200)),y)); QTest.mouseMove(t,QPoint(round(t.tx(1800)),y)); QTest.mouseRelease(t,Qt.MouseButton.LeftButton,pos=QPoint(round(t.tx(1800)),y))
    delta=w.project.lines[0].start-1000; assert delta>0
    assert [line.start for line in w.project.lines]==[start+delta for start in [1000,2500,5000,7500]]; w.close()


def test_drift_dialog_cancel_apply_save_and_reopen(qapp,tmp_path):
    w=window(qapp,tmp_path); before=w.project.to_dict(); w.time_scope.setCurrentIndex(w.time_scope.findData('all'))
    def cancel():
        d=qapp.activeModalWidget(); d.set_anchors([(1000,1000),(8300,9300)]); assert d.preview_result.project.lines[-1].end==9300; d.reject()
    QTimer.singleShot(20,cancel); w.drift_button.click(); assert w.project.to_dict()==before and not w.history.undo_stack
    def apply():
        d=qapp.activeModalWidget(); d.set_anchors([(1000,1000),(8300,9300)]); d.apply_button.click()
    QTimer.singleShot(20,apply); w.drift_button.click(); assert w.project.lines[-1].end==9300 and len(w.history.undo_stack)==1
    save_project(w.project,tmp_path/'drift.sgproj'); assert load_project(tmp_path/'drift.sgproj').to_dict()==w.project.to_dict()
    w.undo(); assert w.project.to_dict()==before; w.close()


def test_locked_range_is_visible_and_never_silently_skipped(qapp,tmp_path):
    w=window(qapp,tmp_path); w.project.lines[2].locked=True; w.refresh(); w.time_scope.setCurrentIndex(w.time_scope.findData('all')); before=w.project.to_dict()
    assert not w.move_to_playhead.isEnabled() and '3' in w.time_scope_summary.text()
    def inspect():
        d=qapp.activeModalWidget(); d.set_shift(100); assert not d.apply_button.isEnabled() and '3' in d.status.text(); d.reject()
    QTimer.singleShot(20,inspect); w.offset_button.click(); assert w.project.to_dict()==before; w.close()


def test_entire_song_moves_display_windows_as_well_as_singing_and_roundtrips():
    p=song();p.style.display_mode='alternating';old=display_windows(p)
    moved=transform_project(p,range(4),TimeTransform(offset=500)).project;new=display_windows(moved)
    assert [(w.start,w.end,w.slot) for w in new]==[(w.start+500,w.end+500,w.slot) for w in old]
    assert Project.from_dict(moved.to_dict()).to_dict()==moved.to_dict()
    assert moved.to_dict()['version']==14


def test_manual_display_timing_is_independent_and_can_be_reset_for_scope(qapp,tmp_path):
    w=window(qapp,tmp_path);old_times=times(w.line);w.display_begin.setValue(500);w.display_end.setValue(2200);w.display_apply.click()
    assert times(w.line)==old_times and (display_windows(w.project)[0].start,display_windows(w.project)[0].end)==(500,2200)
    w.move_current_line(100);assert (w.line.display_start,w.line.display_end)==(600,2300)
    w.undo();w.display_reset.click();assert w.line.display_start is None and w.line.display_end is None and times(w.line)==old_times
    w.undo();assert w.line.display_start==500;w.close()


def test_suffix_rematch_uses_only_selected_ids_and_preserves_confirmed_snapshots(qapp,tmp_path):
    w=window(qapp,tmp_path);w.current=1;w.project.transcript=[LyricLine('recognition','歌う',10000,11000).to_dict()];w.refresh();w.time_scope.setCurrentIndex(w.time_scope.findData('following'));before=w.project.to_dict();requests=[];w.api.start=lambda request:requests.append(request)
    def select_range():
        d=qapp.activeModalWidget();assert isinstance(d,MatchRangeDialog);d.begin.setValue(9000);d.end.setValue(14000);d.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
    QTimer.singleShot(20,select_range);w.wrong_segment_button.click()
    request=requests[0];assert request['action']=='match' and request['match_range']==[9000,14000]
    assert [line['id'] for line in request['lines']]==['1','2','3'] and not any(line['reviewed'] for line in request['lines'])
    assert all(value['reviewed'] for value in request['_studio_snapshots'].values()) and w.project.to_dict()==before;w.close()


def test_oversized_old_axis_can_still_open_drift_correction(qapp,tmp_path):
    w=window(qapp,tmp_path);w.project.duration=4000;w.refresh();w.time_scope.setCurrentIndex(w.time_scope.findData('all'))
    assert not w.move_to_playhead.isEnabled() and w.drift_button.isEnabled()
    def correct():
        d=qapp.activeModalWidget();d.set_anchors([(1000,0),(8300,4000)]);assert d.apply_button.isEnabled();d.apply_button.click()
    QTimer.singleShot(20,correct);w.drift_button.click();assert w.project.lines[-1].end==4000;w.close()


def test_scope_never_includes_old_hidden_selection_after_search(qapp,tmp_path):
    w=window(qapp,tmp_path);w.time_scope.setCurrentIndex(w.time_scope.findData('selected'));assert w.timing_indices()==[0]
    w.search.setText('不存在');assert not w.offset_button.isEnabled();w.search.clear();w.close()


def test_older_projects_add_optional_display_fields_without_changing_times():
    p=song();data=p.to_dict();data['version']=2
    for line in data['lines']:line.pop('display_start');line.pop('display_end')
    restored=Project.from_dict(data)
    assert all(line.display_start is None and line.display_end is None for line in restored.lines)
    assert [times(line) for line in restored.lines]==[times(line) for line in p.lines]


def test_invalid_display_time_does_not_change_the_project(qapp,tmp_path):
    w=window(qapp,tmp_path);before=w.project.to_dict();w.display_begin.setValue(w.line.start+1);w.display_apply.click()
    assert w.project.to_dict()==before and '晚于' in w.status.text();w.close()


def test_wrong_chorus_range_runs_real_local_match_and_review_with_one_undo(qapp,tmp_path):
    from studio_backend.worker import operation
    w=window(qapp,tmp_path);w.current=1;w.refresh();before=w.project.to_dict();request=[]
    w.project.transcript=[LyricLine('verse','歌う',1000,1800).to_dict(),LyricLine('chorus','歌う',10000,10800).to_dict()]
    before=w.project.to_dict();w.api.start=lambda value:request.append(value)
    def choose():
        d=qapp.activeModalWidget();d.begin.setValue(9000);d.end.setValue(12000);d.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
    QTimer.singleShot(20,choose);w.local_match()
    result=asyncio.run(operation(request[0],tmp_path/'backend',lambda *args:None))
    assert len(result['suggestions'])==1 and result['suggestions'][0]['start']>=9000
    w.api.request=request[0];w.api.folder=tmp_path/'backend';w.api_done(result)
    w.apply_suggestions(result['suggestions'])
    assert w.project.lines[1].start>=9000 and all(w.project.lines[i].to_dict()==before['lines'][i] for i in [0,2,3])
    assert len(w.history.undo_stack)==1
    w.undo();assert w.project.to_dict()==before;w.close()
