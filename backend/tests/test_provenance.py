import copy
import json
from pathlib import Path
import pytest
from studio_backend.model import LyricLine,Unit,Highlight,align_characters
from studio_backend.provenance import create,summary,line_summary,rows,validate,preserve_before_confirmation
from studio_backend.convert import eleven_lines,mai_lines,annotation_suggestion
from studio_backend.japanese import add_mora,Group,retime_groups
from studio_backend.matching import match_lyrics
from studio_backend.continuity import continuous_lines
from studio_backend.analysis import aligned_words,analyze_line


def phrase():
    u=Unit('今日',1000,2000,'きょう',reading_source='dictionary',timing_origin=create('word',1000,2000,'microsoft','transcription'))
    add_mora(u);return LyricLine('a','今日',1000,2000,[u],kana='きょう')


def test_api_word_envelope_never_becomes_character_or_mora_evidence():
    line=eleven_lines({'words':[{'text':'今日','start':1,'end':2,'type':'word'}]})[0]
    assert summary(line.units[0])['kind']=='word'
    line.units[0].kana='きょう';add_mora(line.units[0])
    assert all(summary(h,mora=True)['kind']=='estimated' for h in line.units[0].highlights)
    assert line.units[0].highlights[0].timing_origin['parent_kinds']==['word']


def test_returned_character_array_and_text_alignment_remain_character_references():
    chars=[{'text':'今','start':1,'end':1.4},{'text':'日','start':1.4,'end':2}]
    line=eleven_lines({'words':[{'text':'今日','start':1,'end':2,'type':'word','characters':chars}]})[0]
    original=phrase();grouped=aligned_words(line,original)
    assert summary(grouped.units[0])['kind']=='character'
    assert all(summary(h,mora=True)['kind']=='estimated' for h in grouped.units[0].highlights)
    assert all(summary(u)['origin']['provider']=='elevenlabs' for u in align_characters('今日',chars))


def test_whole_word_matching_retains_word_reference_but_new_cuts_are_estimates():
    recognized=eleven_lines({'words':[{'text':'今日','start':1,'end':2,'type':'word'}]})
    whole=match_lyrics([LyricLine('a','今日',0,3000)],recognized)['suggestions'][0]
    assert whole['units'][0]['timing_origin']['kind']=='word'
    divided=LyricLine('a','今日',0,3000,[Unit('今',0,1500),Unit('日',1500,3000)])
    split=match_lyrics([divided],recognized)['suggestions'][0]
    assert all(u['timing_origin']['kind']=='estimated' for u in split['units'])
    assert all(u['timing_origin']['parent_kinds']==['word'] for u in split['units'])


def test_microsoft_phrase_fallback_is_explicitly_interpolated():
    line=mai_lines({'phrases':[{'text':'今日','offsetMilliseconds':1000,'durationMilliseconds':1000}]})[0]
    assert summary(line)['kind']=='reference' and all(summary(u)['kind']=='estimated' for u in line.units)
    assert all(u.timing_origin['method']=='phrase_distribution' for u in line.units)


def test_old_dicts_roundtrip_without_fabricated_fields_or_granularity():
    old=LyricLine('a','今日',1000,2000,[Unit('今日',1000,2000,'きょう',source='alignment',highlights=[Highlight('きょ',1000,1500),Highlight('う',1500,2000)])]).to_dict()
    assert 'timing_origin' not in json.dumps(old)
    restored=LyricLine.from_dict(old);assert restored.to_dict()==old
    assert summary(restored.units[0])['kind']=='reference' and summary(restored.units[0])['origin']['method']=='legacy'
    assert '字符时间参考' not in summary(restored.units[0])['title']


def old_voice():
    state=json.loads((Path(__file__).parent/'fixtures/v020-staged-acoustic-state.json').read_text(encoding='utf-8'))
    row=next(s for s in state['stages'] if s['key']=='acoustic')['result']['suggestions'][0]
    return LyricLine.from_dict(row)


def test_real_legacy_voice_can_be_described_from_retained_intervals_without_rewriting():
    from studio_backend.provenance import describe
    line=old_voice();before=line.to_dict();h=line.units[0].highlights[0]
    value=describe(h,line,0,0)
    assert value['origin']['provider']=='tifa' and value['origin']['method']=='restored_legacy_voice'
    assert value['origin']['reference']==[h.start,h.end] and line.to_dict()==before
    assert not h.timing_origin and 'timing_origin' not in json.dumps(before)


