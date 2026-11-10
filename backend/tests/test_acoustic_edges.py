"""Breath and release tags only at free line edges, never at human anchors."""
from studio_backend.model import Highlight
from studio_backend.acoustic import plan,propose,protected_equal
from studio_backend.provenance import voice_lookup
from test_acoustic import line,inference

MODEL='8d9bf896da1827f36bf135f80c7ab1fc4f3c1d48f328818b8402c9527c0f014b'


def edges(prepared):return [j.get('edges') for j in prepared['jobs']]


def tagged(prepared,breath=None,release=None):
    result=inference(prepared)
    for job,row in zip(prepared['jobs'],result['jobs']):
        flags=job.get('edges') or {}
        if not any(flags.values()):continue
        values=row['mora'];found={}
        if flags.get('lead'):
            found['breath']=breath(job,values) if breath else None
        if flags.get('trail'):
            found['release']=release(job,values) if release else None
        row['edges']=found
    return result


def shrink(result,lead=0,tail=0):
    # Simulate the model moving the first onset later and the last offset
    # earlier once the breath and reverb have their own tags.
    first=result['jobs'][0]['mora'][0];last=result['jobs'][-1]['mora'][-1]
    first['start']+=lead;first['phones'][0]['start']+=lead
    last['end']-=tail;last['phones'][-1]['end']-=tail
    return result


def test_single_free_run_gets_breath_and_release_tags():
    assert edges(plan(line()))==[{'lead':True,'trail':True}]


def test_locked_first_word_removes_breath_tag_only():
    original=line();original.units[0].locked=True
    assert edges(plan(original))==[{'lead':False,'trail':True}]


def test_locked_last_word_removes_release_tag_only():
    original=line();original.units[1].locked=True
    assert edges(plan(original))==[{'lead':True,'trail':False}]


def test_manual_word_bounds_and_mora_are_anchors_not_free_edges():
    original=line();u=original.units[1];u.source='manual'
    u.highlights=[Highlight(c,2500+i*700,3200+i*700,'manual' if i==2 else 'estimated') for i,c in enumerate(u.kana)]
    prepared=plan(original)
    assert [(j['start'],j['end']) for j in prepared['jobs']]==[(1000,2500),(2500,3900),(4600,6000)]
    assert edges(prepared)==[{'lead':True,'trail':False},None,None]


def test_fixed_first_start_and_last_end_never_get_tags():
    original=line();prepared=plan(original)
    from studio_backend.model import LyricLine
    fixed=LyricLine.from_dict(prepared['baseline'])
    fixed.units[0].highlights[0].fixed_edges=['start'];fixed.units[1].highlights[-1].fixed_edges=['end']
    assert edges(plan(fixed))==[None]


def test_proposal_keeps_tag_spans_outside_mora_and_marks_method():
    original=line();prepared=plan(original)
    result=shrink(tagged(prepared,lambda job,v:[job['start'],job['start']+120],lambda job,v:[job['end']-300,job['end']]),lead=120,tail=300)
    new=propose(prepared,result,'b'*64,'c'*64,'vocals');protected_equal(original,new)
    run=new.timing_evidence['runs'][0]
    assert run['edges']=={'lead':True,'trail':True,'breath':[1000,1120],'release':[5700,6000]}
    assert new.timing_evidence['edge_tags']=='ap-ep-v1'
    assert new.units[0].highlights[0].start==1120 and new.units[1].highlights[-1].end==5700
    assert not any('ms' in n for n in run['notes'])


def test_skipped_or_overlapping_tag_spans_are_dropped_not_trusted():
    prepared=plan(line())
    result=tagged(prepared,lambda job,v:[job['start'],v[0]['start']+50],lambda job,v:None)
    run=propose(prepared,result,'b'*64,'c'*64,'vocals').timing_evidence['runs'][0]
    assert run['edges']=={'lead':True,'trail':True,'breath':None,'release':None}


def test_untagged_runs_have_no_edge_fields():
    original=line();u=original.units[1];u.source='manual'
    u.highlights=[Highlight(c,2500+i*700,3200+i*700,'manual' if i==2 else 'estimated') for i,c in enumerate(u.kana)]
    prepared=plan(original);new=propose(prepared,tagged(prepared),'b'*64,'c'*64,'vocals')
    assert ['edges' in r for r in new.timing_evidence['runs']]==[True,False,False]
    assert new.timing_evidence['runs'][0]['edges']['breath'] is None


def test_engine_without_tags_still_works_for_tagged_requests():
    prepared=plan(line());new=propose(prepared,inference(prepared),'b'*64,'c'*64,'vocals')
    assert new.timing_evidence['runs'][0]['edges']=={'lead':True,'trail':True,'breath':None,'release':None}


def test_voice_lookup_reads_new_and_old_engine_runs_only():
    p=line();mora={'start':1000,'end':1600,'kana':'キ','phones':[{'phone':'k','start':1000,'end':1050},{'phone':'i','start':1050,'end':1600}]}
    for engine in ('tifa-1.0-st-mora-cpu-v1','tifa-1.0-st-mora-cpu-v2'):
        p.timing_evidence={'engine':engine,'model_sha256':MODEL,'runs':[{'mora':[mora],'edges':{'lead':True,'trail':True,'breath':[900,1000],'release':None}}]}
        assert voice_lookup(p)=={(1000,1600):mora}
    p.timing_evidence['engine']='tifa-1.0-st-mora-cpu-v9'
    assert voice_lookup(p)=={}
