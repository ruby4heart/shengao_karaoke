import asyncio
import copy
import json
import pytest
from aiohttp import web
from studio_backend.matching import match_lyrics,normalized
from studio_backend.model import LyricLine,Unit
from studio_backend import api,worker
from studio_backend.settings import Settings
from test_workflow import audio_file


def lyric(text,index=0,**kwargs):
    return LyricLine(str(index),text,index*5000,(index+1)*5000,**kwargs)


def transcript(text,start=1000,step=200,words=False):
    units=[Unit(text,start,start+len(text)*step,source='word')] if words else [
        Unit(c,start+i*step,start+(i+1)*step,source='recognition') for i,c in enumerate(text)]
    return [LyricLine('asr',text,start,start+len(text)*step,units)]


def test_preserves_original_lines_across_asr_boundaries():
    lines=[lyric('今日も、歌う！'),lyric('空の向こうへ',1)]
    result=match_lyrics(lines,transcript('今日も歌う空の向こうへ'))
    a,b=[LyricLine.from_dict(value) for value in result['suggestions']]
    assert a.text==lines[0].text and b.text==lines[1].text
    assert a.start==1000 and a.end==b.start and b.end==3200
    assert a.match['status']=='matched' and a.match['coverage']==1
    assert ''.join(unit.text for unit in a.units)==a.text
    assert not a.reviewed and result['review_required']


def test_japanese_width_kana_and_combining_marks():
    assert normalized('ＡｂＣ１２ ｶﾞッツ、ヴァ！')==normalized('abc12 がっつゔぁ')
    result=match_lyrics([lyric('ガッツ、が\u3099！')],transcript('がっつがが'))
    value=LyricLine.from_dict(result['suggestions'][0])
    assert value.text=='ガッツ、が\u3099！'


def test_missing_verse_not_fabricated_and_later_lines_match():
    lines=[lyric('春の空'),lyric('数えきれない星',1),lyric('歌を届けよう',2)]
    values=match_lyrics(lines,transcript('春の空歌を届けよう'))['suggestions']
    assert values[1]['match']['status']=='unmatched'
    assert values[1]['start']==5000
    assert values[2]['match']['status']=='matched' and values[2]['start']==1600


def test_insertions_typos_and_no_reordering():
    lines=[lyric('明日へ歩こう'),lyric('夢を抱いて',1)]
    values=match_lyrics(lines,transcript('ええ明日へ歩こう夢を抱いてよ'))['suggestions']
    assert [v['text'] for v in values]==[v.text for v in lines]
    assert values[0]['start']>=1400 and values[0]['end']<=values[1]['start']
    weak=match_lyrics([lyric('星が降る夜')],transcript('星か降るよ'))['suggestions'][0]
    assert weak['match']['status'] in {'uncertain','unmatched'}


def test_repeated_chorus_is_uncertain_without_scope():
    source=transcript('君と歌う君と歌う')
    value=match_lyrics([lyric('君と歌う')],source)['suggestions'][0]
    assert value['match']['status']=='uncertain' and value['match']['ambiguous']
    scoped=match_lyrics([lyric('君と歌う')],source,[1800,2600])['suggestions'][0]
    assert scoped['start']==1800 and scoped['match']['status']=='matched'
    missing=match_lyrics([lyric('君と歌う'),lyric('君と歌う',1)],transcript('君と歌う'))['suggestions']
    assert all(value['match']['status']!='matched' for value in missing)


def test_word_time_splits_are_estimates_and_gaps_survive():
    source=transcript('今日も歌う',words=True)
    value=match_lyrics([lyric('今日も歌う')],source)['suggestions'][0]
    assert all(unit['source']=='estimated' for unit in value['units'])
    source=transcript('今日')+transcript('歌う',3000)
    value=match_lyrics([lyric('今日歌う')],source)['suggestions'][0]
    assert next(u for u in value['units'] if u['text'].startswith('歌'))['start']==3000


@pytest.mark.parametrize('protection',['locked','reviewed','unit'])
def test_preserves_manual_results(protection):
    line=lyric('歌う')
    if protection=='unit':
        line.units=[Unit('歌う',0,5000,kana='うたう',locked=True)]
    else:
        setattr(line,protection,True)
    before=line.to_dict()
    value=match_lyrics([line],transcript('歌う'))['suggestions'][0]
    assert value['match']['status']=='protected'
    assert {k:v for k,v in value.items() if k!='match'}=={k:v for k,v in before.items() if k!='match'}


def test_invalid_scope_overlap_and_empty_source():
    with pytest.raises(ValueError,match='范围'):
        match_lyrics([lyric('歌')],transcript('歌'),[1,1])
    with pytest.raises(ValueError,match='重叠'):
        match_lyrics([lyric('歌歌')],transcript('歌')+transcript('歌'))
    with pytest.raises(ValueError,match='转录'):
        match_lyrics([lyric('歌')],[])


def test_matching_cache_shared_with_raw_transcription(tmp_path,monkeypatch):
    settings=Settings(tmp_path/'home');settings.save('elevenlabs','test-never-sent')
    media=tmp_path/'song.wav';audio_file(media);calls=[]
    request={'action':'transcribe','media':str(media),'lines':[]}
    async def scenario():
        async def handler(incoming):
            assert incoming.headers['xi-api-key']=='test-never-sent'
            reader=await incoming.multipart();parts={}
            async for part in reader:
                parts[part.name]=bytes(await part.read())
            assert parts['file'].startswith(b'fLaC') and parts['timestamps_granularity']==b'character'
            calls.append(1)
            return web.json_response({'words':[{'text':c,'start':i*.2,'end':(i+1)*.2,'type':'word'} for i,c in enumerate('今日も歌う')]})
        app=web.Application();app.router.add_post('/stt',handler);runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        monkeypatch.setattr(api,'ELEVEN_STT',f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/stt')
        try:
            first=await worker.operation({**request,'action':'transcribe_match','lines':[lyric('今日も歌う').to_dict()]},settings.root,lambda *a:None)
            assert not first['cached'] and first['match_summary']['matched']==1
            raw=await worker.operation(request,settings.root,lambda *a:None)
            result=await worker.operation({**request,'action':'transcribe_match','lines':[lyric('今日も、歌う').to_dict()]},settings.root,lambda *a:None)
            assert result['cached'] and raw['cached'] and len(calls)==1
            assert result['suggestions'][0]['text']=='今日も、歌う'
            assert result['transcript']==raw['suggestions']
            local=await worker.operation({'action':'match','transcript':raw['suggestions'],'lines':[lyric('今日も歌う').to_dict()]},tmp_path/'no-keys',lambda *a:None)
            assert local['local'] and local['match_summary']['matched']==1 and len(calls)==1
        finally:
            await runner.cleanup()
    asyncio.run(scenario())


def test_transcription_retained_when_matching_fails(tmp_path,monkeypatch):
    settings=Settings(tmp_path/'home');settings.save('elevenlabs','test-never-sent')
    media=tmp_path/'song.wav';audio_file(media)
    async def fake(*args,**kwargs):
        return {'words':[{'text':'歌','start':0,'end':1,'type':'word'}]}
    monkeypatch.setattr(api,'eleven_transcribe',fake)
    output=tmp_path/'result.json'
    request={'action':'transcribe_match','media':str(media),'lines':[lyric('歌').to_dict()],'match_range':[5000,6000]}
    asyncio.run(worker.execute(request,settings.root,output))
    result=json.loads(output.read_text(encoding='utf-8'))
    assert not result['ok'] and result['transcript'][0]['text']=='歌'
    assert '转录已返回' in result['message'] and '无需再次上传' in result['message']
