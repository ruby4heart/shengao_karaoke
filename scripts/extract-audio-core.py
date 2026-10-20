"""Extract toolkit-free FFT and HSL directly from the private Aegisub source.

Only the exception type/include in FFT is adapted; every arithmetic expression
and original copyright notice is retained. The user's original tree is read-only.
"""
from pathlib import Path
import hashlib
import json
root=Path(__file__).resolve().parents[1]
source=root/'vendor'/'aegisub'/'src';target=root/'desktop'/'native'/'aegisub';target.mkdir(parents=True,exist_ok=True)
def read(name):return (source/name).read_text(encoding='utf-8')
def function(text,start):
    a=text.index(start);opening=text.index('{',a);level=1;b=opening+1
    while level:
        if text[b]=='{':level+=1
        if text[b]=='}':level-=1
        b+=1
    return text[a:b]
fft=read('fft.cpp').replace('#include <libaegisub/exception.h>','#include <stdexcept>').replace('agi::InternalError(', 'std::runtime_error(')
(target/'fft.cpp').write_text(fft,encoding='utf-8');(target/'fft.h').write_text(read('fft.h'),encoding='utf-8')
colors=read('colorspace.cpp');notice=colors[:colors.index('/// @file')]
(target/'hsl.cpp').write_text(notice+'\n#include <algorithm>\nstatic unsigned int clip_colorval(int val) { return std::clamp(val,0,255); }\n'+function(colors,'void hsl_to_rgb(')+'\n',encoding='utf-8')
config=json.loads((source/'libresrc'/'default_config.json').read_text(encoding='utf-8'))
(root/'desktop'/'assets'/'aeg-audio-defaults.json').write_text(json.dumps({'Audio':config['Audio'],'Colour':{'Audio Display':config['Colour']['Audio Display'],'Schemes':config['Colour']['Schemes']}},ensure_ascii=False,indent=2),encoding='utf-8')
records=[]
for name in ['fft.cpp','fft.h','colorspace.cpp','audio_renderer_spectrum.cpp','audio_renderer_waveform.cpp','audio_display.cpp','audio_timing_karaoke.cpp','audio_colorscheme.cpp','libresrc/default_config.json']:
    records.append({'file':name,'sha256':hashlib.sha256((source/name).read_bytes()).hexdigest()})
(target/'SOURCES.json').write_text(json.dumps({'source':'Aegisub 3.5.0 private source copy','adaptation':'FFT exception type; HSL extracted unmodified; audio_core.cpp ports original spectrum/waveform arithmetic','files':records},indent=2),encoding='utf-8')
print('Extracted FFT, HSL, audio defaults and source fingerprints')
