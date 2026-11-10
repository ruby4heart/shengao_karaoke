"""Reviewable line-tail flags and reference endings from local audio.

Measured on 263 public PJS phrases with human phoneme labels: the singing
model's own tail (with its release tag) is closer to the human tail than any
energy or pitch rule tried here. Audio therefore never replaces the current
end by default; it only raises flags worth listening to and offers reference
positions. Nothing is selected for the person.
"""
import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path
import numpy as np
from .sound_gaps import signature,leaves

ALGORITHM='line-tails-v1'
MIN_TAIL=30
SHORT_TAIL=60
EDGE_MS=30
EXTEND_MS=1500
WEAK_KANA=frozenset('すくつふちしききぷぴひ')
TYPES={'next':'被下一句抢拍','long':'拖长音','weak':'弱尾音','fade':'渐弱／气声','plain':'普通收尾'}
RULES={'next':'与下一句相接：保持衔接，不另留空白；需要时可延到下一句开口前。',
       'long':'拖长音：以歌声模型句尾为准，混响余韵不算进高亮。',
       'weak':'弱尾音（句末元音弱化）：只保留短促收尾，不拉长到静音。',
       'fade':'渐弱／气声：以歌声模型句尾为准，声音降落位置只作参考。',
       'plain':'普通收尾：以当前句尾为准。'}
CANDIDATES={'release':'声音降落','voicing':'音高结束','next':'下一句开口前'}
NOTICE=('句尾候选只用于试听比较：在公开人工标注上，按音量或音高找到的句尾比歌声模型本身的句尾误差更大，'
        '所以默认保持当前句尾，不自动选择。疑点按声音规则列出，不是准确率。')


def result_hash(report):
    value={key:value for key,value in report.items() if key!='result_sha256'}
    return hashlib.sha256(json.dumps(value,ensure_ascii=True,sort_keys=True,allow_nan=False).encode()).hexdigest()


def validate_report(report):
    if not isinstance(report,dict) or report.get('version')!=1 or report.get('algorithm')!=ALGORITHM:raise ValueError('句尾检查结果版本无效')
    try:valid=report.get('result_sha256')==result_hash(report)
    except (TypeError,ValueError):valid=False
    if not valid:raise ValueError('句尾检查结果不完整或已变化，请重新检查；原时间保留')


def protected(line,unit,item):
    from .provenance import inferred,effective_kind
    from .protection import locked
    if locked(line,[unit]):return '已锁定'
    if line.reviewed:return '本句时间已确认'
    if 'end' in getattr(item,'fixed_edges',[]) or unit.source=='manual' or item.source=='manual':return '人工时间已保护'
    if effective_kind(inferred(item))=='manual' or effective_kind(inferred(unit))=='manual':return '人工时间已保护'
    if line.match.get('status') in {'protected','manual','unmatched','uncertain'}:return '请先确认本句位置'
    return ''


def normalized(text):
    return ''.join(ch for ch in unicodedata.normalize('NFKC',text or '') if not unicodedata.category(ch)[0] in 'PZS')


def model_tail(line):
    """Whether the singing model ended this line itself, with its release tag free to absorb reverb."""
    evidence=line.timing_evidence if isinstance(line.timing_evidence,dict) else {}
    runs=evidence.get('runs') if isinstance(evidence.get('runs'),list) else []
    if evidence.get('edge_tags')!='ap-ep-v1':return False,None
    for run in reversed(runs):
        edges=run.get('edges') if isinstance(run,dict) else None
        if isinstance(edges,dict) and edges.get('trail') is True:
            span=edges.get('release')
            return True,(list(span) if isinstance(span,list) and len(span)==2 and all(type(v) is int for v in span) else None)
    return False,None


def line_hash(line):
    """One line's exact content; a tail result stays usable while its own line is unchanged."""
    return hashlib.sha256(json.dumps(line.to_dict(),ensure_ascii=True,sort_keys=True,allow_nan=False).encode()).hexdigest()


