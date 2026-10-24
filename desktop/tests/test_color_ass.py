"""Render real libass pixels, including complementary outline/shadow sweeps."""
import copy
import pytest
from pathlib import Path
from types import SimpleNamespace
from shengao.color_states import default_profile
from shengao.color_ass import component_events,box_events
from shengao.project import Project
from shengao.presentation import DisplayWindow
from shengao.subtitles import compose
from shengao.render import AssRenderer


def palette():
    p=default_profile(Project().style)
    for state,color in [('waiting','#ff0000'),('singing','#00ff00'),('sung','#ffff00')]:
        p['layers']['lyrics'][state]['primary']={'color':color,'opacity':100}
        p['layers']['lyrics'][state]['secondary']={'color':'#0000ff','opacity':100}
    return p


def pixels(profile,when,box=False):
    window=DisplayWindow(0,3000);r=AssRenderer()
    try:
        if box:events=box_events(profile,window,(1000,2000),(800,400,1120,540))
        else:events=component_events(profile,'lyrics',r'{\an5\pos(960,500)\fs100}田田',window,(1000,2000),1,4,8,timing=(1000,2000),advance=(860,1060))
        r.set_text(compose(Project())+'\n'.join(events)+'\n')
        return r.rgba(1920,1080,when)
    finally:r.close()


def count(raw,rgb):return sum(raw[i:i+3]==bytes(rgb) and raw[i+3]>240 for i in range(0,len(raw),4))


def test_real_waiting_midpoint_and_sung_colours():
    p=palette()
    assert count(pixels(p,500),(255,0,0))>100
    middle=pixels(p,1500)
    assert count(middle,(0,255,0))>100 and count(middle,(0,0,255))>100
    assert count(pixels(p,2500),(255,255,0))>100


def test_real_outline_and_shadow_follow_sweep_with_distinct_colours():
    p=palette();p['motion'].update(outline='sweep',shadow='sweep')
    for state,outline,shadow in [('waiting','#ff00ff','#ff8000'),('singing','#00ffff','#8000ff')]:
        p['layers']['lyrics'][state]['outline']={'color':outline,'opacity':100}
        p['layers']['lyrics'][state]['shadow']={'color':shadow,'opacity':100}
    image=pixels(p,1500)
    for rgb in [(255,0,255),(0,255,255),(255,128,0),(128,0,255)]:assert count(image,rgb)>10


def test_background_is_independent_rounded_layer_and_respects_opacity():
    p=palette();p['box'].update(enabled=True,padding=12,radius=12)
    p['box']['states']['waiting']={'color':'#123456','opacity':50}
    raw=pixels(p,500,box=True)
    center=4*(450*1920+900);corner=4*(388*1920+788)
    assert 125<=raw[center+3]<=130 and raw[corner+3]==0


def test_project_composition_uses_new_profile_and_retains_editable_metadata():
    import base64,json
    from studio_backend.model import LyricLine,Unit
    from shengao.color_states import update_settings
    line=LyricLine('a','田田',1000,2000,[Unit('田田',1000,2000)],display_start=0,display_end=3000)
    p=Project(lines=[line]);p.style.show_ruby=p.style.show_romaji=p.style.show_translation=False
    p.color_styles=update_settings({},palette());before=p.to_dict();text=compose(p,embed=True)
    embedded=json.loads(base64.b64decode(text.splitlines()[0].split(': ',1)[1]))
    assert Project.from_dict(embedded).to_dict()==before and p.to_dict()==before
    r=AssRenderer()
    try:
        r.set_text(text)
        assert count(r.rgba(1920,1080,500),(255,0,0))>100
        assert count(r.rgba(1920,1080,2500),(255,255,0))>100
    finally:r.close()


@pytest.mark.parametrize('when',[520,1520,2520])
def test_new_colours_preview_and_actual_ffmpeg_frames_match(tmp_path,when):
    import shutil,subprocess,numpy as np
    from studio_backend.model import LyricLine,Unit,Highlight
    from shengao.color_states import update_settings
    from shengao.fonts import bundled_fonts
    from shengao.paths import ffmpeg
    unit=Unit('今日',1000,2000,kana='きょう',highlights=[Highlight('きょ',1000,1500),Highlight('う',1500,2000)])
    p=Project(lines=[LyricLine('a','今日',1000,2000,[unit],romaji='kyou',translation='今天',display_start=0,display_end=3000)])
    colors=palette();colors['motion'].update(outline='sweep',shadow='sweep');colors['box'].update(enabled=True,radius=10)
    for state in colors['box']['states']:colors['box']['states'][state]={'color':'#202040','opacity':80}
    p.color_styles=update_settings({},colors);text=compose(p)
    folder=tmp_path/'fonts';folder.mkdir()
    for font in bundled_fonts():shutil.copy2(font.path,folder/Path(font.path).name)
    (tmp_path/'lyrics.ass').write_text(text,encoding='utf-8-sig')
    output=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=black:s=640x360:r=25:d=3',
        '-vf','ass=lyrics.ass:fontsdir=fonts','-ss',str(when/1000),'-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'],cwd=tmp_path,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert output.returncode==0
    actual=np.frombuffer(output.stdout,np.uint8).reshape(360,640,4)[:,:,:3].astype(np.float32)
    renderer=AssRenderer()
    try:renderer.set_text(text);data=np.frombuffer(renderer.rgba(640,360,when),np.uint8).reshape(360,640,4)
    finally:renderer.close()
    expected=data[:,:,:3].astype(np.float32)*data[:,:,3:4]/255;mask=np.max(expected,axis=2)>20
    assert mask.sum()>150 and np.mean(np.abs(expected[mask]-actual[mask]))<18
    assert np.logical_xor(np.max(actual,axis=2)>20,mask).sum()<100
