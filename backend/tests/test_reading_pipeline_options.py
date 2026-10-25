from studio_backend.model import LyricLine,Unit
from studio_backend.romanization import DEFAULT,set_manual
from studio_backend.translation import manual,info
from studio_backend.japanese import segment_line
from studio_backend.analysis import analyze_line
from studio_backend.draft import inputs,keep_readings


def line():return LyricLine('pipeline','星',1000,2000,[Unit('星',1000,2000,'ほし','hoshi',reading_source='dictionary')])


def test_segmentation_and_local_review_honor_selected_romanization():
    old=line();segmented,_=segment_line(old,'mora',{**DEFAULT,'system':'kunrei'});assert segmented.units[0].romaji=='hosi'
    reviewed,_=analyze_line(old,[],0,romanization_rules={**DEFAULT,'system':'kunrei'});assert reviewed.units[0].romaji=='hosi'


def test_local_review_keeps_translation_source_and_roman_override():
    old=manual(set_manual(line(),0,'HO-SHI'),'我的译文');reviewed,_=analyze_line(old,[],0,romanization_rules=DEFAULT)
    assert reviewed.units[0].romaji=='HO-SHI' and info(reviewed)['source']=='manual' and reviewed.translation=='我的译文'


def test_new_workflow_rules_are_validated_and_legacy_inputs_do_not_gain_new_fields():
    request={'lines':[line().to_dict()],'draft_options':{'source':'offline'}};old=inputs(request);assert 'romanization_rules' not in old
    new=inputs({**request,'romanization_rules':{**DEFAULT,'system':'kunrei'}});assert new['romanization_rules']['system']=='kunrei'


def test_stage_reading_keep_restores_manual_roman_metadata():
    old=set_manual(line(),0,'HO-SHI');candidate=line().to_dict();candidate['start']=1100;candidate['units'][0]['start']=1100
    result=LyricLine.from_dict(keep_readings(candidate,old.to_dict()))
    assert result.units[0].romaji=='HO-SHI' and result.units[0].reading_options['romaji']['mode']=='manual'
