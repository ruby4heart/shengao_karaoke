import copy
import json
import re
from pathlib import Path
import numpy as np
import pytest
from PySide6.QtCore import Qt,QEvent,QPointF,QPoint,QTimer
from PySide6.QtGui import QKeyEvent,QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox,QLineEdit
from studio_backend.model import LyricLine,Unit
from studio_backend.japanese import add_mora
from shengao.project import Project,History
from shengao.app import StudioWindow
from shengao.aeg_hotkeys import AUDIO,ALWAYS,command
from shengao.subtitles import compose
from shengao.render import AssRenderer
from shengao.segmentation_dialog import SegmentationDialog,regroup

ROOT=Path(__file__).resolve().parents[2]

def event(name):
    modifiers=Qt.KeyboardModifier.NoModifier
    for text,flag in [('Ctrl-',Qt.KeyboardModifier.ControlModifier),('Alt-',Qt.KeyboardModifier.AltModifier),('Shift-',Qt.KeyboardModifier.ShiftModifier)]:
        if text in name:modifiers|=flag;name=name.replace(text,'')
    if name.startswith('KP_'):modifiers|=Qt.KeyboardModifier.KeypadModifier;name=name[3:]
    keys={'Enter':Qt.Key.Key_Enter if modifiers&Qt.KeyboardModifier.KeypadModifier else Qt.Key.Key_Return,'Add':Qt.Key.Key_Plus,'Subtract':Qt.Key.Key_Minus,'Multiply':Qt.Key.Key_Asterisk,'Right':Qt.Key.Key_Right,'Left':Qt.Key.Key_Left,'Space':Qt.Key.Key_Space}
    return QKeyEvent(QEvent.Type.KeyPress,keys.get(name,ord(name) if len(name)==1 else 0),modifiers)

def test_audio_and_medusa_bindings_cover_exact_user_aegisub_defaults():
    source=json.loads((ROOT/'vendor/aegisub/src/libresrc/default_hotkey.json').read_text())
    assert set(AUDIO)=={key for keys in source['Audio'].values() for key in keys}
    assert set(ALWAYS)=={key for keys in source['Always'].values() for key in keys}
    for key,action in AUDIO.items():assert command(event(key),audio=True)==action
    for key,action in ALWAYS.items():
        assert command(event(key),medusa=True)==action
        assert command(event(key)) is None
    for key in ['Alt-R','Shift-R','Ctrl-G','Shift-Right','+','-']:
        assert command(event(key),audio=True) is None

def make_window(qapp,tmp_path,p):
    w=StudioWindow(home=tmp_path/'home',test=True);w.playback.audio.setMuted(True);w.history=History(p);w.current=0;w.refresh();w.set_stage(2);w.show();qapp.processEvents();return w

def test_real_key_events_commit_sequentially_keep_karaoke_last_edge_and_input_focus(qapp,tmp_path,project):
    p=copy.deepcopy(project);other=copy.deepcopy(p.lines[0]);other.id='next';other.reviewed=True;p.lines.append(other)
    w=make_window(qapp,tmp_path,p);w.playback.audition=lambda *args:True
    w.timeline.setFocus();w.select_target(0,-1);before=w.line.to_dict()
    QTest.keyClick(w.timeline,Qt.Key.Key_Plus);assert w.line.to_dict()==before
    QTest.keyClick(w.timeline,Qt.Key.Key_Plus,Qt.KeyboardModifier.KeypadModifier)
    assert w.line.units[0].end==before['units'][0]['end']+10;w.undo()
    w.select_target(len(w.line.units)-1,-1);last=w.line.to_dict()
    QTest.keyClick(w.timeline,Qt.Key.Key_Plus,Qt.KeyboardModifier.KeypadModifier);assert w.line.to_dict()==last
    w.calibration_tabs.setCurrentIndex(1);w.translation.setFocus();QTest.keyClicks(w.translation,'G123')
    assert w.current==0 and w.line.translation.endswith('G123')
    w.timeline.setFocus();QTest.keyClick(w.timeline,Qt.Key.Key_G,Qt.KeyboardModifier.ShiftModifier)
    assert w.current==1 and w.project.lines[0].reviewed and w.line.start==other.start
    w.current=0;w.refresh();QTest.keyClick(w.timeline,Qt.Key.Key_G)
    assert w.current==1  # Aegisub advances even when Commit has no new changes.
    w.close()

