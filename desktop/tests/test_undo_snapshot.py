import copy
import math
from collections import namedtuple
import pytest
from shengao.undo_snapshot import UndoSnapshot,SnapshotStore
from shengao.process_memory import sample as memory
from shengao.project import History,Project
from test_line_history import sample
from shengao.timing import set_time


def test_snapshot_restores_exact_content_without_aliasing():
    data={'lines':[{'text':'明日','notes':['original']*20} for _ in range(1000)]};before=copy.deepcopy(data);snapshot=UndoSnapshot(data)
    assert snapshot==data and data==snapshot
    data['lines'][0]['notes'].append('external');restored=snapshot.restore();assert restored==before
    restored['lines'][0]['notes'].append('changed');assert snapshot.restore()==before and snapshot['lines']==before['lines']
    assert dict(snapshot)==before


def test_local_python_metadata_keeps_type_and_independence():
    Pair=namedtuple('Pair','name values');data={'pair':Pair('name',['original'])};snapshot=UndoSnapshot(data)
    data['pair'].values.append('external');restored=snapshot.restore()
    assert isinstance(restored['pair'],Pair) and restored['pair'].values==['original']
    restored['pair'].values.append('new');assert snapshot.restore()['pair'].values==['original']


def test_history_roundtrip_preserves_whole_project_and_original_object_references_are_detached():
    p=sample();history=History(p);before=p.to_dict()
    assert history.apply_line('调整',0,lambda line:set_time(line,-1,110,510));after=history.project.to_dict()
    assert isinstance(history.undo_stack[-1][1],UndoSnapshot) and history.undo_stack[-1][1]==before
    assert history.undo() and history.project.to_dict()==before
    assert history.redo() and history.project.to_dict()==after
    assert p.to_dict()==before


def test_legacy_in_memory_dictionary_steps_still_restore_and_failed_restore_keeps_stacks():
    p=sample();before=p.to_dict();history=History(p);history.undo_stack=[('旧记录',before)]
    assert history.undo() and history.project.to_dict()==before
    invalid=copy.deepcopy(before);invalid['lines'][0]['end']=0;history.undo_stack=[('错误记录',UndoSnapshot(invalid))];undo_before=list(history.undo_stack);redo_before=list(history.redo_stack)
    with pytest.raises(ValueError):history.undo()
    assert history.undo_stack==undo_before and history.redo_stack==redo_before and history.project.to_dict()==before


def test_history_cap_and_merging_keep_correct_earliest_snapshot():
    p=Project();history=History(p)
    for index in range(160):assert history.apply('标题',lambda q:setattr(q,'title',str(index)))
    assert len(history.undo_stack)==150
    for _ in range(150):assert history.undo()
    assert history.project.title=='9'
    history=History(sample());before=history.project.to_dict()
    for start in (110,120):assert history.apply_line('微调',0,lambda line:set_time(line,-1,start,start+400),merge_key='same')
    assert len(history.undo_stack)==1 and history.undo() and history.project.to_dict()==before


def test_binary_payload_cannot_be_imported_through_the_snapshot_constructor():
    with pytest.raises(TypeError):UndoSnapshot(b'not an internal dictionary')


def test_many_snapshots_keep_memory_bounded_and_restore_every_complete_document():
    store=SnapshotStore();data={'title':'original','lines':[{'id':str(i),'notes':['original']*100} for i in range(1000)]};before=memory();snapshots=[]
    for index in range(150):
        data['title']=str(index);snapshots.append(store.capture(data))
    after=memory();assert after['private_bytes']-before['private_bytes']<32*1024*1024
    for index in (0,74,149):
        restored=snapshots[index].restore();assert restored['title']==str(index) and restored['lines']==data['lines']
    restored['lines'][0]['notes'].clear();data['lines'][1]['notes'].append('external')
    assert snapshots[0]['lines'][0]['notes']==['original']*100 and snapshots[-1]['lines'][1]['notes']==['original']*100


