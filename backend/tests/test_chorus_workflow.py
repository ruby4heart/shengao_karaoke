import asyncio
import copy
import json
import uuid
import pytest
from studio_backend import chorus_workflow as flow
from test_chorus_reuse import fixture


def request(tmp_path,align=True):
    source,target=fixture();media=tmp_path/'source.wav';media.write_bytes(b'local workflow controls, not actual singing')
    return {'workflow_id':uuid.uuid4().hex,'source_line':source.to_dict(),'source_reading_confirmed':True,
        'lines':[target.to_dict()],'media':str(media),'chorus_options':{'align':align,'audio_role':'original','fit_range':False},
        'neighbor_lines':[source.to_dict(),target.to_dict()],'_studio_context':{'project':'controlled-project'}}


def run(req,home):return asyncio.run(flow.run(req,home,lambda *args:None))


def fake_voice(monkeypatch):
    calls=[]
    async def preflight(request,source_hash):
        calls.append('preflight');assert len(source_hash)==64 and request['draft_options']['acoustic_audio']=='original'
    async def generate(rows,request,root,report,checkpoint,completed):
        calls.append(('voice',copy.deepcopy(rows),copy.deepcopy(completed)))
        values=copy.deepcopy(rows);values[0]['units'][0]['highlights'][0]['end']-=20
        data={'suggestions':values,'partial':False,'acoustic':{'total':len(values),'aligned':len(values),'needs_manual':0},'acoustic_checkpoint':{'processed':{'control':True}}}
        checkpoint(data);return data
    monkeypatch.setattr(flow.singing_stage,'preflight',preflight);monkeypatch.setattr(flow.singing_stage,'run',generate)
    return calls


def test_new_target_voice_result_is_used_and_completed_work_is_reused(tmp_path,monkeypatch):
    req=request(tmp_path);before=copy.deepcopy(req);calls=fake_voice(monkeypatch);home=tmp_path/'home'
    data=run(req,home);assert not data['partial'] and data['review_required'] and req==before
    assert data['suggestions'][0]['units'][0]['kana']=='キミト' and data['suggestions'][0]['start']==15000
    initial=calls[1][1][0]['units'][0]['highlights'][0]['end']
    assert data['suggestions'][0]['units'][0]['highlights'][0]['end']==initial-20
    assert data['reading_reuse']['timing_copied'] is False and data['chorus_workflow']['status']=='completed'
    calls.clear();again=run({**req,'resume':True},home)
    assert calls==[] and again==data


def test_readings_only_requires_no_audio_or_model(tmp_path,monkeypatch):
    req=request(tmp_path,False);req['media']=''
    async def forbidden(*args):raise AssertionError('No model or audio request')
    monkeypatch.setattr(flow.singing_stage,'preflight',forbidden);monkeypatch.setattr(flow.singing_stage,'run',forbidden)
    data=run(req,tmp_path/'home');assert not data['partial'] and '尚未按声音重算' in data['message']
    assert all(h['source']=='estimated' for u in data['suggestions'][0]['units'] for h in u['highlights'])


def test_missing_engine_keeps_reading_candidates_and_can_resume(tmp_path,monkeypatch):
    req=request(tmp_path);home=tmp_path/'home'
    async def unavailable(*args):raise ValueError('模拟模型不可用')
    monkeypatch.setattr(flow.singing_stage,'preflight',unavailable)
    first=run(req,home);assert first['partial'] and first['suggestions'][0]['kana']=='キミトウタウ'
    assert flow.saved_result(req,home)==first
    calls=fake_voice(monkeypatch);data=run({**req,'resume':True},home)
    assert not data['partial'] and len(calls)==2


def test_cancelled_partial_result_resumes_against_immutable_prepared_axis(tmp_path,monkeypatch):
    req=request(tmp_path);home=tmp_path/'home';initial=[]
    async def preflight(*args):pass
    async def interrupted(rows,request,root,report,checkpoint,completed):
        initial.extend(copy.deepcopy(rows));values=copy.deepcopy(rows);values[0]['units'][0]['highlights'][0]['end']-=30
        checkpoint({'suggestions':values,'partial':True,'acoustic_checkpoint':{'processed':{'first-run':True}}})
        raise asyncio.CancelledError()
    monkeypatch.setattr(flow.singing_stage,'preflight',preflight);monkeypatch.setattr(flow.singing_stage,'run',interrupted)
    with pytest.raises(asyncio.CancelledError):run(req,home)
    cached=flow.saved_result(req,home);assert cached['partial'] and cached['suggestions'][0]['units'][0]['highlights'][0]['end']==initial[0]['units'][0]['highlights'][0]['end']-30
    calls=fake_voice(monkeypatch);run({**req,'resume':True},home)
    assert calls[1][1]==initial and calls[1][2]=={'processed':{'first-run':True}}


