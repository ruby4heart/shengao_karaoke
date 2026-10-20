import copy
import pytest
from studio_backend.model import LyricLine,Unit
from studio_backend.acoustic_batch import prepare,finalize

def lyric():return LyricLine('a','君を',1000,2500,[Unit('君を',1000,2500,'きみを','kimiwo',reading_source='manual')],kana='きみを',romaji='kimiwo',translation='保持')

def inference(p):
    job=p['plan']['jobs'][0];rows=[]
    for i,m in enumerate(job['mora']):
        a=950+400*i;b=a+350;rows.append({**m,'start':a,'end':b,'phones':[{'phone':'structural fixture','start':a,'end':b}]})
    return {'engine':'test','model_sha256':'a'*64,'timestep_ms':10,'jobs':[{'index':0,'mora':rows,'agreement':.6}]}

def test_automatic_range_fit_uses_voice_and_preserves_readings_translation():
    old=lyric();p=prepare(old,3000);assert p['plan']['original']['start']==500 and p['plan']['original']['end']==3000
    new=finalize(p,inference(p),'b'*64,'c'*64,'original')
    assert (new.start,new.end)==(950,2100) and new.kana==old.kana and new.romaji==old.romaji and new.translation==old.translation
    assert new.units[0].reading_source=='manual' and not new.reviewed and new.timing_evidence['input_range']==[1000,2500]
    assert new.timing_evidence['notes']==[] # search padding is outside the fitted lyric

def test_fit_refuses_conflicting_manual_presentation_instead_of_changing_it():
    old=lyric();old.display_start=990;p=prepare(old,3000)
    with pytest.raises(ValueError,match='留屏'):finalize(p,inference(p),'b'*64,'c'*64,'original')
    assert old.display_start==990 and old.start==1000

@pytest.mark.parametrize('protection',['line','review','word','manual_time','uncertain','unmatched'])
def test_global_acoustics_never_overwrites_human_or_ambiguous_ranges(protection):
    old=lyric()
    if protection=='line':old.locked=True
    if protection=='review':old.reviewed=True
    if protection=='word':old.units[0].locked=True
    if protection=='manual_time':old.units[0].source='manual'
    if protection in {'uncertain','unmatched'}:old.match={'status':protection}
    with pytest.raises(ValueError):prepare(old,3000)

def test_exact_sixty_second_range_does_not_gain_invalid_padding():
    old=lyric();old.start=0;old.end=60000;old.units[0].start=0;old.units[0].end=60000
    assert prepare(old,65000)['plan']['jobs'][0]['end']==60000


def test_search_padding_stops_at_neighbor_ranges_without_erasing_overlaps():
    old=lyric();previous=LyricLine('prev','前',100,900);following=LyricLine('next','後',2700,2900)
    job=prepare(old,4000,neighbors=[previous,old,following])['plan']['jobs'][0]
    assert (job['start'],job['end'])==(900,2700)
    previous.end=1200;following.start=2400
    job=prepare(old,4000,neighbors=[previous,old,following])['plan']['jobs'][0]
    assert (job['start'],job['end'])==(old.start,old.end)
