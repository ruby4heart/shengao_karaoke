"""A failed paid request says where it stopped and whether it may be billed."""
import asyncio
import json
import socket
from pathlib import Path
import pytest
from aiohttp import web
from studio_backend import api,worker


def serve(handler,scenario):
    async def main():
        server=web.Application();server.router.add_post('/',handler)
        runner=web.AppRunner(server);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        try:return await scenario(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/')
        finally:await runner.cleanup()
    return asyncio.run(main())


def failed(url,**kwargs):
    async def call():
        with pytest.raises(api.ApiError) as failure:await api.request_json(url,{},**kwargs)
        return failure.value
    return call


def test_not_connected_is_not_billed():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    error=asyncio.run(failed(f'http://127.0.0.1:{port}/',payload={})())
    assert error.diagnostics['stage']=='not_connected' and error.diagnostics['billing']=='not_sent'
    assert str(error).startswith('连接服务阶段失败') and '不会产生费用' in str(error)


def test_upload_interrupted_mid_body(tmp_path):
    # Audio files stream in chunks, as the real services receive them. Bytes
    # count once handed to the socket, so "waiting" errs toward caution.
    audio=tmp_path/'audio.flac';audio.write_bytes(b'x'*(48*1024*1024))
    async def handler(request):
        await request.content.read(65536);request.transport.close();await asyncio.sleep(1)
    async def scenario(url):
        with audio.open('rb') as stream:return await failed(url,data=stream,upload_size=audio.stat().st_size)()
    error=serve(handler,scenario)
    assert error.diagnostics['stage']=='uploading' and error.diagnostics['billing']=='unlikely'
    assert 0<error.diagnostics['uploaded_bytes']<audio.stat().st_size
    assert '上传阶段失败' in str(error)


def test_disconnect_after_full_upload_may_be_billed():
    async def handler(request):
        await request.read();request.transport.close();await asyncio.sleep(1)
    error=serve(handler,lambda url:failed(url,data=b'audio'*100,upload_size=500)())
    assert error.diagnostics['stage']=='waiting' and error.diagnostics['billing']=='possibly_billed'
    assert '等待服务处理阶段失败' in str(error) and '账户记录' in str(error)


def test_invalid_json_response_is_a_parsing_failure_with_request_id():
    async def handler(request):
        await request.read();return web.Response(text='<html>proxy page</html>',headers={'x-request-id':'req-123'})
    error=serve(handler,lambda url:failed(url,payload={'a':1})())
    d=error.diagnostics
    assert d['stage']=='parsing' and d['billing']=='likely_billed' and d['request_id']=='req-123'
    assert d['response_bytes']==len('<html>proxy page</html>') and d['exception']=='JSONDecodeError'


@pytest.mark.parametrize('status,stage',[(429,'service_rejected'),(503,'service_error')])
def test_http_errors_are_service_stages(status,stage):
    async def handler(request):
        await request.read();return web.json_response({'error':{'code':'x'}},status=status)
    error=serve(handler,lambda url:failed(url,payload={})())
    assert error.diagnostics['stage']==stage and str(error).startswith(api.STAGES[stage][0])
    assert error.diagnostics['error_code']=='x'


def test_success_records_complete_phase():
    async def handler(request):
        await request.read();return web.json_response({'ok':True})
    async def scenario(url):
        diagnostics={}
        assert await api.request_json(url,{},payload={'x':'歌'},diagnostics=diagnostics)=={'ok':True}
        return diagnostics
    d=serve(handler,scenario)
    assert d['phase']=='complete' and d['uploaded_bytes']>=d['upload_size'] and 'stage' not in d


def test_classification_table():
    assert api.classify({})=='local'
    assert api.classify({'phase':'connecting'})=='not_connected'
    assert api.classify({'phase':'complete'})=='after_response'
    assert api.classify({'phase':'reading_response','http_status':401})=='service_rejected'
    assert api.classify({'phase':'mystery'})=='unknown'
    assert set(api.STAGES)>={'local','not_connected','uploading','waiting','parsing','service_rejected'}


def test_unrecognised_paid_response_is_kept_in_task_folder(tmp_path):
    def report(*_):pass
    report.task_dir=tmp_path;diagnostics={'phase':'complete'}
    with pytest.raises(api.ApiError) as failure:
        worker._converted(lambda:{}['characters'],{'unexpected':'shape'},diagnostics,report)
    assert json.loads((tmp_path/'api-response.json').read_text(encoding='utf-8'))=={'unexpected':'shape'}
    assert failure.value.diagnostics['stage']=='parsing' and '任务目录' in str(failure.value)


def test_local_failure_result_records_stage(tmp_path):
    result=tmp_path/'task'/'result.json';result.parent.mkdir()
    asyncio.run(worker.execute({'action':'segment','lines':[]},tmp_path/'home',result))
    data=json.loads(result.read_text(encoding='utf-8'))
    assert not data['ok'] and data['diagnostics']['stage']=='local' and data['diagnostics']['billing']=='not_sent'
