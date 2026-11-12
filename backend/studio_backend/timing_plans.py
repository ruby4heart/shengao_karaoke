"""Side-by-side timing plans for lines whose sources disagree.

Every plan comes from work that is already saved or runs on this computer:
the stored Scribe transcript, a saved text-alignment result, the local singing
model on the original or the vocal track, the same model on another reading,
and the rhythm of a confirmed identical chorus. Plans are compared syllable by
syllable. Nothing is chosen for the person, no paid request is added, and
locked, confirmed or manually timed lines are listed read-only.
"""
import copy
import hashlib
import json
import statistics
from .model import LyricLine
from .provenance import derived,inferred,effective_kind
from .sound_gaps import signature,leaves

ALGORITHM='timing-plans-v1'
KINDS={'current':'当前时间','scribe':'Scribe 转录时间','alignment':'文字对齐（已保存结果）',
       'local_original':'本机模型 · 原声','local_vocals':'本机模型 · 人声辅助',
       'reading':'本机模型 · 另一读音','chorus':'已确认副歌节奏'}
AGREE_MS=40
DIFF_MS=80
CONFLICT_MS=120
MAX_READINGS=2
MAX_READING_LINES=40
READING_SOURCES=('transcript','song_dictionary','personal_dictionary','deepseek','dictionary_context','dictionary_entry')
READING_LABELS={'transcript':'对应转录','song_dictionary':'本歌词典','personal_dictionary':'个人词典','deepseek':'已存文字建议',
                'dictionary_context':'词典默认读法','dictionary_entry':'词典其他读法'}
LEVELS={'agree':'各来源一致','close':'各来源接近','conflict':'各来源分歧'}
STATUS={'conflict':'来源分歧','uncertain':'匹配不确定','agree':'来源一致','single':'只有当前时间','protected':'已保护'}
NOTICE=('各方案只供并列比较和试听：没有哪一种来源总是更准，所以默认保持当前时间，不自动选择。'
        '方案全部来自已保存的结果或本机计算，没有新增联网或付费请求；锁定、已确认和人工调整的句子只列出，不改动。')


def result_hash(report):
    value={key:value for key,value in report.items() if key!='result_sha256'}
    return hashlib.sha256(json.dumps(value,ensure_ascii=True,sort_keys=True,allow_nan=False).encode()).hexdigest()


def validate_report(report):
    if not isinstance(report,dict) or report.get('version')!=1 or report.get('algorithm')!=ALGORITHM or not isinstance(report.get('lines'),list):
        raise ValueError('多方案比对结果版本无效')
    try:valid=report.get('result_sha256')==result_hash(report)
    except (TypeError,ValueError):valid=False
    if not valid:raise ValueError('多方案比对结果不完整或已变化，请重新比对；原时间保留')


def line_hash(line):
    return hashlib.sha256(json.dumps(line.to_dict(),ensure_ascii=True,sort_keys=True,allow_nan=False).encode()).hexdigest()


def protected(line):
    """Why automatic plans must leave this line alone, or ''."""
    from .protection import reasons,REASONS
    found=[REASONS[key] for key in reasons(line,'draft')]
    items=[line,*line.units,*(h for u in line.units for h in u.highlights)]
    if not found and any(effective_kind(inferred(item))=='manual' for item in items):found.append(REASONS['manual_timing'])
    if not found and line.match.get('status') in {'protected','manual'}:found.append('本句位置已人工确认或受保护')
    return '、'.join(found)


def shape(line):
    return [(u.text,u.kana,[h.kana for h in u.highlights]) for u in line.units]


def fit_display(value,original):
    """Keep the person's display lead-in and hold-out, widened only as far as the plan needs."""
    value.display_start=None if original.display_start is None else min(original.display_start,value.start)
    value.display_end=None if original.display_end is None else max(original.display_end,value.end)


def same_timing(a,b):
    return (a.start,a.end,shape(a),[(i.start,i.end) for _,_,i in leaves(a)])==(b.start,b.end,shape(b),[(i.start,i.end) for _,_,i in leaves(b)])


def _line(value):
    return value if isinstance(value,LyricLine) or value is None else LyricLine.from_dict(value)


