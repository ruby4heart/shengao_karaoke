"""Display metadata acceptance shared by source and frozen application checks."""
import json,subprocess
from pathlib import Path
import numpy as np
from PySide6.QtGui import QImage
from .paths import ffmpeg
from .project import Project,History
from .video_geometry import SQUARE_FILTER
from .encode import encode,EncodeOptions
from .render import AssRenderer
from .subtitles import compose
from studio_backend.model import LyricLine


def exercise(app,StudioWindow,out,check,wait):
    out=Path(out);folder=out/'display-geometry';folder.mkdir(exist_ok=True);records=[];passed=False
    w=StudioWindow(folder/'home',test=True);w.playback.audio.setMuted(True);w.resize(1100,800);w.show()
    def invoke(args):
        result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y',*[str(v) for v in args]],capture_output=True,timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise AssertionError(result.stderr.decode('utf-8',errors='replace')[-2000:])
    def pixels(image):
        image=image.convertToFormat(QImage.Format.Format_RGBA8888)
        return np.frombuffer(image.bits(),np.uint8).reshape(image.height(),image.width(),4).copy()
    def corners(image):
        a=pixels(image);h,width=a.shape[:2]
        return np.array([a[round(h*y)-3:round(h*y)+3,round(width*x)-3:round(width*x)+3,:3].mean(axis=(0,1)) for y in (.25,.75) for x in (.25,.75)])
    try:
        colors='drawbox=x=0:y=0:w=iw/2:h=ih/2:color=0xb71c1c:t=fill,drawbox=x=iw/2:y=0:w=iw/2:h=ih/2:color=0x14995c:t=fill,drawbox=x=0:y=ih/2:w=iw/2:h=ih/2:color=0x1c4ec6:t=fill,drawbox=x=iw/2:y=ih/2:w=iw/2:h=ih/2:color=0xead84c:t=fill'
        sources={}
        for name,size,sar in [('square','640x360','1'),('wide','720x576','64/45'),('narrow','640x360','1/2')]:
            path=folder/(name+'.mp4');invoke(['-f','lavfi','-i',f'color=c=black:s={size}:r=25:d=2','-f','lavfi','-i','sine=sample_rate=48000:duration=2','-vf',colors+',setsar='+sar,'-c:v','h264_mf','-hw_encoding','0','-b:v','3M','-pix_fmt','nv12','-c:a','aac',path]);sources[name]=path
        for name,base,options in [('rot90','square',['-display_rotation','90']),('rot180','square',['-display_rotation','180']),('rot270','square',['-display_rotation','270']),('wide_rot90','wide',['-display_rotation','90']),('mirror','square',['-display_hflip']),('mirror_rot90','square',['-display_rotation','90','-display_hflip'])]:
            path=folder/(name+'.mp4');invoke([*options,'-i',sources[base],'-map','0:v:0','-map','0:a:0','-c','copy',path]);sources[name]=path
        check('display_geometry_nine_actual_metadata_sources',len(sources)==9 and all(v.is_file() for v in sources.values()))
        for name,source in sources.items():
            record={'name':name};records.append(record);original=source.read_bytes()
            reference=folder/(name+'-reference.png');invoke(['-i',source,'-vf',SQUARE_FILTER,'-frames:v','1',reference]);expected=QImage(str(reference));shape=(expected.width(),expected.height());record['display_size']=shape
            w.history=History(Project(lines=[LyricLine('shape','明日',200,1400)]));w.current=0;w.refresh();w.load_media(source,preview=True)
            ready=wait(lambda:w.analysis_job is None and not w.playback.preview_pending and not w.playback.canvas.frame.isNull(),20000)
            record['source_corner_error']=float(np.abs(corners(w.playback.canvas.frame)-corners(expected)).max()) if ready else None
            check('display_geometry_'+name+'_original_shape_and_orientation',ready and (w.project.width,w.project.height)==shape and (w.playback.source_size.width(),w.playback.source_size.height())==shape and abs(w.playback.canvas.aspect-shape[0]/shape[1])<1e-9 and record['source_corner_error']<12)
            w.playback.set_zoom(.5);before=w.project.to_dict();w.prepare_proxy()
            ready=wait(lambda:w.proxy_job is None and w.proxy_active and not w.playback.preview_pending,20000)
            record['proxy_corner_error']=float(np.abs(corners(w.playback.canvas.frame)-corners(expected)).max()) if ready else None
            verification=w.proxy_base['verification'] if ready else {};record['verification']=verification
            check('display_geometry_'+name+'_proxy_preserves_shape_and_document',ready and w.project.to_dict()==before and w.playback.zoom==.5 and (w.playback.source_size.width(),w.playback.source_size.height())==shape and abs(w.playback.canvas.aspect-shape[0]/shape[1])<1e-9 and record['proxy_corner_error']<12 and verification['display_error_pixels']<=2 and verification['proxy']['sar_num']==verification['proxy']['sar_den']==1 and verification['proxy']['input_geometry']['rotation_ccw']==0)
            output=folder/(name+'-encoded.mp4');encoded=encode(w.project,EncodeOptions(str(output),start=200,duration=400));frame=folder/(name+'-encoded.png');invoke(['-i',output,'-frames:v','1',frame]);actual=QImage(str(frame));renderer=AssRenderer()
            try:
                renderer.set_text(compose(w.project));overlay=np.frombuffer(renderer.rgba(*shape,200),np.uint8).reshape(shape[1],shape[0],4);mask=overlay[:,:,3]>250
                record['encode_corner_error']=float(np.abs(corners(actual)-corners(expected)).max())
                record['subtitle_core_pixels']=int(mask.sum());record['subtitle_core_error']=float(np.abs(pixels(actual)[:,:,:3][mask].astype(float)-overlay[:,:,:3][mask]).mean()) if mask.any() and actual.size()==expected.size() else None
                check('display_geometry_'+name+'_original_encode_and_subtitle_pixels',Path(encoded['media'])==source and (actual.width(),actual.height())==shape and record['encode_corner_error']<15 and record['subtitle_core_pixels']>20 and record['subtitle_core_error']<18 and source.read_bytes()==original)
            finally:renderer.close()
        passed=True
    finally:
        (out/'video-geometry-audit.json').write_text(json.dumps({'passed':passed,'scope':'Nine synthetic display-metadata fixtures; real Qt frames, verified proxy, original-source encoding and libass subtitle core pixels; no private media or human accuracy claim.','fixtures':records,'computer_use':False,'paid_api_calls':0},ensure_ascii=False,indent=2),encoding='utf-8')
        w.close();w.deleteLater();app.processEvents()
