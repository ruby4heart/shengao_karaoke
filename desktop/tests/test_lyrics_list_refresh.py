"""Incremental rows must keep navigation, filters, selections and live data exact."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from shengao.project import History,Project
from shengao.timeline import stamp
from studio_backend.model import LyricLine
from test_reading_candidates_workflow import reading_window

ID_ROLE=int(Qt.ItemDataRole.UserRole)+1


def prepare(w,count=20):
    p=Project(lines=[LyricLine('row-'+str(i),'歌 '+str(i),i*300+100,i*300+300) for i in range(count)])
    w.history=History(p);w.current=count//2;w.refresh();return w


def ids(w):return [w.lyrics.item(i).data(ID_ROLE) for i in range(w.lyrics.count())]


def test_one_line_edit_keeps_all_rows_and_updates_actual_text_selection_and_undo(reading_window):
    w=prepare(reading_window,1000);before=w.project.to_dict();rows=[w.lyrics.item(i) for i in range(1000)];current=w.current
    w.change_boundary(-1,-1,w.line.start+10,w.line.end)
    assert all(w.lyrics.item(i) is item for i,item in enumerate(rows))
    assert stamp(w.line.start) in rows[current].text() and w.lyrics.currentRow()==current
    assert [item.data(Qt.ItemDataRole.UserRole) for item in w.lyrics.selectedItems()]==[current]
    w.undo();assert w.project.to_dict()==before and all(w.lyrics.item(i) is item for i,item in enumerate(rows))
    w.redo();assert stamp(w.line.start) in rows[current].text()


def test_direct_model_and_widget_changes_are_observed_without_stale_row_state(reading_window):
    w=prepare(reading_window);row=w.current;item=w.lyrics.item(row)
    w.line.text='新しい歌';w.line.reviewed=True;w.line.start+=10
    item.setText('stale');item.setToolTip('stale');item.setData(Qt.ItemDataRole.UserRole,9999)
    w.refresh_lyrics()
    assert w.lyrics.item(row) is item and '新しい歌' in item.text() and '✓ 时间已确认' in item.text()
    assert stamp(w.line.start) in item.text() and item.toolTip()==w.line.text and item.data(Qt.ItemDataRole.UserRole)==row


def test_filtered_rows_keep_correct_project_indices_after_an_unmatched_insertion(reading_window,qapp):
    w=prepare(reading_window);w.project.lines[2].text=w.project.lines[7].text='match';w.search.setText('match')
    rows=[w.lyrics.item(i) for i in range(2)];assert ids(w)==['row-2','row-7']
    w.project.lines.insert(0,LyricLine('inserted','unrelated',0,50));w.refresh_lyrics()
    assert [w.lyrics.item(i) for i in range(2)]==rows
    assert [item.data(Qt.ItemDataRole.UserRole) for item in rows]==[3,8]
    w.resize(1460,940);qapp.processEvents();w.lyrics.scrollToItem(rows[1]);qapp.processEvents()
    point=w.lyrics.visualItemRect(rows[1]).center();assert w.lyrics.viewport().visibleRegion().contains(point)
    QTest.mouseClick(w.lyrics.viewport(),Qt.MouseButton.LeftButton,pos=point)
    assert w.current==8 and w.line.id=='row-7' and w.lyrics.currentRow()==1


def test_filters_delete_reorder_and_empty_placeholder_remain_exact(reading_window):
    w=prepare(reading_window);w.project.lines[0].reviewed=True;w.filter.setCurrentIndex(1)
    assert 'row-0' not in ids(w) and len(ids(w))==19
    w.project.checks={'row-1':{'reading':True}};w.filter.setCurrentIndex(2)
    assert 'row-1' not in ids(w) and 'row-0' in ids(w)
    w.filter.setCurrentIndex(0);del w.project.lines[2];w.project.lines.reverse();w.refresh_lyrics()
    assert ids(w)==[line.id for line in w.project.lines]
    assert [w.lyrics.item(i).data(Qt.ItemDataRole.UserRole) for i in range(19)]==list(range(19))
    w.history=History(Project());w.current=-1;w.refresh()
    assert w.lyrics.count()==1 and w.lyrics.item(0).data(Qt.ItemDataRole.UserRole) is None and '这里将显示' in w.lyrics.item(0).text()


def test_current_row_can_be_filtered_out_without_leaving_a_stale_current_index(reading_window):
    w=prepare(reading_window);w.search.setText('歌 1');assert w.lyrics.currentRow()>=0
    rows=[w.lyrics.item(i) for i in range(w.lyrics.count())]
    w.current=2;w.refresh_lyrics()
    assert w.lyrics.currentRow()==-1 and [w.lyrics.item(i) for i in range(w.lyrics.count())]==rows


def test_multiselection_and_user_deselection_match_actual_widget_state(reading_window):
    w=prepare(reading_window);w.lyrics.item(2).setSelected(True);w.lyrics.item(7).setSelected(True)
    marked=set(w._selected_lyric_ids);w.refresh_lyrics()
    assert {w.project.lines[item.data(Qt.ItemDataRole.UserRole)].id for item in w.lyrics.selectedItems()}==marked
    w.lyrics.clearSelection();w.refresh_lyrics()
    assert [item.data(Qt.ItemDataRole.UserRole) for item in w.lyrics.selectedItems()]==[w.current]
