import copy
import pytest
from studio_backend.model import LyricLine,Unit
from studio_backend.reading_candidates import dictionary_readings,review


def sample():return LyricLine('lyric','人気の街',1000,3000,[Unit('人気',1000,1800,'にんき'),Unit('の街',1800,3000,'のまち')])


def test_actual_homographs_and_attached_punctuation():
    assert {'にんき','ひとけ'}<={x[0] for x in dictionary_readings('人気')}
    assert {'あした','あす'}<={x[0] for x in dictionary_readings(' 明日、')}
    assert {'いく','ゆく'}<={x[0] for x in dictionary_readings('行く')}


def test_dictionary_lookup_does_not_use_prefix_entries():
    assert 'ひと' not in {x[0] for x in dictionary_readings('人気')}
    assert dictionary_readings('🦄')==()


def test_candidate_sources_are_explained_and_original_kept():
    line=sample();before=copy.deepcopy(line)
    value=review(line,0)
    assert line==before and value['original']==line.to_dict()
    assert value['choices'][0]['kana']=='にんき' and value['choices'][0]['sources'][0]=='current'
    assert next(v for v in value['choices'] if v['kana']=='ひとけ')['sources']==['dictionary_entry']
    assert value['listen']==[820,1980] and '试听' in value['notice']


def test_kanji_recognition_does_not_create_a_phonetic_choice():
    value=review(sample(),0,[LyricLine('asr','人気',1000,1800)],verified=True)
    assert not any('transcript' in x['sources'] for x in value['choices'])
    assert '汉字' in value['notice'] and value['transcript_verified']


def test_kana_transcript_and_unverified_media_are_explicit():
    value=review(sample(),0,[LyricLine('asr','ひとけ',1000,1800)])
    choice=next(x for x in value['choices'] if x['kana']=='ひとけ')
    assert 'transcript' in choice['sources'] and any('未核对' in r for r in choice['reasons'])
    assert '识别文字候选' in value['notice']


def test_other_repeated_verse_is_excluded_and_partial_coverage_not_evidence():
    value=review(sample(),0,[LyricLine('later','ひとけ',10000,10800),LyricLine('short','ひ',1000,1100)])
    assert not any('transcript' in x['sources'] for x in value['choices'])
    assert value['context']==['ひ']


def test_overlapping_recognition_does_not_concatenate_two_readings():
    value=review(sample(),0,[LyricLine('a','ひとけ',1000,1800),LyricLine('b','にんき',1000,1800)])
    assert value['recognized']['overlapping'] and '重叠' in value['notice']
    assert not any('transcript' in x['sources'] for x in value['choices'])


def test_saved_deepseek_suggestion_requires_matching_word_and_nonstale_record():
    line=sample();line.reading_review={'method':'deepseek+transcript','words':[{'text':'人気','suggested':'ひとけ','reason':'上下文中的人影。'}]}
    choice=next(x for x in review(line,0)['choices'] if x['kana']=='ひとけ')
    assert 'deepseek' in choice['sources'] and any('人影' in r for r in choice['reasons'])
    line.reading_review['stale']=True
    assert not any('deepseek' in x['sources'] for x in review(line,0)['choices'])


def test_large_unsplit_word_does_not_run_dictionary_on_ui_thread(monkeypatch):
    import studio_backend.reading_candidates as module
    def fail(_):raise AssertionError('unbounded dictionary work')
    monkeypatch.setattr(module,'word_groups',fail)
    line=LyricLine('long','明'*300,1000,3000,[Unit('明'*300,1000,3000,'あ'*300)])
    value=review(line,0);assert '先分词' in value['notice'] and len(value['choices'])==1


@pytest.mark.parametrize('index',[-1,True,99])
def test_invalid_selection(index):
    with pytest.raises(ValueError):review(sample(),index)
