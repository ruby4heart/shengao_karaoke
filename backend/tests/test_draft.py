import asyncio
import copy
import json
import uuid
import pytest
from studio_backend import draft,worker,api
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.settings import Settings,atomic_json


def request(tmp_path,cloud=False,align=False):
    media=tmp_path/'source.wav';media.write_bytes(b'local synthetic fixture, no API')
    return {'action':'draft','workflow_id':uuid.uuid4().hex,'media':str(media),'language':'ja',
            'draft_options':{'source':'cloud' if cloud else 'offline','readings':'deepseek' if cloud else 'dictionary','align':align},
            'lines':[LyricLine('line','今日も歌う',100,2100).to_dict()],
            '_studio_context':{'project':'test-project','media':{'path':str(media)}}}


def stages(req,home):return draft.load(home,req['workflow_id'])['stages']


def fake_operations(monkeypatch,fail=None,partial=False):
    monkeypatch.setattr(Settings,'key',lambda self,p:'test-never-sent')
    calls=[]
    async def operation(req,root,report):
        action=req['action'];calls.append(action)
        if action==fail:raise api.ApiError('模拟等待中断',{'phase':'reading_response','request_id':'fake-request'})
        if action=='transcribe':return {'suggestions':[LyricLine('transcript','今日も歌う',300,2400).to_dict()]}
        rows=copy.deepcopy(req['lines'])
        if action=='refine':
            rows[0]['translation']='AI 译文'
            if partial:return {'suggestions':rows[:1],'partial':True,'message':'后续模拟批次失败'}
        return {'suggestions':rows}
    return calls,operation


def run(req,home,operation=worker.operation):
    return asyncio.run(draft.run(req,home,lambda *args:None,operation))


def test_legacy_v018_completed_checkpoint_keeps_signature_and_never_reruns(tmp_path):
    from pathlib import Path
    state=json.loads((Path(__file__).parent/'fixtures/v018-offline-draft-state.json').read_text(encoding='utf-8'))
    home=tmp_path/'legacy';path=draft.checkpoint_path(home,state['id']);atomic_json(path,state)
    async def forbidden(*args):raise AssertionError('A completed old stage must not run again')
    data=run({**state['request'],'workflow_id':state['id'],'resume':True},home,forbidden)
    assert not data['partial'] and data['suggestions']==draft.result(state)['suggestions']
    assert draft.load(home,state['id'])['signature']==state['signature']


def test_sequence_review_survives_later_stages_and_completed_checkpoint_recovery(tmp_path,monkeypatch):
    from studio_backend.matching import match_lyrics
    req=request(tmp_path,True);home=tmp_path/'home';calls=[]
    monkeypatch.setattr(Settings,'key',lambda *args:'test-never-sent')
    async def operation(value,root,report):
        calls.append(value['action'])
        if value['action']=='transcribe':return {'suggestions':[LyricLine('asr','今日も歌う追加の語句',1000,4000).to_dict()]}
        if value['action']=='match':return match_lyrics([LyricLine.from_dict(v) for v in value['lines']],[LyricLine.from_dict(v) for v in value['transcript']])
        return {'suggestions':copy.deepcopy(value['lines'])}
    data=run(req,home,operation);evidence=data['sequence_review']
    assert not data['partial'] and evidence['unassigned_transcript']
    assert evidence==next(s for s in stages(req,home) if s['key']=='matching')['result']['sequence_review']
    calls.clear();again=run({**req,'resume':True},home,operation)
    assert calls==[] and again['sequence_review']==evidence and again['suggestions']==data['suggestions']


def test_offline_pipeline_executes_real_dictionary_preview_and_roundtrip(tmp_path,monkeypatch):
    req=request(tmp_path);home=tmp_path/'home'
    async def forbidden(*args):raise AssertionError('offline workflow must not call cloud')
    monkeypatch.setattr(api,'deepseek_annotate',forbidden);monkeypatch.setattr(api,'eleven_align',forbidden);monkeypatch.setattr(api,'eleven_transcribe',forbidden)
    output=tmp_path/'result.json';asyncio.run(worker.execute(req,home,output))
    data=json.loads(output.read_text(encoding='utf-8'));assert data['ok'] and not data['partial']
    line=LyricLine.from_dict(data['suggestions'][0]);assert line.text=='今日も歌う' and line.id=='line'
    assert line.units and all(u.highlights for u in line.units) and not line.reviewed
    assert '均分估算' in data['message'];assert [s['state'] for s in stages(req,home)]==['skipped','completed','completed','skipped','skipped','completed']
    monkeypatch.setattr(Settings,'key',lambda *args:pytest.fail('completed workflow should not read any keys'))
    again=run({**req,'resume':True},home)
    assert again['suggestions']==data['suggestions'] and draft.latest(home,'test-project')['id']==req['workflow_id']


