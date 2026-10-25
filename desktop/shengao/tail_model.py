"""Whole-line movement and manual mora corrections without acoustic guessing."""
import copy
import math
import io
import wave
import numpy as np
from studio_backend.analysis import kana_only
from studio_backend.japanese import morae,romaji
from .timing import manual
from studio_backend.provenance import remember,record_tree


def shift_line(original,delta):
    if original.locked or any(u.locked for u in original.units):raise ValueError('本句或词组已锁定，请先解除锁定')
    if type(delta) not in (int,float) or not math.isfinite(delta):raise ValueError('移动时间无效')
    line=copy.deepcopy(original);delta=max(-line.start,round(delta))
    line.start+=delta;line.end+=delta
    if line.display_start is not None:line.display_start=max(0,line.display_start+delta)
    if line.display_end is not None:line.display_end+=delta
    for unit in line.units:
        unit.start+=delta;unit.end+=delta;unit.source='manual'
        for part in unit.highlights:part.start+=delta;part.end+=delta;part.source='manual'
    record_tree(original,line,'shift');manual(line);line.validate();return line


def replace_mora(original,index,part,reading):
    if original.locked or any(u.locked for u in original.units):raise ValueError('本句或词组已锁定，请先解除锁定')
    reading=kana_only(reading)
    if not reading or len(morae(reading))!=1:raise ValueError('这里填写一个日语音节，例如 て、す、きょ；整词读音请在注音页修改')
    if not 0<=index<len(original.units) or not 0<=part<len(original.units[index].highlights):raise ValueError('请先选择一个演唱音节')
    line=copy.deepcopy(original);unit=line.units[index];before=copy.deepcopy(unit);remember(unit);remember(unit.highlights[part]);unit.highlights[part].kana=reading
    unit.kana=''.join(h.kana for h in unit.highlights);unit.reading_source='manual'
    from studio_backend.romanization import after_reading_change
    after_reading_change(before,unit)
    line.kana=''.join(u.kana for u in line.units);line.romaji=' '.join(u.romaji for u in line.units if u.romaji)
    manual(line);line.validate();return line


def tail_items(line,maximum=6):
    values=[(i,j,h.start,h.end,h.kana) for i,u in enumerate(line.units) for j,h in enumerate(u.highlights)]
    return values[-maximum:]


def energy_info(samples,rate,start,end):
    """Measure the mixture, not a phoneme classification or a vocal score."""
    a=max(0,min(len(samples),round(start*rate/1000)));b=max(a,min(len(samples),round(end*rate/1000)))
    before=max(0,a-round(rate*.25))
    def rms(part):
        values=np.asarray(part,dtype=np.float64)/32768
        return math.sqrt(float(np.mean(values*values))) if len(values) else 0.
    current=rms(samples[a:b]);previous=rms(samples[before:a])
    return {'db':20*math.log10(max(current,1e-6)),'relative':current/max(previous,1e-6),'duration':end-start}


def consonant_clip(samples,rate,start,end):
    """Bounded, causal high/low-pass audition, never written to source media."""
    a=max(0,round(start*rate/1000));b=min(len(samples),round(end*rate/1000))
    if b<=a:raise ValueError('所选范围没有可试听的音频')
    if b-a>262144:raise ValueError('增强试听仅处理短片段，请缩短选择或使用原声')
    values=np.asarray(samples[a:b],dtype=np.float64)/32768
    n=1<<(max(2,len(values)*2)-1).bit_length();freq=np.fft.rfftfreq(n,1/rate);z=np.exp(-2j*np.pi*freq/rate)
    high=math.exp(-2*math.pi*1200/rate);low=math.exp(-2*math.pi*min(10000,rate*.45)/rate)
    response=(((1+high)/2*(1-z)/(1-high*z))*((1-low)/(1-low*z)))**2
    filtered=np.fft.irfft(np.fft.rfft(values,n)*response,n)[:len(values)]
    peak=float(np.max(np.abs(filtered)));gain=min(8.,.7/max(peak,1e-9)) if peak>1e-9 else 1.
    filtered*=gain
    fade=min(len(filtered)//2,round(rate*.003))
    if fade:filtered[:fade]*=np.linspace(0,1,fade);filtered[-fade:]*=np.linspace(1,0,fade)
    pcm=np.clip(np.rint(filtered*32767),-32768,32767).astype('<i2');output=io.BytesIO()
    with wave.open(output,'wb') as stream:stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(int(rate));stream.writeframes(pcm.tobytes())
    return output.getvalue(),{'start':round(a*1000/rate),'end':round(b*1000/rate),'gain':gain}
