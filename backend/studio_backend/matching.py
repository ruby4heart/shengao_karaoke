"""Local monotone lyric/transcript matching; text confidence is not acoustic confidence."""
from collections import Counter
from dataclasses import dataclass
import copy
import unicodedata
from rapidfuzz.distance import Levenshtein

from .model import LyricLine,Unit,Highlight
from .japanese import word_groups,morae
from .provenance import group_basis,derived


def clusters(text):
    result=[]
    for index,char in enumerate(text):
        if result and (unicodedata.combining(char) or char in '\uff9e\uff9f'):
            result[-1][0]+=char;result[-1][2]=index+1
        else:
            result.append([char,index,index+1])
    return result


def normalized(text):
    value=unicodedata.normalize('NFKC',text).casefold()
    return ''.join(chr(ord(c)-0x60) if '\u30a1'<=c<='\u30f6' else c
                   for c in value if unicodedata.category(c)[0] in 'LNM')


def groups(line):
    if line.units:
        result=[];offset=0
        for unit in line.units:
            result.append((unit.text,offset,offset+len(unit.text),unit));offset+=len(unit.text)
        return result
    return [(g.text,g.begin,g.end,Unit(g.text,0,0,g.kana,g.romaji,reading_source='dictionary')) for g in word_groups(line.text)]


@dataclass
class Token:
    char: str
    start: int
    end: int
    precise: bool
    reference: object = None
    part: int = 0
    total: int = 1


def transcript_tokens(lines,time_range=None):
    if sum(len(line.text) for line in lines)>120000:
        raise ValueError('转录文字过长，请先分段处理')
    output=[];previous=0
    for line in sorted(lines,key=lambda value:value.start):
        line.validate()
        units=line.units or [Unit(line.text,line.start,line.end)]
        for unit in units:
            key=normalized(unit.text)
            if not key:
                continue
            if time_range and (unit.end<=time_range[0] or unit.start>=time_range[1]):
                continue
            if output and unit.start<previous-10:
                raise ValueError('转录时间存在重叠，请先整理或选择单一声部的转录结果')
            start=max(previous,unit.start);end=max(start,unit.end)
            if time_range:
                start=max(start,time_range[0]);end=min(end,time_range[1])
            precise=len(key)==1 and unit.source in {'recognition','alignment','manual','matched'} and start==unit.start and end==unit.end
            for index,char in enumerate(key):
                output.append(Token(char,start+round((end-start)*index/len(key)),
                                    start+round((end-start)*(index+1)/len(key)),precise,unit,index,len(key)))
            previous=end
    if not output:
        raise ValueError('没有可用于匹配的转录文字和时间，请先转录或扩大时间范围')
    return output


def reading_tokens(source):
    text=''.join(t.char for t in source);output=[]
    for group in word_groups(text):
        key=normalized(group.kana or group.text)
        values=source[group.begin:group.end]
        if not values or not key:continue
        if key==text[group.begin:group.end]:output.extend(values);continue
        start,end=values[0].start,values[-1].end
        parents=list({id(v.reference):v.reference for v in values if v.reference is not None}.values())
        reference=Unit(key,start,end,timing_origin=derived('estimated',start,end,parents,'reading_match_distribution'))
        for i,char in enumerate(key):
            output.append(Token(char,start+round((end-start)*i/len(key)),start+round((end-start)*(i+1)/len(key)),False,reference,i,len(key)))
    return output


def timing_basis(pairs,source,start,end,exact):
    tokens=[source[i] for i in pairs];groups={}
    for token in tokens:
        if token.reference is not None:groups.setdefault(id(token.reference),[]).append(token)
    parents=[group[0].reference for group in groups.values()]
    complete=exact and len(tokens)>0 and all(t.reference is not None for t in tokens) and all(
        {t.part for t in group}==set(range(group[0].total)) for group in groups.values())
    return group_basis(parents,start,end,'lyric_match') if complete else derived('estimated',start,end,parents,'lyric_match_distribution')


