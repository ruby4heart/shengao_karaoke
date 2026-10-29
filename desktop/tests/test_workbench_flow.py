from pathlib import Path
import pytest
from shengao.app import StudioWindow
from shengao.project import History,file_stamp


@pytest.fixture
def workbench(qapp,tmp_path,project):
    window=StudioWindow(tmp_path/'home',test=True)
    window.history=History(project);window.current=0;window.refresh();window.set_stage(0)
    yield window
    window.close();qapp.processEvents()


def confirm_all(window):
    for line in window.project.lines:
        line.reviewed=True;window.project.checks.setdefault(line.id,{})['reading']=True
    window.refresh()


def test_confirmed_import_page_and_banner_go_to_style_without_api(workbench,monkeypatch):
    w=workbench;confirm_all(w);before=w.project.to_dict()
    assert Path(w.project.media).is_file()
    assert w.prepare_heading.text()=='歌词校对已确认'
    assert w.prepare_next.text()=='检查字幕样式 →'
    assert w.next_button.text()==w.prepare_next.text()
    monkeypatch.setattr(w,'start_api',lambda *a,**kw:pytest.fail('Navigation unexpectedly called an API'))
    w.prepare_next.click()
    assert w.stage==3 and w.project.to_dict()==before
    assert w.next_button.text()=='先看样片，再导出 →'
    w.set_stage(0)
    assert w.prepare_next.text()=='检查字幕样式 →'
    assert w.next_button.text()==w.prepare_next.text()


def test_pending_time_and_pending_reading_are_distinct_routes(workbench):
    w=workbench;assert w.workbench_decision.key=='timing'
    for line in w.project.lines:line.reviewed=True
    w.refresh();assert w.workbench_decision.key=='reading'
    assert '读音' in w.prepare_next.text() and not w.steps[2].complete


def test_missing_media_keeps_lyrics_and_does_not_recommend_regeneration(workbench,tmp_path):
    w=workbench;before=[line.to_dict() for line in w.project.lines]
    w.project.media=str(tmp_path/'moved.mp4');w.refresh()
    assert w.workbench_decision.key=='media_missing'
    assert w.prepare_next.isHidden()
    assert w.prepare_media_button.objectName()=='primary'
    assert [line.to_dict() for line in w.project.lines]==before


def test_visiting_export_does_not_mark_style_or_output_done(workbench):
    w=workbench;confirm_all(w);w.set_stage(4)
    assert not w.steps[3].complete and not w.steps[4].complete
    assert '先看样片' in w.next_button.text()


def test_secondary_regeneration_action_only_opens_the_draft_page(workbench,monkeypatch):
    w=workbench;confirm_all(w);before=w.project.to_dict()
    monkeypatch.setattr(w,'start_api',lambda *a,**kw:pytest.fail('Opening draft options unexpectedly called an API'))
    action=next(a for a in w.prepare_other_menu.actions() if '重新生成' in a.text())
    action.trigger()
    assert w.stage==1 and w.project.to_dict()==before


def test_old_output_stops_counting_as_current_after_a_manual_edit(workbench,tmp_path):
    w=workbench;confirm_all(w);path=tmp_path/'output.mp4';path.write_bytes(b'output availability stub; decoder is not opened')
    w.last_output=str(path);w._last_output_snapshot=w.project.to_dict();w._last_output_stamp=file_stamp(w.project.media);w._last_output_full=True
    w.refresh();assert w.steps[4].complete
    w.project.lines[0].translation='新的人工译文';w.refresh()
    assert not w.steps[4].complete and path.is_file()
