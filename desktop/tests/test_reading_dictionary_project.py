import pytest
from shengao.project import Project,save_project,load_project
from studio_backend.reading_dictionary import put
from studio_backend.model import LyricLine,Unit
from studio_backend.reading_candidates import review


def test_song_dictionary_roundtrip_and_legacy_format_refuses_new_data(tmp_path):
    p=Project(reading_dictionary=put({},'星','せかい','本歌特殊唱法'));path=tmp_path/'本歌词典.sgproj';save_project(p,path)
    assert load_project(path).to_dict()==p.to_dict() and p.to_dict()['version']==12
    old=p.to_dict();old['version']=11
    with pytest.raises(ValueError,match='第 12 版'):Project.from_dict(old)
    old['reading_dictionary']={};assert Project.from_dict(old).reading_dictionary=={}


def test_song_and_personal_readings_are_distinct_selectable_sources():
    line=LyricLine('lyric','星',1000,2000,[Unit('星',1000,2000,'ほし')]);before=line.to_dict()
    value=review(line,0,song_dictionary=put({},'星','せかい','この歌の当て字'),personal_dictionary=put({},'星','あかり','人名'))
    assert next(x for x in value['choices'] if x['kana']=='せかい')['sources']==['song_dictionary']
    assert next(x for x in value['choices'] if x['kana']=='あかり')['sources']==['personal_dictionary']
    assert line.to_dict()==before and value['choices'][0]['kana']=='ほし'