def anchored_opcodes(target,source,line_data,lines,context):
    """Confirmed/locked lines bound the surrounding verses, without moving them."""
    target_pos=source_pos=0
    anchors=context['anchors']
    for begin,end,left,right in [*anchors,(len(target),len(target),len(source),len(source))]:
        for tag,a,b,c,d in Levenshtein.opcodes(target[target_pos:begin],''.join(t.char for t in source[source_pos:left])):
            yield tag,a+target_pos,b+target_pos,c+source_pos,d+source_pos
        if end>begin:
            for tag,a,b,c,d in Levenshtein.opcodes(target[begin:end],''.join(t.char for t in source[left:right])):
                yield tag,a+begin,b+begin,c+left,d+left
        target_pos=end;source_pos=right


def _match_channel(lines,transcript,time_range=None,reading=False,candidates=True,replace_manual=False):
    if not lines:
        raise ValueError('请先粘贴或导入普通歌词，不需要 LRC 时间标签')
    if len(lines)>3000:
        raise ValueError('单次匹配请不要超过 3000 行歌词')
    if time_range is not None:
        if (not isinstance(time_range,(list,tuple)) or len(time_range)!=2 or
            any(type(value) is not int for value in time_range) or not 0<=time_range[0]<time_range[1]):
            raise ValueError('匹配时间范围无效')
    source=transcript_tokens(transcript,time_range)
    if reading:source=reading_tokens(source)
    source_text=''.join(token.char for token in source)
    target=[];line_data=[]
    for line in lines:
        line.validate();parts=groups(line);begin=len(target);members=[]
        for text,_,_,old in parts:
            positions=[]
            match_text=(old.kana or ''.join(g.kana or g.text for g in word_groups(text))) if reading else text
            for value,_,_ in clusters(match_text):
                for char in normalized(value):
                    positions.append(len(target));target.append(char)
                    if len(target)>60000:
                        raise ValueError('匹配文字过长，请分段处理（最多 60000 个归一化字符）')
            members.append((text,positions,old))
        line_data.append((begin,len(target),members))
    target_text=''.join(target)
    if max(len(target_text),len(source_text))>60000:
        raise ValueError('匹配文字过长，请分段处理（最多 60000 个归一化字符）')
    if not target_text:
        raise ValueError('歌词没有可匹配的文字')
    # A single global edit path preserves order across different ASR line breaks.
    mapping=[None]*len(target);exact=[False]*len(target)
    from .matching_context import plan,protected
    context=plan(target_text,source,line_data,lines,allow_text=not reading,time_range=time_range,replace_manual=replace_manual)
    for tag,a,b,c,d in anchored_opcodes(target_text,source,line_data,lines,context):
        if tag in {'equal','replace'}:
            for i,j in zip(range(a,b),range(c,d)):
                mapping[i]=j;exact[i]=target[i]==source[j].char
    from .matching_context import spans
    suggestions=[];summary=Counter();previous_end=0
    for row,(line,(begin,end,members)) in enumerate(zip(lines,line_data)):
        key=target_text[begin:end]
        lower,upper=context['hard_windows'][row]
        # Character/word estimates touching a confirmed boundary are never
        # allowed to carry a neighbouring line across that human position.
        for i in range(begin,end):
            j=mapping[i]
            if j is not None and not lower<=source[j].start<=source[j].end<=upper:
                mapping[i]=None;exact[i]=False
        assigned=[mapping[i] for i in range(begin,end) if mapping[i] is not None]
        exact_count=sum(exact[begin:end]);coverage=exact_count/max(1,end-begin)
        recognized=''.join(token.char for token in source[min(assigned):max(assigned)+1]) if assigned else ''
        score=Levenshtein.normalized_similarity(key,recognized) if key and recognized else 0.0
        left,right=context['regions'][row];local=source_text[left:right];counts=context['counts'][row]
        occurrences=local.count(key) if key else 0
        ambiguous=bool(key and (occurrences>counts[key] or (counts[key]>1 and occurrences!=counts[key])))
        gap=any(source[right].start-source[left].end>2500 for left,right in zip(assigned,assigned[1:]))
        status='matched' if score>=.78 and coverage>=.7 else 'uncertain'
        reasons=[]
        if ambiguous:
            status='uncertain';reasons.append('转录中有多个相同片段，请限定时间范围或人工确认副歌位置')
        if gap:
            status='uncertain';reasons.append('匹配片段中存在较长停顿，请检查是否跨句')
        if not assigned or score<.35 or coverage<.35:
            status='unmatched';reasons.append('没有足够文字对应，未重新分配本行时间')
        if score<.78 or coverage<.7:
            reasons.append('文字对应不足，可能含错字、漏字或额外演唱内容')
        info={'status':status,'score':round(float(score),4),'coverage':round(coverage,4),
              'recognized':recognized,'reason':'；'.join(reasons),'source':'transcript',
              'ambiguous':ambiguous,'timing':'rough','method':'reading' if reading else 'text',
              'original_layout_preserved':True,'context_range':context['windows'][row],
              'hard_context_range':context['hard_windows'][row],
              'source_spans':spans(assigned,source)}
        fixed=protected(line,replace_manual)
        if fixed or status=='unmatched':
            value=copy.deepcopy(line)
            if fixed:
                info['status']='protected';info['reason']='本行有锁定、人工确认或手调时间，保留现有内容'
                previous_end=max(previous_end,line.end)
            value.match=info;suggestions.append(value);summary[info['status']]+=1
            continue
        first=source[min(assigned)].start;last=max(first+10,source[max(assigned)].end)
        # Do not silently shift a later line across a previous matched line.
        if first<previous_end:
            info['status']='unmatched';info['reason']='匹配结果与前一行时间交叉，未应用新时间'
            value=copy.deepcopy(line);value.match=info;suggestions.append(value);summary['unmatched']+=1;continue
        raw_bounds=[]
        for text,positions,old in members:
            pairs=[mapping[i] for i in positions if mapping[i] is not None]
            if pairs:
                left=source[min(pairs)].start;right=source[max(pairs)].end
                precise=all(exact[i] and source[mapping[i]].precise for i in positions if mapping[i] is not None) and len(pairs)==len(positions)
                raw_bounds.append([left,right,precise])
            else:
                raw_bounds.append(None)
        index=0
        while index<len(raw_bounds):
            if raw_bounds[index] is not None:index+=1;continue
            finish=index+1
            while finish<len(raw_bounds) and raw_bounds[finish] is None:finish+=1
            left=raw_bounds[index-1][1] if index else first
            right=raw_bounds[finish][0] if finish<len(raw_bounds) else last
            weights=[max(1,len(members[j][1])) for j in range(index,finish)];total=sum(weights);offset=0
            for j,weight in zip(range(index,finish),weights):
                raw_bounds[j]=[left+round(max(0,right-left)*offset/total),left+round(max(0,right-left)*(offset+weight)/total),False];offset+=weight
            index=finish
        output=[];cursor=first
        for (text,positions,old),(left,right,precise) in zip(members,raw_bounds):
            left=max(cursor,min(last,left));right=max(left,min(last,right))
            unit=Unit(text,left,right,old.kana if old else '',old.romaji if old else '',
                      source='matched' if precise else 'estimated',reading_source=old.reading_source if old else '')
            pairs=[mapping[i] for i in positions if mapping[i] is not None]
            unit.reading_options=copy.deepcopy(old.reading_options) if old else {}
            unit.timing_origin=timing_basis(pairs,source,left,right,len(pairs)==len(positions) and all(exact[i] for i in positions))
            if old and old.highlights:
                duration=max(1,old.end-old.start)
                unit.highlights=[Highlight(part.kana,left+round((right-left)*(part.start-old.start)/duration),
                                           left+round((right-left)*(part.end-old.start)/duration),'estimated') for part in old.highlights]
                from .mora_editing import METHODS
                for h,previous in zip(unit.highlights,old.highlights):
                    custom=previous.source=='manual' and previous.timing_origin.get('method') in METHODS
                    h.source='manual' if custom else 'estimated'
                    h.timing_origin=derived('estimated',h.start,h.end,[unit],previous.timing_origin['method'] if custom else 'mora_distribution',h.kana)
                    if custom:h.timing_origin['operations']=['regroup']
            output.append(unit);cursor=right
        value=LyricLine(line.id,line.text,first,last,output,line.kana or ''.join(u.kana for u in output),line.romaji or ' '.join(u.romaji for u in output if u.romaji),line.translation,
                        line.locked,False,info)
        for key in ('translation','translation_suggestion','translation_original_changed','mora_edits'):
            if key in line.reading_review:value.reading_review[key]=copy.deepcopy(line.reading_review[key])
        value.timing_origin=group_basis(output,first,last,'matched_envelope')
        value.validate();suggestions.append(value);summary[info['status']]+=1;previous_end=last
    if candidates:
        for value,line,(begin,end,_) in zip(suggestions,lines,line_data):
            key=target_text[begin:end]
            if not key or value.match['status'] in {'protected','matched'}:continue
            hits=[];position=source_text.find(key)
            while position>=0 and len(hits)<32:
                hits.append(position);position=source_text.find(key,position+1)
            if len(hits)<2 and value.match['status']=='matched':continue
            choices=[]
            # Prefer candidates close to the current recommendation; retain both
            # earlier/later choruses rather than blindly picking the first one.
            for position in sorted(hits,key=lambda p:abs(source[p].start-value.start))[:8]:
                start,end_time=source[position].start,source[position+len(key)-1].end
                if end_time<=start:continue
                lower,upper=value.match['hard_context_range']
                if start<lower or end_time>upper:continue
                candidate=_match_channel([line],transcript,[start,end_time],reading,False,replace_manual)['suggestions'][0]
                if candidate['match']['status']=='unmatched':continue
                lower,upper=value.match['context_range']
                choices.append({**{name:candidate[name] for name in ('start','end','units','timing_origin')},
                                **{name:candidate['match'][name] for name in ('score','coverage','recognized','method','source_spans')},
                                'outside_context':start<lower or end_time>upper})
            value.match['candidates']=sorted(choices,key=lambda c:c['start'])
    return {'suggestions':[value.to_dict() for value in suggestions],'_context_issues':context['conflicts'],
            'match_summary':{'total':len(lines),**{name:summary[name] for name in ('matched','uncertain','unmatched','protected')}},
            'review_required':True,'matching_version':3,'local':True}