def test_failure_preserves_prior_draft_no_automatic_retry_then_resumes_exact_stage(tmp_path,monkeypatch):
    req=request(tmp_path,True,True);home=tmp_path/'home';calls,operation=fake_operations(monkeypatch,fail='refine')
    data=run(req,home,operation);assert data['partial'] and data['suggestions'] and data['transcript']
    assert calls==['transcribe','match','refine']
    blocked=run({**req,'resume':True},home,operation)
    assert calls==['transcribe','match','refine'] and blocked['workflow']['status']=='paused'
    assert '服务记录' in blocked['message']
    calls2,good=fake_operations(monkeypatch)
    final=run({**req,'resume':True,'retry_stage':'readings'},home,good)
    assert not final['partial'] and calls2==['refine','align']
    assert final['suggestions'][0]['translation']=='AI 译文'


def test_interrupted_paid_stage_does_not_restart_after_process_loss(tmp_path,monkeypatch):
    req=request(tmp_path,True);home=tmp_path/'home';calls,operation=fake_operations(monkeypatch,fail='refine')
    run(req,home,operation);state=draft.load(home,req['workflow_id']);state['stages'][2]['state']='running'
    atomic_json(draft.checkpoint_path(home,req['workflow_id']),state)
    calls2,good=fake_operations(monkeypatch);data=run({**req,'resume':True},home,good)
    assert calls2==[] and data['partial'] and data['suggestions']


def test_completed_checkpoint_corruption_cannot_trigger_billable_replay(tmp_path,monkeypatch):
    req=request(tmp_path,True);home=tmp_path/'home';calls,operation=fake_operations(monkeypatch)
    run(req,home,operation);state=draft.load(home,req['workflow_id']);state['stages'][0]['result']['suggestions'][0]['text']='corrupt'
    atomic_json(draft.checkpoint_path(home,req['workflow_id']),state);calls.clear()
    with pytest.raises(ValueError,match='损坏'):run({**req,'resume':True},home,operation)
    assert not calls


@pytest.mark.parametrize('change',['lyrics','media','options','model'])
def test_changed_inputs_never_reuse_old_stage_as_new_work(tmp_path,monkeypatch,change):
    req=request(tmp_path,True);home=tmp_path/'home';calls,operation=fake_operations(monkeypatch)
    run(req,home,operation);calls.clear();altered=copy.deepcopy(req)
    if change=='lyrics':altered['lines'][0]['text']='明日も歌う'
    elif change=='media':(__import__('pathlib').Path(req['media'])).write_bytes(b'changed audio')
    elif change=='options':altered['draft_options']['align']=True
    else:atomic_json(home/'settings.json',{'deepseek':{'model':'different-test-model'}})
    with pytest.raises(ValueError,match='变化'):run({**altered,'resume':True},home,operation)
    assert not calls


@pytest.mark.parametrize('kind',['line-lock','unit-lock','reviewed','manual','manual-mora'])
def test_manual_confirmed_and_locked_input_cannot_reach_pipeline_cloud(tmp_path,monkeypatch,kind):
    req=request(tmp_path,True);line=LyricLine.from_dict(req['lines'][0])
    if kind=='line-lock':line.locked=True
    elif kind=='reviewed':line.reviewed=True
    else:
        line.units=[Unit(line.text,line.start,line.end,'きょうもうたう')]
        if kind=='unit-lock':line.units[0].locked=True
        elif kind=='manual':line.units[0].source='manual'
        else:line.units[0].highlights=[Highlight('きょうもうたう',line.start,line.end,'manual')]
    req['lines']=[line.to_dict()];calls,operation=fake_operations(monkeypatch)
    with pytest.raises(ValueError,match='人工校准'):run(req,tmp_path/'home',operation)
    assert not calls


