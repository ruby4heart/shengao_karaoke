import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.provenance import create,describe
from studio_backend.reading_change import preview


def sample(source='manual'):
    parts=[Highlight(k,a,b,source) for k,a,b in [('に',1000,1100),('ん',1210,1400),('き',1400,1800)]]
    return LyricLine('line','人気の街',900,3000,[Unit('人気',1000,1800,'にんき',highlights=parts),Unit('の街',1900,3000,'のまち')],reviewed=True)


def test_same_number_keeps_irregular_manual_boundaries_and_neighbor():
    line=sample();line.units[0].highlights[1].fixed_edges=['start'];before=copy.deepcopy(line)
    result=preview(line,0,'ひとけ');candidate=result['line']
    assert line==before and not candidate.reviewed and candidate.units[1]==line.units[1]
    assert [(h.start,h.end,h.source,h.fixed_edges) for h in candidate.units[0].highlights]==[(h.start,h.end,h.source,h.fixed_edges) for h in line.units[0].highlights]
    assert ''.join(h.kana for h in candidate.units[0].highlights)=='ひとけ' and result['kept_boundaries']
    assert (candidate.start,candidate.end)==(line.start,line.end)


def test_changed_reading_retains_old_acoustic_reading_as_reference():
    line=sample('acoustic')
    for h in line.units[0].highlights:h.timing_origin=create('acoustic',h.start,h.end,'tifa','mora',h.kana)
    result=preview(line,0,'ひとけ')['line'];part=result.units[0].highlights[0]
    assert part.timing_origin['reading']=='に' and part.kana=='ひ'
    assert any('旧读音' in v for v in describe(part,result,0,0)['issues'])


def test_changed_count_cannot_discard_manual_or_fixed_axis():
    line=sample()
    with pytest.raises(ValueError,match='旧轴保持'):preview(line,0,'にき')
    line=sample('estimated');line.units[0].highlights[0].fixed_edges=['start']
    with pytest.raises(ValueError,match='旧轴保持'):preview(line,0,'にき')


def test_changed_count_estimate_keeps_word_envelope_and_other_word():
    line=sample('estimated');result=preview(line,0,'にき');candidate=result['line']
    assert not result['kept_boundaries'] and result['after_count']==2
    assert (candidate.units[0].start,candidate.units[0].end)==(1000,1800)
    assert candidate.units[1]==line.units[1] and all(h.source=='estimated' for h in candidate.units[0].highlights)


def test_old_bulk_protection_is_not_mistaken_for_individual_human_boundaries():
    line=sample('manual')
    for h in line.units[0].highlights:h.timing_origin=create('estimated',h.start,h.end,method='mora_distribution')
    assert preview(line,0,'にき')['changed']


def test_same_reading_is_noop_and_locks_are_respected():
    line=sample();assert preview(line,0,line.units[0].kana)['line']==line
    line.units[0].locked=True
    with pytest.raises(ValueError,match='锁定'):preview(line,0,'ひとけ')


@pytest.mark.parametrize('kana',['中文','人気','abc',''])
def test_invalid_phonetic_choice(kana):
    with pytest.raises(ValueError,match='假名'):preview(sample(),0,kana)
