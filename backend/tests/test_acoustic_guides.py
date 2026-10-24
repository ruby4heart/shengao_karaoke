import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.acoustic import plan,propose,protected_equal
from studio_backend.acoustic_guides import prepare,validate_result


def line():
    h=[Highlight(k,1000+i*1000,2000+i*1000) for i,k in enumerate('あいうえ')]
    return LyricLine('guide','合言葉',1000,5000,[Unit('合言葉',1000,5000,'あいうえ','aiue',highlights=h)],kana='あいうえ',translation='保留译文',display_start=0,display_end=5500)


def points():
    return [dict(unit=0,highlight=1,edge='start',time=2400),dict(unit=0,highlight=2,edge='end',time=3800)]


def inference(prepared):
    jobs=[]
    for i,job in enumerate(prepared['jobs']):
        n=len(job['mora']);width=job['end']-job['start'];mora=[]
        for j,m in enumerate(job['mora']):
            a=job['start']+round(width*j/n)+10;b=job['start']+round(width*(j+1)/n)-10
            mora.append({**m,'start':a,'end':b,'phones':[{'phone':'fixture','start':a,'end':b}]})
        jobs.append(dict(index=i,mora=mora))
    return dict(engine='fixture',model_sha256='a'*64,timestep_ms=10,jobs=jobs)


def candidate(p,raw=None):return propose(p,raw or inference(p),'b'*64,'c'*64,'original')


def test_only_between_points_exact_edges_free_opposite_and_original_evidence():
    old=line();before=old.to_dict();p=prepare(old,points());raw=inference(p);new=candidate(p,raw)
    assert old.to_dict()==before and len(p['jobs'])==1
    assert [(m['highlight']) for m in p['jobs'][0]['mora']]==[1,2]
    a,b,c,d=new.units[0].highlights
    assert a==old.units[0].highlights[0] and d==old.units[0].highlights[3]
    assert b.start==2400 and c.end==3800 and b.fixed_edges==['start'] and c.fixed_edges==['end']
    assert b.end==raw['jobs'][0]['mora'][0]['end'] and c.start==raw['jobs'][0]['mora'][1]['start']
    assert raw['jobs'][0]['mora'][0]['phones'][0]['start']==2410
    assert b.timing_origin['reference'][0]==2410 and b.timing_origin['current'][0]==2400
    assert new.timing_evidence['runs'][0]['mora']==raw['jobs'][0]['mora']
    assert not new.reviewed and new.translation==old.translation
    validate_result(p,new);protected_equal(old,new)


def test_manual_mora_and_locked_words_are_excluded_not_relabelled():
    old=line();old.units[0].highlights[1].source='manual'
    p=prepare(old,[dict(unit=0,highlight=0,edge='start',time=1000),dict(unit=0,highlight=3,edge='end',time=5000)])
    assert len(p['jobs'])==2
    new=candidate(p);assert new.units[0].highlights[1]==old.units[0].highlights[1]


def test_fixed_edges_survive_next_generic_alignment_without_freezing_other_end():
    old=candidate(prepare(line(),points()));p=plan(old);new=candidate(p)
    assert new.units[0].highlights[1].start==2400 and new.units[0].highlights[2].end==3800
    protected_equal(old,new)
    new.units[0].highlights[1].start+=1
    with pytest.raises(ValueError,match='固定'):protected_equal(old,new)


def test_two_fixed_edges_exclude_whole_mora_from_inference():
    old=line();old.units[0].highlights[1].fixed_edges=['start','end'];p=plan(old)
    assert all(m['highlight']!=1 for job in p['jobs'] for m in job['mora'])
    new=candidate(p);assert new.units[0].highlights[1]==old.units[0].highlights[1]


@pytest.mark.parametrize('problem',['backwards','outside','duplicate','bool','known'])
def test_bad_point_draft_never_mutates_original(problem):
    old=line();p=points();before=old.to_dict()
    if problem=='backwards':p[0]['time']=4500
    elif problem=='outside':p[0]['time']=0
    elif problem=='duplicate':p.append(copy.deepcopy(p[0]))
    elif problem=='bool':p[0]['highlight']=True
    else:old.units[0].highlights[1].fixed_edges=['start'];before=old.to_dict()
    with pytest.raises(ValueError):prepare(old,p)
    assert old.to_dict()==before


def test_failed_interval_keeps_original_and_stored_draft_usable():
    old=line();before=old.to_dict();p=prepare(old,points());raw=inference(p)
    raw['jobs'][0]={'index':0,'error':'fixture failure'}
    with pytest.raises(ValueError,match='原轴保留'):candidate(p,raw)
    assert old.to_dict()==before and prepare(old,p['guide_points'])==p


def test_corrupt_outside_or_anchor_proposal_rejected():
    p=prepare(line(),points());new=candidate(p)
    new.units[0].highlights[0].end-=1
    with pytest.raises(ValueError,match='范围之外'):validate_result(p,new)
    new=candidate(p);new.units[0].highlights[1].fixed_edges=[]
    with pytest.raises(ValueError,match='固定位置'):validate_result(p,new)


def test_fixed_edge_blocks_unrelated_automatic_matching_and_gap_filling():
    from studio_backend.matching_context import protected
    from studio_backend.continuity import continuous_lines
    old=line();old.units[0].highlights[0].end-=100;old.units[0].highlights[0].fixed_edges=['end']
    assert protected(old)
    new,changes=continuous_lines([old],500)
    assert not changes and new[0].to_dict()==old.to_dict()


@pytest.mark.parametrize('value',[None,'start',['both'],['start','start'],[True],[{}]])
def test_bad_boundary_flags_are_rejected(value):
    old=line();old.units[0].highlights[0].fixed_edges=value
    with pytest.raises(ValueError,match='固定边界'):old.validate()


def test_empty_fixed_edge_field_is_omitted_for_legacy_signatures():
    old=line();data=old.to_dict()
    assert all('fixed_edges' not in h for u in data['units'] for h in u['highlights'])
    assert LyricLine.from_dict(data).to_dict()==data


def test_locked_middle_word_splits_guided_runs_and_remains_identical():
    h=[Highlight(k,1000+n*1000,2000+n*1000) for n,k in enumerate('あいうえお')]
    old=LyricLine('locked','あいうえお',1000,6000,[
        Unit('あい',1000,3000,'あい',highlights=h[:2]),
        Unit('う',3000,4000,'う',locked=True,highlights=h[2:3]),
        Unit('えお',4000,6000,'えお',highlights=h[3:])])
    p=prepare(old,[dict(unit=0,highlight=0,edge='start',time=1000),dict(unit=2,highlight=1,edge='end',time=6000)])
    assert [(job['start'],job['end']) for job in p['jobs']]==[(1000,3000),(4000,6000)]
    assert candidate(p).units[1]==old.units[1]
