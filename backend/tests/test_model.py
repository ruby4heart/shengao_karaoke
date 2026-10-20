import pytest
from studio_backend.model import LyricLine,Unit,align_characters,estimated_units,plain_ass
from studio_backend.convert import annotation_suggestion,eleven_lines,mai_lines
from studio_backend.api import validate_annotations,ApiError
from studio_backend.model import Highlight


def test_karaoke_absolute_boundaries_and_gap():
    line=LyricLine('1','今日も',1000,3000,[Unit('今日',1200,2400,kana='きょう'),Unit('も',2600,3000,kana='も')])
    assert line.karaoke()==r'{\k20}{\kf120}今日{\k20}{\kf40}も'
    assert '|!きょう' in line.karaoke(furigana=True)


def test_validation_rejects_changed_lyrics_and_overlaps():
    with pytest.raises(ValueError,match='原歌词'):
        LyricLine('1','今日',0,1000,[Unit('明日',0,1000)]).validate()
    with pytest.raises(ValueError,match='重叠'):
        LyricLine('1','あい',0,1000,[Unit('あ',0,800),Unit('い',700,1000)]).validate()


def test_estimates_are_marked_and_small_kana_grouped():
    units=estimated_units('きょう',0,900)
    assert [u.text for u in units]==['きょ','う']
    assert all(u.source=='estimated' for u in units)
    assert units[-1].end==900


def test_alignment_coverage_and_offset():
    units=align_characters('今日',[{'text':'今','start':0,'end':.5},{'text':'日','start':.5,'end':1}],5000)
    assert units[0].start==5000 and units[-1].end==6000
    with pytest.raises(ValueError,match='不一致'):
        align_characters('今日',[{'text':'明','start':0,'end':1}])


def test_llm_cannot_change_source_text():
    source=[{'id':'1','text':'今日も'}]
    annotation={'id':'1','kana':'きょうも','romaji':'kyou mo','translation':'今天也',
                'groups':[{'text':'今日','kana':'きょう','romaji':'kyou'},{'text':'も','kana':'も','romaji':'mo'}]}
    assert validate_annotations({'lines':[annotation]},source)[0]['groups'][0]['text']=='今日'
    annotation['groups'][0]['text']='明日'
    with pytest.raises(ApiError,match='原歌词'):
        validate_annotations({'lines':[annotation]},source)


@pytest.mark.parametrize('source',['estimated','manual','mapped','word'])
def test_reading_suggestion_preserves_matching_boundaries(source):
    line=LyricLine('1','今日も',1000,3000,[Unit('今日',1000,2400,source=source),Unit('も',2400,3000)])
    result=annotation_suggestion(line,{'kana':'きょうも','romaji':'kyou mo','translation':'今天也',
                'groups':[{'text':'今日','kana':'きょう','romaji':'kyou'},{'text':'も','kana':'も','romaji':'mo'}]})
    assert result.units[1].start==2400
    assert result.units[0].source==source
    assert line.kana==''  # suggestions don't mutate the current project


def test_recognition_retains_punctuation_and_whitespace():
    result=eleven_lines({'text':'Hello world!', 'words':[{'type':'word','text':'Hello','start':0,'end':.3},
                       {'type':'spacing','text':' '},{'type':'word','text':'world!','start':.4,'end':1}]})
    assert result[0].text=='Hello world!'
    assert result[0].units[0].source=='word'
    result=mai_lines({'phrases':[{'text':'今日、歌う。','offsetMilliseconds':0,'durationMilliseconds':1000,
        'words':[{'text':'今日','offsetMilliseconds':0,'durationMilliseconds':400},
                 {'text':'歌う','offsetMilliseconds':500,'durationMilliseconds':500}]}]})
    assert result[0].text=='今日、歌う。'


def test_ass_user_text_is_literal():
    line=LyricLine('1',r'{\p1}text',0,1000)
    assert r'{\p1}' not in line.karaoke()
    assert plain_ass(r'{\kf20}今日\N歌')=='今日\n歌'


def test_annotation_mapping_keeps_silent_gaps():
    line=LyricLine('1','歌う',0,2000,[Unit('歌',0,800),Unit('う',1200,2000)])
    result=annotation_suggestion(line,{'kana':'うたう','romaji':'utau','translation':'歌唱',
        'groups':[{'text':'歌','kana':'うた','romaji':'uta'},{'text':'う','kana':'う','romaji':'u'}]})
    assert result.units[0].end==800
    assert result.units[1].start==1200


def test_one_kanji_group_supports_multiple_sung_morae():
    unit=Unit('今日',1000,3000,kana='きょう',highlights=[Highlight('きょ',1000,1800),Highlight('う',1800,3000)])
    line=LyricLine('1','今日',1000,3000,[unit])
    line.validate()
    assert line.karaoke(furigana=True)==r'{\kf80}今日|!きょ{\kf120}#|う'
    restored=LyricLine.from_dict(line.to_dict())
    assert restored.units[0].highlights[1].start==1800
    assert restored.text=='今日'
