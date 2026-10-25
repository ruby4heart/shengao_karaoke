import copy
from studio_backend.worker import timing_result
from studio_backend.model import LyricLine,Unit
from studio_backend.romanization import DEFAULT,set_manual
from studio_backend.reading_options import set_ruby
from studio_backend.chorus_reuse import prepare


def line():return LyricLine('default','星',1000,2000,[Unit('星',1000,2000,'ほし','hoshi',reading_source='dictionary')])


def test_matching_and_candidate_choices_use_new_word_default_without_touching_raw_transcript():
    value=line().to_dict();value['match']={'status':'matched','candidates':[{'start':1000,'end':2000,'units':copy.deepcopy(value['units'])}]}
    raw=[{'text':'untouched'}];result=timing_result({'suggestions':[value],'transcript':raw},{'action':'match','romanization_rules':{**DEFAULT,'system':'kunrei'}})
    assert result['suggestions'][0]['units'][0]['romaji']=='hosi'
    assert result['suggestions'][0]['match']['candidates'][0]['units'][0]['romaji']=='hosi' and result['transcript']==raw


def test_matching_keeps_per_word_manual_and_explicit_automatic_rule():
    old=set_manual(line(),0,'HOSHI');value=timing_result({'suggestions':[old.to_dict()]},{'action':'match','romanization_rules':{**DEFAULT,'system':'kunrei'}})['suggestions'][0]
    assert value['units'][0]['romaji']=='HOSHI'
    old.units[0].reading_options['romaji']={'mode':'auto',**DEFAULT};old.units[0].romaji='hoshi'
    value=timing_result({'suggestions':[old.to_dict()]},{'action':'match','romanization_rules':{**DEFAULT,'system':'kunrei'}})['suggestions'][0]
    assert value['units'][0]['romaji']=='hoshi'


def test_protected_match_is_byte_equivalent_and_legacy_request_adds_no_new_options():
    old=line().to_dict();old['match']={'status':'protected'};result=timing_result({'suggestions':[copy.deepcopy(old)]},{'action':'match','romanization_rules':DEFAULT})
    assert result['suggestions'][0]==old
    old['match']={};result=timing_result({'suggestions':[copy.deepcopy(old)]},{'action':'match'})
    assert result['suggestions'][0]==old


def test_reused_chorus_preserves_manual_ruby_and_romanization_settings():
    old=set_ruby(set_manual(line(),0,'HOSHI'),0,{'mode':'whole'});old.reviewed=True
    target=LyricLine('next','星',4000,6000);value=prepare(old,target,True)
    assert value.units[0].reading_options==old.units[0].reading_options and value.units[0].romaji=='HOSHI'
    assert (value.units[0].start,value.units[0].end)==(4000,6000)
