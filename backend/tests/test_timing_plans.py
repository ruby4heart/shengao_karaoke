import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend import timing_plans
from studio_backend.timing_plans import analyze,apply,validate_report,stale_rows,alignment_line,scribe_lines,reading_variants,protected
from studio_backend.provenance import create


def line(uid='a',text='かなす',mora=((400,800,'か'),(800,1200,'な'),(1200,1600,'す')),source='acoustic',**kwargs):
    hs=[Highlight(k,a,b,source,timing_origin=create('acoustic',a,b,'tifa','tifa_mora',k)) for a,b,k in mora]
    unit=Unit(text,mora[0][0],mora[-1][1],''.join(k for _,_,k in mora),source=source,highlights=hs,
              timing_origin=create('acoustic',mora[0][0],mora[-1][1],'tifa','tifa_mora'))
    return LyricLine(uid,text,mora[0][0],mora[-1][1],[unit],kana=unit.kana,**kwargs)


def shifted(value,deltas,tail=0):
    """A copy whose syllable onsets move by the given ms each (and last end by ``tail``)."""
    out=copy.deepcopy(value);hs=out.units[0].highlights
    for h,d in zip(hs,deltas):h.start+=d
    for a,b in zip(hs,hs[1:]):a.end=b.start
    hs[-1].end+=tail;out.units[0].start=hs[0].start;out.units[0].end=hs[-1].end
    out.start=min(out.start,hs[0].start);out.end=max(out.end,hs[-1].end)
    if out.display_start is not None:out.display_start=min(out.display_start,out.start)
    if out.display_end is not None:out.display_end=max(out.display_end,out.end)
    for h in hs:h.timing_origin=create('acoustic',h.start,h.end,'tifa','tifa_mora',h.kana)
    out.units[0].timing_origin=create('acoustic',out.units[0].start,out.units[0].end,'tifa','tifa_mora')
    out.validate();return out


def source(value,note='本机'):return {'line':value,'note':note}


def test_conflicting_sources_are_listed_side_by_side_without_choosing():
    p=line();before=p.to_dict();vocals=shifted(p,[0,200,0])
    report=analyze([p],{'local_original':{0:source(copy.deepcopy(p))},'local_vocals':{0:source(vocals)}})
    validate_report(report);entry=report['lines'][0]
    assert p.to_dict()==before
    assert entry['status']=='conflict' and entry['level']=='conflict' and entry['spread']==200
    assert [v['id'] for v in entry['plans']]==['current','local_original','local_vocals']
    assert entry['plans'][1]['same'] and not entry['plans'][2]['same']
    assert [d['text'] for d in entry['differing']]==['な'] and entry['differing'][0]['outliers']==['local_vocals']
    assert 'な' in entry['reason'] and '人声辅助' in entry['reason']
    assert entry['grid'][1]['values']=={'current':800,'local_original':800,'local_vocals':1000}
    assert entry['plans'][2]['deviation']>entry['plans'][1]['deviation']


def test_close_sources_agree_and_single_source_lines_are_marked():
    p=line();q=line('b',mora=((2000,2400,'か'),(2400,2800,'な'),(2800,3200,'す')))
    report=analyze([p,q],{'local_original':{0:source(shifted(p,[30,-20,10]))}})
    first,second=report['lines']
    assert first['status']=='agree' and first['level']=='agree' and not first['differing']
    assert second['status']=='single' and [v['id'] for v in second['plans']]==['current']


def test_uncertain_matching_is_flagged_even_when_times_agree():
    p=line(match={'status':'uncertain','reason':'短读音'})
    report=analyze([p],{'local_original':{0:source(copy.deepcopy(p))}})
    assert report['lines'][0]['status']=='uncertain' and '不确定' in report['lines'][0]['reason']


@pytest.mark.parametrize('kind',['locked','reviewed','manual','fixed','unit_locked'])
def test_protected_lines_are_listed_read_only_and_never_adopted(kind):
    p=line()
    if kind=='locked':p.locked=True
    elif kind=='reviewed':p.reviewed=True
    elif kind=='unit_locked':p.units[0].locked=True
    elif kind=='manual':p.units[0].highlights[1].source='manual'
    else:p.units[0].highlights[1].fixed_edges=['start']
    assert protected(p)
    report=analyze([p],{'local_vocals':{0:source(shifted(line(),[0,200,0]))}})
    entry=report['lines'][0]
    assert entry['status']=='protected' and [v['id'] for v in entry['plans']]==['current'] and '已保护' in entry['reason']
    with pytest.raises(ValueError):apply([p],report,{'a':'local_vocals'})


