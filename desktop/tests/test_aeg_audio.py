"""Pixel parity against verbatim original renderer bodies using real wxBitmap."""
import ctypes
from pathlib import Path
import numpy as np
import pytest
from shengao.audio_render import AudioRenderer,milliseconds_per_pixel,ruler_scale

ROOT=Path(__file__).resolve().parents[2]

def reference(samples,rate,start,width,height,pixel_ms,amplitude,spectrum,quality,curve,style):
    dll=ctypes.CDLL(str(ROOT/'build'/'desktop-reference'/'shengao-reference.dll'))
    fn=dll.sg_reference_render
    fn.argtypes=[ctypes.c_void_p,ctypes.c_int64,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_double,ctypes.c_float,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p]
    fn.restype=ctypes.c_int
    output=np.empty((height,width,3),np.uint8)
    assert fn(samples.ctypes.data,len(samples),rate,start,width,height,pixel_ms,amplitude,int(spectrum),quality,curve,style,output.ctypes.data)
    return output

@pytest.mark.parametrize('spectrum',[True,False,2])
@pytest.mark.parametrize('rate,level,amplitude,quality,curve,style',[
 (48000,0,1.,1,0,0), (44100,10,1.,1,2,2), (96000,20,1.5,2,3,3),
 (32000,-5,.6,0,1,1), (48000,35,2.,5,4,3), (22050,3,1.,3,0,2)])
def test_original_aegisub_pixel_parity(tmp_path,spectrum,rate,level,amplitude,quality,curve,style):
    rng=np.random.default_rng(731);time=np.arange(rate*3,dtype=np.float64)/rate
    signal=(np.sin(time*2*np.pi*223)*.3+np.sin(time*2*np.pi*1723)*.18+rng.normal(0,.07,len(time)))
    signal*=((time>.2)&(time<2.6));samples=np.clip(signal*32768,-32768,32767).astype(np.int16)
    path=tmp_path/'same-pcm.s16';samples.tofile(path);renderer=AudioRenderer(path,rate)
    width,height,start=176,112,13;pixel_ms=milliseconds_per_pixel(level)
    actual=renderer.rgb(start,width,height,pixel_ms,amplitude,spectrum,quality,curve,np.full(width,style,np.uint8))
    expected=reference(samples,rate,start,width,height,pixel_ms,amplitude,spectrum,quality,curve,style)
    mismatch=np.any(actual!=expected,axis=2)
    if mismatch.any():
        from PIL import Image
        Image.fromarray(actual).save(tmp_path/'new.png');Image.fromarray(expected).save(tmp_path/'original-aeg.png')
    renderer.close()
    assert not mismatch.any(),f'{mismatch.sum()}/{width*height} pixels differ, max delta {np.abs(actual.astype(int)-expected).max()}, evidence {tmp_path}'

def test_aeg_scale_and_zoom_exact_boundaries():
    assert milliseconds_per_pixel(0)==20
    assert milliseconds_per_pixel(4)==10
    assert ruler_scale(20)==(100,10)
    assert ruler_scale(2)==(10,10)
    assert ruler_scale(.2)==(1,10)
