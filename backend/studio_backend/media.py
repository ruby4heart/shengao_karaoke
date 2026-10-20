import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import sys


def ffmpeg_executable():
    bundled = Path(sys.executable).parent / 'ffmpeg.exe'
    if bundled.exists():
        return str(bundled)
    found = shutil.which('ffmpeg')
    if not found:
        raise ValueError('未找到 FFmpeg，请使用完整安装包或将 FFmpeg 加入 PATH')
    return found


async def extract(media, destination, start=None, end=None):
    media = Path(media)
    if not media.is_file():
        raise ValueError('媒体文件不存在')
    command = [ffmpeg_executable(), '-hide_banner','-loglevel','error','-nostdin','-y']
    if start is not None:
        if type(start) is not int or start < 0 or type(end) is not int or end <= start:
            raise ValueError('音频选区时间无效')
        command += ['-ss',f'{start/1000:.3f}']
    command += ['-i',str(media)]
    if start is not None:
        command += ['-t',f'{(end-start)/1000:.3f}']
    command += ['-map','0:a:0','-vn','-ac','1','-ar','16000','-c:a','flac',str(destination)]
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.DEVNULL,
                                                  stderr=asyncio.subprocess.PIPE,
                                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        _,error = await process.communicate()
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError('无法提取音轨，请检查媒体是否含声音及文件是否损坏')
