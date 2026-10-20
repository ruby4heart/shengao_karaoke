"""Original Aegisub FFT, frequency curve, palette and waveform arithmetic."""
import ctypes
import json
from pathlib import Path
import numpy as np
from .paths import RUNTIME,ASSETS

DEFAULTS=json.loads((ASSETS/'aeg-audio-defaults.json').read_text(encoding='utf-8'))

def zoom_factor(level):
    if level>0:return 100+25*level
    if level>=-5:return 100+10*level
    if level>=-11:return 50+(level+5)*5
    return max(1,20+level+11)

def milliseconds_per_pixel(level):return 2000.0/zoom_factor(level)

def ruler_scale(pixel_ms):
    pixels=1000/pixel_ms
    for threshold,minor,major in [(3000,1,10),(300,10,10),(30,100,10),(3,1000,10),(1/3,10000,6),(1/9,60000,10),(1/90,600000,6)]:
        if pixels>threshold:return minor,major
    return 3600000,10

class AudioRenderer:
    def __init__(self,pcm,sample_rate):
        self.samples=np.memmap(pcm,dtype='<i2',mode='r');self.dll=ctypes.CDLL(str(RUNTIME/'shengao-audio.dll'))
        d=self.dll
        d.sg_audio_create.argtypes=[ctypes.c_void_p,ctypes.c_int64,ctypes.c_int];d.sg_audio_create.restype=ctypes.c_void_p
        d.sg_audio_palette.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_double)]
        d.sg_audio_render.argtypes=[ctypes.c_void_p,ctypes.c_int64,ctypes.c_int,ctypes.c_int,ctypes.c_double,ctypes.c_float,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p];d.sg_audio_render.restype=ctypes.c_int
        d.sg_audio_power.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int64,ctypes.c_void_p,ctypes.c_int];d.sg_audio_power.restype=ctypes.c_int
        d.sg_audio_destroy.argtypes=[ctypes.c_void_p]
        self.handle=d.sg_audio_create(self.samples.ctypes.data,len(self.samples),int(sample_rate));self.rate=int(sample_rate)
        if not self.handle:raise ValueError('无法读取波形 PCM 缓存')
        for scheme_index,name in enumerate(['Icy Blue','Green']):
            for style_index,style in enumerate(['Normal','Inactive','Selection','Primary']):
                values=DEFAULTS['Colour']['Schemes'][name][style]
                data=(ctypes.c_double*6)(*[values[x] for x in ['Hue Offset','Hue Scale','Saturation Offset','Saturation Scale','Lightness Offset','Lightness Scale']])
                d.sg_audio_palette(self.handle,scheme_index,style_index,data)

    def rgb(self,start,width,height,pixel_ms,amplitude=1,spectrum=True,quality=1,curve=0,styles=None):
        styles=np.zeros(width,np.uint8) if styles is None else np.ascontiguousarray(styles,dtype=np.uint8)
        if len(styles)!=width:raise ValueError('波形样式范围无效')
        pixels=np.empty((height,width,3),np.uint8)
        if not self.dll.sg_audio_render(self.handle,int(start),width,height,pixel_ms,amplitude,int(spectrum),quality,curve,styles.ctypes.data,pixels.ctypes.data):raise ValueError('音频画面渲染失败')
        return pixels

    def power(self,index,quality=1):
        output=np.empty(32768,np.float32);n=self.dll.sg_audio_power(self.handle,quality,index,output.ctypes.data,len(output))
        if n<0:raise ValueError('FFT 输出缓冲区过小')
        return output[:n]

    def close(self):
        if self.handle:self.dll.sg_audio_destroy(self.handle);self.handle=None
        if hasattr(self.samples,'_mmap') and self.samples._mmap is not None and not self.samples._mmap.closed:self.samples._mmap.close()

    def __del__(self):
        if hasattr(self,'handle') and self.handle:self.close()
