"""Reviewable continuity candidates from audio and retained phoneme evidence.

No result is a pronunciation check or an automatic human confirmation. Original
mixtures need retained, matching phoneme evidence before a join is recommended.
"""
import copy
import hashlib
import json
import re
from pathlib import Path
import numpy as np


def signature(lines):
    value=[line.to_dict() for line in lines]
    return hashlib.sha256(json.dumps(value,ensure_ascii=True,sort_keys=True,allow_nan=False).encode()).hexdigest()


def result_hash(report):
    value={key:value for key,value in report.items() if key!='result_sha256'}
    return hashlib.sha256(json.dumps(value,ensure_ascii=True,sort_keys=True,allow_nan=False).encode()).hexdigest()


def validate_report(report):
    if not isinstance(report,dict) or report.get('version')!=1 or report.get('algorithm')!='sound-gaps-v1':raise ValueError('声音空隙结果版本无效')
    try:valid=report.get('result_sha256')==result_hash(report)
    except (TypeError,ValueError):valid=False
    if not valid:raise ValueError('声音空隙结果不完整或已变化，请重新检查；原时间保留')


def leaves(line):
    return [(i,j,h) for i,u in enumerate(line.units)
            for j,h in (enumerate(u.highlights) if u.highlights else [(None,u)])]


def target_item(lines,position):
    row,word,part=position;unit=lines[row].units[word]
    return lines[row],unit,unit if part is None else unit.highlights[part]


def protected(line,unit,item,new_end=None):
    from .provenance import inferred,effective_kind
    if line.locked or unit.locked:return '已锁定'
    if line.reviewed:return '本句时间已确认'
    kind=effective_kind(inferred(item));word_kind=effective_kind(inferred(unit));line_kind=effective_kind(inferred(line))
    if getattr(item,'fixed_edges',[]) or unit.source=='manual' or item.source=='manual' or kind=='manual':return '人工时间已保护'
    if item.source=='acoustic' or kind=='acoustic':return '保留已有歌声音素边界'
    if new_end is not None and new_end>unit.end and (unit.source=='acoustic' or word_kind=='acoustic'):return '保留已有词组声音边界'
    if new_end is not None and new_end>line.end and line_kind in {'manual','acoustic'}:return '保留已有整句边界'
    if line.match.get('status') in {'protected','manual','unmatched','uncertain'}:return '请先确认本句位置'
    return ''


def targets(lines,maximum=2000,join_lines=False,indices=None):
    if type(maximum) is not int or not 10<=maximum<=5000:raise ValueError('声音空隙分析上限应为 10–5000 毫秒')
    if type(join_lines) is not bool:raise ValueError('句间分析选项无效')
    values_indices=list(range(len(lines))) if indices is None else list(indices)
    if any(type(i) is not int or not 0<=i<len(lines) for i in values_indices):raise ValueError('歌词范围无效')
    active=set(values_indices)
    values=[]
    def add(left,right):
        a,lu,li=target_item(lines,left);b,ru,ri=target_item(lines,right)
        if li.end>=ri.start:return
        reason=protected(a,lu,li,ri.start)
        anchor=protected(b,ru,ri)
        if not reason and b.match.get('status') in {'unmatched','uncertain'} and not anchor.startswith(('人工','已锁定','本句时间')):reason='请先确认后一句位置'
        if not reason and a.id!=b.id and a.display_end is not None and a.display_end<ri.start:reason='手工留屏结束限制此处延尾'
        if not reason and ri.start-li.end>maximum:reason='超过本次分析范围，保留'
        record={'left':left,'right':right,'start':li.end,'end':ri.start,
                'left_id':a.id,'right_id':b.id,'left_text':li.kana or lu.text,'right_text':ri.kana or ru.text,
                'protected':reason,'anchor':anchor,'kind':'line' if a.id!=b.id else 'mora' if left[1]==right[1] else 'word'}
        record['key']=hashlib.sha256(json.dumps(record,ensure_ascii=True,sort_keys=True).encode()).hexdigest()[:24]
        values.append(record)
    groups=[]
    for n,line in enumerate(lines):
        line.validate();group=[[n,i,j] for i,j,h in leaves(line)] if n in active else [];groups.append(group)
        for a,b in zip(group,group[1:]):add(a,b)
    if join_lines:
        for a,b in zip(groups,groups[1:]):
            if a and b:add(a[-1],b[0])
    if len(values)>20000:raise ValueError('空隙过多，请先按本句或选中范围分析')
    return sorted(values,key=lambda value:(value['left'][0],value['start'],value['end']))


def _longest(mask):
    longest=current=0
    for flag in mask:
        current=current+1 if flag else 0;longest=max(longest,current)
    return longest


