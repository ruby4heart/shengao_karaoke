"""Ordered context distinguishes repeated text from actual missing singing."""
import copy
import pytest
from studio_backend.model import LyricLine,Unit
from studio_backend.matching import match_lyrics


def row(text,index=0,start=None,end=None,**kwargs):
    return LyricLine(str(index),text,index*5000 if start is None else start,(index+1)*5000 if end is None else end,**kwargs)


def heard(text,start):
    return LyricLine('asr-'+str(start),text,start,start+len(text)*200,
                     [Unit(c,start+i*200,start+(i+1)*200,source='recognition') for i,c in enumerate(text)])


def test_confirmed_anchor_with_no_asr_tokens_still_partitions_repeated_verses():
    lines=[row('君と歌う'),row('間奏の確認',1,start=10000,end=12000,reviewed=True),row('君と歌う',2,start=15000,end=20000)]
    original=copy.deepcopy(lines);values=match_lyrics(lines,[heard('君と歌う',15000)])['suggestions']
    assert values[0]['match']['status']=='unmatched' and values[0]['start']==0
    assert values[1]['start']==10000 and values[1]['end']==12000 and values[1]['match']['status']=='protected'
    assert values[2]['start']==15000 and values[2]['match']['status']=='matched'
    assert lines==original


def test_unique_surrounding_text_resolves_which_repeated_line_is_missing():
    lines=[row('君と歌う'),row('間奏明け',1),row('君と歌う',2)]
    values=match_lyrics(lines,[heard('間奏明け',10000),heard('君と歌う',15000)])['suggestions']
    assert values[0]['match']['status']=='unmatched'
    assert values[1]['match']['status']=='matched' and values[2]['match']['status']=='matched'
    assert values[2]['start']==15000


def test_unassigned_transcript_is_reviewable_without_changing_original_lyrics():
    lines=[row('青い空'),row('遠い夢',1)];source=[heard('青い空',1000),heard('どこまでも',5000),heard('遠い夢',10000)]
    before=copy.deepcopy(source);result=match_lyrics(lines,source)
    review=result['sequence_review'];extra=review['unassigned_transcript']
    assert any(v['text']=='どこまでも' and v['start']==5000 for v in extra)
    assert review['review_required'] and review['evidence']=='transcript_text_not_singing_confirmation'
    assert [v['text'] for v in result['suggestions']]==['青い空','遠い夢'] and source==before


def test_reversed_unique_verses_are_flagged_instead_of_reordering_lyrics():
    lines=[row('青い空まで'),row('遠い夢まで',1)]
    result=match_lyrics(lines,[heard('遠い夢まで',1000),heard('青い空まで',10000)])
    assert [v['text'] for v in result['suggestions']]==[v.text for v in lines]
    assert any(v['kind']=='order_conflict' for v in result['sequence_review']['issues'])
    assert not all(v['match']['status']=='matched' for v in result['suggestions'])


def test_extra_words_inside_a_matched_line_are_not_swallowed_by_its_envelope():
    result=match_lyrics([row('青い空の向こうへ')],[heard('青い空きっとの向こうへ',1000)])
    extra=result['sequence_review']['unassigned_transcript']
    assert any(v['text']=='きっと' for v in extra)
    assert result['suggestions'][0]['text']=='青い空の向こうへ'


def test_alternative_candidates_never_cross_a_confirmed_empty_anchor():
    lines=[row('君と歌う'),row('間奏の確認',1,start=10000,end=12000,locked=True),row('君と歌う',2,start=15000,end=20000)]
    first=match_lyrics(lines,[heard('君と歌う',15000)])['suggestions'][0]
    assert first['match']['status']=='unmatched' and first['match'].get('candidates',[])==[]


def test_two_repeated_sections_resolve_independently_from_unique_context():
    lines=[row('君と歌う',0),row('空を越えたら',1),row('君と歌う',2),row('夢を見つけた',3),row('君と歌う',4)]
    source=[heard('空を越えたら',10000),heard('君と歌う',15000),heard('夢を見つけた',20000),heard('君と歌う',25000)]
    values=match_lyrics(lines,source)['suggestions']
    assert values[0]['match']['status']=='unmatched'
    assert [v['start'] for v in values[1:]]==[10000,15000,20000,25000]
    assert all(v['match']['status']=='matched' for v in values[1:])


def test_human_boundaries_are_not_crossed_by_a_word_that_straddles_the_cut():
    anchor=row('確認済み',1,start=2000,end=3000,reviewed=True)
    source=[LyricLine('asr','君と歌う',1000,2600,[Unit('君と歌う',1000,2600,source='word')])]
    values=match_lyrics([row('君と歌う'),anchor],source)['suggestions']
    assert values[0]['match']['status']=='unmatched' or values[0]['end']<=2000
    assert values[1]['start']==2000 and values[1]['end']==3000


