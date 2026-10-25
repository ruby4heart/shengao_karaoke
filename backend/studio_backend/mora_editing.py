"""Human highlight grouping, with explicit loss previews and no acoustic claims."""
import copy
from dataclasses import asdict
from .model import Unit,Highlight
from .japanese import hiragana,morae
from .analysis import kana_only
from .provenance import inferred,derived

METHODS={'manual_mora_split','manual_mora_merge','manual_mora_reset'}


def validate_history(records):
    if not isinstance(records,list) or len(records)>100:raise ValueError('音节拆合记录无效。')
    keys={'version','operation','word','text','kana','range','before','after','removed_manual_boundaries','closed_gap_ms','estimated_new_boundaries'}
    for entry in records:
        if not isinstance(entry,dict) or set(entry)!=keys or type(entry['version']) is not int or entry['version']!=1 or entry['operation'] not in {'split','merge','reset'}:raise ValueError('音节拆合记录格式无效。')
        if type(entry['word']) is not int or not 0<=entry['word']<20000 or any(not isinstance(entry[k],str) or len(entry[k])>20000 for k in ('text','kana')):raise ValueError('音节拆合词组资料无效。')
        bounds=entry['range']
        if not isinstance(bounds,list) or len(bounds)!=2 or any(type(v) is not int for v in bounds) or not 0<=bounds[0]<bounds[1]:raise ValueError('音节拆合范围无效。')
        for key in ('removed_manual_boundaries','closed_gap_ms','estimated_new_boundaries'):
            if type(entry[key]) is not int or entry[key]<0:raise ValueError('音节拆合变更数量无效。')
        for key in ('before','after'):
            rows=entry[key]
            if not isinstance(rows,list) or not 1<=len(rows)<=512 or any(not isinstance(h,dict) or set(h)-{'kana','start','end','source','timing_origin','fixed_edges'} for h in rows):raise ValueError('音节拆合边界资料无效。')
            try:
                parts=[Highlight(**h) for h in rows];Unit('',bounds[0],bounds[1],''.join(h.kana for h in parts),highlights=parts).validate()
            except (TypeError,KeyError,ValueError) as error:raise ValueError('音节拆合历史时间无效。') from error


def _human(part):
    origin=inferred(part)
    if origin['kind']=='manual' or 'manual_boundary' in origin.get('operations',[]):return True
    return part.source=='manual' and (origin['method']=='legacy' or origin['kind'] not in {'estimated','character','word','reference','acoustic'})


def _canonical(unit):
    raw=unit.kana;normal=hiragana(raw)
    if not raw or kana_only(raw)!=normal or len(normal)!=len(raw):raise ValueError('先把词组假名改成完整的全角日语读音，再拆合音节；原文不改。')
    spans=[];cursor=0
    for part in morae(normal):spans.append((cursor,cursor+len(part)));cursor+=len(part)
    if cursor!=len(raw):raise ValueError('当前假名无法安全对应字符位置，请先检查词组假名。')
    return spans


