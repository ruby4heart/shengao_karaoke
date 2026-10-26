import copy
from collections import namedtuple
import pytest
from shengao.undo_snapshot import UndoSnapshot
from shengao.project import History,Project
from test_line_history import sample
from shengao.timing import set_time


def test_snapshot_restores_exact_content_without_aliasing_and_compresses_repeated_data():
    data={'lines':[{'text':'明日','notes':['original']*20} for _ in range(1000)]};before=copy.deepcopy(data);snapshot=UndoSnapshot(data)
    assert snapshot.compressed_bytes<10000 and snapshot==data and data==snapshot
    data['lines'][0]['notes'].append('external');restored=snapshot.restore();assert restored==before
    restored['lines'][0]['notes'].append('changed');assert snapshot.restore()==before and snapshot['lines']==before['lines']
    assert dict(snapshot)==before


def test_local_python_metadata_falls_back_without_losing_type_or_independence():
    Pair=namedtuple('Pair','name values');data={'pair':Pair('name',['original'])};snapshot=UndoSnapshot(data)
    assert snapshot.compressed_bytes is None
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


def test_compressed_payload_cannot_be_imported_through_the_snapshot_constructor():
    with pytest.raises(TypeError):UndoSnapshot(b'not an internal dictionary')
