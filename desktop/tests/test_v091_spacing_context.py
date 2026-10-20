"""User regressions: continuous lyrics and visible adjacent singing syllables."""
import copy
import re
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from studio_backend.model import LyricLine,Unit
from studio_backend.japanese import add_mora
from shengao.project import Project,History
from shengao.fonts import bundled_fonts
from shengao.subtitles import compose,layout_line,pieces,ruby_layout
from shengao.render import AssRenderer
from shengao.app import StudioWindow
from shengao.timeline import Timeline
from shengao.theme import STYLE


def lyric_project(texts=None):
    texts=texts or ['真夜中','の','ネオンサイン','が','君','を','抱きしめ','て']
    readings=['まよなか','の','ネオンサイン','が','きみ','を','だきしめ','て']
    units=[Unit(text,1000+n*400,1400+n*400,kana=k) for n,(text,k) in enumerate(zip(texts,readings))]
    for u in units:add_mora(u)
    p=Project(lines=[LyricLine('original',''.join(texts),1000,5000,units=units)])
    p.style.show_romaji=p.style.show_translation=False;p.style.color=p.style.highlight='#ffffff';p.style.outline=p.style.shadow=0
    return p


def frame(renderer,project):
    renderer.set_text(compose(project))
    return np.frombuffer(renderer.rgba(1920,1080,2500),np.uint8).reshape(1080,1920,4).copy()


@pytest.mark.parametrize('font_index,size',[(0,28),(0,62),(1,62),(1,100)])
@pytest.mark.parametrize('spaces',[False,True])
def test_segmented_baseline_has_same_real_glyph_positions_as_continuous_text(font_index,size,spaces):
    words=['真夜中','の','ネオンサイン','が','君','を','抱きしめ','て']
    if spaces:words[2]=' ネオンサイン ';words[6]='抱きしめ\u3000'
    p=lyric_project(words);p.style.show_ruby=False;p.style.size=size
    font=bundled_fonts()[font_index];p.style.font=font.family;p.style.font_file=font.path
    renderer=AssRenderer()
    try:
        segmented=frame(renderer,p);plain=copy.deepcopy(p);plain.lines[0].units=[];continuous=frame(renderer,plain)
        # Compare every visible glyph's horizontal position, including genuine
        # half/full-width source spaces, against one unsegmented ASS event.
        a=np.flatnonzero(segmented[:,:,3].max(axis=0));b=np.flatnonzero(continuous[:,:,3].max(axis=0))
        assert len(a) and len(b)
        assert abs(a[0]-b[0])<=1 and abs(a[-1]-b[-1])<=1
        assert max(min(abs(b-x)) for x in a)<=1
        assert max(min(abs(a-x)) for x in b)<=1
    finally:renderer.close()


def test_long_readings_never_widen_or_shrink_the_original_baseline():
    p=lyric_project();line=p.lines[0];before=line.to_dict();metrics=layout_line(line,p.style)
    line.units[4].kana='きみというひと';line.units[4].highlights=[]
    assert layout_line(line,p.style)[2:]==metrics[2:]
    renderer=AssRenderer()
    try:
        with_ruby=frame(renderer,p);p.style.show_ruby=False;without=frame(renderer,p)
        ys=np.flatnonzero(without[:,:,3].max(axis=1));assert len(ys)
        assert np.array_equal(with_ruby[ys[0]:ys[-1]+1],without[ys[0]:ys[-1]+1])
    finally:renderer.close()
    assert line.text==before['text'] and [(u.start,u.end) for u in line.units]==[(u['start'],u['end']) for u in before['units']]


def test_dense_ruby_fragments_fit_without_colliding_and_keep_individual_timing():
    p=lyric_project(['君','君','君','君','君','君','君','君'])
    for u in p.lines[0].units:u.kana='きみというひと';u.highlights=[];add_mora(u)
    line=p.lines[0];mf,rf,size,ruby_size,widths,width=layout_line(line,p.style)
    annotations=ruby_layout(pieces(line),widths,rf,mf);right=64
    for annotation,u in zip(annotations,line.units):
        center,scale=annotation.center,annotation.scale;w=rf.getlength(u.kana)*scale
        assert center-w/2>=right and 0<scale<=1;right=center+w/2
    assert right<=1856
    text=compose(p);assert '\\fscx' in text
    assert len([r for r in text.splitlines() if r.startswith('Dialogue:') and ',Ruby,' in r])==sum(len(u.highlights) for u in line.units)


