from dataclasses import replace
import pytest
from shengao.workflow_state import Facts,decide,primary_for_stage


def confirmed():
    return Facts(media_selected=True,media_ready=True,line_count=2,timing_confirmed=2,reading_confirmed=2)


def test_confirmed_project_returns_to_style_instead_of_regenerating():
    decision=decide(confirmed())
    assert decision.primary.command=='style'
    assert primary_for_stage(decision,0).stage==3
    assert primary_for_stage(decision,3).command=='export'
    assert any(action.command=='draft_options' for action in decision.secondary)


@pytest.mark.parametrize('changes,key',[
    ({'media_ready':False},'media_missing'),
    ({'media_loading':True},'media_loading'),
    ({'timing_confirmed':1},'timing'),
    ({'reading_confirmed':1},'reading'),
    ({'unsegmented_count':1},'unsegmented'),
    ({'suggestion_count':1},'suggestions'),
    ({'recognition_pending':True},'recognition'),
    ({'task_running':True},'task_running'),
    ({'inline_pending':True},'pending_edit'),
])
def test_unfinished_content_controls_the_recommendation(changes,key):
    assert decide(replace(confirmed(),**changes)).key==key


def test_no_lyrics_prioritises_correct_original_over_recognition():
    decision=decide(Facts(media_ready=True,media_selected=True))
    assert decision.primary.command=='original_lyrics'
    assert [v.command for v in decision.secondary]==['recognize']


def test_raw_ass_can_continue_without_forcing_segmentation_or_confirmation():
    facts=Facts(media_ready=True,media_selected=True,line_count=2,unsegmented_count=2,source_ass_active=True)
    decision=decide(facts)
    assert decision.key=='raw_ass' and decision.primary.command=='export'
    assert decision.stages[1:3]==('needs_work','needs_work')


def test_visiting_a_page_or_producing_only_a_sample_is_not_full_completion():
    decision=decide(confirmed())
    assert decision.stages[3:]==('ready','ready')
    sample=decide(replace(confirmed(),current_output=True))
    assert sample.stages[4]=='ready'
    assert primary_for_stage(sample,4,current_output=True).command=='play_output'
    assert decide(replace(confirmed(),current_output=True,full_output=True)).stages[4]=='done'


@pytest.mark.parametrize('changes',[{'line_count':True},{'line_count':-1},{'timing_confirmed':3}])
def test_invalid_counts_are_not_presented_as_success(changes):
    with pytest.raises(ValueError):decide(replace(confirmed(),**changes))
