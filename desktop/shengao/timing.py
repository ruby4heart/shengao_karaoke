"""Editor-independent boundary and pause operations in milliseconds.

Boundary co-movement follows the existing Shengao studio_calibration design.
Original text and manual readings never change as a consequence of timing edits.
"""
import copy
from dataclasses import asdict
from studio_backend.model import Highlight
from studio_backend.japanese import morae, romaji, add_mora
from studio_backend.provenance import remember,record,record_tree,group_basis,derived

def manual(line):
    if line.display_start is not None:line.display_start=min(line.display_start,line.start)
    if line.display_end is not None:line.display_end=max(line.display_end,line.end)
    line.reviewed=False
    line.match={}
    if line.reading_review: line.reading_review['stale']=True

def retime_unit(unit,start,end):
    if end-start<10: raise ValueError('每段至少保留 10 毫秒')
    old_start,old_end=unit.start,unit.end
    if (start,end)==(old_start,old_end):return
    before=copy.deepcopy(unit)
    shift=end-start==old_end-old_start
    fits=all(start<=h.end and h.start<=end and (i==0 or h.start>=start) and (i==len(unit.highlights)-1 or h.end<=end)
             for i,h in enumerate(unit.highlights))
    for i,h in enumerate(unit.highlights):
        if shift: h.start+=start-old_start;h.end+=start-old_start
        elif fits:
            h.start=start if i==0 and h.start==old_start else max(start,h.start)
            h.end=end if i==len(unit.highlights)-1 and h.end==old_end else min(end,h.end)
        else:
            def moved(t):return max(start,min(end,round((start+(t-old_start)*(end-start)/max(1,old_end-old_start))/10)*10))
            h.start,h.end=moved(h.start),moved(h.end)
        h.source='manual' if fits or shift else 'estimated'
    unit.start,unit.end,unit.source=start,end,'manual'
    record(before,unit,'shift' if shift else 'manual_boundary')
    for old,h in zip(before.highlights,unit.highlights):record(old,h,'shift' if shift else 'manual_boundary' if fits else 'stretch')

def set_time(original,target,start,end,part=None):
    line=copy.deepcopy(original)
    if line.locked: raise ValueError('此行已锁定，请先解除锁定')
    start,end=round(start/10)*10,round(end/10)*10
    if start<0 or end<=start:raise ValueError('开始时间须非负，结束时间须晚于开始')
    if target<0:
        if line.units:
            first,last=line.units[0],line.units[-1]
            if first is last:
                retime_unit(first,start if first.start==line.start or start>first.start else first.start,
                            end if last.end==line.end or end<last.end else last.end)
            else:
                if first.start==line.start or start>first.start:retime_unit(first,start,first.end)
                if last.end==line.end or end<last.end:retime_unit(last,last.start,end)
        line.start,line.end=start,end
    elif part is None:
        unit=line.units[target];old_start,old_end=unit.start,unit.end
        if target and line.units[target-1].end==old_start:retime_unit(line.units[target-1],line.units[target-1].start,start)
        if target+1<len(line.units) and line.units[target+1].start==old_end:retime_unit(line.units[target+1],end,line.units[target+1].end)
        if target==0 and (old_start==line.start or start<line.start):line.start=start
        if target==len(line.units)-1 and (old_end==line.end or end>line.end):line.end=end
        retime_unit(unit,start,end)
    else:
        unit=line.units[target];h=unit.highlights[part];a,b=h.start,h.end
        anchors=[(u.start==u.highlights[0].start,u.end==u.highlights[-1].end) if u.highlights else None for u in line.units]
        bounds=[(u.start,u.end) for u in line.units]
        line_start,line_end=line.start,line.end;first_start,last_end=line.units[0].start,line.units[-1].end
        parts=leaves(line);position=next(i for i,(word,index,_) in enumerate(parts) if word==target and index==part)
        if position and parts[position-1][2].end==a:parts[position-1][2].end=start;parts[position-1][2].source='manual'
        if position+1<len(parts) and parts[position+1][2].start==b:parts[position+1][2].start=end;parts[position+1][2].source='manual'
        h.start,h.end,h.source=start,end,'manual';unit.source='manual'
        for i,u in enumerate(line.units):
            if not u.highlights:continue
            u.start=u.highlights[0].start if anchors[i][0] else min(u.start,u.highlights[0].start)
            u.end=u.highlights[-1].end if anchors[i][1] else max(u.end,u.highlights[-1].end)
            if (u.start,u.end)!=bounds[i]:u.source='manual'
        if first_start==line_start or line.units[0].start<line_start:line.start=line.units[0].start
        if last_end==line_end or line.units[-1].end>line_end:line.end=line.units[-1].end
    for old,new in zip(original.units,line.units):
        if old.locked and asdict(old)!=asdict(new):raise ValueError('这次修改会改变已锁定词组“'+old.text+'”，请先解除锁定')
    record(original,line,'manual_boundary')
    if part is not None and target>=0:
        for old,new in zip(original.units,line.units):
            record(old,new,'manual_boundary')
            for a,b in zip(old.highlights,new.highlights):record(a,b,'manual_boundary')
    manual(line);line.validate();return line

def leaves(line):
    return [(i,j,h) for i,u in enumerate(line.units) for j,h in (enumerate(u.highlights) if u.highlights else [(None,u)])]

def pauses(line,edges=False):
    values=leaves(line);result=[]
    if edges and values and values[0][2].start>line.start:result.append((line.start,values[0][2].start,None,0))
    for n,(a,b) in enumerate(zip(values,values[1:])):
        if a[2].end<b[2].start:result.append((a[2].end,b[2].start,n,n+1))
    if edges and values and values[-1][2].end<line.end:result.append((values[-1][2].end,line.end,len(values)-1,None))
    return result

