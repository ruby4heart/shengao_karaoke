"""Controlled cache output checks context bounds without neural inference."""
import copy
from pathlib import Path
import threading
import pytest
from shengao import acoustic_batch as batch
from studio_backend.chorus_reuse import prepare
from studio_backend.model import LyricLine
from chorus_fixtures import fixture


def controlled(tmp_path,monkeypatch):
    source,target=fixture();candidate=prepare(source,target,True)
    media=tmp_path/'source.wav';media.write_bytes(b'controlled input')
    model=tmp_path/'model';(model/'dictionaries').mkdir(parents=True)
    (model/'dictionaries/japanese_dict_full.txt').write_text('ki\nmi\nto\nu\nta\n',encoding='utf-8')
    monkeypatch.setattr(batch.audio,'available',lambda:model);monkeypatch.setattr(batch,'ffmpeg',lambda:'unused-ffmpeg')
    decode=[]
    def run(args,cancel):decode.append(True);Path(args[-1]).write_bytes(b'\0'*(24000*48*4))
    monkeypatch.setattr(batch,'run',run)
    raw={'engine':batch.audio.ENGINE_VERSION,'model_sha256':batch.audio.MODEL_SHA256}
    monkeypatch.setattr(batch.audio,'read_cache',lambda *args:raw)
    analysis=[]
    def finalize(prepared,*args):
        analysis.append([prepared['plan']['original']['start'],prepared['plan']['original']['end']])
        return LyricLine.from_dict(prepared['plan']['baseline'])
    monkeypatch.setattr(batch.planning,'finalize',finalize)
    neighbors=[LyricLine('left','已确认上一句',14000,14800,reviewed=True).to_dict(),target.to_dict(),
               LyricLine('right','已确认下一句',21100,23000,reviewed=True).to_dict()]
    return media,candidate,neighbors,analysis,decode


def test_other_lyrics_bound_search_without_becoming_extra_processing_targets(tmp_path,monkeypatch):
    media,candidate,neighbors,analysis,decode=controlled(tmp_path,monkeypatch);original=copy.deepcopy(neighbors)
    result=batch.generate([candidate.to_dict()],media,{},tmp_path/'home',threading.Event(),neighbors=neighbors)
    assert analysis==[[14800,21100]] and decode==[True]
    assert [v['id'] for v in result['suggestions']]==['target'] and result['acoustic']['total']==1 and result['acoustic']['model_loads']==0
    assert neighbors==original


def test_context_with_different_target_range_is_rejected_before_decoding(tmp_path,monkeypatch):
    media,candidate,neighbors,analysis,decode=controlled(tmp_path,monkeypatch);neighbors[1]['end']+=50
    with pytest.raises(ValueError,match='已变化'):
        batch.generate([candidate.to_dict()],media,{},tmp_path/'home',threading.Event(),neighbors=neighbors)
    assert decode==[] and analysis==[]
