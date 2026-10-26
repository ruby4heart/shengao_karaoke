import copy
from dataclasses import asdict
import pytest
from PySide6.QtCore import QTimer,Qt,QPoint,QRect
from PySide6.QtGui import QImage,QColor
from PySide6.QtWidgets import QApplication
from shengao.style_workflow import StyleWorkbenchDialog,font_pair,FONT_FIELDS
from shengao.line_layout import make_setting
from shengao.color_states import update_settings,preset_profile
from shengao.subtitles import compose
from studio_backend.model import Unit,LyricLine
from test_reading_candidates_workflow import reading_window


def schedule(fn):
    def invoke():
        d=QApplication.activeModalWidget()
        try:fn(d)
        except BaseException:
            if d is not None:d.reject()
            raise
    QTimer.singleShot(0,invoke)


def test_four_actual_font_previews_use_current_frame_without_moving_main_player(reading_window):
    w=reading_window;frame=QImage(640,360,QImage.Format.Format_RGB32);frame.fill(QColor('#bb5511'));w.playback.canvas.frame=frame
    before=w.project.to_dict();position=w.playback.canvas.position;d=StyleWorkbenchDialog(w.project,0,w);d.render_preview()
    try:
        assert not d.picture.pixmap().isNull() and not d.detail.pixmap().isNull()
        assert all(not card.icon().isNull() for card in d.cards)
        images=[card.icon().pixmap(290,92).toImage() for card in d.cards];icons=[bytes(image.bits()) for image in images]
        assert len(set(icons))==4
        assert d.picture.source_pixmap.toImage().pixelColor(0,0)==QColor('#bb5511')
        d.cards[2].click();d.local_fields['ruby_percent'].setValue(85);d.render_preview()
        assert d.font_choice.currentData()==2 and d.candidate.style.font=='Noto Serif CJK JP Black'
        assert w.project.to_dict()==before and w.playback.canvas.position==position
    finally:d.reject()
    assert d.renderer.closed and not d.timer.isActive() and w.project.to_dict()==before


def test_real_controls_adopt_fonts_and_one_line_wrap_in_one_undo(reading_window):
    w=reading_window;w.project.color_styles=update_settings({},preset_profile(w.project.style,'ruby'),['line'])
    w.line.locked=True;before=w.project.to_dict();count=len(w.history.undo_stack);w.set_stage(3)
    assert w.style_workbench_button.isVisible()
    def choose(d):
        assert isinstance(d,StyleWorkbenchDialog);d.cards[2].click();d.local_fields['size_percent'].setValue(85);d.local_fields['ruby_percent'].setValue(90)
        assert d.breaks.count()==1;d.breaks.item(0).setCheckState(Qt.CheckState.Checked);d.accept()
    schedule(choose);assert w.edit_style_workbench()
    assert w.project.layout_styles['line']==make_setting(w.line,85,90,[2])
    assert w.project.style.font=='Noto Serif CJK JP Black' and len(w.history.undo_stack)==count+1
    assert [v.to_dict() for v in w.project.lines]==before['lines'] and w.project.checks==before['checks']
    assert w.project.color_styles==before['color_styles'] and w.line.locked
    w.undo();assert w.project.to_dict()==before


def test_selecting_a_font_pair_changes_only_four_font_fields(reading_window):
    old=reading_window.project.style;before=asdict(old)
    for index in range(4):
        after=asdict(font_pair(old,index))
        assert {k:v for k,v in after.items() if k not in FONT_FIELDS}=={k:v for k,v in before.items() if k not in FONT_FIELDS}
    assert asdict(old)==before
    with pytest.raises(ValueError):font_pair(old,True)


def test_stale_wrap_survives_font_and_scale_changes_until_new_boundaries_selected(reading_window):
    w=reading_window;old=make_setting(w.line,90,100,[2]);w.project.layout_styles={'line':old}
    w.line.units=[Unit(w.line.text,900,3000,'にんきのまち')];before=copy.deepcopy(old)
    d=StyleWorkbenchDialog(w.project,0,w)
    try:
        assert not d.stale_note.isHidden() and d.candidate.layout_styles['line']==before
        d.font_choice.setCurrentIndex(2);assert d.candidate.layout_styles['line']==before
        d.local_fields['size_percent'].setValue(80)
        assert d.candidate.layout_styles['line']=={**before,'size_percent':80}
        d.reset.click();assert 'line' not in d.candidate.layout_styles and w.project.layout_styles['line']==before and d.stale_note.isHidden()
    finally:d.reject()


