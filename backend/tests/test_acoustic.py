import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.acoustic import plan,propose,protected_equal,pronunciations

def line():
    return LyricLine('a','君を抱きしめて',1000,6000,[Unit('君を',1000,2500,'キミヲ','kimiwo'),Unit('抱きしめて',2500,6000,'だきしめて','dakishimete')],kana='キミヲだきしめて',translation='人工译文',display_start=500,display_end=6500)

def inference(prepared):
    # Structural fixtures only: real frozen/model inference has a separate
    # licensed singing sample and a human phoneme-reference benchmark.
    outputs=[]
    for i,job in enumerate(prepared['jobs']):
        count=len(job['mora']);span=job['end']-job['start'];values=[]
        for j,m in enumerate(job['mora']):
            a=job['start']+round(span*j/count);b=job['start']+round(span*(j+1)/count)
            values.append({**m,'start':a,'end':b,'phones':[{'phone':'test','start':a,'end':b}]})
        outputs.append({'index':i,'mora':values,'agreement':.5})
    return {'engine':'test-acoustic','model_sha256':'a'*64,'timestep_ms':10,'jobs':outputs}

def candidate(prepared,result=None):return propose(prepared,result or inference(prepared),'b'*64,'c'*64,'vocals')

def test_keep_original_katakana_lyric_readings_display_and_real_gaps():
    original=line();prepared=plan(original);result=inference(prepared)
    result['jobs'][0]['mora'][1]['start']+=170;result['jobs'][0]['mora'][1]['phones'][0]['start']+=170
    new=candidate(prepared,result);protected_equal(original,new)
    assert ''.join(h.kana for h in new.units[0].highlights)=='キミヲ'
    assert new.units[0].highlights[1].start-new.units[0].highlights[0].end==170
    assert not new.reviewed and new.timing_evidence['audio_role']=='vocals'
    assert original.units[0].highlights==[]
    from studio_backend.continuity import continuous_lines
    assert continuous_lines([new],500)[0][0].to_dict()==new.to_dict()

def test_human_mora_and_word_bounds_split_only_unfixed_runs():
    original=line();u=original.units[1];u.source='manual';u.highlights=[Highlight(c,2500+i*700,3200+i*700,'manual' if i==2 else 'estimated') for i,c in enumerate(u.kana)]
    prepared=plan(original)
    assert [(r['start'],r['end']) for r in prepared['jobs']]==[(1000,2500),(2500,3900),(4600,6000)]
    result=candidate(prepared);assert result.units[1].highlights[2]==u.highlights[2]
    assert (result.units[1].start,result.units[1].end)==(2500,6000)
    protected_equal(original,result)

def test_locked_word_can_coexist_with_local_recalculation():
    original=line();original.units[0].locked=True
    prepared=plan(original);assert prepared['jobs'][0]['start']==2500
    result=candidate(prepared);assert result.units[0]==original.units[0]
    assert result.units[1].highlights[0].source=='acoustic'

@pytest.mark.parametrize('kind',['reviewed','locked'])
def test_confirmed_line_never_recalculated(kind):
    original=line();setattr(original,kind,True)
    with pytest.raises(ValueError,match='确认|锁定'):plan(original)

def test_invalid_audio_region_keeps_original_unit_not_uniform_replacement():
    original=line();original.units[1].source='manual';prepared=plan(original);raw=inference(prepared)
    raw['jobs'][0]={'index':0,'error':'无声音'};result=candidate(prepared,raw)
    assert result.units[0]==original.units[0] and not result.units[0].highlights
    assert '无声音' in result.timing_evidence['notes']

@pytest.mark.parametrize('failure',['missing','zero','outside','kana'])
def test_malformed_skipped_or_changed_tokens_never_accepted(failure):
    prepared=plan(line());raw=inference(prepared)
    first=raw['jobs'][0]['mora'][0]
    if failure=='missing':raw['jobs']=[]
    if failure=='zero':first['end']=first['start']
    if failure=='outside':first['start']-=10
    if failure=='kana':first['kana']='違'
    with pytest.raises(ValueError):candidate(prepared,raw)

def test_geminate_digraph_long_vowel_and_particle_without_rewriting_kana():
    u=Unit('学校へ',0,1000,'がっこうへ','gakkoue')
    assert pronunciations(u)==(['が','っ','こ','う','へ'],['ga','cl','ko','u','he'])
    assert pronunciations(Unit('へ',0,1,'へ','e'))[1]==['e']
    assert pronunciations(Unit('は、',0,1,'は','wa'))[1]==['wa']
    assert pronunciations(Unit('へ！',0,1,'ヘ','e'))==(['ヘ'],['e'])
    assert pronunciations(Unit('きゃー',0,1,'キャー'))==(['キャ','ー'],['kya','a'])
    for invalid in ('歌','かな かな','ｶﾅ','ー'):
        with pytest.raises(ValueError):pronunciations(Unit('x',0,1,invalid))

def test_human_boundaries_cannot_be_changed_even_by_corrupt_proposal():
    original=line();original.units[0].locked=True;new=candidate(plan(original));new.units[0].start+=1
    with pytest.raises(ValueError,match='锁定'):protected_equal(original,new)
