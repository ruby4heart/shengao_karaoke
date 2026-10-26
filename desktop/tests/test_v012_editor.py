import copy
import json
import re
from pathlib import Path
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPoint,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton,QInputDialog,QDialogButtonBox,QLineEdit,QApplication
from studio_backend.model import LyricLine,Unit,Highlight
from shengao.app import StudioWindow
from shengao.project import Project,History,save_project,load_project
from shengao.tail_model import shift_line,replace_mora,energy_info,consonant_clip
from shengao.tail_dialog import TailDialog
from shengao.fonts import bundled_fonts,font_weight
from shengao.subtitles import compose
from shengao.render import AssRenderer


def window(qapp,tmp_path,p):
    from shengao.theme import STYLE
    qapp.setStyleSheet(STYLE)
    w=StudioWindow(home=tmp_path/'home',test=True);w.playback.audio.setMuted(True);w.history=History(copy.deepcopy(p));w.current=0;w.refresh(True);w.set_stage(2);w.show();qapp.processEvents();return w


def tail_song():
    return Project(lines=[LyricLine('tail','歌います',1000,2000,[
        Unit('歌い',1000,1700,'うたい','utai',highlights=[Highlight('う',1000,1200),Highlight('た',1200,1400),Highlight('い',1400,1700)]),
        Unit('ます',1700,2000,'ます','masu',highlights=[Highlight('ま',1700,1900),Highlight('す',1900,2000)])])],duration=8000)


def attach_pcm(w,tmp_path):
    rate=48000;t=np.arange(rate*8)/rate;samples=(np.sin(t*2*np.pi*220)*10000).astype(np.int16)
    samples[int(1.9*rate):int(2*rate)]=np.random.default_rng(42).normal(0,350,int(.1*rate)).astype(np.int16)
    path=tmp_path/'weak-tail.s16';samples.tofile(path);w.timeline.set_audio({'pcm':str(path),'sample_rate':rate,'duration':8000,'peaks':np.ones(80)})


def test_whole_line_shift_preserves_every_relative_time_and_can_pin_non_grid_start(project):
    line=shift_line(project.lines[0],3);before=line.to_dict();moved=shift_line(line,1500-line.start)
    assert moved.start==1500
    for old,new in zip(line.units,moved.units):
        assert new.text==old.text and new.kana==old.kana and new.end-new.start==old.end-old.start
        assert [(h.start-new.start,h.end-new.start,h.kana) for h in new.highlights]==[(h.start-old.start,h.end-old.start,h.kana) for h in old.highlights]
    assert shift_line(line,-999999).start==0 and line.to_dict()==before
    line.units[0].locked=True
    with pytest.raises(ValueError,match='锁定'):shift_line(line,100)


def test_three_sliders_control_time_display_gain_and_actual_output_volume(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);t=w.timeline;before=w.project.to_dict();a=w.audio_controls
    a.zoom.setValue(20);assert t.zoom_level==20
    a.gain.setValue(75);assert t.amplitude==pytest.approx(3.375)
    w.volume.setValue(40);assert w.playback.audio.volume()==pytest.approx(.4)
    assert all(slider.orientation()==Qt.Orientation.Vertical for slider in [a.zoom,a.gain,w.volume])
    assert w.project.to_dict()==before
    QTest.mouseDClick(a.gain,Qt.MouseButton.LeftButton);assert t.amplitude==1.;w.close()


def test_wrong_time_phrase_can_be_grabbed_in_visible_audio_and_moved_once(qapp,tmp_path,project):
    p=copy.deepcopy(project);p.lines[0]=shift_line(p.lines[0],25000);w=window(qapp,tmp_path,p);t=w.timeline
    t.duration=40000;t.left=0;t.span=10000;w.drag_line.click();before=w.line.to_dict();y=t.audio_top+40
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(80,y));QTest.mouseMove(t,QPoint(180,y))
    assert w.line.to_dict()==before and t.preview_line().start<10000
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(180,y))
    assert w.line.start<10000 and w.line.end-w.line.start==before['end']-before['start'] and len(w.history.undo_stack)==1
    assert [u.text for u in w.line.units]==[u['text'] for u in before['units']]
    w.undo();assert w.line.to_dict()==before;w.redo();assert w.line.start<10000;w.close()


def test_drag_edge_autoscrolls_without_committing_and_escape_cancels(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);t=w.timeline;t.duration=30000;t.left=0
    end=w.line.units[0].end;t.span=end*t.width()/max(1,t.width()-10);t.word=0;before=w.line.to_dict();y=t.audio_top+35
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(t.tx(end)),y))
    QTest.mouseMove(t,QPoint(t.width()-2,y));QTest.qWait(180)
    assert t.left>0 and w.line.to_dict()==before
    QTest.keyClick(t,Qt.Key.Key_Escape);assert t.drag is None and not t.auto_scroll.isActive()
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(t.width()-2,y))
    assert w.line.to_dict()==before and not w.history.undo_stack;w.close()


