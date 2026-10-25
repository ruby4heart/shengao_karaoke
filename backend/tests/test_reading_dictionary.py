import copy
import pytest
from studio_backend.reading_dictionary import put,lookup,remove,merge,validate


def test_multiple_sung_readings_and_normalized_punctuation_without_mutation():
    first=put({},'星','ほし','普通读法');before=copy.deepcopy(first)
    second=put(first,'星','せかい','本歌特殊唱法')
    assert first==before and {e['kana'] for e in lookup(second,'星、')}=={'ほし','せかい'}
    assert lookup(second,'星空')==[]


def test_same_word_reading_updates_note_and_explicit_merge():
    first=put({},'今日','きょう','旧备注');other=put({},'今日','きょう','新备注')
    merged=merge(first,other);assert len(merged['entries'])==1 and merged['entries'][0]['note']=='新备注'
    assert first['entries'][0]['note']=='旧备注' and remove(merged,'今日','きょう')['entries']==[]


@pytest.mark.parametrize('kana',['中文','星','abc',''])
def test_dictionary_requires_phonetic_reading(kana):
    with pytest.raises(ValueError):put({},'星',kana)


def test_duplicate_schema_and_invalid_version_rejected():
    value=put({},'今日','きょう');value['entries']*=2
    with pytest.raises(ValueError,match='重复'):validate(value)
    with pytest.raises(ValueError):validate({'version':True,'entries':[]})
    with pytest.raises(ValueError):validate({'version':2,'entries':[]})
