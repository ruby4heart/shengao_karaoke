"""Timing basis is independent of editor protection and human confirmation.

An API word envelope does not prove its internal mora boundaries. Moving an
estimated run does not turn it into individually calibrated acoustic evidence.
Empty metadata is retained as empty for immutable legacy task signatures.
"""
import copy

KINDS=frozenset(('character','word','estimated','acoustic','manual','imported','reference','unknown'))
PROVIDERS=frozenset(('local','elevenlabs','microsoft','tifa','ass','srt','lrc','mixed','unknown'))
OPERATIONS=frozenset(('shift','stretch','manual_boundary','automatic_gap','sound_gap','regroup','clamp'))
_FIELDS=frozenset(('version','kind','provider','method','reference','current','reading','parent_kinds','operations'))
_CHANGES=(('parent_kinds',KINDS),('operations',OPERATIONS))
_ACCELERATOR=None


def _set_accelerator(module):
    global _ACCELERATOR
    _ACCELERATOR=None
    if module is None:return
    try:context=module.origin_context(_FIELDS,KINDS,PROVIDERS,_CHANGES)
    except (AttributeError,TypeError,ValueError):return
    _ACCELERATOR=(module.origin_valid,context,KINDS,PROVIDERS,OPERATIONS,_FIELDS,_CHANGES)


def validate(value):
    native=_ACCELERATOR
    if native is not None and KINDS is native[2] and PROVIDERS is native[3] and OPERATIONS is native[4] and _FIELDS is native[5] and _CHANGES is native[6] and native[0](native[1],value):return
    if not isinstance(value,dict):raise ValueError('时间来源记录无效')
    if not value:return
    if not value.keys()<=_FIELDS or type(value.get('version')) is not int or value.get('version')!=1 or not isinstance(value.get('kind'),str) or value['kind'] not in KINDS or not isinstance(value.get('provider'),str) or value['provider'] not in PROVIDERS:
        raise ValueError('时间来源类型无效')
    if not isinstance(value.get('method'),str) or len(value['method'])>80:raise ValueError('时间来源说明无效')
    for name in ('reference','current'):
        pair=value.get(name)
        if not isinstance(pair,list) or len(pair)!=2 or type(pair[0]) is not int or type(pair[1]) is not int or not 0<=pair[0]<=pair[1]:raise ValueError('时间来源范围无效')
    if 'reading' in value and (not isinstance(value['reading'],str) or len(value['reading'])>20000):raise ValueError('时间来源读音无效')
    for name,choices in _CHANGES:
        if name not in value:continue
        values=value[name]
        if not isinstance(values,list) or len(values)>len(choices) or any(not isinstance(v,str) or v not in choices for v in values) or (len(values)>1 and len(values)!=len(set(values))):
            raise ValueError('时间来源变更记录无效')


def create(kind,start,end,provider='local',method='',reading=None,parents=()):
    value={'version':1,'kind':kind,'provider':provider,'method':method,'reference':[start,end],'current':[start,end]}
    if reading is not None:value['reading']=reading
    if parents:value['parent_kinds']=sorted(set(parents))
    validate(value);return value


def inferred(item):
    """Do not invent character/word granularity absent from old records."""
    old=getattr(item,'timing_origin',{})
    if old:return copy.deepcopy(old)
    source=getattr(item,'source','')
    if not isinstance(source,str):source=''
    kind={'estimated':'estimated','acoustic':'acoustic','manual':'manual','word':'word',
          'recognition':'reference','alignment':'reference','matched':'reference','mapped':'reference',
          'ass':'imported','srt':'imported','lrc':'imported','imported':'imported'}.get(source,'unknown')
    return create(kind,item.start,item.end,'unknown','legacy',getattr(item,'kana','') if kind=='acoustic' else None)


def remember(item):
    if not item.timing_origin:item.timing_origin=inferred(item)
    return item.timing_origin


