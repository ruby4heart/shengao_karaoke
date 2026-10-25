import json
import subprocess
import numpy as np
from shengao.project import Project
from shengao.fonts import bundled_fonts,project_font_files
from shengao.song_info import DEFAULTS
from shengao.paths import ffmpeg
from shengao.encode import encode,EncodeOptions
from shengao.render import AssRenderer
from shengao.subtitles import compose
from shengao.subtitle_files import export_subtitle
from studio_backend.model import LyricLine


def frame(path,when):
    result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-ss',str(when/1000),'-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    return np.frombuffer(result.stdout,dtype=np.uint8).reshape(360,640,3).astype(float)


def test_actual_full_encode_and_offset_sample_match_live_credits(video,tmp_path):
    font=bundled_fonts()[2]
    p=Project(media=str(video),duration=8000,width=640,height=360,has_video=True,
              lines=[LyricLine('line','明日へ',1000,4000)],
              song_info={**DEFAULTS,'enabled':True,'title':'夜色の練習曲','artist':'声稿 デモ',
                         'font':font.family,'font_file':font.path,'title_size':72,'artist_size':46,
                         'title_color':'#ff3355','artist_color':'#73e8bb','period':'range','start':1000,'end':4000})
    full=tmp_path/'全片.mp4';sample=tmp_path/'偏移样片.mp4'
    encode(p,EncodeOptions(str(full)));encode(p,EncodeOptions(str(sample),start=1200,duration=800))
    actual=frame(full,1200);short=frame(sample,0);renderer=AssRenderer()
    try:
        renderer.add_fonts(project_font_files(p));renderer.set_text(compose(p));overlay=np.frombuffer(renderer.rgba(640,360,1200),dtype=np.uint8).reshape(360,640,4)
    finally:renderer.close()
    mask=(overlay[:,:,3]>250);mask[150:]=False
    assert mask.sum()>250
    glyph_error=float(np.abs(actual[mask]-overlay[:,:,:3][mask]).mean())
    sample_error=float(np.abs(actual-short).mean())
    assert glyph_error<16 and sample_error<3
    export_subtitle(p,tmp_path/'credits.ass')
    # Compare the actual compositors in full-range RGB separately from the
    # chroma subsampling and compression in the deliverable H.264 MP4 above.
    lossless=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-i',str(video),'-vf','format=rgb24,setparams=range=full,ass=credits.ass:fontsdir=credits.assets/fonts','-ss','1.2','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],cwd=tmp_path,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    assert lossless.returncode==0,lossless.stderr.decode(errors='replace')
    lossless_pixels=np.frombuffer(lossless.stdout,dtype=np.uint8).reshape(360,640,3).astype(float)
    renderer_error=float(np.abs(lossless_pixels[mask]-overlay[:,:,:3][mask]).mean())
    assert renderer_error<3
    # Neither before appearance nor after disappearance should contain the logo.
    original=frame(video,500);before=frame(full,500);after=frame(full,4500)
    assert float(np.abs(before[:95]-original[:95]).mean())<2
    assert float(np.abs(after[:95]-original[:95]).mean())<2
    (tmp_path/'credits-encode-metrics.json').write_text(json.dumps({'passed':True,'core_pixels':int(mask.sum()),'lossless_renderer_core_mean_rgb_error':renderer_error,'lossy_h264_core_mean_rgb_error':glyph_error,'offset_sample_mean_rgb_error':sample_error,'font':font.family,'full_duration_ms':8000,'sample_start_ms':1200},indent=2),encoding='utf-8')
