"""Reuse approved text/readings, never the source chorus's timing or locks."""
import copy
import hashlib
import json
from .acoustic import pronunciations
from .japanese import Group,retime_groups
from .matching_context import protected
from .model import Highlight
from .provenance import derived


def signature(line):
    return hashlib.sha256(json.dumps(line.to_dict(),ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')).hexdigest()


def source_valid(source,reading_confirmed):
    source.validate()
    if reading_confirmed is not True or not source.reviewed:raise ValueError('来源句的读音和时间都须先人工确认。')
    if not source.units:raise ValueError('来源句尚未分词，先确认词组与读音。')
    for word in source.units:
        if not isinstance(word.kana,str) or not isinstance(word.romaji,str):raise ValueError('来源词组的假名和罗马音无效。')
        pronunciations(word)
    kana=''.join(u.kana for u in source.units)
    if source.kana and source.kana!=kana:raise ValueError('来源整句假名与词组不一致，请先核对。')
    if not isinstance(source.romaji,str):raise ValueError('来源整句罗马音无效。')


def prepare(source,target,source_reading_confirmed,target_reading_confirmed=False):
    """Tentative regrouping within the target's own range, before new alignment."""
    source_valid(source,source_reading_confirmed);target.validate()
    if source.id==target.id:raise ValueError('来源句不能同时作为复用目标。')
    if source.text!=target.text:raise ValueError('只自动复用原文完全相同的句子；空格或标点不同请先人工核对。')
    if target_reading_confirmed is not False or protected(target):raise ValueError('目标句已有人工时间、确认或锁定，保留当前内容。')
    if any(u.reading_source in {'manual','manual-review'} for u in target.units):raise ValueError('目标句已有手工读音，保留当前内容。')
    groups=[];offset=0
    for word in source.units:
        groups.append(Group(word.text,offset,offset+len(word.text),word.kana,word.romaji));offset+=len(word.text)
    value=copy.deepcopy(target);value.units=retime_groups(target,groups,preserve_readings=False)
    for word,reference in zip(value.units,source.units):
        word.reading_options=copy.deepcopy(reference.reading_options)
        word.source='estimated';word.locked=False;word.reading_source='reused'
        word.timing_origin=derived('estimated',word.start,word.end,target.units or [target],'chorus_reuse_range',word.kana)
        parts,_=pronunciations(word)
        word.highlights=[Highlight(kana,word.start+round((word.end-word.start)*i/len(parts)),
            word.start+round((word.end-word.start)*(i+1)/len(parts)),
            timing_origin=derived('estimated',word.start+round((word.end-word.start)*i/len(parts)),
                word.start+round((word.end-word.start)*(i+1)/len(parts)),[word],'mora_distribution',kana)) for i,kana in enumerate(parts)]
    value.kana=source.kana or ''.join(u.kana for u in value.units)
    value.romaji=source.romaji or ' '.join(u.romaji for u in value.units if u.romaji)
    value.reviewed=False;value.timing_evidence={}
    value.timing_origin=derived('estimated',value.start,value.end,[target],'chorus_reuse_range',value.kana)
    value.reading_review={'notice':'从已确认副歌复用分词与文字读音，另一遍唱法可能不同；时间只来自本句旧范围和估算，须按本段声音重算、试听确认。',
        'reuse':{'source_id':source.id,'source_sha256':signature(source),'source_range':[source.start,source.end],
                 'source_reading_confirmed':True,'source_time_confirmed':True,'timing_copied':False},
        'words':[{'text':u.text,'suggested':u.kana,'basis':'confirmed_chorus','reason':'来自已人工确认的相同原文；本次演唱仍需试听。'} for u in value.units]}
    from .translation import carry
    carry(target,value)
    if 'mora_edits' in target.reading_review:value.reading_review['mora_edits']=copy.deepcopy(target.reading_review['mora_edits'])
    value.validate();return value


def reference_matches(reuse,source,reading_confirmed):
    try:source_valid(source,reading_confirmed)
    except ValueError:return False
    return reuse.get('source_id')==source.id and reuse.get('source_sha256')==signature(source)