def test_corruption_and_changed_source_cannot_silently_reprocess(tmp_path,monkeypatch):
    req=request(tmp_path);home=tmp_path/'home';calls=fake_voice(monkeypatch);run(req,home);calls.clear()
    changed=copy.deepcopy(req);changed['source_line']['units'][0]['romaji']='different'
    with pytest.raises(ValueError,match='已变化'):run({**changed,'resume':True},home)
    assert calls==[]
    path=flow.path_for(home,req['workflow_id']);state=json.loads(path.read_text(encoding='utf-8'));state['data']['suggestions'][0]['kana']='破损'
    path.write_text(json.dumps(state),encoding='utf-8')
    with pytest.raises(ValueError,match='检查点无效'):run({**req,'resume':True},home)
    assert calls==[]


def test_protected_target_is_returned_unchanged_without_audio_work(tmp_path,monkeypatch):
    req=request(tmp_path);req['lines'][0]['reviewed']=True;before=copy.deepcopy(req['lines'])
    calls=fake_voice(monkeypatch);data=run(req,tmp_path/'home')
    assert calls==[] and data['suggestions']==before and data['reading_reuse']['eligible_ids']==[] and data['reading_reuse']['skipped']


def test_real_worker_serializes_local_reading_candidates_without_keys(tmp_path):
    from studio_backend import worker
    req={**request(tmp_path,False),'action':'chorus_reuse'};output=tmp_path/'result.json'
    asyncio.run(worker.execute(req,tmp_path/'home',output));data=json.loads(output.read_text(encoding='utf-8'))
    assert data['ok'] and not data['partial'] and data['suggestions'][0]['kana']=='キミトウタウ'
    assert data['chorus_workflow']['id']==req['workflow_id'] and data['review_required']


def test_worker_cancel_returns_saved_readings_and_partial_voice_result(tmp_path,monkeypatch):
    from studio_backend import worker
    req={**request(tmp_path),'action':'chorus_reuse'};home=tmp_path/'home';output=tmp_path/'cancel.json';entered=asyncio.Event()
    async def preflight(*args):pass
    async def pending(rows,request,root,report,checkpoint,completed):
        checkpoint({'suggestions':copy.deepcopy(rows),'partial':True,'acoustic_checkpoint':{'processed':{}}})
        entered.set();await asyncio.Future()
    monkeypatch.setattr(flow.singing_stage,'preflight',preflight);monkeypatch.setattr(flow.singing_stage,'run',pending)
    async def scenario():
        task=asyncio.create_task(worker.execute(req,home,output));await asyncio.wait_for(entered.wait(),3)
        from pathlib import Path
        Path(str(output)+'.cancel').touch();await asyncio.wait_for(task,3)
    asyncio.run(scenario());data=json.loads(output.read_text(encoding='utf-8'))
    assert data['ok'] and data['cancelled'] and data['partial'] and '云端' not in data['message']
    assert flow.load(home,req['workflow_id'])['status']=='paused' and data['suggestions'][0]['kana']=='キミトウタウ'


def test_voice_output_cannot_rewrite_reused_readings_or_translation(tmp_path,monkeypatch):
    req=request(tmp_path);home=tmp_path/'home'
    async def preflight(*args):pass
    async def bad_voice(rows,request,root,report,checkpoint,completed):
        values=copy.deepcopy(rows);values[0]['romaji']='unexpected rewrite'
        data={'suggestions':values,'partial':False};checkpoint(data);return data
    monkeypatch.setattr(flow.singing_stage,'preflight',preflight);monkeypatch.setattr(flow.singing_stage,'run',bad_voice)
    data=run(req,home)
    assert data['partial'] and data['suggestions'][0]['romaji']=='Kimi-to UTAU!' and '更改' in data['message']