def test_missing_later_key_stops_before_first_paid_submission(tmp_path,monkeypatch):
    req=request(tmp_path,True);home=tmp_path/'home';calls,operation=fake_operations(monkeypatch)
    monkeypatch.setattr(Settings,'key',lambda self,p:'' if p=='deepseek' else 'test-never-sent')
    data=run(req,home,operation)
    assert calls==[] and data['partial'] and 'deepseek' in data['message']
    assert all(s['state']=='pending' for s in stages(req,home))
    monkeypatch.setattr(Settings,'key',lambda self,p:'test-never-sent')
    resumed=run({**req,'resume':True},home,operation);assert not resumed['partial'] and calls==['transcribe','match','refine']


def test_cancelled_worker_returns_partial_draft_and_marks_paused(tmp_path,monkeypatch):
    req=request(tmp_path,True);home=tmp_path/'home';calls,operation=fake_operations(monkeypatch)
    entered=asyncio.Event()
    async def dispatch(value,root,report):
        if value['action']=='draft':return await draft.run(value,root,report,dispatch)
        if value['action']=='refine':entered.set();await asyncio.Future()
        return await operation(value,root,report)
    monkeypatch.setattr(worker,'operation',dispatch)
    async def scenario():
        output=tmp_path/'cancelled.json';task=asyncio.create_task(worker.execute(req,home,output))
        await asyncio.wait_for(entered.wait(),3);(__import__('pathlib').Path(str(output)+'.cancel')).touch();await asyncio.wait_for(task,3)
        return json.loads(output.read_text(encoding='utf-8'))
    data=asyncio.run(scenario());assert data['ok'] and data['cancelled'] and data['suggestions']
    assert stages(req,home)[2]['state']=='cancelled' and data['workflow']['status']=='paused'
    calls2,good=fake_operations(monkeypatch);run({**req,'resume':True},home,good);assert calls2==[]


def test_partial_reading_batch_keeps_all_rows_and_does_not_start_alignment(tmp_path,monkeypatch):
    req=request(tmp_path,True,True);req['lines'].append(LyricLine('second','明日も歌う',2500,4500).to_dict())
    calls,operation=fake_operations(monkeypatch,partial=True);data=run(req,tmp_path/'home',operation)
    assert data['partial'] and len(data['suggestions'])==2
    assert data['suggestions'][0]['translation']=='AI 译文' and data['suggestions'][1]['translation']==''
    assert calls==['transcribe','match','refine']


def test_stage_output_cannot_replace_original_text_or_mark_human_confirmation(tmp_path,monkeypatch):
    req=request(tmp_path);calls,operation=fake_operations(monkeypatch)
    async def bad(value,root,report):
        result=await operation(value,root,report)
        if value['action']=='segment':result['suggestions'][0]['text']='changed lyrics'
        return result
    data=run(req,tmp_path/'home',bad);assert data['partial'] and not data['suggestions'] and '改变了原歌词' in data['message']
    assert calls==['segment']


def test_media_replaced_during_stage_cannot_flow_into_matching(tmp_path,monkeypatch):
    req=request(tmp_path,True);calls,operation=fake_operations(monkeypatch)
    async def replace(value,root,report):
        data=await operation(value,root,report)
        if value['action']=='transcribe':(__import__('pathlib').Path(req['media'])).write_bytes(b'replaced')
        return data
    data=run(req,tmp_path/'home',replace);assert data['partial'] and not data['suggestions'] and calls==['transcribe']


def test_workflow_lock_blocks_concurrent_execution_and_releases_normally(tmp_path):
    path=tmp_path/'test.lock'
    with draft.exclusive(path):
        with pytest.raises(ValueError,match='另一个进程'):
            with draft.exclusive(path):pytest.fail('duplicate workflow acquired lock')
    with draft.exclusive(path):pass


def test_manual_display_windows_and_confirmed_readings_survive_offline_flow(tmp_path):
    req=request(tmp_path);line=LyricLine('line','今日',100,2100,[Unit('今日',100,2100,'こんにち','konnichi',reading_source='manual')],kana='こんにち',romaji='konnichi',translation='原译文',display_start=20,display_end=2500)
    req['lines']=[line.to_dict()];req['reading_confirmed_ids']=['line']
    data=run(req,tmp_path/'home');row=data['suggestions'][0]
    assert row['kana']=='こんにち' and row['romaji']=='konnichi' and row['translation']=='原译文'
    assert row['display_start']==20 and row['display_end']==2500 and not row['reviewed']


