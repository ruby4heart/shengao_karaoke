"""Create a synthetic full-workflow demo, with no downloaded user media."""
from pathlib import Path
import json
import subprocess
root=Path(__file__).resolve().parents[1]
target=root/'desktop'/'assets'/'demo';target.mkdir(parents=True,exist_ok=True)
ffmpeg=root/'dist'/'ShengaoKaraoke-0.7.0-final-win64'/'ffmpeg.exe'
output=target/'tutorial.mp4'
subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i',
 'color=c=0x142238:s=1280x720:r=25:d=8','-i',str(root/'demo'/'demo.wav'),
 '-c:v','h264_mf','-hw_encoding','0','-b:v','3M','-pix_fmt','nv12','-c:a','aac','-shortest',str(output)],check=True)
project=json.loads((root/'demo'/'tutorial.json').read_text(encoding='utf-8'));project['media']='tutorial.mp4';project['title']='第一次制作 · 离线练习'
(target/'tutorial.json').write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
print(output)