def _transform(original,word,first,last,targets,operation,allow_manual=False,allow_gaps=False,chosen_edge=None,fix_chosen=True):
    original.validate()
    if type(word) is not int or not 0<=word<len(original.units):raise ValueError('先选择一个词组。')
    old=original.units[word]
    if original.locked or old.locked:raise ValueError('所选歌词或词组已锁定，请先解除锁定。')
    if any(type(v) is not bool for v in (allow_manual,allow_gaps)):raise ValueError('音节拆合授权选项无效。')
    if type(first) is not int or type(last) is not int or not 0<=first<=last<len(old.highlights) or last-first>=512:raise ValueError('请选择同一词组中相邻的音节，一次最多 512 段。')
    canonical=set(_canonical(old));spans=[];cursor=0
    for h in old.highlights:spans.append((cursor,cursor+len(h.kana),h));cursor+=len(h.kana)
    selected=spans[first:last+1];begin,finish=selected[0][0],selected[-1][1]
    if not targets or targets[0][0]!=begin or targets[-1][1]!=finish or any(a>=b for a,b in targets) or any(b!=c for (_,b),(c,_) in zip(targets,targets[1:])):raise ValueError('新的音节划分未完整保留原假名。')
    boundaries={a for a,b in targets}|{b for a,b in targets};manual_removed=0;closed_gap=0
    for (a,b,left),(c,d,right) in zip(selected,selected[1:]):
        if b in boundaries:continue
        if 'end' in left.fixed_edges or 'start' in right.fixed_edges:raise ValueError('合并会移除内部人工固定点，请先明确解除这个固定点；原轴保持。')
        manual_removed+=int(_human(left) or _human(right));closed_gap+=right.start-left.end
    if manual_removed and not allow_manual:raise ValueError(f'会移除 {manual_removed} 个内部人工边界；先比较并明确允许，外缘和其他音节保持。')
    if closed_gap and not allow_gaps:raise ValueError(f'会把 {closed_gap} ms 间隔并入高亮；先试听并明确允许，不能自动抹掉真实停顿。')
    def edge(position,end=False):
        for a,b,h in (reversed(selected) if end else selected):
            if a<position<=b if end else a<=position<b:
                if position==a:return h.start
                if position==b:return h.end
                local=position-a;parts=morae(h.kana);cuts=[];offset=0
                for part in parts:offset+=len(part);cuts.append(offset)
                fraction=(cuts.index(local)+1)/len(parts) if local in cuts else local/(b-a)
                return round((h.start+(h.end-h.start)*fraction)/10)*10
        raise ValueError('无法对应原音节时间。')
    new=[]
    old_boundaries={v for a,b,h in selected for v in (a,b)}
    new_boundaries=boundaries-old_boundaries
    if chosen_edge is not None and fix_chosen:new_boundaries.discard(chosen_edge[0])
    estimated=len(new_boundaries)
    for a,b in targets:
        exact=next((h for x,y,h in selected if (a,b)==(x,y)),None)
        if exact is not None:new.append(copy.deepcopy(exact));continue
        start,end=edge(a),edge(b,True)
        if chosen_edge is not None:
            position,time=chosen_edge
            if a==position:start=time
            if b==position:end=time
        if end-start<10:raise ValueError('拆分后每段至少保留 10 毫秒，请改位置或扩大原音节范围。')
        parents=[h for x,y,h in selected if x<b and y>a];fixed=[]
        for label,position in [('start',a),('end',b)]:
            anchors=[h for x,y,h in selected if (x if label=='start' else y)==position]
            if any(label in h.fixed_edges or _human(h) for h in anchors) or fix_chosen and chosen_edge is not None and chosen_edge[0]==position:fixed.append(label)
        reading=old.kana[a:b];source='estimated' if (a,b) in canonical else 'manual'
        origin=derived('estimated',start,end,parents,'manual_mora_'+operation,reading);origin['operations']=['regroup']
        new.append(Highlight(reading,start,end,source,origin,fixed))
    value=copy.deepcopy(original);target=value.units[word];target.highlights[first:last+1]=new
    if target.highlights==old.highlights:return {'line':value,'changed':False,'word':word,'selected':[first,last],'removed_manual_boundaries':0,'closed_gap_ms':0,'estimated_new_boundaries':0}
    value.reviewed=False
    history=value.reading_review.get('mora_edits',[])
    entry={'version':1,'operation':operation,'word':word,'text':old.text,'kana':old.kana,'range':[selected[0][2].start,selected[-1][2].end],'before':[asdict(h) for _,_,h in selected],'after':[asdict(h) for h in new],'removed_manual_boundaries':manual_removed,'closed_gap_ms':closed_gap,'estimated_new_boundaries':estimated}
    value.reading_review['mora_edits']=[*copy.deepcopy(history[-99:]),entry];value.validate()
    return {'line':value,'changed':True,'word':word,'selected':[first,first+len(new)-1],'removed_manual_boundaries':manual_removed,'closed_gap_ms':closed_gap,'estimated_new_boundaries':estimated}


def split(original,word,part,cut,at=None,allow_character=False):
    original.validate()
    if type(word) is not int or not 0<=word<len(original.units) or type(part) is not int or not 0<=part<len(original.units[word].highlights):raise ValueError('先选择一个演唱音节。')
    unit=original.units[word];item=unit.highlights[part];prefix=sum(len(h.kana) for h in unit.highlights[:part]);canonical=_canonical(unit)
    if type(cut) is not int or not 0<cut<len(item.kana) or type(allow_character) is not bool:raise ValueError('选择本段假名内部的拆分位置；单个假名可以改时长，或与邻音合并。')
    if prefix+cut not in {b for a,b in canonical} and not allow_character:raise ValueError('这里在拗音内部；需要明确选择高级按字符拆分，不改变整词实际读音。')
    if at is not None and type(at) is not int:raise ValueError('拆分时间须为毫秒整数。')
    if at is None:
        fraction=len(morae(item.kana[:cut]))/len(morae(item.kana)) if prefix+cut in {b for a,b in canonical} else cut/len(item.kana)
        time=round((item.start+(item.end-item.start)*fraction)/10)*10
    else:time=round(at/10)*10
    if not item.start+10<=time<=item.end-10:raise ValueError('拆分位置须在原音节内部，两侧各至少 10 毫秒。')
    # A supplied listening position is a human anchor. The automatic preview
    # midpoint remains an estimate; canonical children can be aligned later.
    return _transform(original,word,part,part,[(prefix,prefix+cut),(prefix+cut,prefix+len(item.kana))],'split',chosen_edge=(prefix+cut,time),fix_chosen=at is not None)


def merge(original,word,first,last,allow_manual=False,allow_gaps=False):
    original.validate()
    if type(word) is not int or not 0<=word<len(original.units) or type(first) is not int or type(last) is not int or not 0<=first<last<len(original.units[word].highlights):raise ValueError('请选择同一词组中至少两个相邻音节。')
    parts=original.units[word].highlights;begin=sum(len(h.kana) for h in parts[:first]);end=begin+sum(len(h.kana) for h in parts[first:last+1])
    return _transform(original,word,first,last,[(begin,end)],'merge',allow_manual,allow_gaps)


def reset(original,word,allow_manual=False,allow_gaps=False):
    original.validate()
    if type(word) is not int or not 0<=word<len(original.units):raise ValueError('先选择一个词组。')
    unit=original.units[word]
    if not unit.highlights:raise ValueError('本词还没有音节，请先补全。')
    return _transform(original,word,0,len(unit.highlights)-1,_canonical(unit),'reset',allow_manual,allow_gaps)
