import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from shengao.tap_timing import TapDraft


@pytest.fixture
def line():
    return LyricLine('tap','あいう',1000,3000,[Unit('あい',1100,1700,'あい','ai',highlights=[Highlight('あ',1100,1400),Highlight('い',1450,1700)]),
        Unit('う',1900,2500,'う','u',highlights=[Highlight('う',1900,2500)])],translation='保持译文',display_start=700,display_end=4000)


def recorded(line,mode='paired',acknowledge_gaps=False):
    d=TapDraft(line,mode,acknowledge_gaps)
    for t in ([1200,1500,1600,1800,2000,2700] if mode=='paired' else [1200,1500,2000,2700]):d.add(t)
    return d


def test_paired_draft_keeps_real_rests_and_never_mutates_original(line):
    before=line.to_dict();draft=recorded(line);result=draft.candidate()
    assert line.to_dict()==before and draft.original.to_dict()==before
    assert [(h.start,h.end) for u in result.units for h in u.highlights]==[(1200,1500),(1600,1800),(2000,2700)]
    assert (result.start,result.end,result.display_start,result.display_end)==(1000,3000,700,4000)
    assert result.text==line.text and result.translation==line.translation and not result.reviewed
    assert [u.kana for u in result.units]==['あい','う'] and result.units[0].romaji=='ai'
    assert result.units[0].highlights[0].timing_origin['current']==[1200,1500]


def test_continuous_requires_acknowledgement_and_has_shared_boundaries(line):
    with pytest.raises(ValueError,match='连续分界'):TapDraft(line,'continuous')
    d=recorded(line,'continuous',True);assert d.required==4
    assert d.ranges()==[(1200,1500),(1500,2000),(2000,2700)]


@pytest.mark.parametrize('bad',[999,3010,-100])
def test_outside_line_and_incomplete_draft_cannot_apply(line,bad):
    d=TapDraft(line)
    with pytest.raises(ValueError):d.add(bad)
    with pytest.raises(ValueError,match='录满'):d.candidate()
    assert not d.points


def test_order_minimum_duration_missing_and_excess_points(line):
    d=TapDraft(line);d.add(1204);assert d.points==[1200]
    with pytest.raises(ValueError):d.add(1200)
    d.add(1500);d.add(1500);d.add(1800);d.add(2000);d.add(2700)
    assert d.complete
    with pytest.raises(ValueError,match='录满'):d.add(2800)
    assert d.back()==2700 and not d.complete;d.add(2600);assert d.complete


@pytest.mark.parametrize('protection',['line','word','missing'])
def test_locked_or_missing_syllables_are_not_invented(line,protection):
    if protection=='line':line.locked=True
    elif protection=='word':line.units[0].locked=True
    else:line.units[0].highlights=[]
    with pytest.raises(ValueError):TapDraft(line)


@pytest.mark.parametrize('protection',['confirmed','word','syllable'])
def test_old_manual_times_require_explicit_replacement(line,protection):
    if protection=='confirmed':line.reviewed=True
    elif protection=='word':line.units[0].source='manual'
    else:line.units[0].highlights[0].source='manual'
    d=recorded(line)
    with pytest.raises(ValueError,match='人工时间'):d.candidate()
    result=d.candidate(allow_manual=True)
    assert not result.reviewed and line.to_dict()==d.original.to_dict()


def test_fixed_edges_are_preserved_in_comparison_and_applied_candidate(line):
    line.units[0].highlights[0].fixed_edges=['start'];line.units[1].highlights[0].fixed_edges=['end']
    d=recorded(line);assert d.ranges()[0][0]==1100 and d.ranges()[-1][1]==2500
    result=d.candidate();assert result.units[0].highlights[0].start==1100 and result.units[1].highlights[0].end==2500
    assert result.units[0].highlights[0].fixed_edges==['start']


def test_fixed_edge_conflict_never_moves_the_fixed_point(line):
    line.units[0].highlights[1].fixed_edges=['start'];d=recorded(line);before=copy.deepcopy(line)
    with pytest.raises(ValueError,match='冲突'):d.candidate()
    assert line.to_dict()==before.to_dict()


def test_replaying_original_notes_preserves_word_margins_and_confirmation(line):
    line.units[0].start=1000;line.units[0].end=1800;line.units[1].start=1850;line.units[1].end=2800;line.reviewed=True
    d=TapDraft(line)
    for _,_,h in d.notes:d.add(h.start);d.add(h.end)
    assert d.candidate().to_dict()==line.to_dict()
