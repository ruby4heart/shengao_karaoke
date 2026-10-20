import json
from pathlib import Path
import subprocess
import threading
import numpy as np
import pytest
from shengao.fonts import bundled_fonts,missing
from shengao.render import AssRenderer
from shengao.subtitles import compose,layout_issues
from shengao.media import analyze
from shengao.encode import EncodeOptions,encode
from shengao.paths import ffmpeg

def test_font_coverage_real_japanese_and_missing():
    font=bundled_fonts()[0]
    assert missing(font.path,'今日も歌う きょう Kyou 今天也要歌唱')==''
    assert missing(font.path,'\U0010ffff')=='\U0010ffff'

def test_collection_keeps_selected_second_family_in_layout_and_export(project,tmp_path):
    from fontTools.ttLib import TTCollection,TTFont
    from shengao.fonts import fonts_in_file,families_in_file,face_index,metric_font
    from shengao.subtitles import layout_line
    from shengao.project import save_project,load_project
    fonts=bundled_fonts();path=tmp_path/'two-families.otc'
    collection=TTCollection();collection.fonts=[TTFont(f.path) for f in fonts]
    collection.save(path);collection.close()
    found=fonts_in_file(str(path));assert [f.family for f in found]==[f.family for f in fonts]
    assert {f.family for f in fonts}.issubset(families_in_file(path))
    assert face_index(str(path),fonts[1].family)==1
    project.style.font=fonts[1].family;project.style.font_file=str(path)
    rendered=compose(project)
    assert 'Style: Lyrics,Noto Serif CJK JP,' in rendered
    metrics=layout_line(project.lines[0],project.style)[0]
    assert metrics.getlength('今日 ABC')==metric_font(fonts[1].path,project.style.size).getlength('今日 ABC')
    saved=tmp_path/'collection.sgproj';save_project(project,saved);reopened=load_project(saved)
    assert compose(reopened)==rendered

def test_live_highlight_changes_and_shows_no_before_line(project):
    renderer=AssRenderer();renderer.set_text(compose(project))
    a=renderer.rgba(640,360,1500);b=renderer.rgba(640,360,2500)
    assert a!=b;assert not any(renderer.rgba(640,360,0));renderer.close()

def test_libass_live_and_ffmpeg_same_pixels(project,tmp_path):
    import shutil
    (tmp_path/'fonts').mkdir()
    for font in bundled_fonts():shutil.copy2(font.path,tmp_path/'fonts'/Path(font.path).name)
    (tmp_path/'lyrics.ass').write_text(compose(project),encoding='utf-8-sig')
    result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=black:s=640x360:r=25:d=3',
        '-vf','ass=lyrics.ass:fontsdir=fonts','-ss','2','-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'],
        cwd=tmp_path,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    rendered=np.frombuffer(result.stdout,np.uint8).reshape(360,640,4)[:,:,:3].astype(np.float32)
    renderer=AssRenderer();renderer.set_text(compose(project));data=np.frombuffer(renderer.rgba(640,360,2000),np.uint8).reshape(360,640,4)
    expected=data[:,:,:3].astype(np.float32)*data[:,:,3:4]/255
    mask=np.max(expected,axis=2)>20
    assert mask.sum()>150
    # FFmpeg's RGB<->YUV conversions can alter edge colors, not glyph positions.
    assert np.mean(np.abs(expected[mask]-rendered[mask]))<18
    assert np.logical_xor(np.max(rendered,axis=2)>20,mask).sum()<100
    renderer.close()

def test_wave_spectrum_cache_and_metadata(video,tmp_path):
    result=analyze(video,tmp_path);again=analyze(video,tmp_path)
    assert abs(int(result['duration'])-8000)<100
    assert (int(result['width']),int(result['height']))==(640,360)
    assert result['spectrum'].shape[0]==96
    assert np.array_equal(result['peaks'],again['peaks'])
    assert len(result['keyframes'])>0 and result['keyframes'][0]==0

def test_real_sample_encode_and_progress(project,video,tmp_path):
    project.media=str(video);project.duration=8000
    output=tmp_path/'日语 试压.mp4';updates=[]
    result=encode(project,EncodeOptions(str(output),1000,2200),progress=updates.append)
    assert result['bytes']>1000 and output.exists();assert updates[-1]['ratio']==1
    info=analyze(output,tmp_path/'probe')
    assert abs(int(info['duration'])-2200)<150
    # Decode a real encoded frame; glyphs must be visible on the background.
    decoded=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-i',str(output),'-ss','0.6','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert decoded.returncode==0
    pixels=np.frombuffer(decoded.stdout,np.uint8).reshape(360,640,3)
    assert (pixels[240:350].max(axis=2)>180).sum()>100

def test_cancel_does_not_publish_half_file(project,video,tmp_path):
    project.media=str(video);project.duration=8000;output=tmp_path/'existing.mp4';output.write_bytes(b'original-output')
    cancel=threading.Event();cancel.set()
    with pytest.raises(ValueError,match='取消'):encode(project,EncodeOptions(str(output)),cancel)
    assert output.read_bytes()==b'original-output'
    assert not list(tmp_path.glob('.shengao-render-*'))

def test_cancel_analysis_cleans_its_staging_files(video,tmp_path):
    cancel=threading.Event();cancel.set()
    with pytest.raises(ValueError,match='取消'):analyze(video,tmp_path,cancel)
    assert not list(tmp_path.iterdir())

def test_low_sample_rate_media_matches_original_linear_doubling(tmp_path):
    import wave
    samples=np.tile(np.array([-32768,-3,-1,0,1,3,32767,0],np.int16),100)
    path=tmp_path/'8000hz.wav'
    with wave.open(str(path),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(samples.tobytes())
    data=analyze(path,tmp_path/'cache');actual=np.fromfile(data['pcm'],np.int16)
    assert int(data['sample_rate'])==32000 and len(actual)==len(samples)*4
    assert actual[:32].tolist()==[-32768,-24576,-16385,-8194,-3,-2,-2,-1,-1,0,0,0,0,0,0,0,1,1,2,2,3,8194,16385,24576,32767,24575,16383,8191,0,-8192,-16384,-24576]
    assert np.array_equal(actual[::4],samples)

def test_audio_only_exports_real_subtitle_video(project,tmp_path):
    data=analyze(project.media,tmp_path/'audio-cache');assert not bool(data['has_video'])
    project.duration=int(data['duration']);project.has_video=False
    output=tmp_path/'纯音频字幕视频.mp4';encode(project,EncodeOptions(str(output),1000,2000,'720p'))
    info=analyze(output,tmp_path/'result-cache')
    assert bool(info['has_video']) and (int(info['width']),int(info['height']))==(1280,720)
    assert abs(int(info['duration'])-2000)<150
    decoded=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-i',str(output),'-ss','0.6','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert decoded.returncode==0
    pixels=np.frombuffer(decoded.stdout,np.uint8).reshape(720,1280,3)
    assert np.abs(pixels[20,20].astype(int)-np.array([12,20,35])).max()<6
    assert (pixels[450:700].max(axis=2)>180).sum()>100