def match_lyrics(lines,transcript,time_range=None,replace_manual=False):
    raw=_match_channel(lines,transcript,time_range,replace_manual=replace_manual)
    phonetic=_match_channel(lines,transcript,time_range,True,replace_manual=replace_manual)
    merged=[];summary=Counter()
    for direct,sound in zip(raw['suggestions'],phonetic['suggestions']):
        a,b=direct['match'],sound['match']
        better=(b['status']!='protected' and b['score']*b['coverage']>a['score']*a['coverage']+.08 and b['coverage']>=.7)
        lower,upper=a['context_range']
        better=better and lower<=sound['start']<sound['end']<=upper
        value=sound if better else direct
        if better:
            for key in ('context_range','hard_context_range'):value['match'][key]=copy.deepcopy(a[key])
            info=value['match'];info['reason']=('按词典读音辅助匹配；特殊唱法请试听。'+info['reason']).rstrip('；')
            if len(morae(value['kana'] or value['text']))<=2 and info['status']=='matched':info['status']='uncertain';info['reason']+='短读音可能存在同音词。'
        if merged and value['match']['status'] in {'matched','uncertain'}:
            previous=merged[-1]
            if previous['match']['status'] in {'matched','uncertain','protected'} and value['start']<previous['end']:
                value=copy.deepcopy(direct);value['match']['status']='unmatched';value['match']['reason']='不同匹配方式的时间交叉，请选择候选或限定范围'
                value['start']=lines[len(merged)].start;value['end']=lines[len(merged)].end;value['units']=copy.deepcopy(lines[len(merged)].to_dict()['units'])
        merged.append(value);summary[value['match']['status']]+=1
    from .matching_context import review
    context_issues=raw.pop('_context_issues',[])
    sequence=review(lines,transcript_tokens(transcript,time_range),merged,context_issues)
    summary=Counter(v['match']['status'] for v in merged)
    return {**raw,'suggestions':merged,'match_summary':{'total':len(lines),**{name:summary[name] for name in ('matched','uncertain','unmatched','protected')}},'original_layout_preserved':True,'sequence_review':sequence}
