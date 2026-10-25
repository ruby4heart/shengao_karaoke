import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.reading_options import set_ruby,validate_ruby


def line(text='抱きしめて',kana='だきしめて'):
    return LyricLine('ruby',text,1000,3000,[Unit(text,1000,3000,kana,highlights=[Highlight(kana,1000,3000,'manual',fixed_edges=['start'])])],reviewed=True)


def test_custom_okurigana_map_only_changes_visual_correspondence():
    old=line();before=copy.deepcopy(old);value=set_ruby(old,0,{'mode':'custom','spans':[[0,1,0,1]]})
    assert old==before and value.units[0].reading_options['ruby']['spans']==[[0,1,0,1]]
    assert value.reviewed and value.units[0].highlights==old.units[0].highlights and value.text==old.text


def test_whole_compound_and_return_to_auto():
    old=line('今日','きょう');whole=set_ruby(old,0,{'mode':'whole'})
    assert whole.units[0].reading_options=={'ruby':{'mode':'whole'}}
    assert set_ruby(whole,0,{'mode':'auto'}).units[0].reading_options=={}


@pytest.mark.parametrize('spans',[[[0,1,0,1]],[[0,2,0,2]],[[0,2,0,4]],[[1,3,0,3]],[[0,2,0,3],[0,1,0,1]]])
def test_invalid_compound_ranges_cannot_split_mora_or_lose_reading(spans):
    with pytest.raises(ValueError):validate_ruby({'mode':'custom','spans':spans},'今日','きょう')


def test_complete_compound_and_two_kanji_parts_validate():
    validate_ruby({'mode':'custom','spans':[[0,2,0,3]]},'今日','きょう')
    validate_ruby({'mode':'custom','spans':[[1,2,1,3],[2,3,3,5]]},'お星様','おほしさま')


def test_new_fields_empty_are_not_added_to_legacy_task_line_dict():
    old=line();assert 'reading_options' not in old.to_dict()['units'][0]
    mapped=set_ruby(old,0,{'mode':'off'});restored=LyricLine.from_dict(mapped.to_dict())
    assert restored.to_dict()==mapped.to_dict()


def test_locked_mapping_preserved():
    old=line();old.units[0].locked=True
    with pytest.raises(ValueError,match='锁定'):set_ruby(old,0,{'mode':'whole'})
