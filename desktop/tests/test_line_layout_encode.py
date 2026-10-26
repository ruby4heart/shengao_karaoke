"""The same wrapped/ruby layout must reach actual encoded video pixels."""
import subprocess
import numpy as np
from shengao.encode import encode,EncodeOptions
from shengao.render import AssRenderer
from shengao.subtitles import compose
from shengao.paths import ffmpeg
from shengao.fonts import project_font_files
from test_line_layout_project import sample


def test_display_only_wrap_and_size_match_live_raster_in_an_actual_sample(video,tmp_path):
    p=sample();p.media=str(video);p.duration=8000;p.width=640;p.height=360;p.fps=25
    before=p.to_dict();output=tmp_path/'逐句字号换行.mp4';encode(p,EncodeOptions(str(output),start=2000,duration=800))
    result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-i',str(output),'-frames:v','1','-f','rawvideo','-pix_fmt','rgba','-'],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0 and len(result.stdout)==640*360*4
    renderer=AssRenderer()
    try:
        renderer.add_fonts(project_font_files(p));renderer.set_text(compose(p));rgba=np.frombuffer(renderer.rgba(640,360,2000),np.uint8).reshape(360,640,4)
    finally:renderer.close()
    actual=np.frombuffer(result.stdout,np.uint8).reshape(360,640,4)[:,:,:3].astype(float);mask=rgba[:,:,3]>250
    assert mask.sum()>150 and np.abs(actual[mask]-rgba[:,:,:3][mask]).mean()<18
    assert p.to_dict()==before
