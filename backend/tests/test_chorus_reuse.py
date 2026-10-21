import copy
import pytest
from studio_backend.chorus_reuse import prepare,reference_matches
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.provenance import create


def fixture():
    source=LyricLine('source','君と歌う',1000,6000,[Unit('君と',1000,2000,'キミト','Kimi-to',source='manual',locked=True),
        Unit('歌う',2000,6000,'ウタウ','UTAU!',source='manual')],kana='キミトウタウ',romaji='Kimi-to UTAU!',reviewed=True)
    target=LyricLine('target','君と歌う',15000,21000,[Unit('君',15000,16500,'きみ','kimi',reading_source='dictionary'),
        Unit('と歌う',16500,21000,'とうたう','to-utau',reading_source='dictionary')],translation='保留本段译文',display_start=14800,display_end=21400)
    return source,target


def test_source_segmentation_and_katakana_are_reused_without_source_axis_or_flags():
    source,target=fixture();before=copy.deepcopy((source,target));value=prepare(source,target,True)
    assert [u.text for u in value.units]==['君と','歌う'] and [u.kana for u in value.units]==['キミト','ウタウ']
    assert value.romaji=='Kimi-to UTAU!' and value.kana==source.kana and value.translation==target.translation
    assert (value.start,value.end,value.display_start,value.display_end)==(15000,21000,14800,21400)
    assert all(15000<=u.start<=u.end<=21000 and not u.locked and u.source=='estimated' for u in value.units)
    assert all(h.source=='estimated' and h.timing_origin['kind']=='estimated' for u in value.units for h in u.highlights)
    assert ''.join(h.kana for u in value.units for h in u.highlights)==source.kana and not value.reviewed
    assert not value.timing_evidence and value.reading_review['reuse']['timing_copied'] is False and (source,target)==before


@pytest.mark.parametrize('kind',['line-lock','word-lock','reviewed','word-time','mora-time','line-time','reading','reading-check'])
def test_existing_target_human_work_is_protected(kind):
    source,target=fixture();reading=False
    if kind=='line-lock':target.locked=True
    elif kind=='word-lock':target.units[0].locked=True
    elif kind=='reviewed':target.reviewed=True
    elif kind=='word-time':target.units[0].source='manual'
    elif kind=='mora-time':target.units[0].highlights=[Highlight(target.units[0].kana,15000,16500,'manual')]
    elif kind=='line-time':target.timing_origin=create('manual',15000,21000)
    elif kind=='reading':target.units[0].reading_source='manual'
    else:reading=True
    before=copy.deepcopy(target)
    with pytest.raises(ValueError,match='保留'):prepare(source,target,True,reading)
    assert target==before


@pytest.mark.parametrize('kind',['unconfirmed-reading','unconfirmed-time','empty-groups','wrong-kana'])
def test_source_must_have_confirmed_consistent_segmentation_and_reading(kind):
    source,target=fixture();reading=True
    if kind=='unconfirmed-reading':reading=False
    elif kind=='unconfirmed-time':source.reviewed=False
    elif kind=='empty-groups':source.units=[]
    else:source.kana='ちがう'
    with pytest.raises(ValueError):prepare(source,target,reading)


def test_real_original_spaces_are_not_normalized_away_to_force_reuse():
    source,target=fixture();target.text='君 と歌う';target.units=[]
    with pytest.raises(ValueError,match='空格'):prepare(source,target,True)


def test_reuse_reference_stops_matching_after_source_changes_or_confirmation_is_removed():
    source,target=fixture();value=prepare(source,target,True);reference=value.reading_review['reuse']
    assert reference_matches(reference,source,True) and not reference_matches(reference,source,False)
    source.units[0].romaji='changed';assert not reference_matches(reference,source,True)
