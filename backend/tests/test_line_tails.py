import copy
import threading
import numpy as np
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend import line_tails
from studio_backend.line_tails import analyze,apply,targets,validate_report
from studio_backend.sound_gaps import signature
from studio_backend.provenance import effective_kind,inferred

RATE=48000
BINDING={'audio_role':'vocals','source_sha256':'a'*64,'audio_sha256':'b'*64}


def voice(spans,seconds=4.,rate=RATE,fade=None):
    """Harmonic tone inside each (start_ms, end_ms) span; silence elsewhere."""
    t=np.arange(int(rate*seconds))/rate;data=np.zeros_like(t)
    for a,b in spans:
        m=(t>=a/1000)&(t<b/1000);data[m]=np.sin(2*np.pi*220*t[m])*.4+np.sin(2*np.pi*440*t[m])*.15
    if fade:
        a,b=fade;m=(t>=a/1000)&(t<b/1000);data[m]*=np.linspace(1,.01,m.sum())
    return np.round(data*32767).astype('<i2')


def line(uid='a',text='かなす',start=400,mora=((400,800,'か'),(800,1200,'な'),(1200,1600,'す')),end=None,tags=True):
    hs=[Highlight(k,a,b,'acoustic') for a,b,k in mora]
    value=LyricLine(uid,text,start,end or mora[-1][1]+200,[Unit(text,mora[0][0],mora[-1][1],''.join(k for _,_,k in mora),'acoustic',highlights=hs)])
    if tags:value.timing_evidence={'edge_tags':'ap-ep-v1','runs':[{'window':[start,value.end],'edges':{'lead':True,'trail':True,'breath':None,'release':None}}]}
    return value


def run(lines,data,tmp_path,role='vocals',indices=None):
    pcm=tmp_path/'v.s16';data.tofile(pcm)
    return analyze(lines,pcm,RATE,{**BINDING,'audio_role':role},indices)


def test_inspection_is_read_only_and_never_selects(tmp_path):
    p=line();before=p.to_dict()
    report=run([p],voice([(400,1600)]),tmp_path)
    tail=report['tails'][0]
    assert p.to_dict()==before and tail['status']=='ok' and tail['recommended'] is None
    validate_report(report)


def test_singing_after_the_highlight_is_flagged_as_cut(tmp_path):
    p=line(end=2400)
    report=run([p],voice([(400,2300)]),tmp_path)
    tail=report['tails'][0];codes={f['code'] for f in tail['flags']}
    assert 'cut' in codes and tail['status']=='flagged'
    names={c['name']:c['end'] for c in tail['candidates']}
    assert 'release' in names and abs(names['release']-2300)<=60
    assert tail['recommended'] in {'voicing','release'} and names[tail['recommended']]>1600


def test_original_mix_never_claims_cut_singing(tmp_path):
    p=line(end=2400)
    tail=run([p],voice([(400,2300)]),tmp_path,role='original')['tails'][0]
    assert 'cut' not in {f['code'] for f in tail['flags']}


def test_tail_dragged_into_silence_is_flagged_and_shorter_reference_offered(tmp_path):
    p=line()
    tail=run([p],voice([(400,1300)]),tmp_path)['tails'][0]
    assert 'silent' in {f['code'] for f in tail['flags']}
    names={c['name']:c['end'] for c in tail['candidates']}
    assert tail['recommended']=='release' and names['release']<1600 and abs(names['release']-1300)<=60


def test_model_tail_touching_its_range_end_is_flagged_only_for_release_tag_engine(tmp_path):
    tagged=line(end=1610);plain=line(uid='b',end=1610,tags=False)
    data=voice([(400,1600)])
    assert 'edge' in {f['code'] for f in run([tagged],data,tmp_path)['tails'][0]['flags']}
    assert 'edge' not in {f['code'] for f in run([plain],data,tmp_path)['tails'][0]['flags']}


def test_very_short_tail_is_flagged(tmp_path):
    p=line(mora=((400,800,'か'),(800,1550,'な'),(1550,1600,'す')))
    assert 'short' in {f['code'] for f in run([p],voice([(400,1600)]),tmp_path)['tails'][0]['flags']}


