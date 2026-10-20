"""Controlled failures test orchestration; real-model singing has separate QA."""
import asyncio
import copy
import json
from pathlib import Path
import threading
import types
import uuid
import pytest
from studio_backend import draft,worker,singing_stage
from studio_backend.model import LyricLine,Unit
from studio_backend.settings import Settings

def request(tmp_path):
    media=tmp_path/'source.wav';media.write_bytes(b'controlled fixture, no audio inference or API')
    rows=[LyricLine(str(i),'今日',i*2500+100,i*2500+2100,[Unit('今日',i*2500+100,i*2500+2100,'きょう','kyou',reading_source='manual')],kana='きょう',romaji='kyou').to_dict() for i in range(2)]
    return {'action':'draft','workflow_id':uuid.uuid4().hex,'media':str(media),'lines':rows,'reading_confirmed_ids':['0','1'],
        'draft_options':{'source':'cloud','provider':'elevenlabs','readings':'dictionary','align':False,'acoustic':True,'acoustic_audio':'original','fit_range':True}}

def batch(rows,processed=1,partial=True):
    statuses={r['id']:{'status':'aligned','reason':'structural fixture'} for r in rows[:processed]}
    return {'suggestions':copy.deepcopy(rows),'partial':partial,'acoustic':{'total':len(rows),'processed':processed,'aligned':processed,'needs_manual':0,'reused':0,'model_loads':1,'source_sha256':'a'*64,'lines':statuses},'acoustic_checkpoint':{'processed':statuses}}

def operation(calls):
    async def call(req,root,report):
        calls.append(req['action'])
        if req['action']=='transcribe':return {'suggestions':[LyricLine('raw','今日',100,4500).to_dict()]}
        return {'suggestions':copy.deepcopy(req['lines'])}
    return call

def test_resume_local_failure_reuses_cloud_stages_and_passes_completed_lines(tmp_path,monkeypatch):
    req=request(tmp_path);home=tmp_path/'home';calls=[];received=[]
    monkeypatch.setattr(Settings,'key',lambda *x:'not-sent')
    def local(rows,source,track,root,cancel,report,checkpoint,fit,role,completed,work):
        received.append(completed)
        if completed is None:checkpoint(batch(rows));raise ValueError('controlled local interruption')
        assert completed['processed']['0']['status']=='aligned'
        return batch(rows,2,False)
    monkeypatch.setattr(singing_stage,'runtime',lambda:types.SimpleNamespace(preflight=lambda *a:None,generate=local))
    first=asyncio.run(draft.run(req,home,lambda *a:None,operation(calls)))
    assert first['partial'] and first['acoustic']['aligned']==1 and calls==['transcribe','match']
    final=asyncio.run(draft.run({**req,'resume':True},home,lambda *a:None,operation(calls)))
    assert not final['partial'] and final['acoustic']['aligned']==2 and len(received)==2
    assert calls==['transcribe','match'] and [s['key'] for s in final['workflow']['stages']]==['transcript','matching','readings','alignment','acoustic','preview']

def test_missing_local_model_is_reported_before_any_paid_operation(tmp_path,monkeypatch):
    req=request(tmp_path);calls=[]
    def missing(*args):raise ValueError('controlled missing engine')
    monkeypatch.setattr(singing_stage,'runtime',lambda:types.SimpleNamespace(preflight=missing))
    data=asyncio.run(draft.run(req,tmp_path/'home',lambda *a:None,operation(calls)))
    assert data['partial'] and not calls and 'missing engine' in data['message']

def test_async_cancel_joins_worker_before_saving_cancelled_stage(tmp_path,monkeypatch):
    req=request(tmp_path);home=tmp_path/'home';started=threading.Event();cleaned=threading.Event();calls=[]
    monkeypatch.setattr(Settings,'key',lambda *x:'not-sent')
    def local(rows,source,track,root,cancel,report,checkpoint,*args):
        checkpoint(batch(rows));started.set()
        try:
            assert cancel.wait(8)
            raise ValueError('controlled cancelled thread')
        finally:cleaned.set()
    monkeypatch.setattr(singing_stage,'runtime',lambda:types.SimpleNamespace(preflight=lambda *a:None,generate=local))
    async def check():
        task=asyncio.create_task(draft.run(req,home,lambda *a:None,operation(calls)))
        for _ in range(150):
            if started.is_set():break
            await asyncio.sleep(.02)
        assert started.is_set();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(check());assert cleaned.is_set()
    state=draft.load(home,req['workflow_id']);stage=next(s for s in state['stages'] if s['key']=='acoustic')
    assert stage['state']=='cancelled' and stage['result']['acoustic']['aligned']==1 and stage['result_hash']==draft.digest(stage['result'])

def test_confirmed_special_reading_and_custom_group_survive_matching():
    original=LyricLine('a','今日も',100,2100,[Unit('今日も',100,2100,'こんにちも','custom',reading_source='manual')],kana='こんにちも',romaji='custom').to_dict()
    coarse=LyricLine('a','今日も',300,2300,[Unit('今日',300,1800,'きょう'),Unit('も',1800,2300,'も')]).to_dict()
    new=draft.keep_readings(coarse,original,True)
    assert new['kana']=='こんにちも' and new['romaji']=='custom' and len(new['units'])==1
    assert new['units'][0]['reading_source']=='manual' and new['units'][0]['start']==300

def test_automatic_segmentation_cannot_turn_unmatched_range_into_voice_evidence(tmp_path,monkeypatch):
    req=request(tmp_path);req['draft_options']['source']='offline';req['lines'][0]['match']={'status':'unmatched','reason':'not located'}
    def local(rows,*args):
        assert rows[0]['match']['status']=='unmatched'
        value=batch(rows,2,False);value['acoustic']['aligned']=0;value['acoustic']['needs_manual']=2
        value['acoustic']['lines']={r['id']:{'status':'needs_manual','reason':'range unknown'} for r in rows};return value
    monkeypatch.setattr(singing_stage,'runtime',lambda:types.SimpleNamespace(preflight=lambda *a:None,generate=local))
    data=asyncio.run(draft.run(req,tmp_path/'home',lambda *a:None,worker.operation))
    assert not data['partial'] and data['acoustic']['needs_manual']==2
