"""Plan acoustic runs between human anchors; never invent missing boundaries."""
import copy
import unicodedata
from .japanese import hiragana,romaji
from .model import Highlight,LyricLine

def reading_parts(reading):
    parts=[]
    for c in reading:
        normalized=hiragana(c)
        if '\uff61'<=c<='\uff9f' or len(normalized)!=1 or not ('ぁ'<=normalized<='ゖ' or c=='ー'):
            raise ValueError('请先把每个词组的实际读音填写为全角日语假名，不含空格、标点或汉字。')
        if parts and normalized in 'ぁぃぅぇぉゃゅょゎゕゖ':parts[-1]+=c
        else:parts.append(c)
    if not parts:raise ValueError('请先补全本句假名，再按歌声对齐。')
    return parts

def pronunciations(unit):
    parts=reading_parts(unit.kana);keys=[];vowel=''
    for part in parts:
        normalized=hiragana(part)
        key='cl' if normalized=='っ' else vowel if normalized=='ー' else romaji(normalized)
        if hiragana(unit.kana) in {'は','へ'} and len(parts)==1 and unit.romaji in {'wa','e'}:key=unit.romaji
        if not key:raise ValueError('长音「ー」前缺少可识别的元音，请先修正假名。')
        keys.append(key)
        vowel=next((c for c in reversed(key) if c in 'aeiou'),vowel)
    return parts,keys

def plan(line):
    line.validate()
    if line.locked or line.reviewed:raise ValueError('本句时间已确认或锁定；如需重算，请先解除本句时间确认。')
    if not line.units:raise ValueError('请先按原歌词分词并填写假名，再对齐歌声。')
    if not 100<=line.end-line.start<=60000:raise ValueError('请用“整句范围”圈住本句歌声，范围须在 0.1 至 60 秒内。')
    baseline=copy.deepcopy(line);jobs=[];pending=[];left=line.start;protected=[]
    def flush(right):
        nonlocal pending,left
        if pending:
            if right-left<max(20,len(pending)*10):raise ValueError('人工固定位置之间没有足够空间容纳未固定音节，请先检查整句范围和固定边界。')
            jobs.append({'start':left,'end':right,'mora':pending});pending=[]
        left=right
    for i,unit in enumerate(baseline.units):
        if unit.locked:
            flush(unit.start);left=unit.end;protected.append({'unit':i,'kind':'locked'});continue
        parts,keys=pronunciations(unit)
        if unit.highlights:
            if [h.kana for h in unit.highlights]!=parts:raise ValueError('本句含人工拆合音节，请先在“补全音节”检查其假名划分。')
        else:
            unit.highlights=[Highlight(p,unit.start+round((unit.end-unit.start)*j/len(parts)),unit.start+round((unit.end-unit.start)*(j+1)/len(parts))) for j,p in enumerate(parts)]
        if unit.source=='manual':flush(unit.start)
        for j,(highlight,key) in enumerate(zip(unit.highlights,keys)):
            if highlight.source=='manual' or set(highlight.fixed_edges)=={'start','end'}:
                flush(highlight.start);left=highlight.end;protected.append({'unit':i,'highlight':j,'kind':'manual'})
            else:
                if 'start' in highlight.fixed_edges:flush(highlight.start)
                pending.append({'unit':i,'highlight':j,'kana':highlight.kana,'pronunciation':key})
                if 'end' in highlight.fixed_edges:flush(highlight.end)
        if unit.source=='manual':flush(unit.end)
    flush(line.end)
    if not jobs:raise ValueError('本句全部音节已人工固定，没有可重算的部分。')
    return {'original':line.to_dict(),'baseline':baseline.to_dict(),'jobs':jobs,'protected':protected}

