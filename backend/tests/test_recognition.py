import asyncio
import copy
import hashlib
from pathlib import Path
import os
import pytest
from studio_backend import recognition,worker,api
from studio_backend.model import LyricLine,Unit


def raw(text='今日も歌う'):
    return [LyricLine('raw',text,1000,1000+len(text)*200,
                     [Unit(c,1000+i*200,1200+i*200,source='recognition') for i,c in enumerate(text)]).to_dict()]


def draft(text='今日も歌う'):
    source=raw(text);return recognition.create(source,{'path':'synthetic'}),source


@pytest.mark.parametrize(('text','expected'),[('今日 も 歌う','今日も歌う'),('I love you','I love you'),('君 と my voice','君と my voice'),('  ネオン  サイン  ','ネオンサイン'),('海　へ','海へ')])
def test_only_candidate_japanese_spaces_are_compacted_without_touching_original(text,expected):
    value,source=draft(text);before=copy.deepcopy(source)
    assert value['rows'][0]['text']==expected and recognition.source_text(value['rows'][0],source)==text
    value['rows'][0]['text']='今日 も  歌う';recognition.validate(value,source,True)
    assert value['rows'][0]['text']=='今日 も  歌う' and source==before


def test_character_evidence_split_and_merge_keep_exact_text_and_true_pause():
    source=raw();source[0]['units'][1]['end']=1300
    value=recognition.create(source,{});before=copy.deepcopy(value)
    split=recognition.split(value,0,2,source)
    assert [(x['text'],x['start'],x['end']) for x in split['rows']]==[('今日',1000,1300),('も歌う',1400,2000)]
    assert all(x['range_source']=='recognition' for x in split['rows'])
    merged=recognition.merge(split,0,source)
    assert merged['rows'][0]['text']==value['rows'][0]['text'] and merged['rows'][0]['spans']==value['rows'][0]['spans']
    assert value==before and recognition.source_text(merged['rows'][0],source)=='今日も歌う'


def test_split_after_typing_uses_honest_estimated_range_and_preserves_user_spaces():
    value,source=draft();value['rows'][0]['text']='今日 も 歌おう'
    split=recognition.split(value,0,3,source)
    assert ''.join(r['text'] for r in split['rows'])=='今日 も 歌おう'
    assert all(r['range_source']=='estimated' for r in split['rows'])
    assert split['rows'][0]['end']==split['rows'][1]['start']


def test_multi_character_word_interpolation_does_not_claim_character_evidence():
    source=[LyricLine('raw','今日も歌う',1000,3000,[Unit('今日も歌う',1000,3000,source='word')]).to_dict()]
    value=recognition.create(source,{});split=recognition.split(value,0,2,source)
    assert all(r['range_source']=='estimated' for r in split['rows'])


def test_split_compacted_text_maintains_source_spans_for_subsequent_splits():
    value,source=draft('今日 も 歌う');split=recognition.split(value,0,2,source)
    assert split['rows'][0]['text']=='今日' and split['rows'][1]['text']=='も歌う'
    again=recognition.split(split,1,1,source)
    assert [r['text'] for r in again['rows']]==['今日','も','歌う']
    assert all(r['range_source']=='recognition' for r in again['rows'])
    merged=recognition.merge(recognition.merge(again,0,source),0,source)
    assert recognition.source_text(merged['rows'][0],source)=='今日 も 歌う'


def test_newlines_in_recognition_become_separate_editable_rows():
    value,source=draft('hello world\n今日も歌う')
    assert [r['text'] for r in value['rows']]==['hello world','今日も歌う']
    assert recognition.source_text(value['rows'][0],source)=='hello world'
    assert recognition.source_text(value['rows'][1],source)=='今日も歌う'


@pytest.mark.parametrize('position',[0,5,-1,True,1.5])
def test_invalid_split_never_mutates_the_current_draft(position):
    value,source=draft();before=copy.deepcopy(value)
    with pytest.raises(ValueError):recognition.split(value,0,position,source)
    assert value==before


