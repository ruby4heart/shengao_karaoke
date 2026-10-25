import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.translation import record_suggestion,manual
from shengao.project import Project,History,file_stamp,save_project,load_project
from shengao.review_issues import collect,state,record_decision,progress,current_issue,proposed_line
from shengao.subtitle_files import export_subtitle


def sample(tmp_path):
    media=tmp_path/'合成输入.dat';media.write_bytes(b'synthetic, not singing')
    line=LyricLine('line','人気の街',1000,3000,[Unit('人気',1000,1800,'にんき'),Unit('の街',1900,3000,'のまち')])
    return Project(media=str(media),duration=8000,lines=[line],checks={'line':{'reading':True}})


def get(project,kind,tag=None):
    values=[v for v in collect(project,False) if v.kind==kind]
    return next(v for v in values if tag is None or v.title==tag)


def test_collection_readonly_and_dictionary_homographs_alone_are_not_conflicts(tmp_path):
    p=sample(tmp_path);before=p.to_dict();items=collect(p,False)
    assert p.to_dict()==before and len([v for v in items if v.kind=='missing'])==2
    assert not [v for v in items if v.kind=='reading']
    assert any(v.kind=='confirmation' for v in items) and progress(items,p.review_states)['saved_adoptions']==0


def test_matching_missing_range_gap_and_length_are_separate_with_context(tmp_path):
    p=sample(tmp_path);line=p.lines[0];line.match={'status':'unmatched','recognized':''};line.units[0].highlights=[Highlight('に',1000,1010),Highlight('ん',1200,1400),Highlight('き',1400,1800)];p.duration=2500
    items=collect(p,False)
    assert {'match','range','gap','duration','missing','confirmation'}<={v.kind for v in items}
    gap=next(v for v in items if v.kind=='gap');assert gap.word==0 and gap.part==1 and '190 ms' in gap.current and '真实休止' in gap.why and not gap.proposal
    assert any(v.kind=='gap' and v.word==1 and v.part==-1 and '100 ms' in v.current for v in items)


def test_bound_transcript_kana_is_candidate_but_unbound_or_kanji_is_not(tmp_path):
    p=sample(tmp_path);p.transcript=[LyricLine('asr','ひとけ',1000,1800).to_dict()];p.transcript_stamp=file_stamp(p.media)
    item=get(p,'reading');assert item.suggested=='ひとけ' and item.proposal['kana']=='ひとけ' and '不是确认事实' in item.why
    p.transcript_stamp={};assert not [v for v in collect(p,False) if v.kind=='reading']
    p.transcript_stamp=file_stamp(p.media);p.transcript=[LyricLine('asr','人気',1000,1800).to_dict()]
    assert not [v for v in collect(p,False) if v.kind=='reading']
    p.transcript_stamp={'path':'old','size':1,'modified_ns':1};assert any(v.kind=='media' and '旧转录' in v.title for v in collect(p,False))


def test_stale_text_proposal_is_comparable_and_not_adoptable(tmp_path):
    p=sample(tmp_path);p.lines[0].reading_review={'method':'deepseek','stale':True,'words':[{'text':'人気','deepseek_suggested':'ひとけ','reason':'文字上下文'}]}
    item=get(p,'reading');assert item.current=='にんき' and item.suggested=='ひとけ' and not item.proposal and '旧建议' in item.why
    with pytest.raises(ValueError,match='手工'):proposed_line(p,item)


def test_fill_missing_mora_proposal_only_touches_selected_word_and_is_estimated(tmp_path):
    p=sample(tmp_path);before=p.to_dict();item=get(p,'missing');candidate=proposed_line(p,item)
    assert candidate.units[0].highlights and not candidate.units[1].highlights and candidate.units[1]==p.lines[0].units[1]
    assert candidate.units[0].kana==p.lines[0].units[0].kana and all(v.source=='estimated' and v.timing_origin['kind']=='estimated' for v in candidate.units[0].highlights)
    assert not candidate.reviewed and p.to_dict()==before and p.checks['line']['reading']


def test_reading_adoption_primitive_keeps_actual_human_fixed_times(tmp_path):
    p=sample(tmp_path);line=p.lines[0];line.units[0].highlights=[Highlight('に',1000,1200,'manual',fixed_edges=['start']),Highlight('ん',1200,1500,'manual'),Highlight('き',1500,1800,'manual',fixed_edges=['end'])]
    line.reading_review={'method':'deepseek','words':[{'text':'人気','suggested':'ひとけ'}]}
    item=get(p,'reading');value=proposed_line(p,item)
    assert value.units[0].kana=='ひとけ' and [(h.start,h.end,h.fixed_edges) for h in value.units[0].highlights]==[(h.start,h.end,h.fixed_edges) for h in line.units[0].highlights]
    line.units[0].locked=True
    with pytest.raises(ValueError,match='锁定'):proposed_line(p,item)