def targets(lines,indices=None):
    from .provenance import inferred,effective_kind
    chosen=list(range(len(lines))) if indices is None else list(indices)
    if any(type(i) is not int or not 0<=i<len(lines) for i in chosen):raise ValueError('歌词范围无效')
    values=[]
    for n in sorted(set(chosen)):
        line=lines[n];line.validate();parts=leaves(line)
        if not parts:continue
        word,part,item=parts[-1];unit=line.units[word]
        following=lines[n+1] if n+1<len(lines) else None
        next_start=following.start if following is not None and following.start>item.start+MIN_TAIL else None
        line_kind=effective_kind(inferred(line))
        bound=line.end if line_kind in {'manual','acoustic'} else line.end+EXTEND_MS
        if next_start is not None:bound=min(bound,next_start)
        if line.display_end is not None:bound=min(bound,line.display_end)
        limit=max(item.end,bound)
        record={'row':n,'line_id':line.id,'position':[n,word,part],'start':item.start,'end':item.end,'line_end':line.end,
                'limit':limit,'next_start':next_start,'text':item.kana or unit.text,'line_text':line.text,
                'protected':protected(line,unit,item)}
        free,span=model_tail(line);record.update(model_tail=free and item.end<=line.end,release_span=span,line_sha=line_hash(line))
        record['key']=hashlib.sha256(json.dumps({k:record[k] for k in ('line_id','position','start','end','limit')},ensure_ascii=True,sort_keys=True).encode()).hexdigest()[:24]
        values.append(record)
    return values