def merge_pauses(original,indices,policy,edges=False):
    if policy=='keep':return copy.deepcopy(original)
    if policy not in ('previous','next'):raise ValueError('请选择停顿处理方式')
    line=copy.deepcopy(original)
    if line.locked or any(u.locked for u in line.units):raise ValueError('已锁定歌词不能修改停顿')
    gaps=pauses(line,edges);parts=leaves(line)
    for index in sorted(set(indices)):
        start,end,left,right=gaps[index]
        chosen=left if policy=='previous' else right
        if chosen is None:chosen=right if left is None else left
        i,j,item=parts[chosen]
        if chosen==left:item.end=end
        else:item.start=start
        item.source='manual';word=line.units[i]
        if j is not None:
            word.start=min(word.start,item.start);word.end=max(word.end,item.end);word.source='manual'
        if left is not None and right is not None and parts[left][0]!=parts[right][0]:
            if policy=='previous':line.units[parts[right][0]].start=max(line.units[parts[right][0]].start,end)
            else:line.units[parts[left][0]].end=min(line.units[parts[left][0]].end,start)
    if indices:manual(line)
    record_tree(original,line,'manual_boundary')
    line.validate();return line

def edit_reading(original,index,kana,latin='',defaults=None):
    line=copy.deepcopy(original);unit=line.units[index]
    if line.locked or unit.locked:raise ValueError('已锁定词组不能修改')
    if any('\u3400'<=c<='\u9fff' or '\uf900'<=c<='\ufaff' for c in kana):raise ValueError('假名栏请填写实际日语读音，例如“きょう”；汉字保留在原文栏')
    changed=unit.kana!=kana
    if changed:remember(unit)
    before=copy.deepcopy(original.units[index]);unit.kana=kana
    if changed:unit.reading_source='manual';unit.highlights=[];add_mora(unit);manual(line)
    from studio_backend.romanization import after_reading_change,set_manual,state,automatic,DEFAULT
    if latin:
        line=set_manual(line,index,latin,defaults);unit=line.units[index]
    elif changed:after_reading_change(before,unit,defaults)
    else:
        rules={key:state(before,defaults)[key] for key in DEFAULT};unit.romaji=automatic(unit,rules);unit.reading_options['romaji']={'mode':'auto',**rules}
    line.kana=''.join(u.kana for u in line.units);line.romaji=' '.join(u.romaji for u in line.units if u.romaji)
    line.validate();return line

def merge_words(original,first,last):
    line=copy.deepcopy(original)
    if line.locked or any(u.locked for u in line.units[first:last+1]):raise ValueError('所选词组已锁定')
    if not 0<=first<last<len(line.units):raise ValueError('请选中至少两个相邻词组')
    from studio_backend.model import Unit
    words=line.units[first:last+1]
    if any(u.reading_options.get('ruby',{}).get('mode','auto')!='auto' for u in words):raise ValueError('合并会改变手工注音对应，请先将相关词切回自动，旧对应保持。')
    merged=Unit(''.join(u.text for u in words),words[0].start,words[-1].end,''.join(u.kana for u in words),
                ' '.join(u.romaji for u in words if u.romaji),'manual',False,[], 'manual')
    merged.timing_origin=group_basis(words,merged.start,merged.end,'regroup')
    for u in words:
        if u.highlights:merged.highlights.extend(copy.deepcopy(u.highlights))
        elif u.kana:merged.highlights.append(Highlight(u.kana,u.start,u.end,u.source,timing_origin=derived('estimated',u.start,u.end,[u],'word_reading_envelope',u.kana)))
    line.units[first:last+1]=[merged];manual(line);line.validate();return line

def split_word(original,index,position):
    line=copy.deepcopy(original);word=line.units[index]
    if word.reading_options.get('ruby',{}).get('mode','auto')!='auto':raise ValueError('拆分会改变手工注音对应，请先将该词切回自动，旧对应保持。')
    if line.locked or word.locked:raise ValueError('所选词组已锁定')
    if not 0<position<len(word.text):raise ValueError('请选择词组内部的文字边界')
    from studio_backend.japanese import Group,retime_groups,word_groups
    offset=sum(len(u.text) for u in line.units[:index]);groups=[];cursor=0
    for i,u in enumerate(line.units):
        if i==index:
            for text in (u.text[:position],u.text[position:]):
                parts=word_groups(text);groups.append(Group(text,cursor,cursor+len(text),''.join(g.kana for g in parts),' '.join(g.romaji for g in parts)))
                cursor+=len(text)
        else:groups.append(Group(u.text,cursor,cursor+len(u.text),u.kana,u.romaji));cursor+=len(u.text)
    line.units=retime_groups(line,groups);manual(line);line.validate();return line

def shift_following(original,boundary,delta):
    line=copy.deepcopy(original)
    if line.locked or any(u.locked for u in line.units):raise ValueError('已锁定歌词不能批量移动边界')
    times=sorted({t for i,j,h in leaves(line) for t in (h.start,h.end)}|{line.start,line.end})
    movable=[t for t in times if boundary<=t<line.end and t>line.start]
    if not movable:return line
    previous=max((t for t in times if t<boundary),default=line.start)
    delta=max(previous+10-movable[0],min(round(delta/10)*10,line.end-10-movable[-1]))
    def moved(time):return time+delta if time in movable else time
    for u in line.units:
        u.start,u.end=moved(u.start),moved(u.end);u.source='manual'
        for h in u.highlights:h.start,h.end,h.source=moved(h.start),moved(h.end),'manual'
    record_tree(original,line,'shift')
    manual(line);line.validate();return line