def test_keep_defer_and_adoption_counts_do_not_set_time_or_reading_confirmation(tmp_path):
    p=sample(tmp_path);p.checks={};items=collect(p,False);before=p.to_dict();one=items[0]
    states=record_decision({},one,'keep');assert state(one,states)=='keep' and progress(items,states)['pending']==len(items)-1
    states=record_decision(states,one,'defer');assert state(one,states)=='defer' and progress(items,states)['pending']==len(items)
    states=record_decision(states,one,'adopted');assert progress(items,states)['saved_adoptions']==1 and not p.lines[0].reviewed and not p.checks
    assert p.to_dict()==before


def test_edited_input_reopens_old_decision_and_keeps_previous_comparison(tmp_path):
    p=sample(tmp_path);old=get(p,'missing');p.review_states=record_decision({},old,'keep');p.lines[0].units[0].kana='ひとけ'
    new=get(p,'missing');assert new.id==old.id and new.fingerprint!=old.fingerprint and state(new,p.review_states)=='changed'
    assert p.review_states[new.id]['current']==old.current and progress(collect(p,False),p.review_states)['changed']==1
    with pytest.raises(ValueError,match='已变化'):current_issue(p,old,False)


def test_reappearing_problem_is_not_hidden_by_a_previous_adoption_of_same_inputs(tmp_path):
    p=sample(tmp_path);old=get(p,'missing');p.review_states=record_decision({},old,'adopted')
    current=get(p,'missing');assert current.fingerprint==old.fingerprint and state(current,p.review_states)=='changed'
    assert progress(collect(p,False),p.review_states)['changed']==1 and progress(collect(p,False),p.review_states)['saved_adoptions']==1


def test_changed_source_reopens_even_unchanged_lyric_and_rejects_old_proposal(tmp_path):
    p=sample(tmp_path);old=get(p,'missing');p.review_states=record_decision({},old,'keep')
    from pathlib import Path
    Path(p.media).write_bytes(b'different source')
    assert state(get(p,'missing'),p.review_states)=='changed'
    with pytest.raises(ValueError,match='已变化'):proposed_line(p,old)


def test_translation_proposal_keeps_times_and_old_original_is_only_comparable(tmp_path):
    p=sample(tmp_path);line=manual(p.lines[0],'手写译文');candidate=copy.deepcopy(line);record_suggestion(line,candidate,'新的译文建议');p.lines[0]=candidate
    item=get(p,'translation');value=proposed_line(p,item)
    assert value.translation=='新的译文建议' and value.units==line.units and value.start==line.start and not value.reading_review['translation']['confirmed']
    p.lines[0].reading_review['translation_suggestion']['for_text']='旧原文'
    assert not get(p,'translation').proposal


def test_decision_save_ass_and_single_undo_roundtrip_without_confirming(tmp_path):
    p=sample(tmp_path);item=get(p,'missing');h=History(p);before=p.to_dict()
    assert h.apply('保留这条疑点',lambda p:setattr(p,'review_states',record_decision(p.review_states,item,'keep')))
    for ext in ('sgproj','ass'):
        path=tmp_path/('疑点状态.'+ext)
        if ext=='ass':export_subtitle(h.project,path)
        else:save_project(h.project,path)
        loaded=load_project(path);assert loaded.review_states==h.project.review_states and loaded.lines[0].to_dict()==p.lines[0].to_dict() and loaded.checks==p.checks
    assert h.undo() and h.project.to_dict()==before


@pytest.mark.parametrize('decision',[None,[],{},True,'resolved'])
def test_invalid_decision_rejected_as_data_not_exception_from_hashing(tmp_path,decision):
    p=sample(tmp_path)
    with pytest.raises(ValueError):record_decision({},get(p,'missing'),decision)


def test_legacy_version_cannot_smuggle_decisions_and_invalid_records_fail_closed(tmp_path):
    p=sample(tmp_path);p.review_states=record_decision({},get(p,'missing'),'defer');data=p.to_dict();data['version']=12
    with pytest.raises(ValueError,match='13'):Project.from_dict(data)
    data['version']=13;entry=next(iter(data['review_states'].values()));entry['decision']=[]
    with pytest.raises(ValueError):Project.from_dict(data)