def propose(prepared,result,source_sha256,audio_sha256,audio_role,leading_gap=True):
    line=LyricLine.from_dict(prepared['baseline']);notes=[];evidence=[];changed=0;changed_units=set();inferred_units=set()
    rows=result.get('jobs',[])
    guides=prepared.get('guide_points',[])
    if guides and any(row.get('error') for row in rows):raise ValueError('固定位置之间有区间未成功，整句原轴保留；定位草稿可继续或转手工校对。')
    changed_units.update(point['unit'] for point in guides)
    if len(rows)!=len(prepared['jobs']) or [r.get('index') for r in rows]!=list(range(len(rows))):raise ValueError('对齐结果缺少区间，未采用。')
    for job,output in zip(prepared['jobs'],rows):
        if output.get('error'):notes.append(output['error']);continue
        values=output.get('mora',[]);previous=job['start'];invalid=False;warnings=[]
        if len(values)!=len(job['mora']):raise ValueError('对齐结果音节数变化，未采用。')
        for mora_index,(target,value) in enumerate(zip(job['mora'],values)):
            if any(target[k]!=value.get(k) for k in ('unit','highlight','kana','pronunciation')):raise ValueError('对齐结果更改了输入读音，未采用。')
            a=value.get('start');b=value.get('end');phones=value.get('phones',[])
            if type(a) is not int or type(b) is not int or not previous<=a<b<=job['end'] or not phones:invalid=True;break
            edge=a
            for phone in phones:
                if type(phone.get('start')) is not int or type(phone.get('end')) is not int or not edge<=phone['start']<phone['end']<=b:invalid=True;break
                edge=phone['end']
            if edge!=b or phones[0]['start']!=a:invalid=True
            if b-a<30:warnings.append(value['kana']+'：音节过短，请细听。')
            if b-a>1500:warnings.append(value['kana']+'：持续超过 1.5 秒，请核对拖音。')
            if a-previous>=150 and (leading_gap or mora_index>0):warnings.append(f'音节前有 {a-previous} ms 间隔，请试听是否休止。')
            previous=b
        if invalid:
            if guides:raise ValueError('固定位置之间未得到完整声音边界，原轴保留；定位草稿可继续或转手工校对。')
            notes.append('模型漏掉音素或边界无效；此区间保留原时间。');continue
        for target,value in zip(job['mora'],values):
            unit=line.units[target['unit']];h=unit.highlights[target['highlight']]
            old_start,old_end=h.start,h.end
            h.start=old_start if 'start' in h.fixed_edges else value['start']
            h.end=old_end if 'end' in h.fixed_edges else value['end']
            if h.start>=h.end:raise ValueError('声音候选与人工固定边界冲突，原时间保留。')
            h.source='acoustic';changed+=1
            from .provenance import create
            h.timing_origin=create('acoustic',value['start'],value['end'],'tifa','phoneme_alignment',h.kana)
            if (h.start,h.end)!=(value['start'],value['end']):
                h.timing_origin['current']=[h.start,h.end];h.timing_origin['operations']=['manual_boundary']
            changed_units.add(target['unit']);inferred_units.add(target['unit'])
            if unit.source!='manual':unit.source='acoustic'
        for a,b in zip(values,values[1:]):
            if a['phones'][-1]['phone']==b['phones'][0]['phone'] and a['end']==b['start']:warnings.append(a['kana']+'／'+b['kana']+'：相同音连续，内部分界需人工听拍。')
        evidence.append({'window':[job['start'],job['end']],'mora':values,'agreement':output.get('agreement'),'notes':warnings});notes+=warnings
    if not changed:raise ValueError('没有生成可用的声音边界，原时间保留。请核对假名与整句范围，或手工划音。')
    original=LyricLine.from_dict(prepared['original'])
    for i,unit in enumerate(line.units):
        if i not in changed_units:line.units[i]=copy.deepcopy(original.units[i]);continue
        if unit.highlights and not unit.locked and unit.source!='manual':
            unit.start=unit.highlights[0].start;unit.end=unit.highlights[-1].end
            if i in inferred_units:unit.timing_origin=create('acoustic',unit.start,unit.end,'tifa','phoneme_envelope',unit.kana)
            else:
                from .provenance import record
                record(original.units[i],unit,'manual_boundary')
    line.reviewed=False
    line.timing_evidence={'engine':result['engine'],'model_sha256':result['model_sha256'],'source_sha256':source_sha256,'audio_sha256':audio_sha256,'audio_role':audio_role,'timestep_ms':result['timestep_ms'],'runs':evidence,'protected':prepared['protected'],'notes':list(dict.fromkeys(notes)),'notice':'按输入假名强制对齐歌声，未核验假名是否唱对；模型分数不是准确率。整句头尾、原文、读音和人工固定部分保留。'}
    if guides:
        from .acoustic_guides import validate_result
        line.timing_evidence['guide_points']=copy.deepcopy(guides)
        line.timing_evidence['guide_scope']=prepared['guide_scope']
        line.timing_evidence['notice']+=' 人工固定的起点或终点精确保留；另一端仍为待审核候选。'
        validate_result(prepared,line)
    line.validate();protected_equal(LyricLine.from_dict(prepared['original']),line)
    return line

def protected_equal(old,new):
    if (old.id,old.text,old.start,old.end,old.kana,old.romaji,old.translation,old.display_start,old.display_end)!=(new.id,new.text,new.start,new.end,new.kana,new.romaji,new.translation,new.display_start,new.display_end) or len(old.units)!=len(new.units):raise ValueError('歌声对齐不能更改整句范围、原文或读音。')
    if (old.locked,old.match,old.reading_review)!=(new.locked,new.match,new.reading_review):raise ValueError('歌声对齐不能更改匹配与读音依据。')
    for before,after in zip(old.units,new.units):
        if (before.text,before.kana,before.romaji,before.reading_source,before.locked)!=(after.text,after.kana,after.romaji,after.reading_source,after.locked):raise ValueError('歌声对齐不能更改词组或读音。')
        if before.locked and before!=after:raise ValueError('人工锁定的词组已变化，拒绝采用。')
        if before.source=='manual' and (before.start,before.end)!=(after.start,after.end):raise ValueError('人工固定的词组范围已变化，拒绝采用。')
        for j,h in enumerate(before.highlights):
            if h.fixed_edges and (j>=len(after.highlights) or not set(h.fixed_edges)<=set(after.highlights[j].fixed_edges) or any(getattr(h,edge)!=getattr(after.highlights[j],edge) for edge in h.fixed_edges)):
                raise ValueError('人工固定起止点已变化，拒绝采用。')
            if h.source=='manual' and (j>=len(after.highlights) or h!=after.highlights[j]):raise ValueError('人工音节已变化，拒绝采用。')