def test_adopting_one_plan_is_one_change_and_keeps_translation_and_display():
    p=line(translation='保留',display_start=300,display_end=1800);q=line('b',mora=((2000,2400,'か'),(2400,2800,'な'),(2800,3200,'す')))
    vocals=shifted(p,[-200,0,0])
    report=analyze([p,q],{'local_vocals':{0:source(vocals),1:source(shifted(q,[0,150,0]))}})
    values,changes=apply([p,q],report,{'a':'local_vocals'})
    a=values[0]
    assert changes==[{'row':0,'line_id':'a','plan':'local_vocals','kind':'local_vocals','label':'本机模型 · 人声辅助','changes_reading':False}]
    assert a.units[0].highlights[0].start==200 and a.start==200 and a.display_start==200 and a.display_end==1800
    assert a.translation=='保留' and not a.reviewed and values[1].to_dict()==q.to_dict()
    history=a.timing_evidence['timing_plans'][-1]
    assert history['plan']=='local_vocals' and history['previous']==[400,1600] and history['report']==report['result_sha256']
    assert p.units[0].highlights[0].start==400


def test_stale_lines_unknown_plans_and_unchanged_plans_are_refused():
    p=line();report=analyze([p],{'local_original':{0:source(copy.deepcopy(p))},'local_vocals':{0:source(shifted(p,[0,200,0]))}})
    with pytest.raises(ValueError,match='相同'):apply([p],report,{'a':'local_original'})
    with pytest.raises(ValueError,match='不在'):apply([p],report,{'a':'scribe'})
    with pytest.raises(ValueError,match='不在'):apply([p],report,{'a':'current'})
    with pytest.raises(ValueError,match='没有选择'):apply([p],report,{})
    edited=copy.deepcopy(p);edited.units[0].highlights[0].kana='が';edited.units[0].kana='がなす';edited.kana='がなす'
    assert stale_rows([edited],report)=={'a'}
    with pytest.raises(ValueError,match='已修改'):apply([edited],report,{'a':'local_vocals'})
    tampered=copy.deepcopy(report);tampered['lines'][0]['plans'][2]['start']=0
    with pytest.raises(ValueError):apply([p],tampered,{'a':'local_vocals'})


def test_plan_that_would_overlap_a_protected_neighbour_is_refused():
    p=line();q=line('b',mora=((1700,2000,'か'),(2000,2300,'な'),(2300,2600,'す')),reviewed=True)
    late=shifted(p,[0,0,0],tail=300)
    report=analyze([p,q],{'local_vocals':{0:source(late)}})
    assert timing_plans.overlaps([p,q],report['lines'][0],report['lines'][0]['plans'][1])==[1]
    with pytest.raises(ValueError,match='重叠'):apply([p,q],report,{'a':'local_vocals'})


def test_plans_that_change_the_reading_need_the_reading_kind():
    p=line();other=copy.deepcopy(p);other.units[0].kana='がなす';other.units[0].highlights[0].kana='が';other.kana='がなす'
    other=shifted(other,[0,200,0])
    report=analyze([p],{'local_vocals':{0:source(other)}})
    with pytest.raises(ValueError,match='读音'):apply([p],report,{'a':'local_vocals'})


def test_text_alignment_needs_matching_words_and_redistributes_missing_syllables():
    p=line();saved=LyricLine('a','かなす',500,1700,[Unit('かなす',500,1700,'かなす',source='alignment',timing_origin=create('character',500,1700,'elevenlabs','text_alignment'))])
    value,note=alignment_line(p,saved.to_dict())
    assert value is not None and '不再请求' in note
    assert [(h.kana,h.start,h.end) for h in value.units[0].highlights]==[('か',500,900),('な',900,1300),('す',1300,1700)]
    assert value.units[0].timing_origin['provider']=='elevenlabs' and not value.reviewed
    wrong=copy.deepcopy(saved);wrong.units[0].kana='がなす'
    value,note=alignment_line(p,wrong)
    assert value is None and '读音' in note
    report=analyze([p],{'alignment':timing_plans.alignment_lines([p],{'a':saved.to_dict()},[0])})
    assert [v['id'] for v in report['lines'][0]['plans']]==['current','alignment']