def test_legacy_line_without_denormalized_kana_uses_existing_group_readings():
    from studio_backend.provenance import describe
    line=old_voice();line.kana='';line.validate();before=line.to_dict()
    value=describe(line,line)
    assert value['origin']['provider']=='tifa' and not any('旧读音' in note for note in value['issues'])
    assert line.to_dict()==before


def test_real_legacy_reading_or_time_edits_are_not_new_acoustic_evidence():
    from studio_backend.provenance import describe
    line=old_voice();h=line.units[0].highlights[0];h.kana='す'
    assert any('旧读音' in note for note in describe(h,line,0,0)['issues'])
    h.start+=10;value=describe(h,line,0,0)
    assert value['display_kind']=='estimated' and any('未能对应' in note for note in value['issues'])


def test_manual_edit_of_legacy_voice_keeps_parent_evidence_across_roundtrip():
    from studio_backend.provenance import describe
    from shengao.timing import set_time
    line=old_voice();h=line.units[0].highlights[0];original=describe(h,line,0,0)['origin']
    changed=set_time(line,0,h.start+10,h.end,0);before=changed.to_dict()
    current=describe(changed.units[0].highlights[0],changed,0,0)
    assert current['origin']['provider']=='tifa' and current['origin']['reference']==original['reference']
    assert 'manual_boundary' in current['origin']['operations'] and current['display_kind']=='manual'
    again=LyricLine.from_dict(before);assert describe(again.units[0].highlights[0],again,0,0)['origin']==current['origin']
    assert changed.to_dict()==before


def test_source_inspection_is_read_only_and_confirmation_does_not_erase_basis():
    line=phrase();before=line.to_dict();rows(line);line_summary(line);assert line.to_dict()==before
    preserve_before_confirmation(line);line.reviewed=True
    for u in line.units:
        u.source='manual'
        for h in u.highlights:h.source='manual'
    assert summary(line.units[0],True)['kind']=='word'
    assert all(summary(h,True,True)['kind']=='estimated' and '已人工确认' in summary(h,True,True)['title'] for h in line.units[0].highlights)


def test_fixed_gap_adjustment_retains_original_range_and_explains_heuristic():
    line=LyricLine('a','あい',0,1000,[Unit('あ',0,300,source='word',timing_origin=create('word',0,300,'elevenlabs','transcription')),Unit('い',400,1000)])
    out,changes=continuous_lines([line],500,False);value=summary(out[0].units[0])
    assert len(changes)==1 and value['origin']['reference']==[0,300] and value['origin']['current']==[0,400]
    assert any('并非声音' in note for note in value['issues']) and line.units[0].end==300


def test_reading_refinement_does_not_fill_existing_acoustic_pause():
    from studio_backend.analysis import smooth_gaps
    line=LyricLine('a','あい',0,1000,[Unit('あ',0,300,source='acoustic'),Unit('い',400,1000,source='acoustic')])
    out,count=smooth_gaps(line,120)
    assert count==0 and out.to_dict()==line.to_dict()


def test_original_voice_checks_remain_visible_but_confirmed_checks_do_not_nag():
    line=phrase();line.timing_evidence={'notes':['同音连续，需要细听']}
    assert any('同音连续' in note for note in rows(line)[0]['issues'])
    line.reviewed=True;value=rows(line)[0]
    assert not value['issues'] and any('同音连续' in note for note in value['detail'])


def test_changed_reading_warns_about_old_acoustic_word_without_touching_neighbors():
    from shengao.timing import edit_reading
    line=phrase();u=line.units[0];u.source='acoustic';u.timing_origin=create('acoustic',u.start,u.end,'tifa','phoneme_envelope',u.kana)
    changed=edit_reading(line,0,'こんにち')
    assert any('旧读音' in note for note in summary(changed.units[0])['issues'])
    assert all(summary(h,mora=True)['kind']=='estimated' for h in changed.units[0].highlights)


