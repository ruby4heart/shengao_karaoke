"""Generate a copyright-free synthetic audio and editable Japanese tutorial."""
import json
import math
from pathlib import Path
import struct
import sys
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from studio_backend.model import LyricLine,Unit
from studio_backend.export import export_ass

folder=ROOT/'demo'
folder.mkdir(exist_ok=True)
rate=22050
with wave.open(str(folder/'demo.wav'),'wb') as output:
    output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate)
    for block in range(8):
        frequency=[330,392,440,494,440,392,330,294][block]
        for i in range(rate):
            envelope=min(1,i/(rate*.03),(rate-i)/(rate*.1))*.12
            value=int(32767*envelope*math.sin(2*math.pi*frequency*i/rate))
            output.writeframesraw(struct.pack('<h',value))
line=LyricLine('demo','今日も歌う',1000,6000,[Unit('今日',1000,3000,'きょう','kyou',source='manual'),
    Unit('も',3200,4000,'も','mo',source='manual'),Unit('歌う',4200,6000,'うたう','utau',source='manual')],
    'きょうもうたう','kyou mo utau','今天也要歌唱')
project={'version':1,'media':'demo.wav','lines':[line.to_dict()],
         'note':'这是合成音调和人工示例字幕，用于熟悉编辑器；不是真实演唱或 API 识别结果。'}
(folder/'tutorial.json').write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
(folder/'rendered.ass').write_text(export_ass([line]),encoding='utf-8-sig')
print('Created synthetic tutorial in',folder)