def scribe_lines(lines,transcript):
    """Re-run the free local lyric match on the stored transcript, for every line at once."""
    from .matching import match_lyrics
    rows=[_line(v) for v in transcript]
    if not rows:return {}
    result=match_lyrics(copy.deepcopy(lines),rows);output={}
    for n,(line,raw) in enumerate(zip(lines,result['suggestions'])):
        value=LyricLine.from_dict(raw);info=value.match;status=info.get('status')
        if status in {'matched','uncertain'}:
            value.translation=line.translation;fit_display(value,line)
            score=f'相似度 {info.get("score",0):.0%}，覆盖 {info.get("coverage",0):.0%}' if isinstance(info.get('score'),(int,float)) and isinstance(info.get('coverage'),(int,float)) else ''
            output[n]={'line':value,'note':('转录匹配可靠' if status=='matched' else '转录匹配不确定')+('：'+score if score else '')+'。',
                       'uncertain':status=='uncertain'}
        else:
            output[n]={'line':None,'note':'Scribe 转录里没有找到可靠对应的这句。' if status=='unmatched' else '本句在匹配中受保护，未重新匹配。',
                       'uncertain':status=='unmatched'}
    return output


def alignment_line(current,saved):
    """Text-alignment times from a saved draft, only where words and readings still agree."""
    saved=_line(saved)
    if saved.text!=current.text:return None,'保存的文字对齐对应另一版原文。'
    if not current.units or [(u.text,u.kana) for u in saved.units]!=[(u.text,u.kana) for u in current.units]:
        return None,'保存的文字对齐分词或读音与当前不同，不能逐音节比较。'
    value=copy.deepcopy(current)
    for unit,ref in zip(value.units,saved.units):
        unit.start,unit.end=ref.start,ref.end;unit.source=ref.source or 'alignment';unit.timing_origin=copy.deepcopy(ref.timing_origin)
        if ref.highlights and [h.kana for h in ref.highlights]==[h.kana for h in unit.highlights]:unit.highlights=copy.deepcopy(ref.highlights)
        else:
            count=len(unit.highlights)
            for i,h in enumerate(unit.highlights):
                a=unit.start+round((unit.end-unit.start)*i/count);b=unit.start+round((unit.end-unit.start)*(i+1)/count)
                h.start,h.end=a,b;h.source='estimated';h.fixed_edges=[]
                h.timing_origin=derived('estimated',a,b,[unit],'mora_distribution',h.kana)
    value.start=min(saved.start,value.units[0].start);value.end=max(saved.end,value.units[-1].end)
    value.timing_origin=copy.deepcopy(saved.timing_origin);value.timing_evidence={};value.reviewed=False
    fit_display(value,current)
    try:value.validate()
    except ValueError as error:return None,'保存的文字对齐时间无效：'+str(error)
    return value,'来自本工程最近一次初稿流程中已完成的文字对齐（当时已付费完成，这次不再请求）。'


def alignment_lines(lines,saved,indices):
    output={}
    for n in indices:
        line=lines[n];row=saved.get(line.id)
        if row is None:output[n]={'line':None,'note':'保存的文字对齐里没有这句。'};continue
        try:value,note=alignment_line(line,row)
        except (TypeError,ValueError,KeyError) as error:value,note=None,'保存的文字对齐记录无效：'+str(error)
        output[n]={'line':value,'note':note}
    return output


def local_lines(lines,rows,result):
    """Per-line results of one local singing-model batch."""
    found={v['id']:v for v in result.get('suggestions',[]) if isinstance(v,dict)}
    states=result.get('acoustic',{}).get('lines',{});output={}
    for n in rows:
        uid=lines[n].id;state=states.get(uid,{})
        if state.get('status')=='aligned' and uid in found:
            value=LyricLine.from_dict(found[uid])
            if value.id!=uid or value.text!=lines[n].text:output[n]={'line':None,'note':'本机模型结果与本句原文不符。'};continue
            output[n]={'line':value,'note':state.get('reason','本机歌声模型生成的音节时间。')}
        else:output[n]={'line':None,'note':state.get('reason','本机模型未能生成这句的候选。')}
    return output


def reading_variants(line,transcript=(),verified=False,defaults=None,limit=MAX_READINGS,song=None,personal=None):
    """Up to ``limit`` copies of the line with one word read differently; times come later from the model."""
    from .reading_candidates import review
    from .reading_change import preview
    from .protection import manual_reading
    picks=[]
    for index,unit in enumerate(line.units):
        if line.locked or unit.locked or unit.reading_source in {'manual','manual-review'} or manual_reading(unit):continue
        try:found=review(line,index,[_line(v) for v in transcript],verified,song,personal)
        except ValueError:continue
        for choice in found['choices']:
            if 'current' in choice['sources']:continue
            ranks=[READING_SOURCES.index(s) for s in choice['sources'] if s in READING_SOURCES]
            if ranks:picks.append((min(ranks),index,choice))
    picks.sort(key=lambda v:(v[0],v[1]));output=[]
    for rank,index,choice in picks:
        if len(output)>=limit:break
        try:value=preview(line,index,choice['kana'],defaults)['line']
        except ValueError:continue
        unit=line.units[index];source=READING_SOURCES[rank]
        output.append({'line':value,'word':index,'text':unit.text,'kana':choice['kana'],'before':unit.kana,'source':source,
                       'note':f'第 {index+1} 词「{unit.text}」改读 {choice["kana"]}（原为 {unit.kana}；来源：{READING_LABELS[source]}）。采用会同时改变读音。'})
    return output


