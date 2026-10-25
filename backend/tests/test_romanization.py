import copy
import pytest
from studio_backend.model import Unit,LyricLine,Highlight
from studio_backend.romanization import DEFAULT,romanize,automatic,set_manual,apply_rules,state
from studio_backend.reading_change import preview


@pytest.mark.parametrize('reading,hepburn,kunrei',[('しちつふ','shichitsufu','sitituhu'),('しゃしゅしょ','shashusho','syasyusyo'),('まっちゃ','matcha','mattya'),('しんよう',"shin'you","sin'you"),('コーヒー','koohii','koohii')])
def test_selectable_spelling(reading,hepburn,kunrei):
    assert romanize(reading)==hepburn and romanize(reading,{**DEFAULT,'system':'kunrei'})==kunrei


def test_dictionary_long_vowels_and_particle_pronunciations_are_contextual():
    assert automatic(Unit('東京',0,1000,'とうきょう'),{**DEFAULT,'long_vowels':'macron'})=='tōkyō'
    assert automatic(Unit('思う',0,1000,'おもう'),{**DEFAULT,'long_vowels':'macron'})=='omou'
    assert automatic(Unit('は',0,1000,'は'))=='wa'
    assert automatic(Unit('は',0,1000,'は'),{**DEFAULT,'particles':False})=='ha'
    assert automatic(Unit('星',0,1000,'せかい'))=='sekai'


def sample():return LyricLine('roman','星',1000,2000,[Unit('星',1000,2000,'ほし','hoshi',highlights=[Highlight('ほ',1000,1400,'manual'),Highlight('し',1400,2000,'manual')])],reviewed=True)


def test_manual_override_preserved_on_kana_change_and_reset_is_explicit():
    old=set_manual(sample(),0,'ho-shi');before=copy.deepcopy(old);value=preview(old,0,'せか')['line']
    assert old==before and value.units[0].romaji=='ho-shi' and value.units[0].reading_options['romaji']['basis']=='ほし'
    kept=apply_rules(value,[0],DEFAULT);assert kept['kept'] and kept['line'].units[0].romaji=='ho-shi'
    reset=apply_rules(value,[0],DEFAULT,True);assert reset['line'].units[0].romaji=='seka' and reset['line'].units[0].reading_options['romaji']['mode']=='auto'


def test_romanization_display_rules_keep_time_kana_and_confirmation():
    old=sample();result=apply_rules(old,[0],{**DEFAULT,'system':'kunrei'},True)['line']
    assert result.units[0].romaji=='hosi' and result.reviewed and result.units[0].kana==old.units[0].kana and result.units[0].highlights==old.units[0].highlights
    assert state(set_manual(old,0,'hō-shi').units[0])['mode']=='manual'


def test_legacy_handwritten_value_not_silently_overwritten_and_lock_kept():
    old=sample();old.units[0].romaji='Hoshi!';assert state(old.units[0])['mode']=='legacy'
    assert apply_rules(old,[0],DEFAULT)['kept']
    old.units[0].locked=True;assert apply_rules(old,[0],DEFAULT,True)['kept'][0]['reason']=='已锁定'


def test_manual_romanization_rejects_kanji_but_allows_blank_override():
    with pytest.raises(ValueError):set_manual(sample(),0,'星')
    assert set_manual(sample(),0,'').units[0].reading_options['romaji']['mode']=='manual'