def test_tail_types(tmp_path):
    long=line(mora=((400,600,'か'),(600,800,'な'),(800,1700,'あ')),text='かなあ')
    weak=line(uid='w',mora=((2000,2300,'か'),(2300,2600,'な'),(2600,2780,'す')))
    data=voice([(400,1700),(2000,2700)])
    tails={v['line_id']:v for v in run([long,weak],data,tmp_path)['tails']}
    assert tails['a']['type']=='long' and tails['w']['type']=='weak'
    joined=line(mora=((400,800,'か'),(800,1200,'な'),(1200,1580,'あ')),text='かなあ')
    following=line(uid='n',mora=((1620,2000,'た'),(2000,2400,'ま')),text='たま',start=1620)
    tails={v['line_id']:v for v in run([joined,following],voice([(400,2400)]),tmp_path,indices=[0])['tails']}
    assert tails['a']['type']=='next' and tails['a']['recommended']=='next'
    assert {c['name']:c['end'] for c in tails['a']['candidates']}['next']==1620


def test_fading_tail_is_classified(tmp_path):
    p=line(mora=((400,700,'か'),(700,1000,'な'),(1000,1500,'あ')),text='かなあ')
    tail=run([p],voice([(400,1500)],fade=(1000,1500)),tmp_path)['tails'][0]
    assert tail['type']=='fade'


def test_repeated_chorus_line_with_different_tail_is_noted(tmp_path):
    a=line(uid='a',text='かなあ',mora=((400,600,'か'),(600,800,'な'),(800,1000,'あ')))
    b=line(uid='b',text='かなあ',start=2000,mora=((2000,2200,'か'),(2200,2400,'な'),(2400,3200,'あ')))
    tails={v['line_id']:v for v in run([a,b],voice([(400,1000),(2000,3200)]),tmp_path)['tails']}
    assert 'repeat' in {f['code'] for f in tails['a']['flags']} and 'repeat' in {f['code'] for f in tails['b']['flags']}


def test_human_locked_and_confirmed_tails_are_protected(tmp_path):
    manual=line(uid='m');manual.units[0].highlights[-1].source='manual'
    fixed=line(uid='f',start=2000,mora=((2000,2400,'か'),(2400,2800,'な')));fixed.units[0].highlights[-1].fixed_edges=['end']
    lock=line(uid='l');lock.locked=True
    done=line(uid='d');done.reviewed=True
    lines=[manual,fixed,lock,done];before=[v.to_dict() for v in lines]
    report=run(lines,voice([(400,3000)]),tmp_path)
    assert [v['status'] for v in report['tails']]==['protected']*4 and [v.to_dict() for v in lines]==before
    with pytest.raises(ValueError,match='保护'):apply(lines,report,{report['tails'][0]['key']:'release'})


def test_apply_moves_only_the_chosen_tail_with_provenance_and_keeps_onsets(tmp_path):
    p=line(end=2400);q=line(uid='q',start=3000,mora=((3000,3300,'た'),(3300,3600,'ま')),text='たま')
    lines=[p,q];report=run(lines,voice([(400,2300),(3000,3600)]),tmp_path)
    tail=report['tails'][0];names={c['name']:c['end'] for c in tail['candidates']}
    values,changes=apply(lines,report,{tail['key']:'release'})
    assert len(changes)==1 and lines[0].units[0].highlights[-1].end==1600
    h=values[0].units[0].highlights[-1]
    assert h.end==names['release'] and h.start==1200 and values[0].units[0].end==names['release']
    assert [x.start for x in values[0].units[0].highlights]==[400,800,1200]
    assert effective_kind(inferred(h))=='estimated' and 'sound_tail' in h.timing_origin['operations']
    assert values[0].timing_evidence['tail_checks'][-1]['choice']=='release' and values[0].timing_evidence['edge_tags']=='ap-ep-v1'
    assert values[1].to_dict()==q.to_dict() and not values[0].reviewed


def test_extension_past_range_end_grows_the_line_but_never_past_next_onset(tmp_path):
    p=line(end=1610);q=line(uid='q',start=1900,mora=((1900,2300,'た'),(2300,2700,'ま')),text='たま')
    report=run([p,q],voice([(400,2700)]),tmp_path,indices=[0])
    tail=report['tails'][0]
    assert tail['limit']==1900 and all(c['end']<=1900 for c in tail['candidates'])
    values,_=apply([p,q],report,{tail['key']:'next'})
    assert values[0].units[0].highlights[-1].end==1900 and values[0].end==1900 and values[1].start==1900


