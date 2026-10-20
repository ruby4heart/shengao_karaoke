from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).resolve().parents[1] / 'assets'
RUNTIME = Path(sys.executable).parent if getattr(sys, 'frozen', False) else ROOT/'build'/'desktop'

def ffmpeg():
    candidates = [RUNTIME/'ffmpeg.exe', ROOT/'dist'/'ShengaoKaraoke-0.7.0-final-win64'/'ffmpeg.exe',
                  ROOT/'build'/'baseline'/'subprojects'/'ffmpeg'/'ffmpeg.exe']
    for path in candidates:
        if path.is_file(): return str(path)
    raise ValueError('完整运行包中缺少 FFmpeg，请重新完整解压软件')

def renderer():
    path=RUNTIME/'shengao-render.dll'
    if not path.exists(): raise ValueError('缺少字幕渲染模块 shengao-render.dll')
    return str(path)
