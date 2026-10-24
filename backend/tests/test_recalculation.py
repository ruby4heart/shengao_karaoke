import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.provenance import create,record_tree
from studio_backend.acoustic import plan,propose
from studio_backend.recalculation import inspect,prepare,validate_result
from test_acoustic_guides import inference


def shifted():
    h=[Highlight(k,1000+i*1000,2000+i*1000,'estimated',create('estimated',1000+i*1000,2000+i*1000,method='text_distribution')) for i,k in enumerate('あいうえ')]
    h[1].start+=10;h[1].source='manual';h[1].timing_origin['current'][0]+=10;h[1].timing_origin['operations']=['manual_boundary']
    h[2].source='acoustic';h[2].timing_origin=create('acoustic',3000,4000,'tifa','phoneme_alignment','う');h[2].fixed_edges=['start']
    old=LyricLine('recalc','合言葉',1000,5000,[Unit('合言葉',1000,5000,'あいうえ',highlights=h)],kana='あいうえ',translation='人工译文',display_start=0,display_end=6000)
    moved=copy.deepcopy(old);moved.start+=500;moved.end+=500;moved.display_start+=500;moved.display_end+=500
    for u in moved.units:
        u.start+=500;u.end+=500;u.source='manual'
        for part in u.highlights:part.start+=500;part.end+=500;part.source='manual'
    record_tree(old,moved,'shift');moved.validate();return moved


def candidate(p,raw=None):return propose(p,raw or inference(p),'b'*64,'c'*64,'original')


def test_default_manual_protection_is_unchanged_explicit_plan_releases_only_known_internals():
    old=shifted();before=old.to_dict()
    with pytest.raises(ValueError,match='人工固定'):plan(old)
    details=inspect(old);assert [p['highlight'] for p in details['released']]==[0,2,3]
    p=prepare(old);new=candidate(p);assert old.to_dict()==before
    assert new.units[0].highlights[1]==old.units[0].highlights[1]
    assert new.units[0].highlights[2].start==3500 and new.units[0].highlights[2].fixed_edges==['start']
    assert all(new.units[0].highlights[i].source=='acoustic' for i in (0,2,3))
    assert (new.start,new.end,new.units[0].start,new.units[0].end)==(old.start,old.end,old.units[0].start,old.units[0].end)
    assert new.translation==old.translation and not new.reviewed
    assert len(new.timing_evidence['recalculation']['previous'])==3
    validate_result(p,new)


def test_reviewed_line_requires_explicit_permission_and_stays_unchanged_until_adoption():
    old=shifted();old.reviewed=True;before=old.to_dict()
    with pytest.raises(ValueError,match='明确允许'):prepare(old)
    p=prepare(old,True);new=candidate(p)
    assert old.to_dict()==before and not new.reviewed and new.timing_evidence['recalculation']['was_reviewed']


@pytest.mark.parametrize('kind',['legacy','manual','imported','stale'])
def test_uncertain_or_actual_human_timing_is_kept(kind):
    old=shifted();h=old.units[0].highlights[0]
    if kind=='legacy':h.timing_origin={}
    elif kind=='manual':h.timing_origin=create('manual',h.start,h.end,method='human_boundary')
    elif kind=='imported':h.timing_origin=create('imported',h.start,h.end,'ass','imported')
    else:h.timing_origin['current'][0]-=1
    p=prepare(old);assert all(v['highlight']!=0 for v in p['recalculation']['released'])
    assert candidate(p).units[0].highlights[0]==h


def test_failed_run_keeps_original_metadata_even_with_success_in_same_word():
    old=shifted();p=prepare(old);raw=inference(p);raw['jobs'][0]={'index':0,'error':'fixture failure'}
    new=candidate(p,raw)
    assert new.units[0].highlights[0]==old.units[0].highlights[0]
    assert new.units[0].highlights[1]==old.units[0].highlights[1]
    assert len(new.timing_evidence['recalculation']['applied'])==2


def test_no_success_keeps_axis_and_original_protection():
    old=shifted();before=old.to_dict();p=prepare(old);raw=inference(p)
    raw['jobs']=[{'index':i,'error':'fixture failure'} for i in range(len(raw['jobs']))]
    with pytest.raises(ValueError,match='原时间保留'):candidate(p,raw)
    assert old.to_dict()==before


def test_forged_permission_or_released_human_mora_is_rejected():
    p=prepare(shifted());new=candidate(p)
    p['recalculation']['released'].append({'unit':0,'highlight':1,'kana':'い','basis':'estimated','operations':[]})
    with pytest.raises(ValueError,match='保护范围已变化'):validate_result(p,new)


def test_locked_word_is_never_released():
    old=shifted();old.units[0].locked=True
    assert inspect(old)['released']==[] and inspect(old)['locked_units']==1
    with pytest.raises(ValueError):prepare(old,True)


def test_permission_to_reopen_confirmation_does_not_imply_releasing_old_protection():
    old=shifted();old.reviewed=True;old.units[0].highlights[3].source='estimated'
    p=prepare(old,True,False);assert p['recalculation']['released']==[]
    new=candidate(p)
    assert all(new.units[0].highlights[i]==old.units[0].highlights[i] for i in (0,1,2))
    assert new.units[0].highlights[3].source=='acoustic' and not new.reviewed


def test_corrupt_permission_types_are_rejected():
    p=prepare(shifted());new=candidate(p)
    for key,value in [('version',True),('release_old_protection','true')]:
        corrupt=copy.deepcopy(p);corrupt['recalculation'][key]=value
        with pytest.raises(ValueError):validate_result(corrupt,new)


def test_real_human_basis_survives_inconsistent_legacy_editor_flags():
    old=shifted();unit=old.units[0];unit.source='estimated';unit.timing_origin=create('manual',unit.start,unit.end,method='human_word_range')
    h=unit.highlights[1];h.source='estimated';h.timing_origin=create('manual',h.start,h.end,method='human_mora')
    p=prepare(old);new=candidate(p)
    assert new.units[0].highlights[1]==h
    assert (new.units[0].start,new.units[0].end,new.units[0].timing_origin)==(unit.start,unit.end,unit.timing_origin)