def change(item,start,end,operation):
    if operation not in OPERATIONS:raise ValueError('时间变更方式无效')
    value=remember(item)
    if [start,end]!=[item.start,item.end]:
        value['operations']=sorted(set(value.get('operations',[]))|{operation})
    value['current']=[start,end];item.start,item.end=start,end


def record(before,after,operation,force=False):
    changed=(before.start,before.end)!=(after.start,after.end)
    if not (changed or force or getattr(before,'source',None)!=getattr(after,'source',None)):return
    value=inferred(before)
    if operation=='shift' and before.end-before.start!=after.end-after.start:operation='stretch'
    if changed:value['operations']=sorted(set(value.get('operations',[]))|{operation})
    value['current']=[after.start,after.end];after.timing_origin=value


def record_tree(before,after,operation):
    def kind(item):return operation(item) if callable(operation) else operation
    record(before,after,kind(before))
    for a,b in zip(before.units,after.units):
        record(a,b,kind(a))
        for x,y in zip(a.highlights,b.highlights):record(x,y,kind(x))


def preserve_before_confirmation(line):
    for unit in line.units:
        remember(unit)
        for h in unit.highlights:remember(h)


def legacy_manual_reading(unit):
    origin=unit.timing_origin
    return bool(unit.source=='manual' and not unit.reading_source and unit.kana and
                (not origin or origin.get('method')=='legacy' and origin.get('kind')=='manual'))


def effective_kind(value):
    ops=set(value.get('operations',[]))
    return 'manual' if 'manual_boundary' in ops else 'estimated' if ops&{'stretch','automatic_gap','sound_gap','clamp'} else value['kind']


def derived(kind,start,end,items,method,reading=None):
    origins=[inferred(v) for v in items];providers={v['provider'] for v in origins};parents={effective_kind(v) for v in origins}
    provider=next(iter(providers)) if len(providers)==1 else 'mixed' if providers else 'local'
    return create(kind,start,end,provider,method,reading,parents)


def group_basis(items,start,end,method='grouped_reference'):
    """Exact outer envelopes may be combined; new interior cuts are estimates."""
    origins=[inferred(v) for v in items]
    valid=bool(items and start==items[0].start and end==items[-1].end and
               all(v['current']==[item.start,item.end] for item,v in zip(items,origins)))
    kinds={effective_kind(v) for v in origins}
    kind=next(iter(kinds)) if valid and len(kinds)==1 else 'reference' if valid and kinds<={'character','word','reference'} else 'estimated'
    value=derived(kind,start,end,items,method)
    if valid and origins and kind!='manual':
        value['reference']=[min(v['reference'][0] for v in origins),max(v['reference'][1] for v in origins)]
        operations=set().union(*(set(v.get('operations',[])) for v in origins))
        if operations:value['operations']=sorted(operations)
    return value


def voice_lookup(line):
    """Recover only the fixed legacy model's retained, nonempty phoneme runs."""
    evidence=line.timing_evidence
    if evidence.get('engine')!='tifa-1.0-st-mora-cpu-v1' or evidence.get('model_sha256')!='8d9bf896da1827f36bf135f80c7ab1fc4f3c1d48f328818b8402c9527c0f014b':return {}
    output={};runs=evidence.get('runs',[])
    if not isinstance(runs,list):return output
    for run in runs:
        if not isinstance(run,dict) or not isinstance(run.get('mora'),list):continue
        for value in run['mora']:
            if not isinstance(value,dict):continue
            a,b=value.get('start'),value.get('end');reading=value.get('kana');phones=value.get('phones')
            if type(a) is int and type(b) is int and 0<=a<b and isinstance(reading,str) and reading and isinstance(phones,list) and phones:
                output.setdefault((a,b),[]).append(value)
    return {key:values[0] for key,values in output.items() if len(values)==1}