def test_move_to_playhead_recovers_out_of_view_line_and_protects_locks(qapp,tmp_path,project):
    p=copy.deepcopy(project);p.duration=60000;p.lines[0]=shift_line(p.lines[0],25000);w=window(qapp,tmp_path,p);before=w.line.to_dict()
    w.playback.seek(10000);w.move_to_playhead.click();assert w.line.start==10000 and w.line.end==15000
    w.undo();assert w.line.to_dict()==before;w.project.lines[0].locked=True;w.refresh();assert not w.move_to_playhead.isEnabled();w.close()


def test_workflow_collapses_and_saves_its_state_without_shrinking_video(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.resize(1460,940);w.set_stage(3);w.view_choice.setCurrentIndex(0);QTest.qWait(60)
    assert not w.navigation_panel.isVisible() and not w.workflow_toggle.isChecked();height=w.workspace_scroll.viewport().height()
    w.workflow_toggle.click();QTest.qWait(60)
    assert w.navigation_panel.isVisible() and all(b.visibleRegion().boundingRect().height()>=60 for b in w.steps)
    assert w.workspace_scroll.viewport().height()<height and w.playback.height()>=280;w.close()
    w=window(qapp,tmp_path,project);assert w.workflow_toggle.isChecked();w.workflow_toggle.click();w.close()


def test_default_views_keep_video_choice_and_reach_full_axis_and_large_style_preview(qapp,tmp_path,project):
    p=copy.deepcopy(project);other=copy.deepcopy(p.lines[0]);other.id='second';p.lines.append(other)
    w=window(qapp,tmp_path,p);w.current=1;w.refresh()
    for width,height in [(1460,940),(960,680),(1280,800),(960,620),(1460,940)]:
        w.resize(width,height);w.set_stage(2);w.show_audio_axis();QTest.qWait(80)
        assert w.view_choice.currentIndex()==0 and w.playback.isVisible()
        assert w.timeline.visibleRegion().boundingRect().height()==w.timeline.height(),(width,height,w.timeline.geometry())
        assert w.previous_context.isVisible() and w.timeline.height()>=180
        w.workflow_toggle.setChecked(True);w.show_audio_axis();QTest.qWait(80)
        assert w.timeline.visibleRegion().boundingRect().height()==w.timeline.height(),(width,height,'expanded')
        assert w.quick_segment.isVisible() and w.quick_reading.isVisible() and w.calibrate_footer.isVisible()
        w.workflow_toggle.setChecked(False);QTest.qWait(50)
    w.set_stage(3);QTest.qWait(50)
    assert w.playback.isVisible() and not w.audio_group.isVisible() and w.playback.canvas.height()>350
    w.close()


def test_obvious_segmentation_and_reading_actions_follow_original_lyrics(qapp,tmp_path,project):
    p=copy.deepcopy(project);p.lines[0].units=[];p.lines[0].kana=p.lines[0].romaji='';w=window(qapp,tmp_path,p);original=w.line.text
    w.quick_segment.click();assert QApplication.activeModalWidget() is None
    w.inline_segment.dictionary.click();w.inline_segment.apply.click();assert w.line.units and w.line.text==original
    w.quick_reading.click();assert w.calibration_tabs.currentIndex()==1 and w.change_reading_button.isEnabled()
    w.change_reading_button.click();editor=QApplication.focusWidget();assert isinstance(editor,QLineEdit);editor.setText('こんにち');assert w.flush_edits()
    assert w.line.units[0].kana=='こんにち' and w.line.text==original
    w.quick_timing.click();assert w.calibration_tabs.currentIndex()==0 and w.timeline.granularity=='mora';w.close()


def test_beginner_next_actions_advance_in_order_without_aegisub_knowledge(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);w.set_stage(1);assert '检查假名' in w.next_button.text();w.next_button.click()
    assert w.stage==2 and w.calibration_tabs.currentIndex()==1
    w.calibrate_footer.click();assert w.project.checks[w.line.id]['reading'] and not w.line.reviewed
    assert '校准时间' in w.next_button.text();w.next_button.click();assert w.calibration_tabs.currentIndex()==0
    w.calibrate_footer.click();assert w.line.reviewed and '调整样式' in w.next_button.text()
    w.next_button.click();assert w.stage==3 and '先看样片' in w.next_button.text();w.close()


def test_main_buttons_explain_their_scope(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project)
    missing=[b.text() for b in w.findChildren(QPushButton) if b.text().strip() and not b.toolTip()]
    assert not missing,missing
    assert '相对' in w.move_to_playhead.toolTip() or '一起' in w.move_to_playhead.toolTip();w.close()


def test_weak_tail_view_has_real_audio_context_slow_play_and_cancel(qapp,tmp_path):
    w=window(qapp,tmp_path,tail_song());attach_pcm(w,tmp_path);before=w.line.to_dict();calls=[];w.playback.audition=lambda *args:calls.append(args)
    old_rate=w.playback.player.playbackRate();old_loop=w.playback.loop;d=TailDialog(w.line,w.playback,w.timeline,w);d.show();QTest.qWait(50)
    assert d.part()[2].kana=='す' and d.timeline.span<1500 and '混合' in d.energy.text()
    d.listen(True);assert calls[-1]==(1600,2100,True) and w.playback.player.playbackRate()==.75
    d.listen(False);assert calls[-1]==(1900,2000,True)
    d.mode.setCurrentIndex(1);assert not d.timeline.show_spectrum;d.gain.setValue(4);assert d.timeline.amplitude==4
    assert d.controls_scroll.horizontalScrollBar().maximum()==0
    d.end.setValue(2010);d.reading.setText('て');d.accept_changes()
    assert d.result_line.units[-1].highlights[-1].kana=='て' and d.result_line.end==2010
    assert w.line.to_dict()==before and d.timeline.audio is None and w.playback.player.playbackRate()==old_rate and w.playback.loop==old_loop
    w.close()


def test_tail_pending_reading_survives_nudge_and_switch_and_cancel(qapp,tmp_path):
    w=window(qapp,tmp_path,tail_song());d=TailDialog(w.line,w.playback,w.timeline,w);before=w.project.to_dict()
    d.reading.setText('て');d.end.setValue(2020);d.nudge(1,10);assert d.reading.text()=='て';d.combo.setCurrentIndex(d.selected-1)
    assert d.preview.units[-1].highlights[-1].kana=='て' and d.preview.end==2030
    d.reject();assert w.project.to_dict()==before;w.close()


def test_tail_edits_apply_once_with_undo_and_keep_original_word_text(qapp,tmp_path):
    w=window(qapp,tmp_path,tail_song());before=w.project.to_dict()
    def edit():
        d=qapp.activeModalWidget();assert isinstance(d,TailDialog);d.end.setValue(2020);d.reading.setText('て');d.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
    w.quick_tail.click();QTimer.singleShot(20,edit);w.fine_listener.large.click()
    assert w.line.text=='歌います' and w.line.units[-1].text=='ます' and w.line.units[-1].kana=='まて'
    assert w.line.end==2020 and len(w.history.undo_stack)==1
    w.undo();assert w.project.to_dict()==before;w.redo();assert w.line.end==2020;w.close()


def test_tail_reading_correction_preserves_neighbours_and_rejects_kanji():
    p=tail_song();line=p.lines[0];before=line.to_dict();result=replace_mora(line,1,1,'テ')
    assert result.units[1].kana=='まて' and result.units[1].romaji=='mate'
    assert [(h.start,h.end) for h in result.units[1].highlights]==[(1900-200,1900),(1900,2000)]
    assert line.to_dict()==before
    for bad in ['手','すて','']:
        with pytest.raises(ValueError):replace_mora(line,1,1,bad)
    line.locked=True
    with pytest.raises(ValueError,match='锁定'):replace_mora(line,1,1,'て')


def test_energy_cue_is_only_mixture_level_not_a_phoneme_guess():
    samples=np.concatenate([np.full(12000,10000,np.int16),np.full(12000,1000,np.int16)])
    data=energy_info(samples,48000,250,500)
    assert data['relative']==pytest.approx(.1) and data['duration']==250 and 'phoneme' not in data


def test_consonant_audition_reduces_low_frequency_without_changing_source():
    import io,wave
    rate=48000;t=np.arange(rate)/rate;samples=(np.sin(t*2*np.pi*220)*10000+np.sin(t*2*np.pi*6000)*500).astype(np.int16);before=samples.copy()
    data,info=consonant_clip(samples,rate,0,1000)
    with wave.open(io.BytesIO(data),'rb') as stream:
        assert stream.getframerate()==rate and stream.getnframes()==rate and stream.getnchannels()==1
        result=np.frombuffer(stream.readframes(rate),'<i2').astype(float)
    before_fft=np.abs(np.fft.rfft(samples.astype(float)));after_fft=np.abs(np.fft.rfft(result))
    assert after_fft[6000]/after_fft[220]>10*(before_fft[6000]/before_fft[220])
    assert np.array_equal(samples,before) and info['start']==0 and info['end']==1000 and info['gain']<=8
    silent,_=consonant_clip(np.zeros(4800,np.int16),rate,0,100)
    with wave.open(io.BytesIO(silent),'rb') as stream:assert not any(stream.readframes(4800))


def test_enhanced_tail_plays_real_memory_audio_and_keeps_original_media(qapp,tmp_path,project):
    import time
    w=window(qapp,tmp_path,tail_song());attach_pcm(w,tmp_path);w.playback.open(project.media);source=w.playback.player.source();before=w.project.to_dict()
    d=TailDialog(w.line,w.playback,w.timeline,w);d.show();d.enhance.setChecked(True);d.listen(True)
    deadline=time.monotonic()+5
    while time.monotonic()<deadline and d.filtered_player.position()<30:qapp.processEvents();QTest.qWait(10)
    assert d.filtered_player.duration()>0 and d.filtered_player.position()>=30,d.status.text()
    assert d.filtered_audio.isMuted() and d.filtered_player.pitchCompensation() and d.filtered_player.playbackRate()==.75
    assert w.playback.player.source()==source and w.project.to_dict()==before
    calls=[];w.playback.audition=lambda *args:calls.append(args);d.audio_action('line')
    assert d.filtered_player.playbackState().name=='StoppedState' and calls[-1]==(1000,2000,True)
    d.reject();assert d.filtered_player.playbackState().name=='StoppedState';w.close()


def test_recommended_fonts_keep_exact_weight_through_save_and_ass(qapp,tmp_path,project):
    w=window(qapp,tmp_path,project);before=[l.to_dict() for l in w.project.lines];w.apply_preset(2)
    assert font_weight(w.project.style.font_file,w.project.style.font)==900
    assert font_weight(w.project.style.ruby_font_file,w.project.style.ruby_font)==700
    assert '\\b900' in compose(w.project) and [l.to_dict() for l in w.project.lines]==before
    path=tmp_path/'weight.sgproj';save_project(w.project,path);p=load_project(path)
    assert font_weight(p.style.font_file,p.style.font)==900 and compose(p)==compose(w.project)
    w.history=History(p);w.refresh();assert Path(w.font_choice.currentData().path).name=='NotoSerifCJKjp-Black.otf';w.close()


def test_mixed_font_library_renders_same_black_face_as_isolated_file(tmp_path,project):
    import shutil
    p=copy.deepcopy(project);font=bundled_fonts()[3];p.style.font=font.family;p.style.font_file=font.path;p.style.show_ruby=p.style.show_romaji=p.style.show_translation=False
    text=compose(p);only=tmp_path/'only-black';only.mkdir();shutil.copy2(font.path,only/Path(font.path).name)
    mixed=AssRenderer();isolated=AssRenderer(fonts=only)
    try:
        mixed.set_text(text);isolated.set_text(text);black=mixed.rgba(960,540,2000);assert black==isolated.rgba(960,540,2000)
        p.style.font_file=bundled_fonts()[1].path;mixed.set_text(compose(p));assert mixed.rgba(960,540,2000)!=black
    finally:mixed.close();isolated.close()


def test_black_mincho_and_bold_ruby_match_actual_ffmpeg_frame(qapp,tmp_path,project):
    import shutil,subprocess
    from shengao.paths import ffmpeg
    w=window(qapp,tmp_path,project);w.apply_preset(2);p=copy.deepcopy(w.project);w.close();text=compose(p)
    (tmp_path/'lyrics.ass').write_text(text,encoding='utf-8-sig');folder=tmp_path/'fonts';folder.mkdir()
    for font in bundled_fonts():shutil.copy2(font.path,folder/Path(font.path).name)
    result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=black:s=640x360:r=25:d=3','-vf','ass=lyrics.ass:fontsdir=fonts','-ss','1.5','-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'],cwd=tmp_path,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    renderer=AssRenderer()
    try:
        renderer.set_text(text);rgba=np.frombuffer(renderer.rgba(640,360,1500),np.uint8).reshape(360,640,4)
        expected=rgba[:,:,:3].astype(float)*rgba[:,:,3:4]/255;actual=np.frombuffer(result.stdout,np.uint8).reshape(360,640,4)[:,:,:3].astype(float)
        mask=np.max(expected,axis=2)>20;assert mask.sum()>300 and np.abs(actual[mask]-expected[mask]).mean()<18
    finally:renderer.close()


def test_closed_renderer_cannot_render_through_a_released_native_handle():
    renderer=AssRenderer();renderer.close();renderer.close()
    assert renderer.handle is None and renderer.rgba(16,16,0)==bytes(16*16*4)
    with pytest.raises(ValueError,match='关闭'):renderer.set_text('[Script Info]')