def test_whole_phrase_shift_preserves_estimated_mora_basis_and_direct_drag_is_separate():
    from shengao.project import Project
    from shengao.time_transform import TimeTransform,transform_project
    from shengao.timing import set_time
    line=phrase();moved=transform_project(Project(duration=5000,lines=[line]),[0],TimeTransform(offset=300)).project.lines[0]
    assert all(h.source=='manual' and summary(h,mora=True)['display_kind']=='estimated' for h in moved.units[0].highlights)
    assert all('shift' in h.timing_origin['operations'] for h in moved.units[0].highlights)
    dragged=set_time(moved,0,1310,1800,0)
    assert summary(dragged.units[0].highlights[0],mora=True)['display_kind']=='manual'
    assert dragged.units[0].highlights[0].timing_origin['kind']=='estimated'


def test_drift_distinguishes_outside_translation_from_inside_stretch():
    from shengao.project import Project
    from shengao.time_transform import TimeTransform,transform_project
    p=Project(duration=6000,lines=[phrase()])
    shifted=transform_project(p,[0],TimeTransform(anchors=((2000,2200),(4000,4500)))).project.lines[0]
    assert shifted.units[0].timing_origin['operations']==['shift']
    stretched=transform_project(p,[0],TimeTransform(anchors=((0,0),(5000,5500)))).project.lines[0]
    assert stretched.units[0].timing_origin['operations']==['stretch']
    assert summary(stretched.units[0])['display_kind']=='estimated' and summary(stretched.units[0])['kind']=='word'


def test_confirmed_timing_does_not_become_confirmed_reading():
    line=phrase();line.units[0].reading_source='';line.reviewed=True
    result,_=analyze_line(line,[],preserve_legacy=True)
    assert not result.reading_review['words'][0]['legacy']
    assert result.units[0].reading_source!='manual'


@pytest.mark.parametrize('mutation',[
    lambda v:v.update(version=True),lambda v:v.update(reference=[20,10]),lambda v:v.update(current=[False,100]),
    lambda v:v.update(provider='https://untrusted.example/key'),lambda v:v.update(operations=['shift','shift']),
    lambda v:v.update(parent_kinds=['invented']),lambda v:v.update(extra='unsupported'),
    lambda v:v.update(operations=None),lambda v:v.update(parent_kinds=None),
    lambda v:v.update(reference=(0,100)),lambda v:v.update(current=[0,True])])
def test_invalid_origin_records_are_rejected(mutation):
    value=create('word',0,100,'elevenlabs','transcription');mutation(value)
    with pytest.raises(ValueError):validate(value)


def test_original_v020_completed_acoustic_checkpoint_keeps_signature_without_any_rerun(tmp_path,monkeypatch):
    import asyncio
    import hashlib
    from studio_backend import draft,worker,singing_stage
    from studio_backend.settings import atomic_json,Settings
    fixture=Path(__file__).parent/'fixtures/v020-staged-acoustic-state.json';raw=fixture.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='be504a8df75f7d2bcf7e4122de9e6fb755d7c5ec683a0e1c7d51b14399618f5e'
    state=json.loads(raw);request=state['request'];assert draft.inputs(request)==request
    # Alias only the old filesystem name to the exact included public audio.
    # The fixture, request, signature and completed stage payloads stay intact.
    audio=Path(__file__).resolve().parents[2]/'desktop/assets/alignment-demo/pjs056_song.wav'
    assert hashlib.sha256(audio.read_bytes()).hexdigest()=='92037425e4b461b4efbcf1c38585e8e5122a3dfb5b41e589ae8c9a9390c250b4'
    media=request['media'].casefold().replace('/','\\');is_file=Path.is_file;fingerprint=worker.fingerprint
    def old_path(path):return str(path).casefold().replace('/','\\')==media
    monkeypatch.setattr(Path,'is_file',lambda path:True if old_path(path) else is_file(path))
    monkeypatch.setattr(worker,'fingerprint',lambda path:fingerprint(audio if old_path(path) else path))
    def forbidden(*args,**kwargs):raise AssertionError('Completed old stages must not run a provider or model')
    monkeypatch.setattr(singing_stage,'runtime',forbidden);monkeypatch.setattr(Settings,'key',forbidden)
    home=tmp_path/'home';atomic_json(draft.checkpoint_path(home,state['id']),state);messages=[]
    result=asyncio.run(draft.run({**request,'workflow_id':state['id'],'resume':True},home,lambda stage,message:messages.append(message),forbidden))
    assert not result['partial'] and result['suggestions']==draft.result(state)['suggestions']
    assert draft.load(home,state['id'])['signature']==state['signature'] and all('/6' in m for m in messages)
    assert fixture.read_bytes()==raw