def test_medusa_mode_explicitly_enabled_and_isolated_from_modal_dialog(qapp,tmp_path,project):
    w=make_window(qapp,tmp_path,project);calls=[];w.playback.audition=lambda *args:calls.append(args)
    w.calibration_tabs.setCurrentIndex(1);w.translation.setFocus();QTest.keyClick(w.translation,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier)
    assert not calls
    from shengao.audio_shortcuts import Profile
    w.adopt_audio_profile(Profile.defaults(medusa=True,protect_text=False));QTest.keyClick(w.translation,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier)
    assert calls[-1][:2]==w.selected_times()
    d=SegmentationDialog(w.line,w.playback,w);d.show();qapp.processEvents();field=QLineEdit(d);QTest.keyClick(field,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier)
    assert field.text()=='5' and len(calls)==1;d.close();w.close()

def test_table_selection_in_mora_mode_targets_a_real_syllable(qapp,tmp_path,project):
    w=make_window(qapp,tmp_path,project);w.granularity.setCurrentIndex(w.granularity.findData('mora'));w.select_target(1,-1)
    assert (w.timeline.word,w.timeline.part)==(1,0)
    part=copy.deepcopy(w.line.units[1].highlights[0]);w.audio_action('length_plus')
    assert w.line.units[1].highlights[0].end==part.end+10;w.undo();assert w.line.units[1].highlights[0]==part;w.close()

def test_audio_actions_select_toggle_scroll_and_shift_commit_in_line_mode(qapp,tmp_path,project):
    p=copy.deepcopy(project);other=copy.deepcopy(p.lines[0]);other.id='second';p.lines.append(other)
    w=make_window(qapp,tmp_path,p);calls=[];w.playback.audition=lambda *args:calls.append(args);w.playback.toggle=lambda:pytest.fail('B must audition selection, not unrestricted video')
    w.select_target(1,-1);w.audio_action('toggle');assert calls[-1][:2]==w.selected_times()
    w.timeline.duration=90000;w.timeline.span=8000;w.timeline.left=5000;before=w.timeline.left
    w.audio_action('scroll_right');assert abs(w.timeline.left-before-128*w.timeline.pixel_ms/w.timeline.devicePixelRatioF())<w.timeline.pixel_ms
    w.granularity.setCurrentIndex(w.granularity.findData('line'));count=len(calls);w.audio_action('next');assert w.current==1 and len(calls)==count
    w.current=0;w.refresh();end=w.line.end;w.audio_action('confirm_default');assert w.current==1 and (w.line.start,w.line.end)==(end,end+3000)
    w.undo();assert w.project.lines[1].to_dict()==other.to_dict();w.close()

@pytest.mark.parametrize('position',['top','center','bottom'])
def test_dense_or_multiline_double_displays_stay_in_frame_and_unrelated_overlaps_do_not_move_earlier_lyrics(position):
    p=Project(lines=[LyricLine('first','今日も歌う',1000,6000,units=[Unit('今日も歌う',1000,6000,'きょうもうたう')])]);p.style.display_mode='alternating';p.style.position=position;p.style.size=108;p.style.ruby_size=46
    before=compose(p)
    for n in range(12):p.lines.append(LyricLine(str(n),'君と歌う',30000,36000,units=[Unit('君と歌う',30000,36000,'きみとうたう')]))
    r=AssRenderer()
    try:
        r.set_text(before);a=r.rgba(640,360,2000);r.set_text(compose(p));assert r.rgba(640,360,2000)==a
        for n in range(13):
            isolated=copy.deepcopy(p);isolated.lines[n].text+='\n明日も歌う';isolated.lines[n].units=[];isolated.style.size=180;isolated.style.ruby_size=180;isolated.style.bottom=400
            text=compose(isolated);positions=re.findall(r'\\pos\([^,]+,(-?[0-9.]+)\)',text)
            assert positions and all(0<float(y)<1080 for y in positions)
        # Every original phrase has non-transparent pixels when rendered alone
        # at the same positions composed for the dense project.
        rows=compose(p).splitlines();header='\n'.join(rows[:rows.index('[Events]')+2])+'\n'
        events=[line for line in rows if line.startswith('Dialogue:') and ',Lyrics,' in line]
        for n,row in enumerate(events):
            r.set_text(header+row+'\n');assert any(r.rgba(640,360,2000 if n==0 else 32000))
    finally:r.close()

