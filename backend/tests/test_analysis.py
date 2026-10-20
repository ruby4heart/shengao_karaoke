import asyncio
import copy
import pytest
from studio_backend.analysis import analyze_line,smooth_gaps,annotation_input
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.api import validate_annotations,ApiError
from studio_backend import worker,api


def lyric():
    return LyricLine('1','明日も',1000,3000,[Unit('明日',1000,2000,'あした','ashita',source='matched'),Unit('も',2050,3000,'も','mo',source='matched')])


def test_timed_kana_recognition_corrects_polyphonic_kanji_without_changing_lyrics():
    original=lyric();before=copy.deepcopy(original)
    asr=[LyricLine('asr','あす も',1000,3000,[Unit('あす ',1000,2000),Unit('も',2050,3000)])]
    value,skip=analyze_line(original,asr)
    assert not skip and original==before and value.text=='明日も'
    assert value.units[0].kana=='あす' and value.units[0].reading_source=='transcript'
    assert value.units[0].end==value.units[1].start==2030
    assert value.reading_review['words'][0]['before']=='あした'
    assert value.reading_review['words'][0]['basis']=='transcript'
    assert value.reading_review['requires_review'] and value.match==original.match


def test_same_kanji_asr_is_not_claimed_to_be_phonetic_evidence():
    value,_=analyze_line(lyric(),[LyricLine('asr','明日も',1000,3000)])
    assert value.units[0].kana=='あした'
    assert value.reading_review['words'][0]['basis']=='dictionary'


def test_wrong_chorus_and_cross_word_asr_tokens_cannot_replace_readings():
    for asr in ([LyricLine('asr','あす',10000,11000)],
                [LyricLine('asr','あすも',1000,3000,[Unit('あすも',1000,3000)])]):
        value,_=analyze_line(lyric(),asr)
        assert value.units[0].kana=='あした'


@pytest.mark.parametrize('kind',['manual','legacy'])
def test_manual_readings_and_highlights_are_preserved(kind):
    original=lyric();unit=original.units[0]
    unit.highlights=[Highlight('あ',1000,1300,'manual'),Highlight('し',1400,1700,'manual'),Highlight('た',1700,2000,'manual')]
    if kind=='manual':unit.reading_source='manual'
    else:unit.source='manual'
    value,_=analyze_line(original,[LyricLine('asr','あす',1000,2000)],preserve_legacy=True)
    assert value.units[0].kana==unit.kana and value.units[0].highlights==unit.highlights
    assert value.units[0].start==unit.start and value.units[0].end==unit.end
    assert value.reading_review['words'][0]['basis']=='manual'


@pytest.mark.parametrize('kind',['locked','unit'])
def test_protected_lines_do_not_change(kind):
    original=lyric()
    if kind=='unit':original.units[0].locked=True
    else:setattr(original,kind,True)
    value,skip=analyze_line(original,[])
    assert skip and value==original


def test_short_gaps_close_but_long_rests_and_manual_edges_do_not():
    original=LyricLine('1','歌うよ',0,3000,[Unit('歌',0,800),Unit('う',900,1200),Unit('よ',1600,3000)])
    value,count=smooth_gaps(original)
    assert count==1 and value.units[0].end==value.units[1].start==850
    assert value.units[2].start==1600 and original.units[0].end==800
    original.units[0].highlights=[Highlight('うた',0,800,'manual')];original.units[0].kana='うた'
    value,count=smooth_gaps(original)
    assert not count and value==original


@pytest.mark.parametrize('threshold',[-1,501,True,2.5])
def test_gap_threshold_is_validated(threshold):
    with pytest.raises(ValueError):smooth_gaps(lyric(),threshold)


