"""Keep Aegisub's timeline drawing bodies verbatim, without its application.

The private vendor tree is the reproducible source. The user's original tree
is read only when explicitly supplied as --source for a provenance audit.
"""
from pathlib import Path
import argparse
import hashlib
import json

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=root/'vendor'/'aegisub'/'src');parser.add_argument('--output',type=Path,default=root/'desktop'/'native'/'aegisub')
args=parser.parse_args();source=args.source;target=args.output;target.mkdir(parents=True,exist_ok=True)
raw=(source/'audio_display.cpp').read_text(encoding='utf-8')
def function(start):
    a=raw.index(start);b=raw.index('{',a)+1;level=1
    while level:
        if raw[b]=='{':level+=1
        elif raw[b]=='}':level-=1
        b+=1
    return raw[a:b]
classes=raw[raw.index('class AudioDisplayScrollbar final'):raw.index('\nnamespace {',raw.index('class AudioDisplayTimeline final'))]
names=['PaintMarkers','PaintFoot','PaintLabels','PaintTrackCursor']
bodies={name:function('void AudioDisplay::'+name+'(') for name in names}
notice=raw[:raw.index('#include')]
(target/'timeline_view.inc').write_text(notice+'\n// Verbatim classes and drawing methods; see TIMELINE-SOURCES.json.\n'+classes+'\n'+'\n\n'.join(bodies.values())+'\n',encoding='utf-8')
cfg=json.loads((source/'libresrc'/'default_config.json').read_text(encoding='utf-8'))
import re
colours=[list(map(int,re.findall(r'\d+',cfg['Colour']['Schemes'][scheme][focus][part]))) for scheme in ['Icy Blue','Green'] for focus in ['UI','UI Focused'] for part in ['Light','Dark','Selection']]
(target/'timeline_colours.inc').write_text('// Aegisub default UI colours, generated from default_config.json.\nstatic const unsigned char ui_colours[2][2][3][3] = {'+','.join(str(v) for c in colours for v in c)+'};\n',encoding='utf-8')
metadata={'source':'Aegisub 3.5.0 src/audio_display.cpp','sha256':hashlib.sha256((source/'audio_display.cpp').read_bytes()).hexdigest(),'classes_sha256':hashlib.sha256(classes.encode()).hexdigest(),'methods':{name:hashlib.sha256(body.encode()).hexdigest() for name,body in bodies.items()},'adaptation':'Verbatim drawing classes/methods. Own scene, plain marker arrays and default colours replace the Aegisub controller/options. wxMemoryDC/wxGCDC run offscreen only; Qt owns the application and input.'}
(target/'TIMELINE-SOURCES.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
print(target/'timeline_view.inc')
