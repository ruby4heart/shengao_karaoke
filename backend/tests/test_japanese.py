import copy
import pytest
from studio_backend.japanese import word_groups,morae,romaji,segment_line
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.matching import match_lyrics


def test_original_spaces_punctuation_and_words_are_authoritative():
    text='  今日 も\t歌う！  '
    groups=word_groups(text)
    assert ''.join(g.text for g in groups)==text
    assert [g.text.strip() for g in groups]==['今日','も','歌う！']
    assert groups[0].kana=='きょう' and groups[0].romaji=='kyou'
    for source in ('今日も歌う','今 日 も 歌 う','きょう も うたう'):
        result=match_lyrics([LyricLine('1',text,0,5000)],[LyricLine('asr',source,1000,3000)])['suggestions'][0]
        assert result['text']==text and ''.join(u['text'] for u in result['units'])==text
        assert [u['text'].strip() for u in result['units']]==['今日','も','歌う！']
        assert result['start']==1000 and result['end']==3000


def test_dictionary_words_and_morae_keep_kanji_groups():
    value,skipped=segment_line(LyricLine('1','今日も歌う',1000,6000),'mora')
    assert not skipped
    assert [u.text for u in value.units]==['今日','も','歌う']
    assert [p.kana for p in value.units[0].highlights]==['きょ','う']
    assert value.kana=='きょうもうたう'
    assert value.romaji=='kyou mo utau'
    assert value.units[0].start==1000 and value.units[-1].end==6000
    assert '|!きょ' in value.karaoke(furigana=True)


def test_segmentation_preserves_word_times_pauses_and_manual_reading():
    line=LyricLine('1','今日も歌う',1000,6000,[Unit('今日',1000,3000,'きょう','kyou',source='manual'),
        Unit('も',3200,4000,'も','mo',source='matched'),Unit('歌う',4200,6000,'うたう','utau',source='matched')])
    value,_=segment_line(line,'mora')
    assert [(u.start,u.end) for u in value.units]==[(1000,3000),(3200,4000),(4200,6000)]
    assert value.units[0].source=='manual'
    value.units[0].highlights[0].end=1800;value.units[0].highlights[1].start=1800
    again,_=segment_line(value,'mora')
    assert again.units[0].highlights==value.units[0].highlights


@pytest.mark.parametrize('kind',['locked','reviewed','unit'])
def test_segment_does_not_overwrite_protected_work(kind):
    line=LyricLine('1','今日も歌う',0,5000)
    if kind=='unit':line.units=[Unit(line.text,0,5000,locked=True)]
    else:setattr(line,kind,True)
    before=copy.deepcopy(line)
    value,skipped=segment_line(line,'mora')
    assert skipped and value==before


def test_morae_and_hepburn_cover_small_kana_sokuon_and_particles():
    assert morae('キャットー')==['きゃ','っ','と','ー']
    assert romaji('まっちゃ')=='matcha'
    assert romaji('しんよう')=="shin'you"
    assert [g.romaji for g in word_groups('君は空へ')]==['kimi','wa','sora','e']


def test_chorus_candidates_include_each_original_position():
    line=LyricLine('1','今日も歌う',0,5000)
    source=[LyricLine('a','今日 も 歌う',1000,3000),LyricLine('b','今日も歌う',10000,12000)]
    result=match_lyrics([line],source)['suggestions'][0]
    assert result['match']['status']=='uncertain'
    assert [(c['start'],c['end']) for c in result['match']['candidates']]==[(1000,3000),(10000,12000)]
    for candidate in result['match']['candidates']:
        assert ''.join(u['text'] for u in candidate['units'])==line.text


def test_confirmed_middle_chorus_anchors_surrounding_verses():
    lines=[LyricLine('a','空を見上げて',0,5000),LyricLine('anchor','君と歌う',10000,12000,reviewed=True),LyricLine('b','夢を抱いて',5000,10000)]
    source=[LyricLine('a','空を見上げて',1000,3000),LyricLine('extra','君と歌う',5000,7000),
            LyricLine('anchor','君と歌う',10000,12000),LyricLine('b','夢を抱いて',15000,17000)]
    values=match_lyrics(lines,source)['suggestions']
    assert values[0]['start']==1000 and values[1]['match']['status']=='protected'
    assert values[1]['start']==10000 and values[2]['start']==15000


def test_llm_reading_can_correct_dictionary_without_destroying_manual_morae():
    from studio_backend.convert import annotation_suggestion
    line=LyricLine('1','明日',1000,3000,[Unit('明日',1000,3000,'あした','ashita',source='matched',
        highlights=[Highlight('あ',1000,1400,'manual'),Highlight('し',1400,2200,'manual'),Highlight('た',2200,3000,'manual')])])
    same=annotation_suggestion(line,{'kana':'あした','romaji':'ashita','translation':'明天','groups':[{'text':'明日','kana':'あした','romaji':'ashita'}]})
    assert same.units[0].highlights==line.units[0].highlights
    changed=annotation_suggestion(line,{'kana':'あす','romaji':'asu','translation':'明天','groups':[{'text':'明日','kana':'あ す','romaji':'asu'}]})
    assert changed.units[0].kana=='あす'
    assert [h.kana for h in changed.units[0].highlights]==['あ','す']
    assert (changed.units[0].start,changed.units[0].end)==(1000,3000)


def test_short_homophonic_reading_is_not_auto_accepted():
    value=match_lyrics([LyricLine('1','今日',0,5000)],[LyricLine('asr','きょう',1000,2000)])['suggestions'][0]
    assert value['match']['method']=='reading' and value['match']['status']=='uncertain'