def test_changed_deleted_and_reordered_lines_keep_their_own_historical_values():
    store=SnapshotStore();data={'title':'song','lines':[{'id':'a','notes':['a']},{'id':'b','notes':['b']}]};first=store.capture(data)
    data['lines'][0]['notes'].append('new');second=store.capture(data)
    data['lines'].reverse();third=store.capture(data);del data['lines'][0];fourth=store.capture(data)
    assert first['lines']==[{'id':'a','notes':['a']},{'id':'b','notes':['b']}]
    assert second['lines']==list(reversed(third['lines'])) and fourth['lines']==[{'id':'a','notes':['a','new']}]
    store.adopt(first);assert store.capture(first.restore())==first and second['lines'][0]['notes']==['a','new']


def test_restored_style_and_media_python_metadata_cannot_mutate_other_history_steps():
    class Text(str):pass
    p=sample();p.style.name=Text('style');p.style.name.notes=['style'];p.media=Text('source');p.media.notes=['source']
    history=History(p);before=p.to_dict()
    for start in (110,120):assert history.apply_line('调整',0,lambda line:set_time(line,-1,start,start+400))
    assert history.undo();history.project.style.name.notes.append('new');history.project.media.notes.append('new')
    assert history.undo_stack[-1][1]==before and history.undo()
    assert history.project.style.name.notes==['style'] and history.project.media.notes==['source']


def test_equal_string_values_with_different_extra_python_state_are_not_reused():
    class Text(str):pass
    p=sample();p.style.name=Text('same text');p.style.name.notes=['original'];history=History(p)
    assert history.apply('标题',lambda q:setattr(q,'title','first'))
    history.project.style.name.notes.append('unrecorded')
    assert history.apply_line('时间',0,lambda line:set_time(line,-1,110,510))
    assert history.undo() and history.project.style.name.notes==['original','unrecorded']
    assert history.undo() and history.project.style.name.notes==['original']


def test_python_equal_values_with_different_nested_types_and_float_signs_stay_distinct():
    store=SnapshotStore();first=store.capture({'lines':[{'id':'a','notes':[1,0.0]}]})
    second=store.capture({'lines':[{'id':'a','notes':[True,-0.0]}]})
    a=first.restore()['lines'][0]['notes'];b=second.restore()['lines'][0]['notes']
    assert type(a[0]) is int and type(b[0]) is bool and math.copysign(1,a[1])==1 and math.copysign(1,b[1])==-1


@pytest.mark.parametrize('base,value',[(str,'text'),(bytes,b'text'),(int,1),(float,1.0),(list,[1]),(dict,{'value':1}), (tuple,(1,))])
def test_scalar_and_container_subclasses_keep_extra_state(base,value):
    class Value(base):pass
    item=Value(value);item.notes=['first'];store=SnapshotStore();first=store.capture({'item':item})
    item.notes.append('second');second=store.capture({'item':item})
    assert first.restore()['item'].notes==['first'] and second.restore()['item'].notes==['first','second']


def test_custom_reduction_cannot_disguise_extra_state_as_a_builtin():
    class Value(str):
        def __reduce_ex__(self,protocol):raise AssertionError('fingerprinting must not execute custom reduction')
        def __deepcopy__(self,memo):
            result=Value(self);memo[id(self)]=result;result.notes=copy.deepcopy(self.notes,memo);return result
    item=Value('text');item.notes=['first'];store=SnapshotStore();first=store.capture({'item':item})
    item.notes.append('second');second=store.capture({'item':item})
    assert first.restore()['item'].notes==['first'] and second.restore()['item'].notes==['first','second']


def test_builtin_graph_fingerprints_preserve_aliases_cycles_and_container_types():
    shared=[];cycle=[];cycle.append(cycle);store=SnapshotStore()
    first=store.capture({'value':[shared,shared],'cycle':cycle,'sequence':(1,)})
    second=store.capture({'value':[[],[]],'cycle':cycle,'sequence':[1]})
    a=first.restore();b=second.restore()
    assert a['value'][0] is a['value'][1] and b['value'][0] is not b['value'][1]
    assert a['cycle'][0] is a['cycle'] and b['cycle'][0] is b['cycle']
    assert type(a['sequence']) is tuple and type(b['sequence']) is list
