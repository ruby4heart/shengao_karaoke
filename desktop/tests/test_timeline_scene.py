"""Test the Qt -> original offscreen timeline scene contract and live drags."""
import json
from pathlib import Path
import numpy as np
import pytest
from shengao.timeline import Timeline
from shengao.timeline_view import TimelineRenderer,Scene,cursor_label

ROOT=Path(__file__).resolve().parents[2]

def test_verbatim_methods_match_audit_of_user_original_source():
    shipped=json.loads((ROOT/'desktop/native/aegisub/TIMELINE-SOURCES.json').read_text())
    original=json.loads((ROOT/'desktop/native/aegisub/UPSTREAM-TIMELINE-AUDIT.json').read_text())
    assert shipped['classes_sha256']==original['classes_sha256']
    assert shipped['methods']==original['methods']

def test_scene_has_original_marker_order_styles_and_single_label_per_group(qapp,project):
    t=Timeline();t.resize(1000,260);t.set_line(project.lines[0]);t.duration=8000;t.keyframes=[2000]
    scene,markers,labels=t.scene()
    assert len(labels)==len(project.lines[0].units)
    assert [x[2] for x in labels]==[u.text for u in project.lines[0].units]
    # Original karaoke controller uses dotted, 2px yellow separators; no seconds.
    yellow=[m for m in markers if m[2:5]==(255,255,0)]
    assert yellow and all(m[6:]==(2,1,0) for m in yellow)
    assert all(m[2:5]!=(0,100,255) for m in markers)
    red=next(m for m in markers if m[2:5]==(216,0,0));blue=next(m for m in markers if m[2:5]==(0,0,216))
    assert red[-1]==2 and blue[-1]==1
    assert markers[-1][2:5]==(255,0,255)
    assert scene.cursor_label is None
    t.hover=1235;scene,_,_=t.scene();assert scene.cursor_label==b'0:00:01.24'
    t.close()

def test_drag_preview_moves_boundary_and_highlight_without_touching_project(qapp,project):
    t=Timeline();t.resize(1000,260);line=project.lines[0];t.set_line(line);t.word=0
    before=line.to_dict();a,b=line.units[0].start,line.units[0].end
    t.drag=(0,-1,1,a,b,False);t.ghost=b+100
    provisional=t.preview_line()
    assert provisional.units[0].end==b+100
    # This fixture intentionally has a 200ms pause; do not erase it on drag.
    assert provisional.units[1].start==line.units[1].start
    scene,markers,labels=t.scene();assert scene.selection_end==b+100
    assert labels[0][1]==b+100 and line.to_dict()==before
    t.drag=(0,-1,1,a,b,True);provisional=t.preview_line()
    assert provisional.units[1].end==line.units[1].end+100
    assert line.to_dict()==before
    t.close()

def test_original_offscreen_scene_dpi_and_body_pixels(qapp):
    renderer=TimelineRenderer()
    for dpr in [1.,1.25,1.5,2.]:
        width,height=round(820*dpr),round(240*dpr);top=renderer.top(dpr)
        body=np.full((height-top-15,width,3),37,np.uint8)
        scene=Scene(width,height,180000,125,0,0,-1,-1,-1,10.,dpr,None)
        pixels=renderer.rgb(scene,body)
        assert np.array_equal(pixels[top:height-15],body)
        assert np.any(pixels[:top]!=37) and np.any(pixels[-15:]!=37)
    assert cursor_label(36001235)=='10:00:01.24'

@pytest.mark.parametrize('mode',[0,1,2])
def test_qt_audio_style_boundaries_use_original_truncated_pixels(qapp,project,tmp_path,mode):
    from test_aeg_audio import reference
    from shengao.timing import set_time
    rate=48000;seconds=np.arange(rate*8)/rate
    samples=(np.sin(seconds*2*np.pi*441)*12500).astype(np.int16)
    pcm=tmp_path/'pixels.s16';samples.tofile(pcm)
    t=Timeline();t.resize(500,240);t.set_line(set_time(project.lines[0],-1,1010,6010));t.word=0
    t.show_spectrum=mode==1;t.waveform_averages=mode==2
    t.set_audio({'pcm':str(pcm),'sample_rate':rate,'duration':8000,'peaks':np.ones(8)})
    t.span=10000;t.left=0;t.render_audio();height=t.cache_rgb.shape[0]
    expected=reference(samples,rate,0,500,height,20.,1.,mode,1,0,0)
    selected=t.line.units[0]
    for a,b,style in [(t.line.start,t.line.end,2),(selected.start,selected.end,3)]:
        rendered=reference(samples,rate,0,500,height,20.,1.,mode,1,0,style)
        left,right=max(0,int(a/20)),min(500,int(b/20));expected[:,left:right]=rendered[:,left:right]
    assert np.array_equal(t.cache_rgb,expected)
    t.audio.close();t.audio=None;t.close()