def chorus_sources(lines,row,confirmed):
    from .chorus_reuse import source_valid
    found=[]
    for n,line in enumerate(lines):
        if n==row or line.text!=lines[row].text or line.id not in confirmed:continue
        try:source_valid(line,True)
        except ValueError:continue
        found.append(n)
    return sorted(found,key=lambda n:abs(n-row))[:2]


def chorus_line(source,target,anchors,number=None):
    """The confirmed chorus's syllable rhythm, placed where the other plans put this line."""
    if shape(source)!=shape(target):return None,'已确认副歌的分词、读音或音节划分与本句不同，不能套用节奏。'
    own=leaves(source)
    offsets=[anchor-item.start for (_,_,item),anchor in zip(own,anchors) if anchor is not None]
    offset=round(statistics.median(offsets)) if offsets else leaves(target)[0][2].start-own[0][2].start
    offset=max(offset,-source.start)
    value=copy.deepcopy(target)
    for unit,ref in zip(value.units,source.units):
        unit.start,unit.end=ref.start+offset,ref.end+offset;unit.source='estimated'
        unit.timing_origin=derived('estimated',unit.start,unit.end,[ref],'chorus_rhythm',unit.kana)
        for h,r in zip(unit.highlights,ref.highlights):
            h.start,h.end=r.start+offset,r.end+offset;h.source='estimated';h.fixed_edges=[]
            h.timing_origin=derived('estimated',h.start,h.end,[r],'chorus_rhythm',h.kana)
    value.start=source.start+offset;value.end=source.end+offset
    value.timing_origin=derived('estimated',value.start,value.end,[source],'chorus_rhythm',value.kana)
    value.timing_evidence={};value.reviewed=False;fit_display(value,target)
    try:value.validate()
    except ValueError as error:return None,'副歌节奏放到本句位置后无效：'+str(error)
    delta=leaves(value)[0][2].start-leaves(target)[0][2].start
    who=f'第 {number} 句' if number is not None else '相同歌词'
    return value,f'沿用{who}（已人工确认）的音节节奏，起点对到其他方案的多数位置（比当前 {delta:+d} ms）；只是节奏参考，本次演唱可能不同。'


def level(base,line):
    if not base.units or [u.text for u in base.units]!=[u.text for u in line.units]:return 'line'
    if [len(u.highlights) for u in base.units]==[len(u.highlights) for u in line.units]:return 'syllable'
    return 'word'


def grid(base,plans):
    rows=[{'text':item.kana or base.units[w].text,'word':w,'part':p,'values':{}} for w,p,item in leaves(base)]
    tail={'text':'句尾','word':None,'part':None,'values':{}}
    firsts={}
    for i,row in enumerate(rows):firsts.setdefault(row['word'],i)
    for plan in plans:
        line=plan['_line'];own=leaves(line);plan['level']=kind=level(base,line)
        if not own:continue
        if kind=='syllable':
            for row,(_,_,item) in zip(rows,own):row['values'][plan['id']]=item.start
        elif kind=='word':
            for w,unit in enumerate(line.units):
                if w in firsts:rows[firsts[w]]['values'][plan['id']]=unit.start
        elif rows:rows[0]['values'][plan['id']]=own[0][2].start
        tail['values'][plan['id']]=own[-1][2].end
    for row in [*rows,tail]:
        values=list(row['values'].values())
        median=statistics.median(values) if values else None
        row['median']=None if median is None else round(median)
        row['spread']=max(values)-min(values) if len(values)>=2 else 0
        row['outliers']=[k for k,v in row['values'].items() if abs(v-median)>DIFF_MS] if len(values)>=3 else []
    return rows,tail