def overlapping_project(project):
    p=copy.deepcopy(project);other=copy.deepcopy(p.lines[0]);other.id='second'
    delta=4600;other.start+=delta;other.end+=delta
    for u in other.units:
        u.start+=delta;u.end+=delta
        for h in u.highlights:h.start+=delta;h.end+=delta
    p.lines.append(other);p.duration=12000;return p


@pytest.mark.parametrize('mode',['line','words','mora'])
def test_previous_syllable_markers_are_visible_in_every_mode_without_becoming_drag_targets(qapp,project,mode):
    p=overlapping_project(project);t=Timeline();t.resize(900,260);t.granularity=mode;t.set_neighbors(p.lines[0]);t.set_line(p.lines[1])
    scene,markers,labels=t.scene();tail=t.reference_segments(p.lines[0])[-1]
    assert t.left<=tail[2] and p.lines[0].end<=t.left+t.span
    assert any(m[0]==p.lines[0].end and m[2:5]==(93,205,195) for m in markers)
    assert any(m[0]==tail[2] and m[2:5]==(93,205,195) for m in markers)
    assert all(v[2]>=p.lines[1].start for v in t.targets());t.close()


def window(qapp,tmp_path,project):
    qapp.setStyleSheet(STYLE);w=StudioWindow(home=tmp_path/'home',test=True);w.history=History(overlapping_project(project));w.current=1;w.show();w.refresh(True);w.set_stage(2);qapp.processEvents();return w


def test_previous_lane_click_selects_exact_mora_then_edit_and_undo(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);context=w.previous_context;t=w.timeline;original=w.project.to_dict()
    assert context.isVisible() and '重叠 400 ms' in context.caption.text()
    s=t.reference_segments(t.previous_line)[-1];x=round(t.tx((s[2]+s[3])/2));view=(t.left,t.span)
    QTest.mouseClick(context.lane,Qt.MouseButton.LeftButton,pos=QPoint(x,14));qapp.processEvents()
    assert w.current==0 and (t.word,t.part)==(s[0],s[1]) and t.granularity=='mora'
    assert w.calibration_tabs.currentIndex()==0 and (t.left,t.span)==view
    assert w.project.to_dict()==original
    a,b=w.selected_times();w.change_boundary(t.word,t.part,a,b-200)
    assert w.line.end==5800;w.move_line(1);assert '重叠 200 ms' in context.caption.text()
    w.undo();assert w.project.to_dict()==original and '重叠 400 ms' in context.caption.text();w.close()


def test_context_audition_drag_preview_and_first_line_state(qapp,tmp_path,project,monkeypatch):
    w=window(qapp,tmp_path,project);t=w.timeline;context=w.previous_context;calls=[]
    monkeypatch.setattr(w.playback,'audition',lambda a,b,loop=False:calls.append((a,b,loop)))
    s=t.reference_segments(t.previous_line)[-1];x=round(t.tx((s[2]+s[3])/2))
    QTest.mouseClick(context.lane,Qt.MouseButton.RightButton,pos=QPoint(x,14))
    assert calls[-1][:2]==(s[2],s[3]) and w.current==1
    context.listen.click();assert calls[-1][0]<=s[2] and calls[-1][1]>w.line.start
    before=w.project.to_dict();a,b=w.line.units[0].start,w.line.units[0].end
    t.drag=(0,-1,0,a,b,False);t.ghost=a+100;t.viewChanged.emit()
    assert '重叠 300 ms' in context.caption.text() and w.project.to_dict()==before
    t.drag=None;t.ghost=None;w.move_line(-1);assert context.isHidden() and t.previous_line is None;w.close()


def test_context_can_be_shown_on_compact_window_without_clipping_navigation(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.resize(960,680);qapp.processEvents()
    w.grab().save(str(tmp_path/'overlap-compact.png'))
    assert w.previous_context.visibleRegion().boundingRect().height()==w.previous_context.height()
    assert w.previous_context.lane.height()>=23 and w.previous_context.caption.isVisible()
    assert w.timeline.visibleRegion().boundingRect().height()>=180
    assert not w.navigation_panel.isVisible()
    w.workflow_toggle.click();qapp.processEvents();QTest.qWait(30)
    assert all(b.visibleRegion().boundingRect().height()>=60 for b in w.steps)
    w.workflow_toggle.click();qapp.processEvents();QTest.qWait(30)
    assert w.timeline.visibleRegion().boundingRect().height()>=180
    w.grab().save(str(tmp_path/'overlap-compact.png'));w.close()
