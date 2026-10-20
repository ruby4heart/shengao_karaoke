"""Real local decode/cache checks; no cloud or model calls."""
import hashlib
import os
import threading
import wave
from pathlib import Path
import numpy as np
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from shengao import media,sound_gap_audio


def audio(path,frequency):
    t=np.arange(96000)/48000;values=(np.sin(2*np.pi*frequency*t)*.3*32767).astype('<i2')
    with wave.open(str(path),'wb') as stream:stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(48000);stream.writeframes(values.tobytes())


def lines():return [LyricLine('a','かな',400,1600,[Unit('かな',400,1600,'かな',highlights=[Highlight('か',400,900),Highlight('な',1000,1600)])])]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_wave_cache_uses_content_even_with_same_size_and_timestamp(tmp_path):
    source=tmp_path/'原声.wav';audio(source,220);stamp=source.stat();a=media.analyze(source,tmp_path/'cache')
    audio(source,440);assert source.stat().st_size==stamp.st_size;os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    b=media.analyze(source,tmp_path/'cache')
    assert str(a['source_sha256'])!=str(b['source_sha256']) and a['pcm']!=b['pcm']
    assert str(b['source_sha256'])==sha(source)


def test_corrupt_pcm_cache_is_rebuilt(tmp_path):
    source=tmp_path/'voice.wav';audio(source,220);a=media.analyze(source,tmp_path/'cache');expected=sha(a['pcm'])
    with Path(a['pcm']).open('r+b') as stream:stream.seek(300);stream.write(b'\x00'*100)
    assert sha(a['pcm'])!=expected
    b=media.analyze(source,tmp_path/'cache');assert sha(b['pcm'])==expected==str(b['pcm_sha256'])


def test_sound_gap_cache_and_adoption_guard_reject_changed_source(tmp_path):
    source=tmp_path/'voice.wav';audio(source,220);stamp=source.stat();cancel=threading.Event()
    first=sound_gap_audio.generate(lines(),source,{},'original',tmp_path/'home',cancel)
    audio(source,440);os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    with pytest.raises(ValueError,match='变化'):sound_gap_audio.verify(source,{},first['binding'],cancel)
    second=sound_gap_audio.generate(lines(),source,{},'original',tmp_path/'home',cancel)
    assert first['binding']['source_sha256']!=second['binding']['source_sha256']
    assert first['binding']['pcm_sha256']!=second['binding']['pcm_sha256']
    assert len(list((tmp_path/'home/sound-gap-audio').glob('*/audio.json')))==2


def test_cancelled_wave_preparation_never_starts_decoder(tmp_path,monkeypatch):
    source=tmp_path/'voice.wav';audio(source,220);cancel=threading.Event();cancel.set()
    monkeypatch.setattr(media.subprocess,'Popen',lambda *a,**k:pytest.fail('Cancelled job must not launch FFmpeg'))
    with pytest.raises(ValueError,match='取消'):media.analyze(source,tmp_path/'cache',cancel)
