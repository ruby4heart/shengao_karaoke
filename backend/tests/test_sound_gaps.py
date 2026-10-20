import copy
import threading
import numpy as np
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.sound_gaps import analyze,apply,measurements,classify,targets,signature

BINDING={'audio_role':'vocals','source_sha256':'a'*64,'audio_sha256':'b'*64}


def sound(rate=48000):
    t=np.arange(rate*2)/rate
    return np.round((np.sin(2*np.pi*220*t)*.4+np.sin(2*np.pi*440*t)*.15)*32767).astype('<i2')


def line():
    return LyricLine('a','かな',400,1600,[Unit('かな',400,1600,'かな',highlights=[Highlight('か',400,900),Highlight('な',1000,1600)])])


def test_continuous_vocals_and_original_accompaniment_have_different_decisions():
    metrics=measurements(sound(),48000,900,1000)
    assert classify(metrics,'vocals')[0]=='continuous'
    assert classify(metrics,'original')[0]=='uncertain'


def test_short_real_silence_is_kept_inside_short_gap():
    data=sound();data[round(.915*48000):round(.985*48000)]=0
    metrics=measurements(data,48000,900,1000)
    assert metrics['quiet_ms']>=25 and classify(metrics,'vocals')[0]=='quiet'


def test_unvoiced_noise_is_not_called_continuous_vocals():
    rng=np.random.default_rng(42);data=(rng.normal(0,.2,96000)*32767).astype('<i2')
    assert classify(measurements(data,48000,900,1000),'vocals')[0]=='uncertain'


def test_inspection_is_read_only_and_manual_gap_is_protected(tmp_path):
    original=line();original.units[0].highlights[0].source='manual';before=original.to_dict()
    pcm=tmp_path/'v.s16';sound().tofile(pcm)
    report=analyze([original],pcm,48000,BINDING)
    assert report['gaps'][0]['status']=='protected' and original.to_dict()==before


def test_missing_pcm_context_is_not_a_join():
    assert classify(measurements(sound(),48000,1980,2100),'vocals')[0]=='unavailable'


def test_cancel_does_not_change_any_timing(tmp_path):
    p=line();before=signature([p]);cancel=threading.Event();cancel.set()
    pcm=tmp_path/'v.s16';sound().tofile(pcm)
    with pytest.raises(ValueError,match='取消'):analyze([p],pcm,48000,BINDING,cancel=cancel)
    assert signature([p])==before


def test_shorter_threshold_never_overrides_manual_or_forces_a_join():
    p=line();assert targets([p],maximum=50)[0]['protected']
    assert not targets([p],maximum=200)[0]['protected']


@pytest.mark.parametrize('rate,start,end',[(True,1,2),(48000,True,10),(48000,5,5),(48000,-1,10),(7999,1,2),(48000,1.5,2)])
def test_invalid_clock_is_rejected(rate,start,end):
    with pytest.raises(ValueError):measurements(sound(),rate,start,end)


def checked(tmp_path,p=None,data=None):
    p=p or line();pcm=tmp_path/'voices.s16';(sound() if data is None else data).tofile(pcm)
    return p,analyze([p],pcm,48000,BINDING)


def test_adoption_changes_only_tail_and_keeps_following_manual_anchor(tmp_path):
    p=line();p.units[0].highlights[1].source='manual';before=p.to_dict();p,report=checked(tmp_path,p)
    assert report['gaps'][0]['status']=='continuous'
    values,changes=apply([p],report,[report['gaps'][0]['key']])
    updated=values[0]
    assert p.to_dict()==before and len(changes)==1 and updated.units[0].highlights[0].end==1000
    assert updated.units[0].highlights[1]==p.units[0].highlights[1]
    assert updated.text==p.text and updated.units[0].kana==p.units[0].kana and not updated.reviewed
    assert 'sound_gap' in updated.units[0].highlights[0].timing_origin['operations']
    assert updated.timing_evidence['gap_checks'][0]['binding']==BINDING


def test_quiet_gap_needs_explicit_manual_decision(tmp_path):
    data=sound();data[round(.915*48000):round(.985*48000)]=0
    p,report=checked(tmp_path,data=data);key=report['gaps'][0]['key']
    with pytest.raises(ValueError,match='试听'):apply([p],report,[key])
    values,_=apply([p],report,[key],manual=[key])
    h=values[0].units[0].highlights[0]
    assert h.source=='manual' and 'manual_boundary' in h.timing_origin['operations']


def test_late_edit_and_protected_tail_cannot_be_overwritten(tmp_path):
    p,report=checked(tmp_path);key=report['gaps'][0]['key'];p.translation='保留新译文'
    with pytest.raises(ValueError,match='变化'):apply([p],report,[key])
    p=line();p.units[0].highlights[0].source='manual';p,report=checked(tmp_path,p);key=report['gaps'][0]['key']
    with pytest.raises(ValueError,match='保护'):apply([p],report,[key],manual=[key])


def test_retained_phoneme_requires_exact_audio_binding_and_reading(tmp_path):
    p=line();binding={**BINDING,'audio_role':'original'}
    p.timing_evidence={**binding,'engine':'tifa-1.0-st-mora-cpu-v1','model_sha256':'8d9bf896da1827f36bf135f80c7ab1fc4f3c1d48f328818b8402c9527c0f014b',
        'runs':[{'mora':[{'start':400,'end':1000,'kana':'か','phones':[{'phone':'k','start':400,'end':450},{'phone':'a','start':450,'end':1000}]}]}]}
    pcm=tmp_path/'v.s16';sound().tofile(pcm)
    assert analyze([p],pcm,48000,binding)['gaps'][0]['status']=='continuous'
    assert analyze([p],pcm,48000,{**binding,'audio_sha256':'c'*64})['gaps'][0]['status']=='uncertain'
    p.timing_evidence['runs'][0]['mora'][0]['kana']='き'
    assert analyze([p],pcm,48000,binding)['gaps'][0]['status']=='uncertain'


def test_scope_does_not_bridge_nonadjacent_selected_lines():
    values=[]
    for n in range(3):
        p=line();p.id=str(n);p.start+=n*2000;p.end+=n*2000
        for u in p.units:
            u.start+=n*2000;u.end+=n*2000
            for h in u.highlights:h.start+=n*2000;h.end+=n*2000
        values.append(p)
    chosen=targets(values,5000,True,[0,2])
    assert len(chosen)==2 and all(v['kind']=='mora' for v in chosen)


def test_real_leaf_origin_is_protected_even_if_old_source_flag_is_estimated():
    from studio_backend.provenance import create
    p=line();h=p.units[0].highlights[0];h.timing_origin=create('acoustic',h.start,h.end,'tifa')
    assert targets([p])[0]['protected']=='保留已有歌声音素边界'


def test_real_word_envelope_does_not_claim_estimated_inner_mora_is_fixed():
    from studio_backend.provenance import create
    p=line();u=p.units[0];u.source='acoustic';u.timing_origin=create('acoustic',u.start,u.end,'tifa')
    assert not targets([p])[0]['protected']


def test_modified_result_file_is_rejected_without_changing_input(tmp_path):
    p,report=checked(tmp_path);before=p.to_dict();report['gaps'][0]['status']='quiet'
    with pytest.raises(ValueError,match='结果不完整或已变化'):apply([p],report,[report['gaps'][0]['key']])
    assert p.to_dict()==before
