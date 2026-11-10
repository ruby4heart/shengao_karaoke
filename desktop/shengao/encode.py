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
from .subtitles import compose
from .media import has_video
from .video_geometry import SQUARE_FILTER
from .render_plan import NO_WINDOW,FRAME,render_fonts,subtitle_fingerprint,verify_output,probe_output

@dataclass
class EncodeOptions:
    output:str
    start:int=0
    duration:int=0
    size:str='source'
    quality:str='standard'
    encoder:str='cpu'
    # Which H.264 encoder the CPU choice uses: the Windows Media Foundation
    # encoder shipped with the release, or libx264 when only that one passed the
    # local capability check.
    codec:str='h264_mf'

def encoder_args(options):
    # This CPU Media Foundation path is exercised on the Windows release target.
    bitrate='12M' if options.quality=='high' else '6M'
    if options.encoder=='cpu' and options.codec=='libx264':return ['-c:v','libx264','-preset','medium','-b:v',bitrate,'-pix_fmt','yuv420p']
    if options.codec not in ('h264_mf','libx264'):raise ValueError('不支持的视频编码器')
    if options.encoder=='cpu':return ['-c:v','h264_mf','-hw_encoding','0','-b:v',bitrate,'-pix_fmt','nv12']
    if options.encoder=='hardware':return ['-c:v','h264_mf','-hw_encoding','1','-b:v',bitrate,'-pix_fmt','nv12']
    raise ValueError('不支持的编码器选项')

def capabilities():
    result=subprocess.run([ffmpeg(),'-hide_banner','-encoders'],capture_output=True,creationflags=NO_WINDOW)
    text=result.stdout.decode('utf-8',errors='replace')
    names={line.split()[1] for line in text.splitlines() if len(line.split())>1 and line.startswith(' V')}
    def works(args):
        probe=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin',
            '-f','lavfi','-i','color=s=128x128:r=25:d=0.04','-frames:v','1',*args,'-f','null','-'],
            capture_output=True,timeout=15,creationflags=NO_WINDOW)
        return probe.returncode==0
    supported={}
    for name,hardware in [('cpu','0'),('hardware','1')]:
        supported[name]=('h264_mf' in names or 'h264_mf' in text) and works(['-c:v','h264_mf','-hw_encoding',hardware,'-pix_fmt','nv12'])
    codec='h264_mf' if supported['cpu'] else None
    if codec is None and 'libx264' in names and works(['-c:v','libx264','-pix_fmt','yuv420p']):supported['cpu']=True;codec='libx264'
    aac=False
    if ' aac ' in text:
        probe=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin',
            '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','0.04','-c:a','aac','-f','null','-'],
            capture_output=True,timeout=15,creationflags=NO_WINDOW)
        aac=probe.returncode==0
    return {**{name:available and aac for name,available in supported.items()},'aac':aac,'cpu_codec':codec,
            'description':'已实际编码验证本机 H.264 视频与 AAC 音频能力'}

def capability_text(value,audio_only=False):
    """One sentence for the export page: what this computer can encode."""
    cpu='CPU 可用'+('（使用 libx264）' if value.get('cpu_codec')=='libx264' else '') if value.get('cpu') else 'CPU 不可用'
    hardware='显卡可用' if value.get('hardware') else '显卡不可用'
    text=f'本机编码检查：{cpu}；{hardware}'
    if not value.get('aac'):text+='；AAC 音频编码不可用，无法生成带声音的 MP4'
    elif not value.get('cpu') and not value.get('hardware'):text+='；没有可用的 H.264 编码器，无法生成 MP4'
    return text+('。音频将生成深色背景的字幕视频。' if audio_only else '。输出 H.264 + AAC 的 MP4，帧率跟随源视频，完成后会读回检查。')

def video_filter(size,video):
    """Burn subtitles onto the picture itself, before letterboxing.

    The live preview draws the ASS over the video picture only, never over
    added black bars, so a fixed output size scales the picture, burns the
    subtitles at that size, and pads afterwards; the subtitles keep the same
    place and size relative to the picture as in the preview and the sample."""
    filters=[SQUARE_FILTER] if video else []
    if size in FRAME:
        width,height=FRAME[size]
        filters.append(f'scale={width}:{height}:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2')
    elif size!='source':raise ValueError('输出尺寸选项无效')
    filters.append('ass=lyrics.ass:fontsdir=fonts')
    if size in FRAME:filters.append(f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2')
    return ','.join(filters)

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
    filter_text=video_filter(options.size,video);args=encoder_args(options)
    executable=ffmpeg()
    # A video without its own sound track gives a silent MP4; anything else must keep its sound.
    audio=True if not video else bool(probe_output(project.media,executable)['audio'])
    # Stage beside destination for atomic publication, including cross-volume paths.
    with tempfile.TemporaryDirectory(prefix='.shengao-render-',dir=output.parent) as folder:
        folder=Path(folder);fonts=folder/'fonts';fonts.mkdir()
        stage=folder/'encoded.mp4'
        # Lets the caller record the folder, so an interrupted run can be cleaned up.
        progress({'stage':str(folder)})
        import hashlib
        # The same font files the live preview loads and the ASS export carries.
        used_fonts=render_fonts(project)
        for path in used_fonts:shutil.copy2(path,fonts/(hashlib.sha256(path.read_bytes()).hexdigest()[:12]+path.suffix))
        text=compose(project);(folder/'lyrics.ass').write_text(text,encoding='utf-8-sig')
        fingerprint=subtitle_fingerprint(text,used_fonts)
        command=[executable,'-hide_banner','-loglevel','error','-nostdin','-y']
        if video:
            command+=['-i',str(Path(project.media).resolve()),'-map','0:V:0','-map','0:a:0?']
        else:
            command+=['-f','lavfi','-i',f'color=c=0x0c1423:s={project.width}x{project.height}:r={project.fps:g}',
                      '-i',str(Path(project.media).resolve()),'-map','0:v:0','-map','1:a:0']
        command+=['-vf',filter_text]
        # -ss after filtering retains absolute ASS timing in samples.
        if options.start:command+=['-ss',f'{options.start/1000:.3f}']
        if options.duration or not video:command+=['-t',f'{total/1000:.3f}']
        command+=args+['-c:a','aac','-b:a','192k','-movflags','+faststart','-progress','pipe:1','-nostats',str(stage)]
        started=time.monotonic();elapsed_ms=0
        with tempfile.TemporaryFile() as errors:
            process=subprocess.Popen(command,cwd=folder,stdout=subprocess.PIPE,stderr=errors,creationflags=NO_WINDOW)
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
                if cancel is not None and cancel.is_set():raise ValueError('压制已取消；原素材和工程未改动')
                # Read the file back: only a playable H.264/AAC MP4 of the full
                # requested length is published and reported as finished.
                checked=verify_output(stage,total,options.size,executable,audio=audio)
                if cancel is not None and cancel.is_set():raise ValueError('压制已取消；原素材和工程未改动')
                os.replace(stage,output)
                progress({'ratio':1,'elapsed':time.monotonic()-started,'remaining':0})
                return {'output':str(output),'media':project.media,'media_role':project.media_role,'seconds':time.monotonic()-started,'bytes':output.stat().st_size,
                        'fingerprint':fingerprint,'fonts':[path.name for path in used_fonts],'codec':args[1],
                        'checked':{'duration_ms':checked['duration'],'video':checked['video'],'audio':checked['audio'],'width':checked['width'],'height':checked['height']}}
            finally:
                if process.poll() is None:process.kill();process.wait()
                process.stdout.close();reader.join(2)
