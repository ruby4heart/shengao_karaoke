import json,math,random
from dataclasses import dataclass
from collections import namedtuple
import pytest
from studio_backend import model
from studio_backend.settings import atomic_json
from shengao import fast_snapshot,checkpoint_encoding as codec


@pytest.fixture(autouse=True)
def native_codec():
    previous=model._SNAPSHOT_ACCELERATOR;status=fast_snapshot.enable();assert status['enabled'],status
    assert codec.available()
    try:yield
    finally:model._SNAPSHOT_ACCELERATOR=previous


def standard(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def test_plain_data_uses_fast_encoder_and_keeps_json_values_and_float_signs():
    before=codec.status()['encoding_calls']['fast']
    value={'歌词':'明日も歌う','values':[True,False,1,None,-0.0,0.0,1e-7,1.2345678901234567]}
    actual=json.loads(codec.dumps(value));assert actual==json.loads(standard(value))
    assert math.copysign(1,actual['values'][4])==-1 and codec.status()['encoding_calls']['fast']==before+1


@pytest.mark.parametrize('value',[{'large':2**100},{1:'integer',None:'none'},{'tuple':(1,2)},'lone\ud800'])
def test_edge_values_keep_standard_encoding_semantics(value):
    assert json.loads(codec.dumps(value))==json.loads(standard(value))


@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_values_are_rejected_and_never_silently_become_null(tmp_path,value):
    path=tmp_path/'checkpoint.json';atomic_json(path,{'old':'kept'},compact=True);before=path.read_bytes()
    with pytest.raises(ValueError):atomic_json(path,{'nested':[value]},compact=True,dumps=codec.dumps)
    assert path.read_bytes()==before and not list(tmp_path.glob('*.tmp'))


def test_uncommon_types_keep_old_rejection_or_container_behavior():
    @dataclass
    class Data:field:int
    with pytest.raises(TypeError):codec.dumps({'data':Data(1)})
    with pytest.raises(TypeError):codec.dumps({'data':b'bytes'})
    Pair=namedtuple('Pair','a b');value={'pair':Pair(1,2)}
    assert codec.dumps(value)==standard(value)


def test_cycles_fall_back_to_the_original_circular_reference_error():
    value=[];value.append(value)
    with pytest.raises(ValueError,match='Circular reference'):codec.dumps(value)
    assert codec.dumps([1])=='[1]'


def test_missing_optional_encoder_or_native_guard_keeps_standard_path(monkeypatch):
    value={'same':[1,-0.0,'日本語']};previous=model._SNAPSHOT_ACCELERATOR
    model._SNAPSHOT_ACCELERATOR=None
    try:assert not codec.available() and codec.dumps(value)==standard(value)
    finally:model._SNAPSHOT_ACCELERATOR=previous
    monkeypatch.setattr(codec,'orjson',None);assert not codec.available() and codec.dumps(value)==standard(value)


def test_random_finite_trees_roundtrip_exactly():
    randomizer=random.Random(502)
    def tree(depth):
        if not depth:return randomizer.choice([0,-1,True,False,None,-0.0,1e-12,'歌词'])
        if randomizer.randrange(2):return {str(i):tree(depth-1) for i in range(randomizer.randrange(5))}
        return [tree(depth-1) for _ in range(randomizer.randrange(5))]
    for _ in range(200):
        value=tree(5);assert json.loads(codec.dumps(value))==json.loads(standard(value))