def test_draft_mutations_and_source_hash_are_validated():
    value,source=draft();changed=copy.deepcopy(source);changed[0]['text']='明日も歌う';changed[0]['units'][0]['text']='明'
    with pytest.raises(ValueError,match='原始转录已变化'):recognition.validate(value,changed)
    for mutate in [lambda r:r.update(end=r['start']),lambda r:r.update(text='a\nb'),lambda r:r['spans'][0].update(end=999),lambda r:r.update(id='')]:
        bad=copy.deepcopy(value);mutate(bad['rows'][0])
        with pytest.raises(ValueError):recognition.validate(bad,source)


def test_blank_edits_can_be_saved_but_cannot_be_confirmed_and_manual_insert_has_no_fake_source():
    value,source=draft();value=recognition.insert(value,0,source)
    assert value['rows'][1]['spans']==[] and value['rows'][1]['range_source']=='estimated'
    recognition.validate(value,source)
    with pytest.raises(ValueError,match='空白歌词'):recognition.confirmed_lines(value,source)
    value['rows'][1]['text']='あした';result=recognition.confirmed_lines(value,source)
    assert result['text_confirmed'] and result['suggestions'][1]['text']=='あした'
    assert result['suggestions'][1]['match']['recognized_original']==''


def test_confirmed_wording_remains_exact_and_time_reading_are_not_marked_confirmed(monkeypatch):
    value,source=draft('今日 も 歌う');value['rows'][0]['text']='今日も歌おう'
    before=copy.deepcopy(source)
    async def forbidden(*args):raise AssertionError('text confirmation must not use a cloud API')
    monkeypatch.setattr(api,'eleven_align',forbidden);monkeypatch.setattr(api,'deepseek_annotate',forbidden)
    result=recognition.confirmed_lines(value,source);line=LyricLine.from_dict(result['suggestions'][0])
    assert line.text=='今日も歌おう' and not line.reviewed and not line.locked
    assert line.match['text_confirmed'] and line.units and all(u.highlights for u in line.units)
    assert source==before and result['draft_hash']==recognition.signature(value)


def test_worker_verifies_media_content_even_when_path_size_and_mtime_match(tmp_path):
    media=tmp_path/'source.wav';media.write_bytes(b'abcd');stat=media.stat()
    stamp={'path':os.path.normcase(str(media.resolve())),'size':stat.st_size,'modified_ns':stat.st_mtime_ns}
    source=raw();value=recognition.create(source,stamp,hashlib.sha256(b'abcd').hexdigest())
    req={'action':'confirm_recognition','media':str(media),'transcript':source,'recognition_draft':value}
    result=asyncio.run(worker.operation(req,tmp_path/'home',lambda *args:None))
    assert result['local'] and result['text_confirmed']
    media.write_bytes(b'efgh');os.utime(media,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    with pytest.raises(ValueError,match='素材内容已变化'):
        asyncio.run(worker.operation(req,tmp_path/'home',lambda *args:None))


def test_rare_cjk_and_combining_marks_keep_valid_character_boundaries():
    value,source=draft('𠮷 野');assert value['rows'][0]['text']=='𠮷野'
    value,source=draft('か\u3099く')
    with pytest.raises(ValueError,match='组合字符'):recognition.split(value,0,1,source)
    split=recognition.split(value,0,2,source);assert [r['text'] for r in split['rows']]==['か\u3099','く']


def test_transcription_cache_returns_source_fingerprint_and_does_not_repeat_request(tmp_path,monkeypatch):
    from studio_backend.settings import Settings
    media=tmp_path/'source.wav';media.write_bytes(b'synthetic input');calls=[]
    monkeypatch.setattr(Settings,'key',lambda *args:'test-never-sent')
    async def extract(source,target,*args):target.write_bytes(b'fLaC local fake')
    async def transcribe(audio,key,language,diagnostics):
        calls.append(1);return {'words':[{'text':'今日','start':.1,'end':1.1}]}
    monkeypatch.setattr(worker,'extract',extract);monkeypatch.setattr(api,'eleven_transcribe',transcribe)
    req={'action':'transcribe','media':str(media),'lines':[]}
    first=asyncio.run(worker.operation(req,tmp_path/'home',lambda *args:None));second=asyncio.run(worker.operation(req,tmp_path/'home',lambda *args:None))
    assert calls==[1] and second['cached'] and first['suggestions']==second['suggestions']
    assert first['media_fingerprint']==second['media_fingerprint']==hashlib.sha256(media.read_bytes()).hexdigest()
