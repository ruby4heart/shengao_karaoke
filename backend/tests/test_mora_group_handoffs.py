import copy
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.mora_editing import split
from studio_backend.analysis import analyze_line
from studio_backend.matching import match_lyrics
from studio_backend.draft import keep_readings
from studio_backend.chorus_reuse import prepare
from studio_backend.convert import annotation_suggestion
from studio_backend.acoustic import plan


def base():
    return LyricLine('target','歌',1000,4000,[Unit('歌',1000,4000,'きょうも',highlights=[Highlight('きょ',1000,2000,'acoustic'),Highlight('う',2000,3000),Highlight('も',3000,4000)])])


def test_dictionary_and_text_review_preserve_custom_groups_and_historical_basis():
    old=split(base(),0,0,1,allow_character=True)['line'];before=old.to_dict();value,_=analyze_line(old,[],maximum=0)
    assert value.reading_review['mora_edits']==old.reading_review['mora_edits'] and value.units[0].highlights==old.units[0].highlights
    candidate=annotation_suggestion(old,{'groups':[{'text':'歌','kana':'きょうも','romaji':'kyoumo'}],'translation':'演示译文'})
    assert candidate.reading_review['mora_edits']==old.reading_review['mora_edits'] and candidate.units[0].highlights==old.units[0].highlights and old.to_dict()==before


def test_default_matching_keeps_custom_group_and_explicit_rematch_keeps_structure_protection():
    old=split(base(),0,0,1,allow_character=True)['line'];transcript=[LyricLine('asr','歌',5000,8000)]
    untouched=LyricLine.from_dict(match_lyrics([old],transcript)['suggestions'][0]);assert untouched.units[0].highlights==old.units[0].highlights
    moved=LyricLine.from_dict(match_lyrics([old],transcript,replace_manual=True)['suggestions'][0])
    assert [h.kana for h in moved.units[0].highlights]==['き','ょ','う','も'] and moved.start==5000 and moved.end==8000
    assert all(h.source=='manual' and h.timing_origin['kind']=='estimated' for h in moved.units[0].highlights[:2])
    assert moved.reading_review['mora_edits']==old.reading_review['mora_edits']
    prepared=plan(moved);assert [(m['unit'],m['highlight']) for job in prepared['jobs'] for m in job['mora']]==[(0,2),(0,3)]


def test_stage_reading_carry_retains_group_history_even_when_old_worker_omits_it():
    old=split(base(),0,0,1,allow_character=True)['line'];row=copy.deepcopy(old.to_dict());row['reading_review']={}
    result=LyricLine.from_dict(keep_readings(row,old.to_dict()))
    assert result.reading_review['mora_edits']==old.reading_review['mora_edits'] and result.units[0].highlights==old.units[0].highlights


def test_chorus_reuse_preserves_targets_audit_without_copying_source_audit():
    target=LyricLine('target','今日',1000,3000,[Unit('今日',1000,3000,'きょう',highlights=[Highlight('きょう',1000,3000,'acoustic')])]);target=split(target,0,0,2)['line']
    source=copy.deepcopy(target);source.id='source';source.reviewed=True;source.reading_review={}
    value=prepare(source,target,True)
    assert value.reading_review['mora_edits']==target.reading_review['mora_edits'] and value.reading_review['reuse']['source_id']=='source' and not value.reviewed