def measurements(samples,rate,start,end):
    """10 ms energy and 40 ms periodicity windows on a shared 5 ms clock."""
    if type(rate) is not int or not 8000<=rate<=192000 or type(start) is not int or type(end) is not int or not 0<=start<end:raise ValueError('声音分析范围或采样率无效')
    first=round(start*rate/1000);last=round(end*rate/1000)
    if last>len(samples):return {'available':False,'reason':'空隙超出有效音轨'}
    margin=round(rate*.2);left=max(0,first-margin);right=min(len(samples),last+margin)
    data=np.asarray(samples[left:right],dtype=np.float32)/32768
    if not np.isfinite(data).all():raise ValueError('声音数据包含无效数值')
    size=max(64,round(rate*.04));hop=max(1,round(rate*.005));energy_size=max(8,round(rate*.01))
    centers=np.arange(size//2,len(data)-size//2+1,hop,dtype=np.int64)
    if not len(centers):return {'available':False,'reason':'上下文声音不足'}
    offsets=np.arange(size)-size//2;frames=data[centers[:,None]+offsets]
    frames=frames-frames.mean(axis=1,keepdims=True)
    e_offsets=np.arange(energy_size)-energy_size//2
    energy=data[centers[:,None]+e_offsets]
    rms=np.sqrt(np.mean(energy*energy,axis=1))
    windowed=frames*np.hanning(size).astype(np.float32)
    length=1<<(2*size-1).bit_length();frequency=np.fft.rfft(windowed,n=length,axis=1)
    acf=np.fft.irfft(frequency*np.conjugate(frequency),n=length,axis=1)
    minimum=max(2,rate//1600);maximum=min(size-1,rate//70)
    periodic=np.max(acf[:,minimum:maximum+1],axis=1)/np.maximum(acf[:,0],1e-15)
    times=(centers+left)*1000/rate;inside=(times>=start)&(times<end)
    before=(times<start)&(times>=start-150);after=(times>=end)&(times<end+150)
    if not inside.any() or not before.any() or not after.any():return {'available':False,'reason':'边界两侧声音不足，先保留'}
    reference=min(float(np.median(rms[before])),float(np.median(rms[after])))
    quiet=rms[inside]<=max(1e-5,reference*.08)
    quiet_ms=_longest(quiet)*hop*1000/rate
    # Compare normalized spectral shape, not absolute volume or elapsed time.
    spectrum=np.abs(frequency)
    spectrum/=np.maximum(np.linalg.norm(spectrum,axis=1,keepdims=True),1e-15)
    template=(np.mean(spectrum[before],axis=0)+np.mean(spectrum[after],axis=0))*.5
    template/=max(float(np.linalg.norm(template)),1e-15)
    similarity=spectrum[inside]@template
    return {'available':True,'quiet_ms':round(float(quiet_ms),3),
            'periodic_fraction':float(np.mean(periodic[inside]>=.65)),
            'context_periodicity':min(float(np.median(periodic[before])),float(np.median(periodic[after]))),
            'energy_ratio':float(np.quantile(rms[inside],.1)/max(reference,1e-12)),
            'context_rms':reference,'spectral_similarity':float(np.quantile(similarity,.1)),
            'frames':int(inside.sum()),'step_ms':hop*1000/rate}


def phoneme_cover(lines,target,binding):
    from .provenance import voice_lookup
    from .japanese import hiragana
    line,unit,item=target_item(lines,target['left']);evidence=line.timing_evidence
    if any(evidence.get(key)!=binding.get(key) for key in ('source_sha256','audio_sha256','audio_role')):return None
    if not all(binding.get(key) for key in ('source_sha256','audio_sha256','audio_role')):return None
    current=hiragana(item.kana)
    for value in voice_lookup(line).values():
        if not current or not current.endswith(hiragana(value['kana'])):continue
        edge=value['start'];valid=True
        for phone in value['phones']:
            if not isinstance(phone,dict):valid=False;break
            a,b=phone.get('start'),phone.get('end')
            if type(a) is not int or type(b) is not int or not edge<=a<b<=value['end']:valid=False;break
            edge=b
        if not valid or edge!=value['end'] or value['phones'][0].get('start')!=value['start']:continue
        for phone in value['phones']:
            if not isinstance(phone.get('phone'),str) or phone['phone'] not in {'a','i','u','e','o'}:continue
            a,b=phone.get('start'),phone.get('end')
            if type(a) is int and type(b) is int and 0<=a<=target['start']<target['end']<=b:
                return {'phone':phone['phone'],'start':a,'end':b,'kana':value['kana']}
    return None


def classify(metrics,role,phone=None):
    if not metrics.get('available'):return 'unavailable',metrics.get('reason','声音依据不可用')
    if metrics['quiet_ms']>=25:return 'quiet','检测到连续低能量区间，先保留并试听是否休止'
    if phone:return 'continuous','匹配的歌声音素覆盖此处，声音未见明显低能量间隔'
    if role!='vocals':return 'uncertain','原声中的伴奏可能持续；不能据此确认歌声连续'
    if (metrics['context_rms']>=1e-4 and metrics['energy_ratio']>=.5 and
            metrics['periodic_fraction']>=.8 and metrics['context_periodicity']>=.65 and
            metrics['spectral_similarity']>=.75):
        return 'continuous','人声辅助中持续周期性声音与两侧相近，建议延续高亮后试听'
    return 'uncertain','声音或边界不够明确，保留；可带上下文试听后人工决定'


def analyze(lines,pcm,rate,binding,maximum=2000,join_lines=False,cancel=None,progress=lambda value:None,indices=None):
    if type(rate) is not int or not 8000<=rate<=192000:raise ValueError('声音采样率无效')
    if type(join_lines) is not bool:raise ValueError('句间分析选项无效')
    if binding.get('audio_role') not in {'vocals','original'}:raise ValueError('声音来源无效')
    if any(not isinstance(binding.get(key),str) or not re.fullmatch('[0-9a-f]{64}',binding[key]) for key in ('source_sha256','audio_sha256')):raise ValueError('缺少本次素材或音轨指纹')
    original=signature(lines);values=targets(lines,maximum,join_lines,indices)
    pcm=Path(pcm)
    if not pcm.is_file() or not pcm.stat().st_size or pcm.stat().st_size%2:raise ValueError('缺少完整的可分析音轨，请重新准备声音')
    samples=np.memmap(pcm,dtype='<i2',mode='r')
    try:
        for n,value in enumerate(values):
            if cancel is not None and cancel.is_set():raise ValueError('已取消声音空隙分析，原时间保留')
            if value['protected']:
                value.update(status='protected',reason=value['protected'],metrics={},phoneme=None)
            else:
                metrics=measurements(samples,rate,value['start'],value['end']);phone=phoneme_cover(lines,value,binding)
                status,reason=classify(metrics,binding['audio_role'],phone)
                value.update(status=status,reason=reason,metrics=metrics,phoneme=phone)
            progress({'completed':n+1,'total':len(values)})
    finally:samples._mmap.close()
    if signature(lines)!=original:raise ValueError('歌词在分析期间已变化，未采用')
    result={'version':1,'algorithm':'sound-gaps-v1','signature':original,'binding':copy.deepcopy(binding),
            'maximum_ms':maximum,'join_lines':bool(join_lines),'indices':None if indices is None else sorted(set(indices)),'gaps':values,
            'notice':'声音连续候选用于延续高亮，不验证读音或逐音起点；低能量不等同已确认的语言休止。'}
    result['result_sha256']=result_hash(result);return result


def apply(lines,report,selected,manual=()):
    """Only extend chosen automatic tails; following onsets are immutable."""
    from .provenance import change,remember
    validate_report(report)
    if report.get('signature')!=signature(lines):raise ValueError('歌词或时间已变化，请重新检查空隙；人工修改保留')
    current={v['key']:v for v in targets(lines,report['maximum_ms'],report['join_lines'],report.get('indices'))}
    given={v['key']:v for v in report['gaps']}
    if len(given)!=len(report['gaps']):raise ValueError('声音空隙结果重复')
    chosen=set(selected);forced=set(manual)
    if not forced<=chosen:raise ValueError('人工处理项不在本次选择中')
    if not chosen<=current.keys() or not chosen<=given.keys():raise ValueError('空隙已经变化，请重新检查')
    values=copy.deepcopy(lines);changes=[]
    for key in (value['key'] for value in current.values() if value['key'] in chosen):
        if key not in current or key not in given:raise ValueError('空隙已经变化，请重新检查')
        target=current[key];result=given[key]
        if target['protected']:raise ValueError('不能修改已保护的边界：'+target['protected'])
        if any(result.get(name)!=target[name] for name in ('left','right','start','end','left_id','right_id')):raise ValueError('空隙结果与当前时间不符')
        if result.get('status')!='continuous' and key not in forced:raise ValueError('这个间隔没有连续声音建议；请先试听并明确选择人工处理')
        line,unit,item=target_item(values,target['left']);a,b=target['start'],target['end']
        operation='manual_boundary' if key in forced else 'sound_gap'
        change(item,item.start,b,operation);item.source='manual' if key in forced else 'estimated'
        if item is not unit and unit.end<b:
            change(unit,unit.start,b,operation);unit.source=item.source
        elif key in forced:remember(unit);unit.source='manual'
        if line.end<b:change(line,line.start,b,operation)
        line.reviewed=False
        if line.reading_review:line.reading_review['stale']=True
        entry={'range':[a,b],'decision':'manual' if key in forced else 'continuous','reason':result.get('reason',''),
               'binding':copy.deepcopy(report['binding']),'metrics':copy.deepcopy(result.get('metrics',{})),
               'phoneme':copy.deepcopy(result.get('phoneme'))}
        history=line.timing_evidence.get('gap_checks',[])
        history=history if isinstance(history,list) else []
        line.timing_evidence['gap_checks']=[*history[-199:],entry]
        changes.append({**target,'manual':key in forced})
    for line in values:line.validate()
    return values,changes
