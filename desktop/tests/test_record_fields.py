"""Fast record preparation must preserve detached readers and model hooks."""
import copy,sys
from dataclasses import dataclass,field
import pytest
from studio_backend import model
from shengao import fast_snapshot
from shengao.project import Project,History
from shengao.timing import set_time
from test_project_snapshot_isolation import project


@pytest.fixture
def native():
    previous=model._SNAPSHOT_ACCELERATOR
    status=fast_snapshot.enable();assert status['enabled'],status
    try:yield model._SNAPSHOT_ACCELERATOR[0]
    finally:model._SNAPSHOT_ACCELERATOR=previous


def test_plain_preparation_keeps_input_order_unknown_filtering_and_independent_fields(native):
    shared={'nested':[True,1,-0.0,None]}
    value={'text':'明日','unknown':object(),'reading_review':shared,'match':shared,'units':object()}
    result=native.record_fields(value,model.LyricLine.__dataclass_fields__,'units')
    assert list(result)==['text','reading_review','match']
    assert result['reading_review']==shared and result['match']==shared
    assert result['reading_review'] is not result['match']
    result['reading_review']['nested'].append('changed')
    assert shared['nested']==[True,1,-0.0,None] and result['match']==shared


def test_reader_matches_python_and_detaches_all_nested_records(native):
    data=project().to_dict()
    data['lines'][0]['unknown']=object();data['lines'][0]['units'][0]['unknown']=object()
    accelerator=model._SNAPSHOT_ACCELERATOR
    model._SNAPSHOT_ACCELERATOR=None;expected=Project.from_dict(data).to_dict()
    model._SNAPSHOT_ACCELERATOR=accelerator
    restored=Project.from_dict(data);assert restored.to_dict()==expected
    data['lines'][0]['reading_review']['notes']['values'].append('input')
    data['lines'][0]['units'][0]['highlights'][0]['fixed_edges'].append('end')
    assert restored.to_dict()==expected
    restored.lines[0].units[0].highlights[1].fixed_edges.append('start')
    assert data['lines'][0]['units'][0]['highlights'][1].get('fixed_edges',[])==[]


@pytest.mark.parametrize('location',['line','unit'])
def test_opaque_copy_hooks_run_once_without_speculative_side_effects(native,location):
    calls=[]
    class Note:
        def __deepcopy__(self,memo):calls.append('copy');return {'copied':[1]}
    data=project().lines[0].to_dict()
    if location=='line':data['reading_review']['custom']=Note()
    else:data['units'][0]['reading_options']={'custom':Note()}
    line=model.LyricLine._from_dict_record(data)
    assert calls==['copy']
    target=line.reading_review if location=='line' else line.units[0].reading_options
    assert target['custom']=={'copied':[1]}


def test_custom_line_constructor_and_unit_post_init_are_still_invoked(native,monkeypatch):
    calls=[];original=model.Unit.__post_init__
    def post_init(self):calls.append(('unit',self.text));original(self)
    monkeypatch.setattr(model.Unit,'__post_init__',post_init)
    @dataclass
    class Line(model.LyricLine):
        extra:list=field(default_factory=list)
        def __post_init__(self):calls.append(('line',self.text));self.extra.append('constructed')
    data=project().lines[0].to_dict()
    calls.clear()
    line=Line._from_dict_record(data)
    assert type(line) is Line and line.extra==['constructed']
    assert calls==[*(('unit',u['text']) for u in data['units']),('line',data['text'])]


@pytest.mark.parametrize('value',[{'reading_review':({'tuple':[1]},)}, {'reading_review':{1:[2]}}])
def test_uncommon_plain_values_keep_python_copy_semantics(native,value):
    # Tuple values take the existing detach path; integer nested keys remain valid.
    source=project().lines[0].to_dict();source.update(value)
    expected=copy.deepcopy(value['reading_review'])
    result=model.LyricLine._from_dict_record(source)
    assert result.reading_review==expected and result.reading_review is not value['reading_review']


def test_mapping_subclasses_are_delegated_to_the_existing_reader(native):
    calls=[]
    class Record(dict):
        def items(self):calls.append('items');return super().items()
    source=Record(project().lines[0].to_dict())
    assert native.record_fields(source,model.LyricLine.__dataclass_fields__,'units') is NotImplemented
    restored=model.LyricLine.from_dict(source)
    assert restored.text==source['text'] and calls==['items']


def test_invalid_neighbor_blocks_line_edit_and_keeps_history_unchanged(native):
    p=project();p.lines.append(model.LyricLine('neighbor','次',600,1000));h=History(p)
    h.project.lines[1].start=1100
    before=h.project.to_dict()
    with pytest.raises(ValueError):h.apply_line('timing',0,lambda line:set_time(line,-1,110,510))
    assert h.project.to_dict()==before and h.undo_stack==[] and h.redo_stack==[]


def test_subclass_values_keep_the_previous_fallback(native):
    class Notes(list):pass
    notes=Notes([1]);notes.extra=['state']
    source=project().lines[0].to_dict();source['reading_review']={'custom':notes}
    restored=model.LyricLine._from_dict_record(source)
    assert type(restored.reading_review['custom']) is Notes
    assert restored.reading_review['custom'].extra==['state']
    restored.reading_review['custom'].extra.append('changed')
    assert notes.extra==['state']


def test_copy_hook_cannot_replace_the_constructor_already_resolved_for_this_unit(native,monkeypatch):
    original=model.Unit
    class OtherUnit(original):pass
    class ChangeBinding:
        def __deepcopy__(self,memo):monkeypatch.setattr(model,'Unit',OtherUnit);return 'kept'
    source=project().lines[0].to_dict()
    source['units'][0]['reading_source']=ChangeBinding()
    line=model.LyricLine._from_dict_record(source)
    assert type(line.units[0]) is original and line.units[0].reading_source=='kept'


def test_custom_schema_lookup_keeps_python_metaclass_hooks(native):
    accesses=[]
    class Meta(type):
        def __getattribute__(cls,name):
            if name=='__dataclass_fields__':accesses.append(name)
            return super().__getattribute__(name)
    class Line(model.LyricLine,metaclass=Meta):pass
    source=project().lines[0].to_dict();accelerator=model._SNAPSHOT_ACCELERATOR
    model._SNAPSHOT_ACCELERATOR=None
    expected=Line._from_dict_record(source);count=len(accesses);accesses.clear()
    model._SNAPSHOT_ACCELERATOR=accelerator
    actual=Line._from_dict_record(source);actual_count=len(accesses)
    assert actual.to_dict()==expected.to_dict() and actual_count==count


def test_native_recursion_errors_release_partial_results_and_input_references(native):
    cycle=[];cycle.append(cycle)
    source={'reading_review':{'nested':cycle}}
    before=sys.getrefcount(source),sys.getrefcount(cycle),sys.getrefcount(source['reading_review'])
    for _ in range(20):
        with pytest.raises(RecursionError):native.record_fields(source,model.LyricLine.__dataclass_fields__,'units')
    assert (sys.getrefcount(source),sys.getrefcount(cycle),sys.getrefcount(source['reading_review']))==before