def test_llm_payload_contains_original_groups_recognition_and_neighboring_lyrics():
    payload=annotation_input(lyric(),[LyricLine('asr','あすも',1000,3000)],('君と','歌う'))
    assert [g['text'] for g in payload['groups']]==['明日','も']
    assert payload['groups'][0]['dictionary']=='あした'
    assert payload['recognition'][0]['text']=='あすも'
    assert payload['previous_lyric']=='君と' and payload['next_lyric']=='歌う'


@pytest.mark.parametrize('bad',['明日','あす明','ashita'])
def test_llm_cannot_return_kanji_or_chinese_as_kana(bad):
    output={'lines':[{'id':'1','kana':bad,'romaji':'asu','translation':'明天','groups':[{'text':'明日','kana':bad,'romaji':'asu'}]}]}
    with pytest.raises(ApiError,match='假名'):validate_annotations(output,[{'id':'1','text':'明日'}])


def test_llm_cannot_resegment_the_original_word_groups():
    output={'lines':[{'id':'1','kana':'あすも','romaji':'asu mo','translation':'明天也','groups':[{'text':'明日も','kana':'あすも','romaji':'asu mo'}]}]}
    with pytest.raises(ApiError,match='分词边界'):validate_annotations(output,[{'id':'1','text':'明日も','groups':[{'text':'明日'},{'text':'も'}]}])


def test_refinement_without_keys_uses_only_local_dictionary_and_asr(tmp_path):
    result=asyncio.run(worker.operation({'action':'refine','lines':[lyric().to_dict()],'transcript':[LyricLine('asr','あす',1000,2000).to_dict()]},tmp_path,lambda *_:None))
    assert result['local'] and result['transcript_used']
    assert result['suggestions'][0]['units'][0]['kana']=='あす'


def test_legacy_manually_timed_word_without_reading_can_still_get_kana():
    original=LyricLine('1','歌',1000,2000,[Unit('歌',1000,2000,source='manual')])
    value,_=analyze_line(original,[])
    assert value.units[0].kana=='うた' and value.units[0].start==1000 and value.units[0].end==2000


def test_missing_particle_reading_gets_spoken_romaji():
    original=LyricLine('1','は',1000,2000,[Unit('は',1000,2000)])
    value,_=analyze_line(original,[])
    assert value.units[0].romaji=='wa'


def test_confirmed_timing_still_allows_reading_review_but_never_closes_gaps():
    original=lyric();original.reviewed=True
    value,skip=analyze_line(original,[LyricLine('asr','あす',1000,2000)])
    assert not skip and value.units[0].kana=='あす'
    assert value.units[0].end==2000 and value.units[1].start==2050
    assert not value.reviewed
    again,_=analyze_line(value,[])
    assert again.units[0].end==2000 and again.units[1].start==2050


def test_legacy_unknown_readings_can_receive_review_only_candidates_without_moving_manual_time():
    original=lyric();original.units[0].source='manual'
    value,_=analyze_line(original,[LyricLine('asr','あす',1000,2000)])
    assert value.units[0].kana=='あす' and value.units[0].source=='manual'
    assert value.units[0].end==2000 and value.units[1].start==2050
    assert value.reading_review['words'][0]['legacy']


def test_explicit_manual_reading_override_is_opt_in_and_keeps_manual_time():
    original=lyric();original.units[0].reading_source='manual';original.units[0].source='manual'
    heard=[LyricLine('asr','あす',1000,2000)]
    kept,_=analyze_line(original,heard)
    revised,_=analyze_line(original,heard,preserve_manual=False)
    assert kept.units[0].kana=='あした' and revised.units[0].kana=='あす'
    assert revised.units[0].start==1000 and revised.units[0].end==2000 and revised.units[1].start==2050


def test_existing_kana_gets_missing_romaji_offline_without_moving_timing():
    original=LyricLine('1','今日',1000,3000,[Unit('今日',1000,3000,'きょう')])
    value,_=analyze_line(original,[])
    assert value.units[0].romaji=='kyou' and value.reading_review['words'][0]['before_romaji']==''
    assert value.units[0].start==1000 and value.units[0].end==3000