def describe(item,line,word=-1,part=-1,lookup=None):
    """Read-only legacy recovery needs actual retained intervals, not a flag."""
    own=item.timing_origin;origin=inferred(item)
    if own and (origin['provider']!='unknown' or origin['kind'] not in {'acoustic','unknown'}):return summary(item,line.reviewed,part>=0)
    voice=lookup if lookup is not None else voice_lookup(line)
    marked=origin['kind']=='acoustic' or not own and getattr(item,'source','')=='acoustic'
    fitted=word<0 and bool(line.timing_evidence.get('fit_range'))
    if voice and (marked or fitted):
        a,b=origin['reference']
        references=[voice.get((a,b))] if part>=0 else sorted((v for (x,y),v in voice.items() if a<=x<y<=b),key=lambda v:v['start'])
        if references and all(references) and sum(len(v['kana']) for v in references)<=20000 and a==references[0]['start'] and b==references[-1]['end']:
            proxy=copy.copy(item);reading=''.join(v['kana'] for v in references)
            proxy.timing_origin={**origin,'kind':'acoustic','provider':'tifa','method':'restored_legacy_voice','reading':reading}
            return summary(proxy,line.reviewed,part>=0)
        if own:
            value=summary(item,line.reviewed,part>=0);value['detail' if line.reviewed or 'manual_boundary' in origin.get('operations',[]) else 'issues'].append('旧声音标记的参考范围未能对应保留的音素；不作为新的声音验证。');return value
        value=summary(item,line.reviewed,part>=0)
        value['display_kind']='estimated';value['title']='已人工确认 · 保留旧歌声标记' if line.reviewed else '旧歌声边界 · 待复核'
        message='旧歌声标记保留，但当前边界未能对应保留的音素区间；不当作新的声学验证。'
        value['detail' if line.reviewed else 'issues'].append(message);return value
    return summary(item,line.reviewed,part>=0)


def summary(item,confirmed=False,mora=False):
    value=inferred(item);kind=value['kind'];ops=set(value.get('operations',[]));issues=[]
    names={'character':'字符时间参考','word':'单词时间参考','estimated':'估算音节' if mora else '估算范围',
           'acoustic':'歌声候选','manual':'人工时间','imported':'导入字幕时间','reference':'文字时间参考','unknown':'来源未记录'}
    title=names[kind];detail=[]
    displayed=effective_kind(value)
    if displayed=='estimated' and kind!='estimated':
        title='变换后估算';detail.append('原始时间依据：'+names[kind]+'；当前位置经过重新计算，不能沿用原始边界的粒度。')
    if value['method']=='legacy':detail.append('旧记录未保留完整来源；不推断缺失的字／词粒度。')
    if value['method']=='legacy' and kind=='manual':detail.append('旧版人工标记也用于整体移动，无法据此判断是否曾逐音校准。')
    if value['method']=='lrc_end_estimate':detail.append('LRC 提供起点；本句结束按下一标签或默认 5 秒推算。')
    if value['method']=='phrase_transcription':title='整句时间参考';detail.append('服务只返回整句范围，内部词组与音节需要另行估算或对齐。')
    if value['method']=='restored_legacy_voice':detail.append('旧工程保留的音素区间与原始参考范围逐项对应；仅读取依据，不改写旧记录。')
    if value.get('parent_kinds'):detail.append('上级时间依据：'+'、'.join(names[k] for k in value['parent_kinds'])+'。')
    if 'manual_boundary' in ops:title='人工调整';detail.append('手动修改过这个范围的边界，原始依据仍保留。')
    if 'shift' in ops:detail.append('整体手动平移过；内部相对时间未因此得到逐音验证。')
    if 'stretch' in ops:detail.append('按比例／分段调整过；内部边界需要重新试听。')
    if 'automatic_gap' in ops:issues.append('曾按固定短间隙规则延续／调整边界，并非声音休止判断。')
    if 'sound_gap' in ops:detail.append('按声音连续候选延续过高亮，后一音节起点保持；不等于重新识别逐音边界。')
    if 'clamp' in ops:issues.append('返回的时间重叠曾被整理，请核对边界。')
    if kind=='estimated':
        detail.append(('原始轴' if 'manual_boundary' in ops else '当前轴')+'由已有范围内插或按假名分配，未识别到每个演唱音节的声音起点。')
    if displayed=='estimated' and not confirmed:issues.append('内部时间为估算，需试听或按歌声重算。')
    if kind in {'character','word','reference'}:detail.append('文字的字／词时间参考，不等同日语演唱音素边界。')
    if kind=='acoustic':detail.append('按输入假名强制对齐声音；不能据此确认假名是否唱对。')
    if value['current']!=[item.start,item.end]:issues.append('时间已改变，原始来源尚未记录这次变更。')
    if kind=='acoustic' and 'reading' in value:
        from .japanese import hiragana
        current_reading=getattr(item,'kana','');current_reading=current_reading if isinstance(current_reading,str) else ''
        if hasattr(item,'units') and item.units:current_reading=''.join(u.kana for u in item.units if isinstance(u.kana,str))
        different_reading=hiragana(value['reading'])!=hiragana(current_reading)
    else:different_reading=False
    if different_reading:
        if 'manual_boundary' in ops or confirmed:detail.append('原始歌声依据对应旧读音，不作为当前假名的声音验证；保留人工校对结果。')
        else:issues.append('歌声依据对应旧读音；当前假名需重新对齐或人工校准。')
    if item.end==item.start:issues.append('零时长，请检查是否漏音。')
    elif mora and not confirmed and item.end-item.start<30:issues.append('音节短于 30 ms，请细听。')
    elif mora and not confirmed and item.end-item.start>1500:issues.append('音节超过 1.5 秒，请核对拖音。')
    fixed=getattr(item,'fixed_edges',[])
    if fixed:
        title+=' · 固定'+('起止点' if len(fixed)==2 else '起点' if fixed==['start'] else '终点')
        detail.append('只固定列出的人工边界；未固定的另一端仍需试听，不自动算作人工确认。')
    if confirmed:title='已人工确认 · '+title
    elif 'manual_boundary' in ops:title+=' · 待确认'
    elif ops:title+=' · 已调整'
    else:title+=' · 待试听'
    if getattr(item,'source','')=='manual' and displayed!='manual' and not confirmed:
        title+=' · 已保护';detail.append('人工操作保护只防止自动覆盖，不表示这些边界已经逐音校准。')
    return {'kind':kind,'display_kind':displayed,'title':title,'detail':detail,'issues':issues,'origin':value,'confirmed':bool(confirmed)}