def test_scribe_plan_rematches_the_stored_transcript_locally():
    p=LyricLine('a','今日も歌う',0,5000,[Unit('今日も',0,2500,'きょうも'),Unit('歌う',2500,5000,'うたう')])
    for u in p.units:
        from studio_backend.japanese import add_mora;add_mora(u)
    text='今日も歌う';rows=[LyricLine('asr',text,1000,2000,[Unit(c,1000+i*200,1200+i*200,source='recognition') for i,c in enumerate(text)])]
    found=scribe_lines([p],[r.to_dict() for r in rows])
    value=found[0]['line']
    assert value is not None and value.start==1000 and value.end==2000 and '可靠' in found[0]['note']
    report=analyze([p],{'scribe':found})
    entry=report['lines'][0]
    assert entry['status']=='conflict' and entry['plans'][1]['kind']=='scribe' and entry['plans'][1]['line']['match']['status']=='matched'
    assert scribe_lines([p],[])=={}


def test_confirmed_identical_chorus_lends_its_rhythm_at_the_consensus_position():
    ref=line('ref',mora=((10000,10300,'か'),(10300,10900,'な'),(10900,11200,'す')),reviewed=True)
    p=line();vocals=shifted(p,[100,100,100])
    report=analyze([ref,p],{'local_vocals':{1:source(vocals)}},indices=[1],confirmed={'ref'})
    entry=report['lines'][0];chorus=next(v for v in entry['plans'] if v['kind']=='chorus')
    hs=LyricLine.from_dict(chorus['line']).units[0].highlights
    assert [h.end-h.start for h in hs]==[300,600,300]
    assert chorus['label'].endswith('（第 1 句）') and '已人工确认' in chorus['note']
    assert hs[0].start in range(400,520)
    assert hs[0].timing_origin['method']=='chorus_rhythm'
    report=analyze([ref,p],{},indices=[1],confirmed=set())
    assert all(v['kind']!='chorus' for v in report['lines'][0]['plans'])
    other=line('ref',text='かなす',mora=((10000,10300,'か'),(10300,10900,'な'),(10900,11200,'ず')),reviewed=True)
    other.units[0].kana='かなず';other.kana='かなず'
    report=analyze([other,p],{},indices=[1],confirmed={'ref'})
    assert report['lines'][0]['unavailable'][0]['kind']=='chorus'


def test_reading_variants_change_one_word_and_compare_by_word():
    p=LyricLine('a','今日',1000,1600,[Unit('今日',1000,1600,'きょう','kyou',source='acoustic')],kana='きょう')
    from studio_backend.japanese import add_mora;add_mora(p.units[0])
    found=reading_variants(p)
    assert found and found[0]['kana']=='こんにち' and found[0]['source'] in timing_plans.READING_SOURCES
    variant=found[0]['line']
    assert variant.units[0].kana=='こんにち' and p.units[0].kana=='きょう'
    report=analyze([p],{'reading':{0:[{**found[0],'line':variant}]}})
    plan=report['lines'][0]['plans'][1]
    assert plan['kind']=='reading' and plan['changes_reading'] and plan['level']=='word' and 'こんにち' in plan['label']
    values,changes=apply([p],report,{'a':plan['id']})
    assert values[0].units[0].kana=='こんにち' and changes[0]['changes_reading']
    manual=copy.deepcopy(p);manual.units[0].reading_source='manual'
    assert reading_variants(manual)==[]


def test_unavailable_sources_are_explained_per_line_and_overall():
    p=line()
    report=analyze([p],{'local_original':{0:{'line':None,'note':'存在尚不支持的假名组合'}}},unavailable={'scribe':'没有与当前素材对应的 Scribe 转录'})
    entry=report['lines'][0]
    assert entry['unavailable']==[{'kind':'local_original','label':'本机模型 · 原声','reason':'存在尚不支持的假名组合'}]
    assert report['sources']['scribe']=={'label':'Scribe 转录时间','available':False,'note':'没有与当前素材对应的 Scribe 转录'}
    assert report['sources']['alignment']['available']


def test_local_batch_results_map_to_lines():
    p=line();q=line('b',mora=((2000,2400,'か'),(2400,2800,'な'),(2800,3200,'す')))
    result={'suggestions':[shifted(p,[0,50,0]).to_dict(),q.to_dict()],
            'acoustic':{'lines':{'a':{'status':'aligned','reason':'已生成歌声候选'},'b':{'status':'needs_manual','reason':'存在尚不支持的假名组合'}}}}
    found=timing_plans.local_lines([p,q],[0,1],result)
    assert found[0]['line'].units[0].highlights[1].start==850 and found[1]=={'line':None,'note':'存在尚不支持的假名组合'}
