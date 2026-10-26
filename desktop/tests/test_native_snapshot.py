"""The production accelerator must retain the Python serializer's exact contract."""
from pathlib import Path
from dataclasses import dataclass
from collections import namedtuple
import copy,gc,json,random,sys
import pytest
from studio_backend import model
from shengao import fast_snapshot
from test_project_snapshot_isolation import project


@pytest.fixture
def acceleration():
    previous=model._SNAPSHOT_ACCELERATOR;status=fast_snapshot.enable();assert status['enabled'],status
    try:yield model._SNAPSHOT_ACCELERATOR
    finally:model._SNAPSHOT_ACCELERATOR=previous


def test_full_project_and_json_field_order_match_python_including_uncommon_metadata(acceleration):
    @dataclass
    class Detail:values:list
    Pair=namedtuple('Pair','name values')
    class Text(str):pass
    p=project();p.lines[0].reading_review['extra']=Pair('name',[Detail([1,True,-0.0])])
    p.lines[0].reading_review['hidden_unit']=copy.deepcopy(p.lines[0].units[0])
    p.lines[0].translation=Text('translation');p.lines[0].translation.notes=['extra state']
    model._SNAPSHOT_ACCELERATOR=None;expected=p.to_dict();expected_json=json.dumps(expected,ensure_ascii=False)
    model._SNAPSHOT_ACCELERATOR=acceleration;actual=p.to_dict()
    assert actual==expected and json.dumps(actual,ensure_ascii=False)==expected_json
    assert type(actual['lines'][0]['reading_review']['extra']) is Pair
    assert actual['lines'][0]['translation'].notes==['extra state']
    restored=type(p).from_dict(actual);assert restored.to_dict()==expected
    actual['lines'][0]['reading_review']['extra'].values[0]['values'].append('external')
    assert p.to_dict()==expected and restored.to_dict()==expected


def test_random_plain_trees_and_tuples_keep_exact_structure_and_values(acceleration):
    native,fields,detach=acceleration;randomizer=random.Random(803)
    def tree(depth):
        if depth==0:return randomizer.choice([None,True,False,1,-0.0,0.0,'日本語',b'bytes'])
        kind=randomizer.randrange(4)
        if kind==0:return {str(i):tree(depth-1) for i in range(randomizer.randrange(4))}
        if kind==1:return [tree(depth-1) for _ in range(randomizer.randrange(4))]
        if kind==2:return tuple(tree(depth-1) for _ in range(randomizer.randrange(4)))
        return tree(0)
    for _ in range(200):
        value=tree(5);actual=native.snapshot(value,fields,model._model_snapshot);expected=model._model_snapshot(value)
        assert repr(actual)==repr(expected) and detach(value)==model._detached(value)


def test_native_exceptions_balance_references_and_recursion_guard(acceleration):
    native,fields,detach=acceleration;reference='reference-'+str(id(native));value={'value':[reference,reference]};before=sys.getrefcount(reference)
    for _ in range(10000):result=native.snapshot(value,fields,model._model_snapshot)
    del result;assert sys.getrefcount(reference)==before
    class Bad:
        def __deepcopy__(self,memo):raise ValueError('copy failed')
    failing={'reference':reference,'later':Bad()};before=sys.getrefcount(reference)
    for _ in range(100):
        with pytest.raises(ValueError,match='copy failed'):native.snapshot(failing,fields,model._model_snapshot)
    assert sys.getrefcount(reference)==before
    cycle=[];cycle.append(cycle)
    with pytest.raises(RecursionError):native.snapshot(cycle,fields,model._model_snapshot)
    assert native.snapshot([1],fields,model._model_snapshot)==[1]


def test_container_mutation_during_uncommon_copy_keeps_python_iterator_semantics(acceleration):
    native,fields,detach=acceleration
    def dictionary():
        value={}
        class Mutator:
            def __deepcopy__(self,memo):value['new']='item';return 'copied'
        value['original']=Mutator();return value
    for operation in (model._model_snapshot,lambda value:native.snapshot(value,fields,model._model_snapshot)):
        with pytest.raises(RuntimeError,match='dictionary changed size'):operation(dictionary())
    def sequence():
        value=[]
        class Mutator:
            def __deepcopy__(self,memo):value.pop();return 'copied'
        value.extend([Mutator(),'removed']);return value
    assert native.snapshot(sequence(),fields,model._model_snapshot)==model._model_snapshot(sequence())==['copied']


def test_legacy_omission_collects_original_nodes_before_uncommon_truth_callbacks(acceleration):
    native=acceleration[0];events=[]
    class Empty:
        def __init__(self,name,action=lambda:None):self.name=name;self.action=action
        def __bool__(self):events.append(self.name);self.action();return False
    a={'timing_origin':Empty('a')};b={'timing_origin':Empty('b')}
    u={'timing_origin':Empty('u'),'highlights':[a]};v={'timing_origin':Empty('v'),'highlights':[b]}
    units=[u,v];root={'units':units,'timing_origin':Empty('root',units.clear)};nodes=[root,u,v,a,b]
    assert native.clean_lyric(root,model._LEGACY_EMPTY_KEYS)
    assert events==['root','u','v','a','b'] and all('timing_origin' not in node for node in nodes)


@pytest.mark.parametrize('key',['timing_origin','fixed_edges','reading_options'])
def test_legacy_omission_keeps_default_pop_and_required_pop_error_semantics(acceleration,key):
    native=acceleration[0];value={'units':[]}
    class Empty:
        def __bool__(self):del value[key];return False
    value[key]=Empty()
    if key=='timing_origin':assert native.clean_lyric(value,model._LEGACY_EMPTY_KEYS)
    else:
        with pytest.raises(KeyError):native.clean_lyric(value,model._LEGACY_EMPTY_KEYS)


def test_nonstandard_containers_fall_back_before_any_legacy_omission(acceleration):
    class Custom(dict):pass
    value={'timing_origin':{},'units':[Custom(highlights=[])]};before=copy.deepcopy(value)
    assert not acceleration[0].clean_lyric(value,model._LEGACY_EMPTY_KEYS) and value==before


@pytest.mark.parametrize('change',['binary','source','abi','module'])
def test_manifest_rejects_corruption_source_and_abi_mismatches(tmp_path,change):
    binary,record=fast_snapshot.verify(source=fast_snapshot.ROOT/'desktop/native/snapshot.c')
    (tmp_path/binary.name).write_bytes(binary.read_bytes());source=tmp_path/'snapshot.c';source.write_bytes((fast_snapshot.ROOT/'desktop/native/snapshot.c').read_bytes())
    if change=='binary':(tmp_path/binary.name).write_bytes(b'corrupted')
    elif change=='source':source.write_text('different source',encoding='utf-8')
    elif change=='abi':record['python_abi']='cp999'
    else:record['module']='different.pyd'
    (tmp_path/'snapshot-native.json').write_text(json.dumps(record),encoding='utf-8')
    with pytest.raises(ValueError):fast_snapshot.verify(tmp_path,source)


def test_missing_accelerator_keeps_python_path_without_changing_document(monkeypatch):
    previous=model._SNAPSHOT_ACCELERATOR;p=project();expected=p.to_dict()
    def missing(*args,**kwargs):raise FileNotFoundError('missing local module')
    monkeypatch.setattr(fast_snapshot,'verify',missing)
    try:
        status=fast_snapshot.enable();assert not status['enabled'] and model._SNAPSHOT_ACCELERATOR is None
        assert p.to_dict()==expected
    finally:model._SNAPSHOT_ACCELERATOR=previous
