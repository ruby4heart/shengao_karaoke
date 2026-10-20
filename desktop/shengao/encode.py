"""Single render specification used for sample and final video output."""
from dataclasses import dataclass
from pathlib import Path
import copy
import os
import re
import shutil
import subprocess
import tempfile
import time
from .paths import ffmpeg
from .fonts import resolve_font
from .subtitles import compose
from .media import has_video

@dataclass
class EncodeOptions:
    output:str
    start:int=0
    duration:int=0
    size:str='source'
    quality:str='standard'
    encoder:str='cpu'

def encoder_args(options):
    # This CPU Media Foundation path is exercised on the Windows release target.
    bitrate='12M' if options.quality=='high' else '6M'
    if options.encoder=='cpu':return ['-c:v','h264_mf','-hw_encoding','0','-b:v',bitrate,'-pix_fmt','nv12']
    if options.encoder=='hardware':return ['-c:v','h264_mf','-hw_encoding','1','-b:v',bitrate,'-pix_fmt','nv12']
    raise ValueError('不支持的编码器选项')

def capabilities():
    result=subprocess.run([ffmpeg(),'-hide_banner','-encoders'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    text=result.stdout.decode('utf-8',errors='replace')
    supported={}
    for name,hardware in [('cpu','0'),('hardware','1')]:
        if 'h264_mf' not in text:supported[name]=False;continue
        probe=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin',
            '-f','lavfi','-i','color=s=128x128:r=25:d=0.04','-frames:v','1',
            '-c:v','h264_mf','-hw_encoding',hardware,'-pix_fmt','nv12','-f','null','-'],
            capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        supported[name]=probe.returncode==0
    aac=False
    if ' aac ' in text:
        probe=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin',
            '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','0.04','-c:a','aac','-f','null','-'],
            capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        aac=probe.returncode==0
    return {**{name:available and aac for name,available in supported.items()},'aac':aac,'description':'已实际编码验证本机 H.264 视频与 AAC 音频能力'}

def encode(project,options,cancel=None,progress=lambda x:None):
    if not project.media or not Path(project.media).is_file():raise ValueError('请先添加有效的媒体文件')
    if not project.lines:raise ValueError('请先准备歌词')
    output=Path(options.output).resolve()
    sources=[project.media,*[entry.path for entry in project.media_versions.values()]]
    if any(output==Path(source).resolve() or (output.exists() and Path(source).is_file() and output.samefile(source)) for source in sources):raise ValueError('输出文件不能覆盖原素材或任一视频源版本')
    if not output.parent.exists():raise ValueError('输出目录不存在')
    if options.start<0 or options.duration<0:raise ValueError('试压时间范围无效')
    total=options.duration or max(0,project.duration-options.start)
    if total<=0:raise ValueError('无法确定媒体时长，请等待素材分析完成')
    if options.start>=project.duration:raise ValueError('试压开始时间超出素材时长')
    video=project.has_video if project.has_video is not None else has_video(project.media)
    # Stage beside destination for atomic publication, including cross-volume paths.
    with tempfile.TemporaryDirectory(prefix='.shengao-render-',dir=output.parent) as folder:
        folder=Path(folder);fonts=folder/'fonts';fonts.mkdir()
        stage=folder/'encoded.mp4'
        import hashlib
        for name,family in [('font_file','font'),('ruby_font_file','ruby_font'),('translation_font_file','translation_font')]:
            path=resolve_font(getattr(project.style,name),getattr(project.style,family))
            shutil.copy2(path,fonts/(hashlib.sha256(path.read_bytes()).hexdigest()[:12]+path.suffix))
        for value in project.font_assets.values():
            path=Path(value)
            if path.is_file():shutil.copy2(path,fonts/(hashlib.sha256(path.read_bytes()).hexdigest()[:12]+path.suffix))
        (folder/'lyrics.ass').write_text(compose(project),encoding='utf-8-sig')
        filter_text='ass=lyrics.ass:fontsdir=fonts'
        if options.size=='1080p':filter_text='scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,'+filter_text
        elif options.size=='720p':filter_text='scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,'+filter_text
        elif options.size!='source':raise ValueError('输出尺寸选项无效')
        command=[ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y']
        if video:
            command+=['-i',str(Path(project.media).resolve()),'-map','0:v:0','-map','0:a:0?']
        else:
            command+=['-f','lavfi','-i',f'color=c=0x0c1423:s={project.width}x{project.height}:r={project.fps:g}',
                      '-i',str(Path(project.media).resolve()),'-map','0:v:0','-map','1:a:0']
        command+=['-vf',filter_text]
        # -ss after filtering retains absolute ASS timing in samples.
        if options.start:command+=['-ss',f'{options.start/1000:.3f}']
        if options.duration or not video:command+=['-t',f'{total/1000:.3f}']
        command+=encoder_args(options)+['-c:a','aac','-b:a','192k','-movflags','+faststart','-progress','pipe:1','-nostats',str(stage)]
        started=time.monotonic();elapsed_ms=0
        with tempfile.TemporaryFile() as errors:
            process=subprocess.Popen(command,cwd=folder,stdout=subprocess.PIPE,stderr=errors,creationflags=subprocess.CREATE_NO_WINDOW)
            import queue,threading
            lines=queue.Queue()
            def read():
                for line in process.stdout:lines.put(line.decode('utf-8',errors='replace').strip())
                lines.put(None)
            reader=threading.Thread(target=read,daemon=True);reader.start()
            try:
                while True:
                    if cancel is not None and cancel.is_set():process.kill();process.wait();raise ValueError('压制已取消；原素材和工程未改动')
                    try:line=lines.get(timeout=.1)
                    except queue.Empty:
                        if process.poll() is not None and not reader.is_alive():break
                        continue
                    if line is None:break
                    if line.startswith('out_time_us='):
                        try:elapsed_ms=int(line.split('=',1)[1])/1000
                        except ValueError:continue
                        ratio=min(1,max(0,elapsed_ms/total));spent=time.monotonic()-started
                        progress({'ratio':ratio,'elapsed':spent,'remaining':spent*(1-ratio)/ratio if ratio>.005 else None})
                code=process.wait();reader.join(2);errors.seek(0);log=errors.read().decode('utf-8',errors='replace')
                if code or not stage.exists() or stage.stat().st_size<128:
                    raise ValueError('视频压制失败。'+('显卡编码不可用，可改为 CPU 后重试。' if options.encoder=='hardware' else '')+log[-1400:])
                if cancel is not None and cancel.is_set():raise ValueError('压制已取消')
                os.replace(stage,output)
                progress({'ratio':1,'elapsed':time.monotonic()-started,'remaining':0})
                return {'output':str(output),'media':project.media,'media_role':project.media_role,'seconds':time.monotonic()-started,'bytes':output.stat().st_size}
            finally:
                if process.poll() is None:process.kill();process.wait()
                process.stdout.close();reader.join(2)