def test_manual_line_range_is_never_extended(tmp_path):
    p=line(end=1610);p.timing_origin={'version':1,'kind':'manual','provider':'local','method':'','reference':[400,1610],'current':[400,1610]}
    tail=run([p],voice([(400,2600)]),tmp_path)['tails'][0]
    assert tail['limit']==1610 and all(c['end']<=1610 for c in tail['candidates'])


def test_stale_or_tampered_results_are_refused(tmp_path):
    p=line(end=2400);report=run([p],voice([(400,2300)]),tmp_path);key=report['tails'][0]['key']
    edited=copy.deepcopy([p]);edited[0].units[0].highlights[0].end=790
    with pytest.raises(ValueError,match='已变化'):apply(edited,report,{key:'release'})
    forged=copy.deepcopy(report);forged['tails'][0]['candidates'][0]['end']=2399
    with pytest.raises(ValueError,match='已变化'):apply([p],forged,{key:forged['tails'][0]['candidates'][0]['name']})
    with pytest.raises(ValueError,match='候选'):apply([p],report,{key:'missing'})


def test_cancel_keeps_timing(tmp_path):
    p=line();before=signature([p]);cancel=threading.Event();cancel.set()
    pcm=tmp_path/'v.s16';voice([(400,1600)]).tofile(pcm)
    with pytest.raises(ValueError,match='取消'):analyze([p],pcm,RATE,BINDING,cancel=cancel)
    assert signature([p])==before


def test_silent_range_is_unavailable_not_flagged_as_problem(tmp_path):
    tail=run([line()],voice([]),tmp_path)['tails'][0]
    assert tail['status']=='unavailable' and tail['candidates']==[]


def test_release_tag_span_is_carried_for_display(tmp_path):
    p=line();p.timing_evidence['runs']=[{'window':[300,2000],'edges':{'lead':True,'trail':True,'breath':None,'release':[1600,1900]}}]
    assert targets([p])[0]['release_span']==[1600,1900] and targets([p])[0]['model_tail']


def test_fixed_line_end_is_not_reported_as_a_model_tail(tmp_path):
    p=line(end=1610);p.timing_evidence['runs'][0]['edges']['trail']=False
    assert not targets([p])[0]['model_tail']
    assert 'edge' not in {f['code'] for f in run([p],voice([(400,1600)]),tmp_path)['tails'][0]['flags']}


def test_one_adoption_leaves_other_unchanged_lines_adoptable(tmp_path):
    p=line(end=2400);q=line(uid='q',start=3000,mora=((3000,3300,'た'),(3300,3500,'ま')),text='たま',end=4400)
    lines=[p,q];report=run(lines,voice([(400,2300),(3000,4300)],seconds=5),tmp_path)
    first,second=report['tails']
    assert first['status']=='flagged' and second['status']=='flagged'
    values,_=apply(lines,report,{first['key']:'release'})
    assert line_tails.stale_rows(values,report)=={first['key']}
    again,changes=apply(values,report,{second['key']:second['candidates'][0]['name']})
    assert len(changes)==1 and again[0].to_dict()==values[0].to_dict()
    with pytest.raises(ValueError,match='已变化'):apply(values,report,{first['key']:'release'})


def test_edit_elsewhere_does_not_block_but_own_text_edit_does(tmp_path):
    p=line(end=2400);q=line(uid='q',start=3000,mora=((3000,3300,'た'),(3300,3600,'ま')),text='たま')
    report=run([p,q],voice([(400,2300),(3000,3600)]),tmp_path,indices=[0]);key=report['tails'][0]['key']
    other=copy.deepcopy([p,q]);other[1].translation='别处的译文'
    assert apply(other,report,{key:'release'})[1]
    own=copy.deepcopy([p,q]);own[0].translation='本句译文'
    with pytest.raises(ValueError,match='已变化'):apply(own,report,{key:'release'})


def test_quick_flags_need_no_audio_and_skip_protected_lines():
    short=line(mora=((400,800,'か'),(800,1550,'な'),(1550,1600,'す')))
    edge=line(uid='e',start=2000,mora=((2000,2400,'か'),(2400,2800,'な')),end=2810)
    fine=line(uid='f',start=3000,mora=((3000,3400,'か'),(3400,3800,'な')))
    done=line(uid='d',start=4000,mora=((4000,4400,'か'),(4400,4420,'な')));done.reviewed=True
    found={t['line_id']:{f['code'] for f in v} for t,v in line_tails.quick_flags([short,edge,fine,done])}
    assert found=={'a':{'short'},'e':{'edge'}}
