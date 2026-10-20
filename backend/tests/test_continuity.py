import asyncio
import copy
import hashlib
import json
import wave
import pytest
from studio_backend.continuity import continuous_lines,continuous_result
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend import worker,api
from studio_backend.settings import Settings


def lines():
    a=Unit('今日',0,500,kana='きょう',highlights=[Highlight('きょ',0,200),Highlight('う',250,500)])
    b=Unit('も',700,1300,kana='も',highlights=[Highlight('も',700,1300)])
    c=Unit('歌う',1500,2400,kana='うたう',highlights=[Highlight('う',1500,1800),Highlight('た',1800,2100),Highlight('う',2100,2400)])
    return [LyricLine('a','今日も',0,1300,[a,b]),LyricLine('b','歌う',1500,2400,[c])]


def onsets(values):return [(line.start,[(u.start,[h.start for h in u.highlights]) for u in line.units]) for line in values]


def test_automatic_mora_word_and_sentence_gaps_join_without_moving_any_onset():
    original=lines();before=copy.deepcopy(original);value,changes=continuous_lines(original)
    assert {c['kind'] for c in changes}=={'mora','word','line'} and len(changes)==3
    assert value[0].units[0].highlights[0].end==250
    assert value[0].units[0].end==value[0].units[1].start==700
    assert value[0].end==value[0].units[-1].end==value[0].units[-1].highlights[-1].end==1500
    assert onsets(original)==onsets(value) and original==before
    assert [x.text for x in value]==[x.text for x in original]
    again,changes=continuous_lines(value);assert not changes and again==value


@pytest.mark.parametrize('kind',['reviewed','locked','unit_locked','manual_word','manual_mora','unmatched','protected','manual_status'])
def test_manual_confirmed_locked_and_unmatched_edges_remain_untouched(kind):
    original=lines();a=original[0]
    if kind=='unit_locked':a.units[0].locked=True
    elif kind=='manual_word':
        for u in a.units:u.source='manual'
    elif kind=='manual_mora':
        for u in a.units:
            for h in u.highlights:h.source='manual'
    elif kind in {'unmatched','protected','manual_status'}:a.match={'status':'manual' if kind=='manual_status' else kind}
    else:setattr(a,kind,True)
    value,changes=continuous_lines(original)
    assert value[0]==original[0] and not any(c['id']=='a' for c in changes)


def test_long_rests_and_optional_sentence_gaps_survive():
    original=lines();original[1].start=2200;original[1].units[0].start=2200;original[1].units[0].highlights=[]
    original[1].units[0].end=original[1].end=3000
    value,changes=continuous_lines(original);assert value[0].end==1300 and all(c['kind']!='line' for c in changes)
    value,changes=continuous_lines(lines(),join_lines=False);assert value[0].end==1300 and len(changes)==2
    value,changes=continuous_lines(lines(),0);assert not changes and value==lines()


@pytest.mark.parametrize('maximum',[-1,2001,True,2.5])
def test_threshold_is_bounded_and_strictly_integer(maximum):
    with pytest.raises(ValueError):continuous_lines(lines(),maximum)


def test_word_envelope_padding_and_original_spaces_are_not_silently_removed():
    original=lines();original[0].text='今日 も';original[0].units[0].text='今日 '
    original[0].units[0].highlights[-1].end=450
    value,changes=continuous_lines(original,join_lines=False)
    assert value[0].text=='今日 も' and value[0].units[0].end==500 and value[0].units[1].start==700


def test_repeated_chorus_alternatives_get_continuous_word_edges_too():
    line=lines()[0];line.match={'status':'uncertain','candidates':[{'start':line.start,'end':line.end,'units':line.to_dict()['units']}]}
    result=continuous_result({'suggestions':[line.to_dict()]},join_lines=False)
    candidate=result['suggestions'][0]['match']['candidates'][0]
    assert candidate['closed_gaps']==2 and candidate['units'][0]['end']==candidate['units'][1]['start']


def test_segment_worker_preserves_gaps_by_default_and_replays_explicit_legacy_policy(tmp_path):
    request={'action':'segment','mode':'mora','lines':[x.to_dict() for x in lines()],'join_lines':True}
    result=asyncio.run(worker.operation({**request,'gap_ms':500},tmp_path,lambda *_:None));assert result['closed_gaps']==3
    keep=asyncio.run(worker.operation(request,tmp_path,lambda *_:None))
    assert keep['closed_gaps']==0
    assert [x['units'] for x in keep['suggestions']]==[x.to_dict()['units'] for x in lines()]
    assert [(x['start'],x['end']) for x in keep['suggestions']]==[(x.start,x.end) for x in lines()]


def test_explicit_legacy_match_joins_gaps_without_editing_raw_transcript(tmp_path):
    transcript=[x.to_dict() for x in lines()];original=copy.deepcopy(transcript)
    result=asyncio.run(worker.operation({'action':'match','lines':[LyricLine('a','今日も',0,1300).to_dict(),LyricLine('b','歌う',1500,2400).to_dict()],'transcript':transcript,'join_lines':True,'gap_ms':500},tmp_path,lambda *_:None))
    assert result['closed_gaps']>=2 and transcript==original and result['transcript']==original
    assert result['suggestions'][0]['end']==result['suggestions'][1]['start']


def test_regenerating_offline_clears_stale_failed_matching_status(tmp_path):
    source=lines();source[0].match={'status':'unmatched','reason':'old failed match'}
    result=asyncio.run(worker.operation({'action':'segment','mode':'mora','lines':[x.to_dict() for x in source]},tmp_path,lambda *_:None))
    assert result['closed_gaps']==0 and not result['suggestions'][0]['match']
    assert source[0].match['status']=='unmatched'


def test_alignment_cache_replays_raw_timing_locally_for_both_policies(tmp_path,monkeypatch):
    home=tmp_path/'home';Settings(home).save('elevenlabs','mock-never-sent');media=tmp_path/'synthetic.wav'
    with wave.open(str(media),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*48000)
    source=LyricLine('a','今日も',0,2500,[Unit('今日',0,1000,kana='きょう'),Unit('も',1200,2500,kana='も')])
    calls=[]
    async def align(*args):
        calls.append(1)
        return {'characters':[{'text':'今','start':0,'end':.4},{'text':'日','start':.4,'end':1.0},{'text':'も','start':1.2,'end':2.5}]}
    monkeypatch.setattr(api,'eleven_align',align)
    request={'action':'align','media':str(media),'lines':[source.to_dict()],'gap_ms':500}
    filled=asyncio.run(worker.operation(request,home,lambda *_:None));assert filled['closed_gaps']==1
    cache=next((home/'cache').glob('*.json'));cached_bytes=cache.read_bytes()
    keep=asyncio.run(worker.operation({**request,'gap_ms':0},home,lambda *_:None))
    assert keep['cached'] and keep['suggestions'][0]['units'][0]['end']==1000
    assert keep['suggestions'][0]['units'][1]['start']==1200
    again=asyncio.run(worker.operation(request,home,lambda *_:None))
    assert again['cached'] and again['suggestions'][0]['units'][0]['end']==1200
    assert calls==[1] and cache.read_bytes()==cached_bytes
