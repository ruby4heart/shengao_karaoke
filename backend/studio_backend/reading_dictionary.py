"""User-approved pronunciation entries; dictionaries never confirm audio timing."""
import copy
import unicodedata
from .analysis import kana_only


def key(text):
    text=unicodedata.normalize('NFKC',text).strip()
    while text and unicodedata.category(text[0]).startswith('P'):text=text[1:]
    while text and unicodedata.category(text[-1]).startswith('P'):text=text[:-1]
    return text


def validate(document):
    if document=={}:return
    if not isinstance(document,dict) or set(document)!={'version','entries'} or type(document.get('version')) is not int or document['version']!=1:
        raise ValueError('读音词典格式或版本无效。')
    entries=document['entries']
    if not isinstance(entries,list) or len(entries)>5000:raise ValueError('读音词典最多保存 5000 条。')
    seen=set()
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)!={'text','kana','note'}:raise ValueError('读音词典条目格式无效。')
        if not isinstance(entry['text'],str) or not key(entry['text']) or len(entry['text'])>256:raise ValueError('词典原文须为 1 至 256 个字符。')
        if not isinstance(entry['kana'],str) or not kana_only(entry['kana']) or kana_only(entry['kana'])!=entry['kana'] or len(entry['kana'])>1000:raise ValueError('词典读音须为规范日语假名。')
        if not isinstance(entry['note'],str) or len(entry['note'])>1000:raise ValueError('词典备注最多 1000 字。')
        identity=(key(entry['text']),entry['kana'])
        if identity in seen:raise ValueError('读音词典包含重复的原文与假名。')
        seen.add(identity)


def put(document,text,kana,note=''):
    validate(document)
    if not isinstance(text,str) or not isinstance(kana,str) or not isinstance(note,str):raise ValueError('词典原文、读音与备注须为文字。')
    reading=kana_only(kana)
    if not reading:raise ValueError('先填写实际日语假名，再记入词典。')
    value=copy.deepcopy(document) if document else {'version':1,'entries':[]}
    entry={'text':text,'kana':reading,'note':note};identity=(key(text),reading)
    found=next((i for i,e in enumerate(value['entries']) if (key(e['text']),e['kana'])==identity),None)
    if found is None:value['entries'].append(entry)
    else:value['entries'][found]=entry
    validate(value);return value


def remove(document,text,kana):
    validate(document);value=copy.deepcopy(document) if document else {'version':1,'entries':[]};identity=(key(text),kana_only(kana))
    value['entries']=[e for e in value['entries'] if (key(e['text']),e['kana'])!=identity]
    return value


def lookup(document,text):
    validate(document);surface=key(text)
    return [copy.deepcopy(e) for e in document.get('entries',[]) if key(e['text'])==surface]


def merge(left,right):
    validate(left);validate(right);entries={}
    for entry in [*left.get('entries',[]),*right.get('entries',[])]:entries[(key(entry['text']),entry['kana'])]=copy.deepcopy(entry)
    value={'version':1,'entries':list(entries.values())};validate(value);return value
