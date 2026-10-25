import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.convert import annotation_suggestion
from studio_backend.reading_suggestion import validate_text_result
from studio_backend.analysis import analyze_line


def line():
    parts=[Highlight(k,a,b,'manual') for k,a,b in [('に',1000,1100),('ん',1210,1400),('き',1400,1800)]];parts[1].fixed_edges=['start']
    return LyricLine('safe','人気',900,2000,[Unit('人気',1000,1800,'にんき','ninki',highlights=parts,reading_source='dictionary')],reviewed=True,display_start=500,display_end=2500)


def annotation(kana):return {'groups':[{'text':'人気','kana':kana,'romaji':'model','start':99999,'end':100000}],'translation':'译文'}


def test_text_model_same_mora_count_keeps_real_manual_and_fixed_times():
    old=line();value=annotation_suggestion(old,annotation('ひとけ'));validate_text_result(old,value)
    assert value.units[0].kana=='ひとけ' and [(h.start,h.end,h.fixed_edges) for h in value.units[0].highlights]==[(1000,1100,[]),(1210,1400,['start']),(1400,1800,[])]
    assert (value.display_start,value.display_end)==(500,2500) and not value.reviewed


def test_text_model_count_change_keeps_old_axis_and_retains_alternative():
    old=line();value=annotation_suggestion(old,annotation('にき'));validate_text_result(old,value)
    assert value.units[0].kana=='にんき' and value.units[0].highlights==old.units[0].highlights
    assert value.reading_review['words'][0]['deepseek_suggested']=='にき' and value.reading_review['words'][0]['protection_notice']


def test_local_kana_review_uses_same_boundary_rule():
    old=line();value,_=analyze_line(old,[LyricLine('asr','ひとけ',1000,1800)],0);validate_text_result(old,value)
    assert value.units[0].kana=='ひとけ' and value.units[0].highlights[1].start==1210 and value.units[0].highlights[1].fixed_edges==['start']


def test_forged_fixed_time_or_voice_evidence_is_rejected():
    old=line();value=annotation_suggestion(old,annotation('ひとけ'));value.units[0].highlights[1].start+=10
    with pytest.raises(ValueError):validate_text_result(old,value)
    value=annotation_suggestion(old,annotation('ひとけ'));value.timing_evidence={'engine':'invented-by-text'}
    with pytest.raises(ValueError,match='声音时间依据'):validate_text_result(old,value)


def test_text_model_without_old_word_axis_only_gets_program_estimates():
    old=LyricLine('blank','人気',1000,2000);value=annotation_suggestion(old,annotation('にんき'));validate_text_result(old,value)
    assert all(h.source=='estimated' for h in value.units[0].highlights)