def test_previous_partial_readings_remain_available_if_explicit_retry_fails(tmp_path,monkeypatch):
    req=request(tmp_path,True);home=tmp_path/'home';calls,operation=fake_operations(monkeypatch,partial=True)
    first=run(req,home,operation);assert first['suggestions'][0]['translation']=='AI 译文'
    calls2,bad=fake_operations(monkeypatch,fail='refine')
    second=run({**req,'resume':True,'retry_stage':'readings'},home,bad)
    assert second['suggestions']==first['suggestions'] and second['partial']
    assert calls2==['refine'] and draft.load(home,req['workflow_id'])['stages'][2]['state']=='failed'


def test_confirmed_worker_termination_marks_running_stage_failed_without_losing_cache(tmp_path,monkeypatch):
    req=request(tmp_path,True);home=tmp_path/'home';calls,operation=fake_operations(monkeypatch,fail='refine')
    run(req,home,operation);state=draft.load(home,req['workflow_id']);state['stages'][2]['state']='running';state['status']='running'
    atomic_json(draft.checkpoint_path(home,req['workflow_id']),state)
    draft.mark_stopped(home,req['workflow_id'])
    status=draft.load_summary(home,req['workflow_id']);assert status['status']=='paused' and status['stages'][2]['state']=='failed'
    assert draft.saved_result(req,home)['suggestions']


def test_existing_translation_and_manual_reading_survive_deepseek_stage(tmp_path,monkeypatch):
    req=request(tmp_path,True);home=tmp_path/'home';req['lines'][0]['translation']='人工译文'
    calls,operation=fake_operations(monkeypatch);data=run(req,home,operation)
    assert data['suggestions'][0]['translation']=='人工译文' and not data['partial']


def test_windows_checkpoint_rename_retries_only_local_write(tmp_path,monkeypatch):
    from studio_backend import settings
    path=tmp_path/'atomic.json';atomic_json(path,{'before':True});replace=settings.os.replace;calls=[]
    def transient(source,target):
        calls.append(1)
        if len(calls)<3:raise PermissionError('simulated Windows sharing violation')
        return replace(source,target)
    monkeypatch.setattr(settings.os,'replace',transient)
    atomic_json(path,{'after':True})
    assert len(calls)==3 and json.loads(path.read_text())=={'after':True}
    assert not list(tmp_path.glob('*.tmp'))


def test_checkpoint_write_failure_preserves_previous_document_and_cleans_staging(tmp_path,monkeypatch):
    from studio_backend import settings
    path=tmp_path/'atomic.json';atomic_json(path,{'before':True})
    def forbidden(*args):raise PermissionError('simulated persistent sharing violation')
    monkeypatch.setattr(settings.os,'replace',forbidden)
    with pytest.raises(PermissionError):atomic_json(path,{'after':True})
    assert json.loads(path.read_text())=={'before':True} and not list(tmp_path.glob('*.tmp'))


def test_existing_transcript_matches_original_lyrics_without_upload_and_rejects_wrong_source(tmp_path,monkeypatch):
    from pathlib import Path
    import os
    req=request(tmp_path);req['draft_options']['source']='reuse';media=Path(req['media']);stat=media.stat()
    req['transcript_stamp']={'path':os.path.normcase(str(media.resolve())),'size':stat.st_size,'modified_ns':stat.st_mtime_ns}
    req['transcript']=[LyricLine('recognition','今日 も 歌う',200,2500,[Unit('今日 も 歌う',200,2500,source='recognition')]).to_dict()]
    async def forbidden(*args):raise AssertionError('reuse must not upload')
    monkeypatch.setattr(api,'eleven_transcribe',forbidden);data=run(req,tmp_path/'home')
    assert not data['partial'] and data['suggestions'][0]['text']==req['lines'][0]['text'] and data['transcript']==req['transcript']
    assert data['workflow']['stages'][0]['title']=='复用已有转录'
    bad=copy.deepcopy(req);bad['workflow_id']=uuid.uuid4().hex;bad['transcript_stamp']['size']+=1
    with pytest.raises(ValueError,match='素材版本'):run(bad,tmp_path/'home')
