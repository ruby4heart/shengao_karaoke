"""Ordered text context and reviewable omissions, never singing confirmation."""
from bisect import bisect_left,bisect_right
from collections import Counter


def protected(line,replace_manual=False):
    def manual(item):
        origin=item.timing_origin
        return getattr(item,'source','')=='manual' or origin.get('kind')=='manual' or bool(
            set(origin.get('operations',[]))&{'manual_boundary','shift','stretch'})
    return line.locked or line.reviewed or (not replace_manual and manual(line)) or any(
        u.locked or (not replace_manual and (manual(u) or any(manual(h) for h in u.highlights))) for u in line.units)


def plan(target,source,line_data,lines,allow_text=True,time_range=None,replace_manual=False):
    keys=[target[a:b] for a,b,_ in line_data];starts=[v.start for v in source];ends=[v.end for v in source]
    source_text=''.join(v.char for v in source);hard=[];conflicts=[];cursor=0
    for i,(line,(a,b,_)) in enumerate(zip(lines,line_data)):
        if not protected(line,replace_manual):continue
        left=bisect_left(starts,line.start);right=bisect_left(ends,line.end+1)
        # Empty transcript ranges are important: an omitted confirmed line
        # must still separate the verses before it from the verses after it.
        if cursor<=left<=right<=len(source):
            hard.append((i,a,b,left,right,'manual',line.start,line.end));cursor=right
        else:conflicts.append({'kind':'protected_overlap','line_ids':[line.id],'reason':'人工位置存在重叠或顺序差异，保留原值并试听'})
    anchors=list(hard);row=position=0
    for following in [*hard,(len(lines),len(target),len(target),len(source),len(source),'end',0,0)]:
        stop,a,b,left,right,kind,begin_ms,end_ms=following
        counts=Counter(keys[row:stop]);block=source_text[position:left];guides=[]
        if allow_text:
            for i in range(row,stop):
                key=keys[i]
                if len(key)<4 or counts[key]!=1 or any(u.locked for u in lines[i].units):continue
                hit=block.find(key)
                if hit<0 or block.find(key,hit+1)>=0:continue
                x=position+hit;y=x+len(key);start,end,_=line_data[i]
                guides.append((i,start,end,x,y,'text',source[x].start,source[y-1].end))
            bad=set();previous=-1
            for index,value in enumerate(guides):
                if value[3]<previous:bad.add(index)
                previous=max(previous,value[4])
            following=len(source)+1
            for index in range(len(guides)-1,-1,-1):
                if guides[index][4]>following:bad.add(index)
                following=min(following,guides[index][3])
            if bad:
                conflicts.append({'kind':'order_conflict','line_ids':[lines[v[0]].id for i,v in enumerate(guides) if i in bad],
                    'ranges':[{'id':lines[v[0]].id,'start':v[6],'end':v[7]} for i,v in enumerate(guides) if i in bad],
                    'reason':'不同原歌词的唯一文字片段在转录中顺序不同，请试听后限定实际时段；原歌词不重排'})
            anchors.extend(v for i,v in enumerate(guides) if i not in bad)
        row=stop+1;position=right
    anchors.sort(key=lambda value:value[0]);regions=[None]*len(lines);counts=[None]*len(lines);windows=[None]*len(lines)
    minimum=time_range[0] if time_range else 0
    maximum=time_range[1] if time_range else max(source[-1].end,max(v.end for v in lines))
    row=position=0;lower=minimum
    for anchor in [*anchors,(len(lines),len(target),len(target),len(source),len(source),'end',maximum,maximum)]:
        stop,a,b,left,right,kind,begin_ms,end_ms=anchor
        begin_ms=max(minimum,min(maximum,begin_ms));end_ms=max(begin_ms,min(maximum,end_ms))
        tally=Counter(keys[row:stop])
        for i in range(row,stop):
            regions[i]=(position,left);counts[i]=tally;windows[i]=[lower,max(lower,begin_ms)]
        if stop<len(lines):
            regions[stop]=(left,right);counts[stop]=Counter({keys[stop]:1});windows[stop]=[begin_ms,end_ms]
        row=stop+1;position=right;lower=end_ms
    hard_windows=[[minimum,maximum] for _ in lines];row=0;lower=minimum
    for anchor in [*hard,(len(lines),0,0,0,0,'end',maximum,maximum)]:
        stop,a,b,left,right,kind,begin_ms,end_ms=anchor
        begin_ms=max(minimum,min(maximum,begin_ms));end_ms=max(begin_ms,min(maximum,end_ms))
        for i in range(row,stop):hard_windows[i]=[lower,max(lower,begin_ms)]
        if stop<len(lines):hard_windows[stop]=[begin_ms,end_ms]
        row=stop+1;lower=end_ms
    return {'anchors':[(a,b,left,right) for _,a,b,left,right,*_ in anchors],
            'regions':regions,'counts':counts,'windows':windows,'hard_windows':hard_windows,'conflicts':conflicts}