def compare(entry,base,plans):
    rows,tail=grid(base,plans);every=[*rows,tail]
    for plan in plans:
        gaps=[abs(row['values'][plan['id']]-row['median']) for row in every if plan['id'] in row['values'] and len(row['values'])>=2]
        plan['deviation']=round(statistics.mean(gaps)) if gaps else None
    spread=max((row['spread'] for row in every),default=0)
    kind='agree' if spread<=AGREE_MS else 'close' if spread<=CONFLICT_MS else 'conflict'
    differing=[{'index':i,'text':row['text'],'spread':row['spread'],'outliers':row['outliers']} for i,row in enumerate(rows) if row['spread']>DIFF_MS]
    if tail['spread']>DIFF_MS:differing.append({'index':len(rows),'text':'句尾','spread':tail['spread'],'outliers':tail['outliers']})
    entry.update(grid=rows,tail=tail,spread=spread,level=kind,differing=differing)


def describe(entry):
    labels={p['id']:p['label'] for p in entry['plans']}
    if entry['status']=='protected':return '本句已保护（'+entry['protected']+'），只列出，不比较也不改动。'
    if entry['status']=='single':return '没有其他可用来源，只有当前时间。'+('本句匹配不确定，请试听位置。' if entry.get('uncertain') else '')
    text=f'{LEVELS[entry["level"]]}：各方案最大相差 {entry["spread"]} ms。'
    if entry['differing']:
        parts=[]
        for item in entry['differing'][:6]:
            who='、'.join(labels.get(k,k) for k in item['outliers'])
            parts.append(f'{item["text"]}（差 {item["spread"]} ms'+(f'，偏离多数：{who}' if who else '')+'）')
        text+='差异音节：'+'；'.join(parts)+('…' if len(entry['differing'])>6 else '')+'。'
    if entry.get('uncertain'):text+='匹配不确定，位置本身也要试听。'
    return text


def analyze(lines,sources,indices=None,confirmed=(),unavailable=None,chorus=True):
    """Compare every available plan for the chosen lines; the current timing stays the default."""
    chosen=list(range(len(lines))) if indices is None else sorted(set(indices))
    if any(type(i) is not int or not 0<=i<len(lines) for i in chosen):raise ValueError('歌词范围无效')
    for line in lines:line.validate()
    original=signature(lines);confirmed=set(confirmed);unavailable=dict(unavailable or {});output=[]
    for n in chosen:
        line=lines[n];reason=protected(line)
        entry={'row':n,'line_id':line.id,'text':line.text,'line_sha':line_hash(line),'start':line.start,'end':line.end,
               'match':line.match.get('status',''),'protected':reason,'plans':[],'unavailable':[],'uncertain':line.match.get('status') in {'uncertain','unmatched'}}
        current={'id':'current','kind':'current','label':KINDS['current'],'note':'保持现在的时间，不做改动。','_line':line}
        plans=[current]
        if not reason:
            for kind in ('scribe','alignment','local_original','local_vocals'):
                value=sources.get(kind,{}).get(n)
                if value is None:continue
                if value.get('uncertain') and kind=='scribe':entry['uncertain']=True
                if value.get('line') is None:entry['unavailable'].append({'kind':kind,'label':KINDS[kind],'reason':value.get('note','')});continue
                plans.append({'id':kind,'kind':kind,'label':KINDS[kind],'note':value.get('note',''),'_line':_line(value['line'])})
            for k,value in enumerate(sources.get('reading',{}).get(n,[])):
                label=f'{KINDS["reading"]}（{value.get("text","")}→{value.get("kana","")}）'
                if value.get('line') is None:entry['unavailable'].append({'kind':'reading','label':label,'reason':value.get('note','')});continue
                plans.append({'id':f'reading-{k+1}','kind':'reading','label':label,'note':value.get('note',''),'_line':_line(value['line'])})
            if chorus and line.units:
                rows,_=grid(line,plans)
                anchors=[row['median'] for row in rows]
                for k,m in enumerate(chorus_sources(lines,n,confirmed)):
                    value,note=chorus_line(lines[m],line,anchors,m+1)
                    label=f'{KINDS["chorus"]}（第 {m+1} 句）'
                    if value is None:entry['unavailable'].append({'kind':'chorus','label':label,'reason':note});continue
                    plans.append({'id':f'chorus-{k+1}','kind':'chorus','label':label,'note':note,'_line':value,'source_row':m})
        compare(entry,line,plans)
        for plan in plans:
            value=plan.pop('_line');plan['same']=plan['kind']=='current' or same_timing(value,line)
            plan.update(line=value.to_dict(),start=value.start,end=value.end,reading=value.kana or ''.join(u.kana for u in value.units),
                        changes_reading=[u.kana for u in value.units]!=[u.kana for u in line.units])
        entry['plans']=plans
        others=[p for p in plans if p['kind']!='current']
        entry['status']=('protected' if reason else 'conflict' if entry['level']=='conflict' else 'uncertain' if entry['uncertain']
                         else 'single' if not others else 'agree')
        entry['reason']=describe(entry);output.append(entry)
    if signature(lines)!=original:raise ValueError('歌词在比对期间已变化，未采用')
    result={'version':1,'algorithm':ALGORITHM,'signature':original,'indices':chosen,'notice':NOTICE,
            'sources':{kind:{'label':KINDS[kind],'available':kind not in unavailable,'note':unavailable.get(kind,'')} for kind in KINDS if kind!='current'},
            'lines':output}
    result['result_sha256']=result_hash(result);return result