def test_click_double_line_mode_at_empty_playhead_seeks_and_renders_without_changing_axis(qapp,tmp_path,project):
    w=make_window(qapp,tmp_path,project);w.set_stage(3);before=[x.to_dict() for x in w.project.lines];w.playback.seek(9000);w.subtitle_toggle.setChecked(False)
    w.display_mode.setCurrentIndex(w.display_mode.findData('alternating'));qapp.processEvents();w.playback.tick()
    assert w.subtitle_toggle.isChecked() and w.line.start<=w.playback.canvas.position<w.line.end
    assert any(w.playback.canvas.renderer.rgba(640,360,w.playback.canvas.position))
    assert [x.to_dict() for x in w.project.lines]==before;w.close()

def test_unmatched_line_can_be_cut_regenerated_and_retimed_without_recognition(qapp,tmp_path):
    line=LyricLine('unmatched','真夜中のネオンサイン',0,5000,match={'status':'unmatched'})
    w=make_window(qapp,tmp_path,Project(lines=[line]));assert '未匹配' in w.segmentation_hint.text() and w.resegment_button.isEnabled()
    d=SegmentationDialog(line,w.playback,w);d.toggle_cut(3);assert [d.table.item(n,0).text() for n in range(d.table.rowCount())]==['真夜中','のネオンサイン']
    d.dictionary.click();assert d.table.rowCount()>1;d.clear.click();assert d.table.rowCount()==1;d.reject();assert w.line.to_dict()==line.to_dict()
    def apply_modal():
        dialog=qapp.activeModalWidget();assert isinstance(dialog,SegmentationDialog);dialog.toggle_cut(3);dialog.begin.setValue(10000);dialog.end.setValue(16000);dialog.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
    QTimer.singleShot(20,apply_modal);w.resegment_dialog()
    assert [u.text for u in w.line.units]==['真夜中','のネオンサイン'] and (w.line.start,w.line.end)==(10000,16000)
    assert not w.line.match and w.calibration_tabs.currentIndex()==1 and not w.project.checks[line.id]['reading']
    w.undo();assert w.line.to_dict()==line.to_dict();w.redo();assert len(w.line.units)==2;w.close()

def test_regroup_preserves_exact_group_manual_readings_and_protects_locks(project):
    line=copy.deepcopy(project.lines[0]);line.units[0].kana='あす';line.units[0].highlights=[];line.units[0].reading_source='manual';add_mora(line.units[0]);cuts=[];cursor=0
    for u in line.units[:-1]:cursor+=len(u.text);cuts.append(cursor)
    result=regroup(line,cuts);assert result.units[0]==line.units[0]
    line.units[0].locked=True
    with pytest.raises(ValueError,match='锁定'):regroup(line,cuts)

def test_waveform_switch_is_immediate_preserves_axis_and_persists(qapp,tmp_path,project):
    w=make_window(qapp,tmp_path,project);before=w.project.to_dict();w.timeline.left=1200;w.timeline.span=5000;w.playback.seek(2000)
    w.audio_view.setCurrentIndex(1);assert not w.timeline.show_spectrum
    assert w.timeline.left==1200 and w.timeline.span==5000 and w.project.to_dict()==before and w.playback.canvas.position==2000
    w.close();w=make_window(qapp,tmp_path,project);assert w.audio_view.currentData()=='waveform' and not w.timeline.show_spectrum
    w.audio_view.setCurrentIndex(0);assert w.timeline.show_spectrum;w.close()

def test_video_wheel_zoom_changes_size_scrolls_and_restores_fit(qapp,tmp_path,project):
    w=make_window(qapp,tmp_path,project);w.view_choice.setCurrentIndex(0);w.playback.set_source_size(1920,1080);qapp.processEvents();p=w.playback;before=p.canvas.size();zoom=before.width()/1920
    e=QWheelEvent(QPointF(100,100),QPointF(100,100),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
    qapp.sendEvent(p.canvas,e);qapp.processEvents();assert p.zoom==pytest.approx(zoom+.125,abs=.0001) and p.canvas.width()>before.width()
    p.set_zoom(2);qapp.processEvents();assert p.viewport.horizontalScrollBar().maximum()>0
    p.set_zoom(.125);assert p.canvas.size().width()==240
    QTest.mouseDClick(p.canvas,Qt.MouseButton.LeftButton);qapp.processEvents();assert p.zoom is None
    old_width=p.viewport.width();w.large_video.click();qapp.processEvents();assert not w.right_panel.isVisible() and p.viewport.width()>old_width
    w.refresh();assert not w.right_panel.isVisible();w.large_video.click();assert w.right_panel.isVisible();w.close()