def rows(line):
    output=[];lookup=voice_lookup(line)
    def add(item,word,part,text,level):
        value=describe(item,line,word,part,lookup)
        if word<0 and line.match.get('status') in {'uncertain','unmatched'}:value['issues'].insert(0,'歌词位置存疑：'+line.match.get('reason','请先圈住正确唱段。'))
        if word<0:
            notes=line.timing_evidence.get('notes',[])
            if isinstance(notes,list):
                for note in notes[:100]:
                    if not isinstance(note,str):continue
                    target=value['detail'] if line.reviewed else value['issues']
                    target.append('原始声音分析提示（修改后需复核）：'+note[:1000])
        output.append({**value,'word':word,'part':part,'text':text,'level':level,'start':item.start,'end':item.end})
    add(line,-1,-1,line.text,'整句')
    for i,unit in enumerate(line.units):
        add(unit,i,-1,unit.text,'词组')
        for j,h in enumerate(unit.highlights):add(h,i,j,h.kana,'音节')
    return output


def line_summary(line):
    from collections import Counter
    leaves=[(h,i,j) for i,u in enumerate(line.units) for j,h in enumerate(u.highlights)] or [(u,i,-1) for i,u in enumerate(line.units)]
    lookup=voice_lookup(line);counts=Counter(describe(v,line,i,j,lookup)['display_kind'] for v,i,j in leaves)
    names={'character':'字符参考','word':'词时间参考','estimated':'估算','acoustic':'歌声候选','manual':'人工','imported':'导入','reference':'旧文字参考','unknown':'来源未记录'}
    body='、'.join(f'{names[k]} {n}' for k,n in counts.items()) or '尚未划分词组／音节'
    return ('已确认；原始依据：' if line.reviewed else '待试听：')+body