def stale_rows(lines,report):
    """Line ids changed since the comparison; their old plans are comparison only."""
    current={line.id:line_hash(line) for line in lines}
    return {v['line_id'] for v in report.get('lines',[]) if current.get(v.get('line_id'))!=v.get('line_sha')}


def apply(lines,report,choices):
    """Replace only the chosen lines with the chosen plan, as one reviewable change."""
    validate_report(report)
    if not isinstance(choices,dict) or not choices:raise ValueError('没有选择要采用的方案')
    entries={v['line_id']:v for v in report['lines']};rows={line.id:n for n,line in enumerate(lines)}
    if len(entries)!=len(report['lines']):raise ValueError('多方案比对结果重复')
    values=copy.deepcopy(lines);changes=[]
    for uid in sorted(choices,key=lambda k:rows.get(k,-1)):
        plan_id=choices[uid];entry=entries.get(uid);row=rows.get(uid)
        if entry is None or row is None:raise ValueError('所选句子已不在当前歌词中，请重新比对；人工修改保留')
        current=lines[row]
        if line_hash(current)!=entry['line_sha']:raise ValueError(f'第 {row+1} 句在比对后已修改，请重新比对；人工修改保留')
        reason=protected(current)
        if reason:raise ValueError(f'第 {row+1} 句已保护（{reason}），不能采用方案')
        plan=next((p for p in entry['plans'] if p['id']==plan_id),None)
        if plan is None or plan['kind']=='current':raise ValueError('所选方案不在本次结果中')
        if plan.get('same'):raise ValueError(f'第 {row+1} 句所选方案与当前时间相同')
        value=LyricLine.from_dict(plan['line'])
        if value.id!=current.id or value.text!=current.text:raise ValueError('方案与本句原文不符，请重新比对')
        if plan['kind']!='reading' and [u.kana for u in value.units]!=[u.kana for u in current.units]:raise ValueError('方案改变了读音，请重新比对')
        for other in (row-1,row+1):
            if not 0<=other<len(values):continue
            neighbor=values[other];overlap=value.start<neighbor.end if other<row else value.end>neighbor.start
            if overlap and protected(neighbor):raise ValueError(f'第 {row+1} 句的方案会与已保护的第 {other+1} 句重叠，请手工处理')
        value.translation=current.translation;value.locked=False;value.reviewed=False;fit_display(value,current)
        old=current.timing_evidence.get('timing_plans',[]) if isinstance(current.timing_evidence,dict) else []
        old=old if isinstance(old,list) else []
        value.timing_evidence=copy.deepcopy(value.timing_evidence) if isinstance(value.timing_evidence,dict) else {}
        value.timing_evidence['timing_plans']=[*old[-199:],{'plan':plan['kind'],'label':plan['label'],'previous':[current.start,current.end],
            'range':[value.start,value.end],'level':entry['level'],'spread':entry['spread'],'differing':[d['text'] for d in entry['differing']],
            'changes_reading':bool(plan.get('changes_reading')),'report':report['result_sha256']}]
        value.validate();values[row]=value
        changes.append({'row':row,'line_id':uid,'plan':plan_id,'kind':plan['kind'],'label':plan['label'],'changes_reading':bool(plan.get('changes_reading'))})
    return values,changes


def overlaps(lines,entry,plan):
    """Neighbouring lines a plan would overlap; shown before adoption."""
    row=next((n for n,line in enumerate(lines) if line.id==entry['line_id']),None)
    if row is None:return []
    found=[]
    if row>0 and plan['start']<lines[row-1].end:found.append(row-1)
    if row+1<len(lines) and plan['end']>lines[row+1].start:found.append(row+1)
    return found
