import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.mora_editing import split,merge,reset
from studio_backend.romanization import set_manual
from studio_backend.reading_options import set_ruby
from studio_backend.provenance import inferred


def line():
    value=LyricLine('mora','今日も',1000,4000,[Unit('今日',1000,3000,'きょう',highlights=[Highlight('きょう',1000,3000,'manual')]),Unit('も',3200,4000,'も',highlights=[Highlight('も',3200,4000,'manual')])],reviewed=True,translation='今天也')
    return set_ruby(set_manual(value,0,'KYOH'),0,{'mode':'whole'})


def test_split_keeps_original_kana_roman_ruby_neighbor_axis_and_outer_human_points():
    old=line();before=old.to_dict();value=split(old,0,0,2)['line'];parts=value.units[0].highlights
    assert [h.kana for h in parts]==['きょ','う'] and [(h.start,h.end) for h in parts]==[(1000,2000),(2000,3000)]
    assert parts[0].fixed_edges==['start'] and parts[1].fixed_edges==['end'] and all(inferred(h)['kind']=='estimated' for h in parts)
    assert value.text==old.text and value.units[0].kana==old.units[0].kana and value.units[0].romaji=='KYOH' and value.units[0].reading_options==old.units[0].reading_options
    assert value.units[1]==old.units[1] and value.translation==old.translation and not value.reviewed and old.to_dict()==before


def test_supplied_split_position_adds_explicit_shared_fixed_edge():
    value=split(line(),0,0,2,at=2180)['line'];a,b=value.units[0].highlights
    assert a.end==b.start==2180 and a.fixed_edges==['start','end'] and b.fixed_edges==['start','end']


def test_reset_and_split_estimate_same_mora_proportions_and_count_shared_cut_once():
    original=line();a=split(original,0,0,2);b=reset(original,0)
    assert [(h.kana,h.start,h.end,h.fixed_edges) for h in a['line'].units[0].highlights]==[(h.kana,h.start,h.end,h.fixed_edges) for h in b['line'].units[0].highlights]
    assert a['estimated_new_boundaries']==b['estimated_new_boundaries']==1
    assert not {'end'} & set(a['line'].units[0].highlights[0].fixed_edges)
    assert split(original,0,0,2,at=2000)['estimated_new_boundaries']==0


def test_advanced_character_split_is_explicit_and_default_restores_digraph():
    old=LyricLine('small','君',1000,2000,[Unit('君',1000,2000,'きょ',highlights=[Highlight('きょ',1000,2000,'acoustic')])])
    with pytest.raises(ValueError,match='拗音'):split(old,0,0,1)
    value=split(old,0,0,1,allow_character=True)['line'];assert [h.kana for h in value.units[0].highlights]==['き','ょ']
    assert all(h.source=='manual' and inferred(h)['kind']=='estimated' for h in value.units[0].highlights)
    restored=reset(value,0)['line'];assert [h.kana for h in restored.units[0].highlights]==['きょ']


def test_merge_requires_explicit_internal_manual_loss_and_keeps_outer_points():
    old=split(line(),0,0,2)['line'];a,b=old.units[0].highlights;a.source=b.source='manual';a.timing_origin={};b.timing_origin={}
    with pytest.raises(ValueError,match='人工边界'):merge(old,0,0,1)
    value=merge(old,0,0,1,allow_manual=True)['line'];assert value.units[0].highlights[0].kana=='きょう'
    assert value.units[0].highlights[0].fixed_edges==['start','end'] and value.units[1]==old.units[1]


def test_merge_never_discards_internal_explicit_pin_and_gap_needs_separate_acknowledgment():
    old=split(line(),0,0,2,at=2100)['line']
    with pytest.raises(ValueError,match='固定点'):merge(old,0,0,1,True,True)
    old=split(line(),0,0,2)['line'];old.units[0].highlights[0].end=1900
    with pytest.raises(ValueError,match='间隔'):merge(old,0,0,1)
    value=merge(old,0,0,1,allow_gaps=True);assert value['closed_gap_ms']==100


def test_locked_neighbor_does_not_prevent_local_edit_and_target_lock_does():
    old=line();old.units[1].locked=True;assert split(old,0,0,2)['line'].units[1]==old.units[1]
    old.units[0].locked=True
    with pytest.raises(ValueError,match='锁定'):split(old,0,0,2)


def test_noop_reset_keeps_exact_old_data_and_malformed_history_is_rejected():
    old=split(line(),0,0,2)['line'];before=copy.deepcopy(old.to_dict());result=reset(old,0)
    assert not result['changed'] and result['line'].to_dict()==before
    old.reading_review['mora_edits'][0]['after'][0]['start']=-1
    with pytest.raises(ValueError):old.validate()


def test_alignment_can_compute_canonical_estimates_between_preserved_human_edges():
    from studio_backend.acoustic import plan
    old=split(line(),0,0,2)['line'];prepared=plan(old)
    assert any([(m['unit'],m['highlight']) for m in job['mora']]==[(0,0),(0,1)] for job in prepared['jobs'])
    assert prepared['jobs'][0]['start']==1000 and prepared['jobs'][0]['end']==3000


def test_alignment_skips_protected_custom_digraph_and_keeps_later_mora_indices():
    from studio_backend.acoustic import plan
    from studio_backend.recalculation import inspect
    old=LyricLine('custom','歌',1000,4000,[Unit('歌',1000,4000,'きょうも',highlights=[Highlight('きょ',1000,2000,'acoustic'),Highlight('う',2000,3000),Highlight('も',3000,4000)])])
    value=split(old,0,0,1,allow_character=True)['line'];prepared=plan(value)
    assert [(m['unit'],m['highlight']) for job in prepared['jobs'] for m in job['mora']]==[(0,2),(0,3)]
    assert prepared['jobs'][0]['start']==2000 and prepared['jobs'][0]['end']==4000
    assert len(inspect(value)['kept'])==2 and not inspect(value)['released']


def test_unprotected_noncanonical_input_is_kept_instead_of_reindexed_as_sound_proof():
    from studio_backend.acoustic import plan
    old=LyricLine('ambiguous','歌',1000,2000,[Unit('歌',1000,2000,'きょ',highlights=[Highlight('き',1000,1500),Highlight('ょ',1500,2000)])])
    with pytest.raises(ValueError,match='自定义'):plan(old)