def test_invalid_kanji_kana_gets_dictionary_candidate_instead_of_repeating_kanji():
    original=LyricLine('1','今日',1000,3000,[Unit('今日',1000,3000,'今日')])
    value,_=analyze_line(original,[])
    assert value.units[0].kana=='きょう' and value.reading_review['words'][0]['basis']=='dictionary'


def test_llm_review_can_run_after_timing_confirmation_without_rewriting_word_times(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.Settings,'key',lambda *_:'mock-key')
    calls=[]
    async def annotate(lines,*args,**kwargs):
        calls.append(lines)
        return [{'id':'1','kana':'あすも','romaji':'asu mo','translation':'明天也','groups':[{'text':'明日','kana':'あす','romaji':'asu'},{'text':'も','kana':'も','romaji':'mo'}]}]
    monkeypatch.setattr(api,'deepseek_annotate',annotate)
    original=lyric();original.reviewed=True
    result=asyncio.run(worker.operation({'action':'refine','lines':[original.to_dict()],'use_llm':True},tmp_path,lambda *_:None))
    assert len(calls)==1
    words=result['suggestions'][0]['units']
    assert words[0]['kana']=='あす' and words[0]['end']==2000 and words[1]['start']==2050
    note=result['suggestions'][0]['reading_review']['words'][0]
    assert note['suggested_romaji']=='asu' and note['changed'] and note['basis']=='deepseek'


def test_alignment_returns_original_words_with_precise_outer_character_edges():
    from studio_backend.analysis import aligned_words
    original=LyricLine('1','今日も',0,3000,[Unit('今日',0,2000,'きょう','kyou'),Unit('も',2000,3000,'も','mo')])
    characters=LyricLine('1','今日も',1000,3000,[Unit('今',1000,1400),Unit('日',1450,2000),Unit('も',2050,3000)])
    value=aligned_words(characters,original)
    assert [u.text for u in value.units]==['今日','も'] and (value.units[0].start,value.units[0].end)==(1000,2000)
    assert [h.kana for h in value.units[0].highlights]==['きょ','う']


def test_matching_closes_short_asr_gaps_only_on_suggestions(tmp_path):
    original=LyricLine('1','今日も',0,3000)
    asr=LyricLine('asr','今日も',1000,3000,[Unit('今日',1000,2000),Unit('も',2050,3000)])
    result=asyncio.run(worker.operation({'action':'match','lines':[original.to_dict()],'transcript':[asr.to_dict()]},tmp_path,lambda *_:None))
    assert result['closed_gaps']==1
    assert result['suggestions'][0]['units'][0]['end']==result['suggestions'][0]['units'][1]['start']
    assert result['transcript'][0]['units'][0]['end']==2000


def test_refinement_batches_are_cached_and_partial_api_failure_keeps_completed_results(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.Settings,'key',lambda *_:'mock-key')
    calls=[]
    async def annotate(lines,*args,**kwargs):
        calls.append(lines)
        if len(calls)==2:raise ApiError('mock interrupted')
        return [{'id':line['id'],'kana':'うた','romaji':'uta','translation':'歌','groups':[{'text':'歌','kana':'うた','romaji':'uta','reason':'mock'}]} for line in lines]
    monkeypatch.setattr(api,'deepseek_annotate',annotate)
    lines=[LyricLine(str(i),'歌',i*1000,i*1000+900).to_dict() for i in range(31)]
    request={'action':'refine','lines':lines,'use_llm':True,'context':lines}
    result=asyncio.run(worker.operation(request,tmp_path,lambda *_:None))
    assert result['partial'] and result['completed_lines']==30 and len(result['suggestions'])==30
    assert len(calls)==2 and len(calls[0])==30
    again=asyncio.run(worker.operation(request,tmp_path,lambda *_:None))
    assert len(calls)==3 and len(calls[-1])==1 and len(again['suggestions'])==31
