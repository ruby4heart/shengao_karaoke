import copy
import pytest
from shengao import acoustic_audio as audio
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.provenance import create
from studio_backend.recalculation import prepare


def prepared():
    parts=[Highlight(k,i*1000,(i+1)*1000,'manual',create('manual' if i==1 else 'estimated',i*1000,(i+1)*1000,method='fixture')) for i,k in enumerate('あいう')]
    return prepare(LyricLine('cache','あいう',0,3000,[Unit('あいう',0,3000,'あいう',source='manual',highlights=parts)]))


def inference(plan):
    jobs=[]
    for i,job in enumerate(plan['jobs']):
        rows=[];count=len(job['mora'])
        for n,m in enumerate(job['mora']):
            a=job['start']+round((job['end']-job['start'])*n/count)+10
            b=job['start']+round((job['end']-job['start'])*(n+1)/count)-10
            rows.append({**m,'start':a,'end':b,'phones':[{'phone':'fixture','start':a,'end':b}]})
        jobs.append({'index':i,'mora':rows})
    return {'engine':audio.ENGINE_VERSION,'model_sha256':audio.MODEL_SHA256,'timestep_ms':10,'jobs':jobs}


@pytest.mark.parametrize('kind',['error','invalid_boundary'])
def test_partial_result_never_masquerades_as_complete_cache(tmp_path,kind):
    plan=prepared();raw=inference(plan)
    if kind=='error':raw['jobs'][0]={'index':0,'error':'fixture failure'}
    else:raw['jobs'][0]['mora'][0]['start']=-1
    key=audio.cache_key(plan,'a'*64,'b'*64);audio.write_cache(tmp_path,key,raw)
    assert audio.read_cache(tmp_path,key,plan,'a'*64,'b'*64,'original') is None


def test_completed_recalculation_cache_remains_reusable(tmp_path):
    plan=prepared();raw=inference(plan);key=audio.cache_key(plan,'a'*64,'b'*64)
    audio.write_cache(tmp_path,key,raw)
    assert audio.read_cache(tmp_path,key,plan,'a'*64,'b'*64,'original')==raw
