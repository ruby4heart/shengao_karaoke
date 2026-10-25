"""Editable recognition text stays separate until the user confirms its wording."""
import copy
import hashlib
import json
import re
import unicodedata
from .model import LyricLine,Unit,identifier


def signature(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def japanese(char):
    return bool(char) and ('\u3040'<=char<='\u30ff' or '\u3400'<=char<='\u9fff'
                          or '\uf900'<=char<='\ufaff' or '\uff66'<=char<='\uff9f'
                          or unicodedata.name(char,'').startswith('CJK UNIFIED IDEOGRAPH-'))


def compact(text):
    """Only recognition candidates: retain English spaces and later manual input."""
    kept=[]
    for match in re.finditer(r'\s+|\S',text):
        token=match.group()
        if token.isspace() and match.start()>0 and match.end()<len(text) and japanese(text[match.start()-1]) and japanese(text[match.end()]):continue
        kept.extend(range(match.start(),match.end()))
    while kept and text[kept[0]].isspace():kept.pop(0)
    while kept and text[kept[-1]].isspace():kept.pop()
    return ''.join(text[i] for i in kept),kept


def create(raw,media_stamp,media_fingerprint=''):
    rows=[];timing=timed_chars(raw)
    for value in raw:
        line=LyricLine.from_dict(value)
        for part in re.finditer(r'[^\r\n]+',line.text):
            text,_=compact(part.group())
            if not text:continue
            start=timing[line.id][part.start()][1];end=max(start+10,timing[line.id][part.end()-1][2])
            rows.append({'id':identifier(),'text':text,'start':start,'end':end,
                         'spans':[{'id':line.id,'begin':part.start(),'end':part.end()}],
                         'range_source':'recognition' if part.start()==0 and part.end()==len(line.text) or timing[line.id][part.start()][3] and timing[line.id][part.end()-1][3] else 'estimated'})
    if not rows:raise ValueError('没有可用的识别文字，请检查音轨或准备原歌词')
    value={'version':1,'id':identifier(),'source_hash':signature(raw),'media_stamp':copy.deepcopy(media_stamp),
           'media_fingerprint':media_fingerprint,'rows':rows}
    validate(value,raw);return value


def validate(value,raw,require_text=False):
    if not isinstance(value,dict) or value.get('version')!=1 or not re.fullmatch('[a-f0-9]{32}',str(value.get('id',''))):
        raise ValueError('识别原文草稿格式无效')
    if value.get('source_hash')!=signature(raw):raise ValueError('原始转录已变化，不能将旧的原文草稿套到新结果')
    if not isinstance(value.get('media_stamp'),dict):raise ValueError('识别草稿缺少素材记录')
    fingerprint=value.get('media_fingerprint','')
    if not isinstance(fingerprint,str) or fingerprint and not re.fullmatch('[a-f0-9]{64}',fingerprint):raise ValueError('识别草稿的素材指纹无效')
    source={}
    for item in raw:
        line=LyricLine.from_dict(item)
        if line.id in source:raise ValueError('原始转录编号重复')
        source[line.id]=line
    rows=value.get('rows')
    if not isinstance(rows,list) or len(rows)>10000 or require_text and not rows:raise ValueError('请至少保留一句歌词')
    ids=set();length=0
    for row in rows:
        if not isinstance(row,dict) or not re.fullmatch('[a-f0-9]{32}',str(row.get('id',''))) or row['id'] in ids:raise ValueError('识别草稿行编号无效')
        ids.add(row['id']);text=row.get('text')
        if not isinstance(text,str) or '\n' in text or '\r' in text or len(text)>20000:raise ValueError('请每行保留一句，过长的内容需要拆分')
        if require_text and not text.strip():raise ValueError('有空白歌词，请填写或删除这一行')
        length+=len(text)
        if type(row.get('start')) is not int or type(row.get('end')) is not int or not 0<=row['start']<row['end']:raise ValueError('识别参考范围无效')
        if row.get('range_source') not in {'recognition','estimated'}:raise ValueError('识别范围来源无效')
        if not isinstance(row.get('spans'),list):raise ValueError('识别原文对应关系无效')
        for span in row['spans']:
            old=source.get(span.get('id'))
            if old is None or type(span.get('begin')) is not int or type(span.get('end')) is not int or not 0<=span['begin']<span['end']<=len(old.text):raise ValueError('识别原文对应范围无效')
    if length>120000:raise ValueError('原文草稿超过 120000 字，请分段处理')


def source_text(row,raw):
    source={x['id']:x['text'] for x in raw}
    return ''.join(source[s['id']][s['begin']:s['end']] for s in row['spans'])


def timed_chars(raw):
    result={}
    for data in raw:
        line=LyricLine.from_dict(data);chars=[]
        units=line.units
        if not units:
            units=[Unit(line.text,line.start,line.end)]
        for unit in units:
            n=len(unit.text)
            for i,char in enumerate(unit.text):
                chars.append((char,unit.start+round((unit.end-unit.start)*i/max(1,n)),
                              unit.start+round((unit.end-unit.start)*(i+1)/max(1,n)),
                              n==1 and unit.source in {'recognition','alignment','manual'}))
        result[line.id]=chars
    return result


def split(value,index,position,raw):
    validate(value,raw)
    if type(index) is not int or not 0<=index<len(value['rows']):raise ValueError('请先选择要拆分的句子')
    result=copy.deepcopy(value);row=result['rows'][index];text=row['text']
    if type(position) is not int or not 0<position<len(text) or not text[:position].strip() or not text[position:].strip():
        raise ValueError('把光标放在两句之间；拆开后的两句都要有文字')
    if unicodedata.category(text[position]).startswith('M') or text[position]=='\u200d' or text[position-1]=='\u200d':
        raise ValueError('不能在一个组合字符中间拆句，请把光标移到字符之后')
    if row['end']-row['start']<20:raise ValueError('参考范围过短，先保留一整句，之后在校轴区调整')
    source=source_text(row,raw);clean,kept=compact(source)
    mapping=list(range(len(source))) if source==text else kept if clean==text else None
    source_cut=mapping[position] if mapping else None
    left_spans=[];right_spans=[];offset=0
    for span in row['spans']:
        size=span['end']-span['begin'];cut=min(size,max(0,source_cut-offset)) if source_cut is not None else size
        if source_cut is None:
            left_spans.append(copy.deepcopy(span));right_spans.append(copy.deepcopy(span))
        else:
            if cut:left_spans.append({**span,'end':span['begin']+cut})
            if cut<size:right_spans.append({**span,'begin':span['begin']+cut})
        offset+=size
    # Character evidence may locate the split; token interpolation is still only
    # an estimate and is never labelled an acoustic mora boundary.
    boundary=row['start']+round((row['end']-row['start'])*position/len(text))
    boundary=max(row['start']+10,min(row['end']-10,boundary));left_end=right_start=boundary;kind='estimated'
    if mapping:
        chars=timed_chars(raw);flat=[c for s in row['spans'] for c in chars[s['id']][s['begin']:s['end']]]
        a,b=flat[mapping[position-1]],flat[mapping[position]]
        if row['start']<a[2]<=b[1]<row['end']:
            left_end,right_start=a[2],b[1];kind='recognition' if a[3] and b[3] else 'estimated'
    left={**row,'text':text[:position],'end':left_end,'spans':left_spans,'range_source':kind}
    right={**row,'id':identifier(),'text':text[position:],'start':right_start,'spans':right_spans,'range_source':kind}
    result['rows'][index:index+1]=[left,right];validate(result,raw);return result


def merge(value,index,raw):
    validate(value,raw)
    if not 0<=index<len(value['rows'])-1:raise ValueError('后面没有可合并的句子')
    result=copy.deepcopy(value);a,b=result['rows'][index:index+2]
    spans=copy.deepcopy(a['spans'])
    for span in b['spans']:
        if spans and spans[-1]['id']==span['id'] and spans[-1]['end']==span['begin']:spans[-1]['end']=span['end']
        elif span not in spans:spans.append(copy.deepcopy(span))
    result['rows'][index:index+2]=[{**a,'text':a['text']+b['text'],'start':min(a['start'],b['start']),
        'end':max(a['end'],b['end']),'spans':spans,
        'range_source':'recognition' if a['range_source']==b['range_source']=='recognition' else 'estimated'}]
    validate(result,raw);return result


def insert(value,index,raw):
    result=copy.deepcopy(value);rows=result['rows'];position=max(0,min(len(rows),index+1))
    start=rows[position-1]['end'] if position else 0
    end=max(start+10,rows[position]['start']) if position<len(rows) else start+5000
    rows.insert(position,{'id':identifier(),'text':'','start':start,'end':end,'spans':[],'range_source':'estimated'})
    validate(result,raw);return result


def confirmed_lines(value,raw,romanization_rules=None):
    """Local matching/dictionary only, after an explicit wording confirmation."""
    from .matching import match_lyrics
    from .japanese import segment_line
    validate(value,raw,require_text=True)
    base=[LyricLine(r['id'],r['text'],r['start'],r['end']) for r in value['rows']]
    transcript=[LyricLine.from_dict(r) for r in raw]
    matched=match_lyrics(base,transcript);output=[]
    for original,data in zip(value['rows'],matched['suggestions']):
        line=LyricLine.from_dict(data);line,_=segment_line(line,'mora',romanization_rules)
        if line.id!=original['id'] or line.text!=original['text']:raise ValueError('本地分词改变了已核对原文，已拒绝加入')
        line.match.update(text_confirmed=True,text_origin='recognition_draft',draft_id=value['id'],
            recognized_original=source_text(original,raw),range_source=original['range_source'])
        line.reviewed=False;line.validate();output.append(line.to_dict())
    return {'suggestions':output,'local':True,'text_confirmed':True,'draft_id':value['id'],
            'draft_hash':signature(value),'message':'原文已核对并生成本地粗稿；假名和时间仍需试听确认。'}
