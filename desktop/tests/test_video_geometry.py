"""Real images, display metadata and original-source encodes must agree."""
from pathlib import Path
import subprocess,time
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QColor,QTransform
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.paths import ffmpeg
from shengao.video_geometry import geometry,SQUARE_FILTER
from shengao import proxy_video,media
from shengao.project import Project,History
from shengao.encode import encode,EncodeOptions
from shengao.render import AssRenderer
from shengao.subtitles import compose
from shengao.playback import Playback
from studio_backend.model import LyricLine


def invoke(args):
    r=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y',*[str(a) for a in args]],capture_output=True,timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
    assert r.returncode==0,r.stderr.decode('utf-8',errors='replace');return r


@pytest.fixture(scope='module')
def geometry_sources(tmp_path_factory):
    root=tmp_path_factory.mktemp('display-geometry');sources={}
    colors="drawbox=x=0:y=0:w=iw/2:h=ih/2:color=0xb71c1c:t=fill,drawbox=x=iw/2:y=0:w=iw/2:h=ih/2:color=0x14995c:t=fill,drawbox=x=0:y=ih/2:w=iw/2:h=ih/2:color=0x1c4ec6:t=fill,drawbox=x=iw/2:y=ih/2:w=iw/2:h=ih/2:color=0xead84c:t=fill"
    for key,size,sar in [('base','640x360','1'),('wide','720x576','64/45'),('narrow','640x360','1/2')]:
        path=root/(key+'.mp4');invoke(['-f','lavfi','-i',f'color=c=black:s={size}:r=25:d=2','-f','lavfi','-i','sine=sample_rate=48000:duration=2','-vf',colors+',setsar='+sar,'-c:v','h264_mf','-hw_encoding','0','-b:v','3M','-pix_fmt','nv12','-c:a','aac',path]);sources[key]=path
    for key,input_key,opts in [('rot90','base',['-display_rotation','90']),('rot180','base',['-display_rotation','180']),('rot270','base',['-display_rotation','270']),('wide_rot90','wide',['-display_rotation','90']),('mirror','base',['-display_hflip']),('mirror_rot90','base',['-display_rotation','90','-display_hflip'])]:
        path=root/(key+'.mp4');invoke([*opts,'-i',sources[input_key],'-map','0:v:0','-map','0:a:0','-c','copy',path]);sources[key]=path
    return root,sources


def wait(app,fn,timeout=15):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        app.processEvents();QTest.qWait(10)
        if fn():return
    assert fn()


def array(image):
    image=image.convertToFormat(QImage.Format.Format_RGBA8888);return np.frombuffer(image.bits(),np.uint8).reshape(image.height(),image.width(),4).copy()


def corners(image):
    values=array(image);h,w=values.shape[:2]
    return np.array([values[max(0,round(h*y)-3):round(h*y)+3,max(0,round(w*x)-3):round(w*x)+3,:3].mean(axis=(0,1)) for y in (.25,.75) for x in (.25,.75)])


@pytest.mark.parametrize('name',['base','wide','narrow','rot90','rot180','rot270','wide_rot90','mirror','mirror_rot90'])
def test_source_proxy_and_encoded_orientation_shape_and_colors_agree(qapp,geometry_sources,tmp_path,name):
    root,sources=geometry_sources;source=sources[name];original=source.read_bytes();data=media.analyze(source,root/'wave')
    ref=tmp_path/'reference.png';invoke(['-i',source,'-vf',SQUARE_FILTER,'-frames:v','1',ref]);expected=QImage(str(ref));shape=(int(data['width']),int(data['height']))
    assert (expected.width(),expected.height())==shape
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True);w.history=History(Project(lines=[LyricLine('lyric','明日',200,1400)]));w.current=0;w.refresh();w.show();w.load_media(source,preview=True)
    try:
        wait(qapp,lambda:w.analysis_job is None and not w.playback.preview_pending and not w.playback.canvas.frame.isNull())
        assert (w.project.width,w.project.height)==shape and (w.playback.source_size.width(),w.playback.source_size.height())==shape
        assert w.playback.canvas.aspect==pytest.approx(shape[0]/shape[1])
        assert np.abs(corners(w.playback.canvas.frame)-corners(expected)).max()<12
        w.playback.set_zoom(.5);before=w.project.to_dict();w.prepare_proxy();wait(qapp,lambda:w.proxy_active and w.proxy_job is None and not w.playback.preview_pending)
        assert w.playback.zoom==.5 and (w.playback.source_size.width(),w.playback.source_size.height())==shape and w.project.to_dict()==before
        assert w.playback.canvas.aspect==pytest.approx(shape[0]/shape[1])
        assert np.abs(corners(w.playback.canvas.frame)-corners(expected)).max()<12
        verification=w.proxy_base['verification'];assert verification['display_error_pixels']<=2 and verification['proxy']['sar_num']==verification['proxy']['sar_den']==1 and verification['proxy']['input_geometry']['rotation_ccw']==0
        result=tmp_path/'encoded.mp4';encode(w.project,EncodeOptions(str(result),start=200,duration=400))
        frame=tmp_path/'encoded.png';invoke(['-i',result,'-frames:v','1',frame]);actual=QImage(str(frame))
        assert (actual.width(),actual.height())==shape and np.abs(corners(actual)-corners(expected)).max()<15
        # Subtitle core pixels are compared independently of background; the
        # original source is read for this encode even while proxy is active.
        renderer=AssRenderer()
        try:
            renderer.set_text(compose(w.project));overlay=np.frombuffer(renderer.rgba(*shape,200),np.uint8).reshape(shape[1],shape[0],4)
            mask=overlay[:,:,3]>250;rgb=array(actual)[:,:,:3].astype(float)
            assert mask.sum()>20 and np.abs(rgb[mask]-overlay[:,:,:3][mask]).mean()<18
        finally:renderer.close()
        w.use_original_preview();wait(qapp,lambda:not w.playback.preview_pending)
        assert w.playback.canvas.aspect==pytest.approx(shape[0]/shape[1]) and source.read_bytes()==original
    finally:w.close();qapp.processEvents()


def test_frame_presentation_transform_is_applied_after_surface_conversion(qapp):
    image=QImage(32,16,QImage.Format.Format_RGB32);image.fill(QColor('red'));image.setPixelColor(3,2,QColor('blue'))
    frame=QVideoFrame(image);frame.setRotation(type(frame.rotation())(90));frame.setMirrored(True);p=Playback()
    try:
        p.canvas.video_frame(frame);expected=frame.toImage().transformed(QTransform().rotate(90)).flipped(Qt.Orientation.Horizontal)
        assert p.canvas.frame==expected and (p.source_size.width(),p.source_size.height())==(16,32)
    finally:p.clear();p.timer.stop();p.canvas.renderer.close();p.deleteLater();qapp.processEvents()


def test_other_stream_rotation_and_cover_art_do_not_override_selected_video():
    log='Stream #0:0: Video: mjpeg, 800x800 (attached pic)\n rotation of 90.00 degrees\nStream #0:1: Video: h264, 720x576 [SAR 64:45 DAR 16:9]\n Display Matrix: rotation of -90.00 degrees\nStream #0:2: Video: h264, 640x360\n rotation of 180.00 degrees'
    data=geometry(log);assert (data['display_width'],data['display_height'])==(576,1024) and data['rotation_ccw']==270
