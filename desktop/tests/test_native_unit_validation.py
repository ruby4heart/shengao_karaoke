"""Native structure certification must preserve complete Python validation."""
import copy,gc,random,sys,weakref
import pytest
from shengao import fast_snapshot
from studio_backend import model,provenance
from studio_backend.model import Unit,Highlight


@pytest.fixture
def native():
    previous=model._SNAPSHOT_ACCELERATOR
    assert fast_snapshot.enable()['enabled']
    try:yield sys.modules['_shengao_snapshot']
    finally:model._set_snapshot_accelerator(None if previous is None else previous[0])


def sample():
    return Unit('明日',100,400,'あした',highlights=[Highlight('あ',100,180),Highlight('し',200,300),Highlight('た',300,400)])


def outcome(unit,accelerated):
    saved=model._UNIT_STRUCTURE_ACCELERATOR,provenance._ACCELERATOR
    if not accelerated:model._UNIT_STRUCTURE_ACCELERATOR=None;provenance._ACCELERATOR=None
    try:
        unit.validate();return None
    except Exception as error:return type(error),str(error)
    finally:model._UNIT_STRUCTURE_ACCELERATOR,provenance._ACCELERATOR=saved


@pytest.mark.parametrize('case',['normal','manual-origin','large-integers','empty-highlights','zero-duration','unicode'])
def test_native_certifies_real_structures_and_keeps_python_result(native,case):
    unit=sample()
    if case=='manual-origin':
        for part in unit.highlights:
            part.timing_origin=provenance.create('manual',part.start,part.end,'local')
            part.fixed_edges=['start','end']
    elif case=='large-integers':
        offset=1<<180;unit.start+=offset;unit.end+=offset
        for part in unit.highlights:part.start+=offset;part.end+=offset
    elif case=='empty-highlights':unit.highlights=[];unit.kana=None
    elif case=='zero-duration':unit=Unit('あ',0,0,'あ',highlights=[Highlight('あ',0,0)])
    elif case=='unicode':unit=Unit('𠮷',0,100,'𠮷\ud800',highlights=[Highlight('𠮷',0,50),Highlight('\ud800',50,100)])
    before=copy.deepcopy(unit)
    context=model._UNIT_STRUCTURE_ACCELERATOR
    assert native.unit_structure_valid(context[1],context[2][1],unit)
    assert outcome(unit,False)==outcome(unit,True)==None and unit==before


@pytest.mark.parametrize('case',['text-type','text-length','negative','bool-time','reversed','overlap','beyond','highlight-bool','empty-reading','reading-mismatch','duplicate-edge','unknown-edge','many-edges','edge-type','bad-origin'])
def test_invalid_structures_keep_exact_original_python_errors(native,case):
    unit=sample();part=unit.highlights[1]
    if case=='text-type':unit.text=None
    elif case=='text-length':unit.text='あ'*20001
    elif case=='negative':unit.start=-1
    elif case=='bool-time':unit.start=True
    elif case=='reversed':unit.end=99
    elif case=='overlap':part.start=170
    elif case=='beyond':part.end=401
    elif case=='highlight-bool':part.end=True
    elif case=='empty-reading':part.kana=''
    elif case=='reading-mismatch':unit.kana='あしたあ'
    elif case=='duplicate-edge':part.fixed_edges=['start','start']
    elif case=='unknown-edge':part.fixed_edges=['middle']
    elif case=='many-edges':part.fixed_edges=['start','end','start']
    elif case=='edge-type':part.fixed_edges=None
    elif case=='bad-origin':part.timing_origin={'version':1}
    expected=outcome(unit,False)
    assert expected is not None and outcome(unit,True)==expected
    context=model._UNIT_STRUCTURE_ACCELERATOR
    assert not native.unit_structure_valid(context[1],context[2][1],unit)


def test_random_boundaries_and_readings_match_pure_python(native):
    rng=random.Random(3077)
    for _ in range(160):
        unit=sample();part=rng.choice(unit.highlights)
        part.start=rng.randrange(50,450);part.end=rng.randrange(50,450)
        if rng.randrange(4)==0:part.kana=rng.choice(['','あ','した'])
        assert outcome(unit,True)==outcome(unit,False)


def test_custom_provenance_validator_is_called_for_every_record(native,monkeypatch):
    unit=sample();calls=[];original=provenance.validate
    def observe(value):calls.append(value);return original(value)
    monkeypatch.setattr(provenance,'validate',observe)
    unit.validate()
    assert calls==[unit.timing_origin,*[part.timing_origin for part in unit.highlights]]


def test_properties_and_container_subclasses_keep_the_original_hook_path(native,monkeypatch):
    unit=sample();calls=[]
    with monkeypatch.context() as change:
        change.setattr(Unit,'kana',property(lambda self:(calls.append('kana'),self.__dict__['kana'])[1]))
        unit.validate();assert calls==['kana']
    class Parts(list):
        def __iter__(self):calls.append('iterate');return super().__iter__()
    unit.highlights=Parts(unit.highlights);calls.clear()
    unit.validate();assert calls==['iterate','iterate']


def test_invalid_reading_options_are_checked_before_structure_shortcut(native,monkeypatch):
    unit=sample();unit.reading_options={'invalid':True};original=model._UNIT_STRUCTURE_ACCELERATOR;calls=[]
    def observe(*args):calls.append(args);return original[0](*args)
    monkeypatch.setattr(model,'_UNIT_STRUCTURE_ACCELERATOR',(observe,*original[1:]))
    assert outcome(unit,True)==outcome(unit,False) and outcome(unit,True) is not None
    assert not calls


def test_changed_provenance_contract_falls_back_before_native_call(native,monkeypatch):
    unit=sample();original=model._UNIT_STRUCTURE_ACCELERATOR;calls=[]
    def observe(*args):calls.append(args);return original[0](*args)
    monkeypatch.setattr(model,'_UNIT_STRUCTURE_ACCELERATOR',(observe,*original[1:]))
    monkeypatch.setattr(provenance,'PROVIDERS',frozenset((*provenance.PROVIDERS,'custom')))
    for part in unit.highlights:part.timing_origin=provenance.create('manual',part.start,part.end,'custom')
    unit.validate();assert not calls


def test_context_does_not_retain_model_types_and_handles_collected_types(native):
    baseline=sys.getrefcount(Unit)
    for _ in range(100):context=native.unit_context(Unit,Highlight);del context
    gc.collect();after=sys.getrefcount(Unit);assert after==baseline
    first=type('TemporaryUnit',(),{});second=type('TemporaryHighlight',(),{})
    first_ref=weakref.ref(first);second_ref=weakref.ref(second);context=native.unit_context(first,second)
    del first,second;gc.collect()
    assert first_ref() is None and second_ref() is None
    assert not native.unit_structure_valid(context,provenance._ACCELERATOR[1],None)
