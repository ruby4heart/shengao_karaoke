"""Token layout for the model's optional breath (AP) and release (EP) tags."""
import pytest
import alignment_engine as engine

DICTIONARY={'か':['k','a'],'い':['i']}
VOCABULARY={'AP':1,'EP':2,'ja/k':10,'ja/a':11,'ja/i':12}


def job(**edges):
    value={'start':5000,'end':7000,'mora':[{'unit':0,'highlight':0,'kana':'か','pronunciation':'か'},{'unit':0,'highlight':1,'kana':'い','pronunciation':'い'}]}
    if edges:value['edges']=edges
    return value


def test_untagged_job_keeps_v1_tokens_and_groups():
    phones,ids,groups,owners=engine.edge_tokens(job(),DICTIONARY,VOCABULARY)
    assert (phones,ids,groups,owners)==(['k','a','i'],[10,11,12],[1,1,2],[0,0,1])


def test_breath_and_release_are_separate_skippable_groups():
    phones,ids,groups,owners=engine.edge_tokens(job(lead=True,trail=True),DICTIONARY,VOCABULARY)
    assert ids==[1,10,11,12,2] and groups==[1,2,2,3,4] and owners==['lead',0,0,1,'trail']
    assert all(a<b for a,b in zip(sorted(set(groups)),sorted(set(groups))[1:]))


@pytest.mark.parametrize('edges',[{'lead':1},{'tail':True},{'trail':'yes'}])
def test_malformed_edge_request_is_refused(edges):
    with pytest.raises(ValueError,match='edge'):engine.edge_tokens(job(**edges),DICTIONARY,VOCABULARY)


def test_tag_spans_never_enter_mora_and_are_reported_separately():
    value=job(lead=True,trail=True);phones,_,_,owners=engine.edge_tokens(value,DICTIONARY,VOCABULARY)
    spans=[(0.0,0.25),(0.25,0.30),(0.30,0.70),(0.72,1.10),(1.10,1.60)]
    output=engine.collect(value,phones,owners,spans)
    assert [(m['start'],m['end']) for m in output['mora']]==[(5250,5700),(5720,6100)]
    assert [p['phone'] for m in output['mora'] for p in m['phones']]==['k','a','i']
    assert output['edges']=={'breath':[5000,5250],'release':[6100,6600]}


def test_skipped_tag_reports_none_and_untagged_job_has_no_edges():
    value=job(lead=True,trail=True);phones,_,_,owners=engine.edge_tokens(value,DICTIONARY,VOCABULARY)
    output=engine.collect(value,phones,owners,[(0.1,0.1),(0.1,0.3),(0.3,0.7),(0.7,1.2),(1.2,1.2)])
    assert output['edges']=={'breath':None,'release':None} and output['mora'][0]['start']==5100
    plain=job();phones,_,_,owners=engine.edge_tokens(plain,DICTIONARY,VOCABULARY)
    assert 'edges' not in engine.collect(plain,phones,owners,[(0,.2),(.2,.5),(.5,.9)])


def test_engine_contract_version_marks_the_new_token_layout():
    assert engine.ENGINE_VERSION=='tifa-1.0-st-mora-cpu-v2'
