import asyncio
import json
import pytest
from aiohttp import web
from studio_backend import api


def test_http_contract_and_authentication_isolation(tmp_path,monkeypatch):
    audio=tmp_path/'audio.flac';audio.write_bytes(b'fLaC-contract')
    async def scenario():
        seen=[]
        async def handler(request):
            if request.path=='/deepseek':
                assert request.headers['Authorization']=='Bearer deepseek-key'
                assert 'xi-api-key' not in request.headers
                body=await request.json()
                assert body['response_format']=={'type':'json_object'}
                content={'lines':[{'id':'1','kana':'うた','romaji':'uta','translation':'歌',
                                  'groups':[{'text':'歌','kana':'うた','romaji':'uta'}]}]}
                return web.json_response({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]})
            reader=await request.multipart();parts={}
            async for part in reader:
                parts[part.name]=bytes(await part.read())
            seen.append(request.path)
            if request.path=='/mai':
                assert request.headers['Ocp-Apim-Subscription-Key']=='mai-key'
                assert 'xi-api-key' not in request.headers
                assert json.loads(parts['definition'])['enhancedMode']['model']=='MAI-Transcribe-2'
                assert parts['audio']==b'fLaC-contract'
            else:
                assert request.headers['xi-api-key']=='eleven-key'
                assert parts['file']==b'fLaC-contract'
                if request.path=='/align':
                    assert parts['text'].decode()=='歌'
                else:
                    assert parts['timestamps_granularity']==b'character'
                    assert parts['language_code']==b'ja'
            return web.json_response({'ok':True})
        server=web.Application();server.router.add_post('/{path}',handler)
        runner=web.AppRunner(server);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        base=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
        monkeypatch.setattr(api,'ELEVEN_STT',base+'/stt')
        monkeypatch.setattr(api,'ELEVEN_ALIGN',base+'/align')
        monkeypatch.setattr(api,'DEEPSEEK',base+'/deepseek')
        monkeypatch.setattr(api,'azure_url',lambda endpoint:base+'/mai')
        try:
            diagnostics={}
            await api.eleven_transcribe(audio,'eleven-key',diagnostics=diagnostics)
            assert diagnostics['uploaded_bytes']>0
            await api.eleven_align(audio,'歌','eleven-key')
            await api.mai_transcribe(audio,'mai-key','test')
            result=await api.deepseek_annotate([{'id':'1','text':'歌'}],'deepseek-key')
            assert result[0]['kana']=='うた'
            assert seen==['/stt','/align','/mai']
        finally:
            await runner.cleanup()
    asyncio.run(scenario())


def test_http_failure_is_not_retried():
    async def scenario():
        calls=[]
        async def handler(request):
            calls.append(1)
            return web.json_response({'detail':{'status':'quota_exceeded'}},status=429)
        server=web.Application();server.router.add_post('/',handler)
        runner=web.AppRunner(server);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        try:
            port=site._server.sockets[0].getsockname()[1]
            with pytest.raises(api.ApiError,match='429') as failure:
                await api.request_json(f'http://127.0.0.1:{port}/',{},payload={})
            assert len(calls)==1
            assert failure.value.diagnostics['http_status']==429
            assert failure.value.diagnostics['error_code']=='quota_exceeded'
            assert failure.value.diagnostics['elapsed_ms']>=0
        finally:
            await runner.cleanup()
    asyncio.run(scenario())