def test_new_lyric_text_does_not_silently_rewrite_old_wrap_basis(reading_window):
    w=reading_window;w.project.layout_styles={'line':make_setting(w.line,90,100,[2])}
    w.line.text='違う歌詞';w.line.units=[];d=StyleWorkbenchDialog(w.project,0,w)
    try:
        original=copy.deepcopy(d.candidate.layout_styles['line']);d.local_fields['ruby_percent'].setValue(80)
        assert d.candidate.layout_styles['line']['text']=='人気の街' and d.candidate.layout_styles['line']['breaks']==[2]
        d.breaks.item(0).setCheckState(Qt.CheckState.Checked)
        assert d.candidate.layout_styles['line']['text']=='違う歌詞' and d.candidate.layout_styles['line']['breaks']==[1]
        assert w.project.layout_styles['line']==original
    finally:d.reject()


def test_raw_ass_requires_explicit_choice_and_original_effect_source_is_preserved(reading_window):
    w=reading_window;raw=compose(w.project).replace('WrapStyle: 0','WrapStyle: 2');w.project.source_ass=raw;w.project.source_ass_active=True;before=w.project.to_dict()
    d=StyleWorkbenchDialog(w.project,0,w)
    assert not d.apply.isEnabled();d.accept();assert not d.result_ready
    d.reject();assert w.project.to_dict()==before
    def choose(d):d.use_shengao.setChecked(True);d.cards[3].click();d.accept()
    schedule(choose);assert w.edit_style_workbench()
    assert not w.project.source_ass_active and w.project.source_ass==raw and w.project.lines[0].to_dict()==before['lines'][0]
    w.undo();assert w.project.to_dict()==before


def test_late_project_edit_rejects_font_draft_and_preserves_new_content(reading_window):
    w=reading_window;before=asdict(w.project.style)
    def choose(d):d.cards[2].click();w.project.note='后台新修改';d.accept()
    schedule(choose);assert not w.edit_style_workbench()
    assert asdict(w.project.style)==before and w.project.note=='后台新修改' and '已变化' in w.status.text()


def test_same_path_source_replacement_rejects_old_frame_draft(reading_window,tmp_path):
    import shutil
    w=reading_window;target=tmp_path/'更换源.mp4';shutil.copy2(w.project.media,target);w.project.media=str(target);before=asdict(w.project.style)
    def choose(d):d.cards[2].click();target.write_bytes(target.read_bytes()+b'changed');d.accept()
    schedule(choose);assert not w.edit_style_workbench()
    assert asdict(w.project.style)==before and '已变化' in w.status.text()


@pytest.mark.parametrize('size,large',[((900,800),False),((640,600),True)])
def test_dialog_footer_and_scroll_contents_are_reachable_at_small_sizes(reading_window,qapp,size,large):
    if large:reading_window.project.style=reading_window.preset_style(2)
    d=StyleWorkbenchDialog(reading_window.project,0,reading_window);d.resize(*size);d.show();qapp.processEvents()
    try:
        assert d.rect().contains(d.buttons.geometry())
        assert d.scroll.horizontalScrollBar().maximum()==0
        d.scroll.ensureWidgetVisible(d.breaks);qapp.processEvents()
        rect=QRect(d.breaks.mapTo(d.scroll.viewport(),QPoint(0,0)),d.breaks.size())
        assert d.scroll.viewport().rect().contains(rect)
    finally:d.reject()


def test_missing_words_can_leave_preview_for_exact_current_line_segmentation(reading_window,monkeypatch):
    w=reading_window;w.project.lines.append(LyricLine('unmatched','未匹配歌詞',3100,5000));w.current=1;w.refresh();before=w.project.to_dict();seen=[]
    monkeypatch.setattr(w,'resegment_current',lambda:seen.append(w.line.id))
    def choose(d):assert d.line.id=='unmatched';d.segment.click()
    schedule(choose);assert not w.edit_style_workbench() and seen==['unmatched'] and w.project.to_dict()==before


def test_layout_issue_edit_opens_the_affected_line_not_the_previous_selection(reading_window,monkeypatch):
    from shengao.review_issues import collect
    w=reading_window;w.project.lines.append(LyricLine('long','長'*70,3200,5000));w.current=0;w.refresh();seen=[]
    item=next(v for v in collect(w.project) if v.kind=='layout' and v.line_id=='long')
    monkeypatch.setattr(w,'edit_style_workbench',lambda:seen.append(w.line.id) or True)
    assert w.manual_review_issue(item,specific=True) and seen==['long'] and w.current==1
