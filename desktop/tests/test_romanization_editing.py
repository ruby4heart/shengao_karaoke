from studio_backend.model import Unit,LyricLine
from studio_backend.romanization import DEFAULT,set_manual,apply_rules
from studio_backend.convert import annotation_suggestion
from shengao.timing import edit_reading


def line():return LyricLine('r','星',1000,2000,[Unit('星',1000,2000,'ほし','hoshi',reading_source='dictionary')],reviewed=True)


def test_direct_kana_edit_preserves_explicit_roman_override_and_basis():
    old=set_manual(line(),0,'HOSHI');value=edit_reading(old,0,'せかい')
    assert value.units[0].romaji=='HOSHI' and value.units[0].reading_options['romaji']['basis']=='ほし'


def test_direct_roman_override_has_its_own_source_and_does_not_retime():
    old=line();value=edit_reading(old,0,'ほし','ho-shi')
    assert value.reviewed and value.units[0].reading_source=='dictionary' and value.units[0].reading_options['romaji']['mode']=='manual'
    assert (value.start,value.end,value.units[0].start,value.units[0].end)==(1000,2000,1000,2000)


def test_text_model_cannot_overwrite_manual_roman_value():
    old=set_manual(line(),0,'HOSHI');value=annotation_suggestion(old,{'groups':[{'text':'星','kana':'せかい','romaji':'sekai'}],'translation':'世界'},DEFAULT)
    assert value.units[0].kana=='せかい' and value.units[0].romaji=='HOSHI'
    assert value.units[0].reading_options['romaji']['basis']=='ほし'


def test_automatic_rule_survives_subsequent_kana_edit():
    old=apply_rules(line(),[0],{**DEFAULT,'system':'kunrei'},True)['line'];value=edit_reading(old,0,'しほ')
    assert value.units[0].romaji=='siho' and value.units[0].reading_options['romaji']['system']=='kunrei'