def spans(indices,source):
    """Mapped transcript character ranges, including interior insertions as gaps."""
    groups=[]
    for index in sorted(set(indices)):
        if groups and index==groups[-1][-1]+1:groups[-1].append(index)
        else:groups.append([index])
    return [{'start':source[g[0]].start,'end':source[g[-1]].end,
             'text':''.join(source[i].char for i in g),'source_chars':[g[0],g[-1]+1]} for g in groups]


def review(lines,source,values,conflicts):
    issues=list(conflicts);by_id={v['id']:v for v in values}
    for conflict in conflicts:
        if conflict['kind']!='order_conflict':continue
        for uid in conflict['line_ids']:
            value=by_id[uid];info=value['match']
            if info['status']=='matched':info['status']='uncertain'
            if info['status']!='protected':info['reason']='；'.join(v for v in [info['reason'],conflict['reason']] if v)
    for line,value in zip(lines,values):
        info=value['match'];kind=None
        if info['status']=='unmatched':kind='missing_lyric_candidate'
        elif info.get('ambiguous'):kind='repeat_ambiguity'
        elif info['status']=='uncertain':kind='weak_correspondence'
        if kind:
            issues.append({'kind':kind,'line_ids':[line.id],'start':info.get('context_range',[value['start'],value['end']])[0],
                'end':info.get('context_range',[value['start'],value['end']])[1],
                'reason':'未找到足够对应，可能漏识别、缺唱或原文不同；请先试听。' if kind=='missing_lyric_candidate' else info['reason']})
    # A line envelope would swallow an extra phrase inserted *inside* a line.
    # Keep explicit mapped spans instead. Reading-assisted spans are only rough
    # references; a partial overlap is conservatively treated as assigned.
    covered=sorted((s['start'],s['end']) for v in values if v['match']['status']!='unmatched' and v['match']['method']=='reading'
                   for s in v['match'].get('source_spans',[]))
    characters=sorted(s['source_chars'] for v in values if v['match']['status']!='unmatched' and v['match']['method']=='text'
                      for s in v['match'].get('source_spans',[]))
    char_starts=[v[0] for v in characters]
    union=[]
    for start,end in covered:
        if union and start<=union[-1][1]:union[-1][1]=max(union[-1][1],end)
        else:union.append([start,end])
    groups=[];current=[];time_starts=[v[0] for v in union]
    for index,token in enumerate(source):
        char_index=bisect_right(char_starts,index)-1
        used=char_index>=0 and index<characters[char_index][1]
        # Raw word envelopes can contain several estimated characters in one
        # millisecond. Index evidence, rather than a zero-width time overlap,
        # keeps those assigned characters from becoming false "extra words".
        if token.start==token.end:
            time_index=bisect_right(time_starts,token.start)-1
            used=used or time_index>=0 and token.start<=union[time_index][1]
        else:
            time_index=bisect_left(time_starts,token.end)-1
            used=used or time_index>=0 and token.start<union[time_index][1]
        if used or current and token.start-current[-1].end>2500:
            if current:groups.append(current);current=[]
        if not used:current.append(token)
    if current:groups.append(current)
    extras=[{'text':''.join(v.char for v in group),'start':group[0].start,'end':max(group[0].start+10,group[-1].end),
             'kind':'unassigned_transcript','reason':'转录中尚未对应到原歌词的文字（忽略空格和标点），可能为多唱、漏句或识别错误；需试听确认。'} for group in groups]
    by_start=sorted((v['start'],v['id']) for v in values);by_end=sorted((v['end'],v['id']) for v in values)
    for extra in extras:
        nearby=[]
        for boundaries,point in ((by_start,extra['start']),(by_end,extra['end'])):
            index=bisect_left(boundaries,(point,''))
            nearby.extend((abs(t-point),uid) for t,uid in boundaries[max(0,index-1):index+1])
        extra['line_ids']=[min(nearby)[1]]
    return {'version':1,'issues':issues,'unassigned_transcript':extras,'review_required':True,
            'evidence':'transcript_text_not_singing_confirmation','notice':'只按文字及人工位置检查整首顺序；声音与读音仍需试听确认。'}