def test_local_scope_limits_issue_list_extras_and_candidate_alternatives():
    result=match_lyrics([row('君と歌う')],[heard('君と歌う',1000),heard('君と歌う',15000)],[14000,17000])
    assert result['suggestions'][0]['start']==15000
    assert not result['sequence_review']['unassigned_transcript']
    assert all(v['start']>=14000 and v['end']<=17000 for v in result['sequence_review']['issues'])


def test_phonetic_matching_does_not_label_the_whole_kana_transcript_as_extra():
    line=row('今日も歌う');line.units=[Unit('今日も歌う',0,5000,'きょうもうたう')]
    result=match_lyrics([line],[heard('きょうもうたう',1000)])
    assert result['suggestions'][0]['match']['method']=='reading'
    assert result['sequence_review']['unassigned_transcript']==[]


def test_original_spaces_grouping_readings_and_transcript_remain_unchanged():
    import json
    line=row('君 と歌う');line.units=[Unit('君 ',0,1000,'きみ','kimi'),Unit('と歌う',1000,5000,'とうたう','to-utau')]
    source=[heard('君と 歌う',1000)];before=copy.deepcopy((line,source))
    result=match_lyrics([line],source);value=LyricLine.from_dict(result['suggestions'][0])
    assert [u.text for u in value.units]==['君 ','と歌う']
    assert [u.kana for u in value.units]==['きみ','とうたう'] and (line,source)==before
    assert json.loads(json.dumps(result,allow_nan=False))==result


@pytest.mark.parametrize('kind',['word','mora','word-lock'])
def test_unconfirmed_human_times_are_kept_as_context_until_explicit_replacement(kind):
    from studio_backend.model import Highlight
    middle=row('間奏の確認',1,start=10000,end=12000)
    middle.units=[Unit(middle.text,10000,12000,'かくにん')]
    if kind=='word':middle.units[0].source='manual'
    elif kind=='mora':middle.units[0].highlights=[Highlight('かくにん',10000,12000,'manual')]
    else:middle.units[0].locked=True
    lines=[row('君と歌う'),middle,row('君と歌う',2,start=15000,end=20000)]
    values=match_lyrics(lines,[heard('君と歌う',15000)])['suggestions']
    assert values[0]['match']['status']=='unmatched' and values[2]['start']==15000
    assert values[1]['match']['status']=='protected'
    assert {k:v for k,v in values[1].items() if k!='match'}=={k:v for k,v in middle.to_dict().items() if k!='match'}
    explicit=match_lyrics([middle],[heard(middle.text,15000)],[14000,17000],replace_manual=True)['suggestions'][0]
    assert explicit['match']['status']==('protected' if kind=='word-lock' else 'matched')


def test_reversed_sections_do_not_mark_unaffected_outer_context_as_uncertain():
    texts=['前奏を越えて','青い空まで','遠い夢まで','終わりの歌声']
    result=match_lyrics([row(t,i) for i,t in enumerate(texts)],[heard(texts[i],1000+j*5000) for j,i in enumerate([0,2,1,3])])
    assert result['suggestions'][0]['match']['status']=='matched' and result['suggestions'][-1]['match']['status']=='matched'
    assert next(v for v in result['sequence_review']['issues'] if v['kind']=='order_conflict')['line_ids']==['1','2']


def test_sub_millisecond_character_estimates_are_not_false_extra_words():
    text='あ'*120;line=row(text)
    source=[LyricLine('asr',text,1000,1010,[Unit(text,1000,1010,source='word')])]
    result=match_lyrics([line],source)
    assert result['suggestions'][0]['match']['status']=='matched'
    assert result['sequence_review']['unassigned_transcript']==[]


@pytest.mark.parametrize('operation',['manual_boundary','shift','stretch'])
def test_manually_placed_unsegmented_line_is_preserved_without_unit_flags(operation):
    from studio_backend.provenance import create
    line=row('君と歌う',start=1000,end=3000)
    line.timing_origin=create('estimated',1000,3000);line.timing_origin['operations']=[operation]
    source=[heard(line.text,15000)]
    kept=match_lyrics([line],source)['suggestions'][0]
    assert kept['match']['status']=='protected' and (kept['start'],kept['end'])==(1000,3000) and kept['units']==[]
    replaced=match_lyrics([line],source,[14000,17000],replace_manual=True)['suggestions'][0]
    assert replaced['match']['status']=='matched' and replaced['start']==15000