def track(samples,rate,start,end):
    """10 ms energy and 40 ms periodicity on a shared 5 ms clock, absolute ms times."""
    first=max(0,round(start*rate/1000));last=min(len(samples),round(end*rate/1000))
    size=max(64,round(rate*.04));hop=max(1,round(rate*.005));energy_size=max(8,round(rate*.01))
    if last-first<size+hop:return None
    data=np.asarray(samples[first:last],dtype=np.float32)/32768
    if not np.isfinite(data).all():raise ValueError('声音数据包含无效数值')
    centers=np.arange(size//2,len(data)-size//2+1,hop,dtype=np.int64)
    frames=data[centers[:,None]+(np.arange(size)-size//2)];frames=frames-frames.mean(axis=1,keepdims=True)
    energy=data[centers[:,None]+(np.arange(energy_size)-energy_size//2)];rms=np.sqrt(np.mean(energy*energy,axis=1))
    windowed=frames*np.hanning(size).astype(np.float32);length=1<<(2*size-1).bit_length()
    spectrum=np.fft.rfft(windowed,n=length,axis=1);acf=np.fft.irfft(spectrum*np.conjugate(spectrum),n=length,axis=1)
    low=max(2,rate//1600);high=min(size-1,rate//70)
    periodic=np.max(acf[:,low:high+1],axis=1)/np.maximum(acf[:,0],1e-15)
    return (centers+first)*1000/rate,rms,periodic


def _db(value):return 20*float(np.log10(max(float(value),1e-7)))


def measure(samples,rate,target):
    a,e,limit=target['start'],target['end'],target['limit']
    data=track(samples,rate,a-150,limit+150)
    if data is None:return {'available':False,'reason':'句尾附近声音不足或超出音轨'}
    times,rms,periodic=data;inside=(times>=a)&(times<max(e,a+80))
    if inside.sum()<4:return {'available':False,'reason':'句尾音节太短，无法测量声音'}
    reference=float(np.percentile(rms[inside],90))
    if reference<1e-4:return {'available':False,'reason':'句尾范围内几乎没有声音，请先确认本句位置'}
    index=np.where(inside)[0];peak=int(index[np.argmax(rms[index])])
    def first(mask,hold):
        for i in range(peak,len(times)-hold+1):
            if times[i]>limit:return None
            if mask[i:i+hold].all():return int(round(times[i]))
        return None
    fall=first(rms<reference*10**(-20/20),16);unvoiced=first(periodic<.5,10)
    quiet=rms[(times>=a)&(times<e)]<reference*10**(-30/20);trailing=0
    for flag in quiet[::-1]:
        if not flag:break
        trailing+=1
    after=(times>=e+50)&(times<min(limit,e+300))
    after_db=_db(np.median(rms[after]))-_db(reference) if after.sum()>=10 else None
    after_periodic=float(np.median(periodic[after])) if after.sum()>=10 else None
    body=(times>=a+.3*(e-a))&(times<e)
    slope=float(np.polyfit(times[body],20*np.log10(np.maximum(rms[body],1e-7)),1)[0]*100) if body.sum()>=6 else 0.
    return {'available':True,'reference_db':round(_db(reference),2),'release':fall,'voicing':unvoiced,
            'trailing_quiet_ms':trailing*5,'after_db':None if after_db is None else round(after_db,2),
            'after_periodicity':None if after_periodic is None else round(after_periodic,3),
            'voiced_fraction':round(float(np.mean(periodic[inside]>=.6)),3),'slope_db_per_100ms':round(slope,2)}


def tail_type(target,metrics):
    from .japanese import hiragana
    duration=target['end']-target['start'];kana=hiragana(target['text'] or '')
    gap=None if target['next_start'] is None else target['next_start']-target['end']
    voiced=metrics.get('voiced_fraction') if metrics.get('available') else None
    if gap is not None and gap<80:return 'next'
    if duration>=700 and (voiced is None or voiced>=.5):return 'long'
    if kana and kana[-1] in WEAK_KANA and (duration<250 or voiced is not None and voiced<.4):return 'weak'
    if metrics.get('available') and duration>=250 and metrics['slope_db_per_100ms']<-4:return 'fade'
    return 'plain'


def flags(target,metrics,role):
    found=[];duration=target['end']-target['start']
    if duration<SHORT_TAIL:found.append({'code':'short','message':f'句尾音节只有 {duration} ms，可能被压缩，歌声或许还在继续。'})
    if target['model_tail'] and target['line_end']-target['end']<EDGE_MS:
        room=target['limit']-target['line_end']>=40
        found.append({'code':'edge','message':'歌声模型的句尾顶到了本句范围末端，没有分出余韵；歌声可能还在继续。'+('可试听候选，或放宽整句范围后重算。' if room else '整句范围受人工边界或下一句限制，请手工核对。')})
    if not metrics.get('available'):return found
    if metrics['trailing_quiet_ms']>=200:found.append({'code':'silent','message':f'高亮最后约 {metrics["trailing_quiet_ms"]} ms 几乎无声，句尾可能拖进了静音。'})
    if role=='vocals' and metrics['after_db'] is not None and metrics['after_db']>-3 and metrics['after_periodicity']>.7:
        found.append({'code':'cut','message':'高亮结束后仍有接近句尾音量的持续歌声，句尾可能被截短。'})
    return found


def candidates(target,metrics):
    a,e,limit=target['start'],target['end'],target['limit'];values=[]
    raw=[('release',metrics.get('release')),('voicing',metrics.get('voicing'))] if metrics.get('available') else []
    if target['next_start'] is not None and 40<=target['next_start']-e<=3000:raw.append(('next',target['next_start']))
    for name,end in raw:
        if type(end) is not int or not a+MIN_TAIL<=end<=limit:continue
        if abs(end-e)<20 or any(abs(end-v['end'])<20 for v in values):continue
        values.append({'name':name,'label':CANDIDATES[name],'end':end,'delta':end-e})
    return values


def recommend(found,kind,options,end):
    codes={v['code'] for v in found};names={v['name']:v['end'] for v in options}
    if 'silent' in codes:return next((n for n in ('release','voicing') if n in names and names[n]<end),None)
    if codes&{'cut','edge','short'}:return next((n for n in ('voicing','release','next') if n in names and names[n]>end),None)
    if kind=='next' and 'next' in names:return 'next'
    return None


def consistency(lines,values,types):
    groups={}
    for n,line in enumerate(lines):
        parts=leaves(line);key=normalized(line.text)
        if parts and len(key)>=2:groups.setdefault(key,[]).append((n,parts[-1][2].end-parts[-1][2].start))
    for value in values:
        siblings=[(n,d) for n,d in groups.get(normalized(value['line_text']),[]) if n!=value['row']]
        if not siblings:continue
        duration=value['end']-value['start'];median=float(np.median([d for n,d in siblings]))
        rows='、'.join(str(n+1) for n,d in siblings[:6])+('…' if len(siblings)>6 else '')
        other={types[n] for n,d in siblings if n in types}
        if abs(duration-median)>max(150,.35*median):
            value['flags'].append({'code':'repeat','message':f'同一句歌词在第 {rows} 句的句尾约 {round(median)} ms，本句 {duration} ms，收法可能不一致。'})
        elif value.get('type') and other and other!={value['type']}:
            value['flags'].append({'code':'repeat','message':f'同一句歌词在第 {rows} 句判为'+'、'.join(TYPES[k] for k in sorted(other))+'，本句是'+TYPES[value['type']]+'，请对照试听。'})


def analyze(lines,pcm,rate,binding,indices=None,cancel=None,progress=lambda value:None):
    if type(rate) is not int or not 8000<=rate<=192000:raise ValueError('声音采样率无效')
    if binding.get('audio_role') not in {'vocals','original'}:raise ValueError('声音来源无效')
    if any(not isinstance(binding.get(key),str) or not re.fullmatch('[0-9a-f]{64}',binding[key]) for key in ('source_sha256','audio_sha256')):raise ValueError('缺少本次素材或音轨指纹')
    original=signature(lines);values=targets(lines,indices)
    pcm=Path(pcm)
    if not pcm.is_file() or not pcm.stat().st_size or pcm.stat().st_size%2:raise ValueError('缺少完整的可分析音轨，请重新准备声音')
    samples=np.memmap(pcm,dtype='<i2',mode='r');types={}
    try:
        for n,value in enumerate(values):
            if cancel is not None and cancel.is_set():raise ValueError('已取消句尾检查，原时间保留')
            if value['protected']:
                value.update(status='protected',reason=value['protected'],metrics={},flags=[],candidates=[],type='',rule='',recommended=None)
            else:
                metrics=measure(samples,rate,value);kind=tail_type(value,metrics);found=flags(value,metrics,binding['audio_role'])
                options=candidates(value,metrics);types[value['row']]=kind
                value.update(metrics=metrics,type=kind,rule=RULES[kind],flags=found,candidates=options,recommended=recommend(found,kind,options,value['end']))
            progress({'completed':n+1,'total':len(values)})
    finally:samples._mmap.close()
    consistency(lines,[v for v in values if not v['protected']],types)
    for value in values:
        if value['protected']:continue
        if value['flags']:value.update(status='flagged',reason='；'.join(f['message'] for f in value['flags']))
        elif not value['metrics'].get('available'):value.update(status='unavailable',reason=value['metrics'].get('reason','声音依据不可用'))
        else:value.update(status='ok',reason='未见明显句尾问题；'+value['rule'])
    if signature(lines)!=original:raise ValueError('歌词在分析期间已变化，未采用')
    result={'version':1,'algorithm':ALGORITHM,'signature':original,'binding':copy.deepcopy(binding),
            'indices':None if indices is None else sorted(set(indices)),'tails':values,'notice':NOTICE}
    result['result_sha256']=result_hash(result);return result


def apply(lines,report,choices):
    """Move only the chosen automatic tail ends; every onset stays where it is."""
    from .provenance import change
    validate_report(report)
    if not isinstance(choices,dict) or not choices:raise ValueError('没有选择要采用的句尾')
    current={v['key']:v for v in targets(lines,report.get('indices'))};given={v['key']:v for v in report['tails']}
    if len(given)!=len(report['tails']):raise ValueError('句尾检查结果重复')
    if not choices.keys()<=current.keys() or not choices.keys()<=given.keys():raise ValueError('句尾时间已变化，请重新检查；人工修改保留')
    values=copy.deepcopy(lines);changes=[]
    for key in (v['key'] for v in current.values() if v['key'] in choices):
        target=current[key];result=given[key];name=choices[key]
        if result.get('line_sha')!=target['line_sha']:raise ValueError('本句歌词或时间已变化，请重新检查句尾；人工修改保留')
        if target['protected']:raise ValueError('不能修改已保护的句尾：'+target['protected'])
        if any(result.get(field)!=target[field] for field in ('position','start','end','limit','line_id')):raise ValueError('句尾结果与当前时间不符')
        option=next((v for v in result.get('candidates',[]) if v.get('name')==name),None)
        if option is None:raise ValueError('所选句尾候选不在本次结果中')
        end=option['end']
        if type(end) is not int or not target['start']+MIN_TAIL<=end<=target['limit'] or end==target['end']:raise ValueError('句尾候选超出当前可用范围')
        row,word,part=target['position'];line=values[row];unit=line.units[word];item=unit if part is None else unit.highlights[part]
        old=item.end;change(item,item.start,end,'sound_tail');item.source='estimated'
        if item is not unit and unit.end==old:change(unit,unit.start,end,'sound_tail');unit.source='estimated'
        if line.end<end:change(line,line.start,end,'sound_tail')
        line.reviewed=False
        entry={'range':[old,end],'choice':name,'type':result.get('type',''),'flags':[f['code'] for f in result.get('flags',[])],
               'recommended':result.get('recommended'),'binding':copy.deepcopy(report['binding']),'metrics':copy.deepcopy(result.get('metrics',{}))}
        history=line.timing_evidence.get('tail_checks',[]);history=history if isinstance(history,list) else []
        line.timing_evidence['tail_checks']=[*history[-199:],entry]
        changes.append({**target,'choice':name,'new_end':end})
    for line in values:line.validate()
    return values,changes


def stale_rows(lines,report):
    """Rows whose line changed since the check; their old result is comparison only."""
    current={line.id:line_hash(line) for line in lines}
    return {v['key'] for v in report.get('tails',[]) if current.get(v.get('line_id'))!=v.get('line_sha')}


def quick_flags(lines):
    """Timing-only tail warnings (no audio): a very short last syllable, or a model tail pinned to its range end."""
    found=[]
    for target in targets(lines):
        if target['protected']:continue
        values=flags(target,{'available':False},'original')
        if values:found.append((target,values))
    return found
