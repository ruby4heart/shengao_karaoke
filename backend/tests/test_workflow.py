import asyncio
import json
import wave
from studio_backend import api,worker
from studio_backend.settings import Settings
from studio_backend.model import LyricLine,Unit


def audio_file(path):
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000)
        output.writeframes(b'\0\0'*48000)


def test_alignment_preserves_ids_and_reuses_cache(tmp_path,monkeypatch):
    settings=Settings(tmp_path/'home');settings.save('elevenlabs','test-never-sent')
    media=tmp_path/'song.wav';audio_file(media)
    line=LyricLine('manual-line','歌',1000,2500,[Unit('歌',1000,2500)])
    calls=[]
    async def fake(audio,text,key,diagnostics):
        assert text=='歌' and key=='test-never-sent'
        assert audio.read_bytes().startswith(b'fLaC')
        calls.append(1)
        return {'characters':[{'text':'歌','start':.1,'end':1.2}]}
    monkeypatch.setattr(api,'eleven_align',fake)
    request={'action':'align','media':str(media),'lines':[line.to_dict()],'range_mode':'selection'}
    async def scenario():
        first=tmp_path/'first.json';second=tmp_path/'second.json'
        await worker.execute(request,settings.root,first)
        result=json.loads(first.read_text(encoding='utf-8'))
        assert result['ok'],result
        suggestion=result['suggestions'][0]
        assert suggestion['id']=='manual-line' and suggestion['start']==1100 and suggestion['end']==2200
        await worker.execute(request,settings.root,second)
        assert json.loads(second.read_text(encoding='utf-8'))['cached']
        line.display_start=500;line.display_end=2800
        third=tmp_path/'display-only.json'
        await worker.execute({**request,'lines':[line.to_dict()]},settings.root,third)
        assert json.loads(third.read_text(encoding='utf-8'))['cached']
        assert len(calls)==1
    asyncio.run(scenario())


def test_locked_line_never_reaches_cloud(tmp_path,monkeypatch):
    settings=Settings(tmp_path/'home');settings.save('deepseek','test-never-sent')
    line=LyricLine('locked','歌',0,1000,locked=True)
    calls=[]
    async def forbidden(*args):
        calls.append(1)
        raise AssertionError('Locked lyrics must not be submitted')
    monkeypatch.setattr(api,'deepseek_annotate',forbidden)
    result=tmp_path/'result.json'
    asyncio.run(worker.execute({'action':'annotate','lines':[line.to_dict()]},settings.root,result))
    data=json.loads(result.read_text(encoding='utf-8'))
    assert not data['ok'] and '锁定' in data['message']
    assert calls==[]
