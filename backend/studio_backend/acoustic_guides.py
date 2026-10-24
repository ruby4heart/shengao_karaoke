"""Explicit human edge constraints, independent of the acoustic model's guess."""
import copy
from bisect import bisect_left
from fractions import Fraction

from .model import LyricLine


def mora_rows(line):
    from .acoustic import pronunciations
    line.validate()
    rows=[]
    for i,unit in enumerate(line.units):
        parts,_=pronunciations(unit)
        if not unit.highlights or [h.kana for h in unit.highlights]!=parts:
            raise ValueError('请先在本句编辑区补全音节，核对假名后再固定位置。')
        for j,h in enumerate(unit.highlights):
            rows.append((i,j,h))
    if not rows:raise ValueError('请先按原歌词分词、填写假名并补全音节。')
    return rows


def prepare(line,points,scope='between'):
    """Interpolate only a draft; no original time is committed on failure."""
    from .acoustic import plan
    if scope not in {'between','line'}:raise ValueError('请选择固定位置之间或本句未固定部分。')
    if not isinstance(points,list) or not 1<=len(points)<=256:raise ValueError('请设置 1 至 256 个人工固定位置。')
    rows=mora_rows(line);index={(i,j):n for n,(i,j,_) in enumerate(rows)}
    normalized=[];seen=set();hard={-1:line.start,len(rows)*2:line.end}
    for n,(i,j,h) in enumerate(rows):
        unit=line.units[i]
        for edge,rank in [('start',2*n),('end',2*n+1)]:
            if unit.locked or h.source=='manual' or edge in h.fixed_edges:
                hard[rank]=getattr(h,edge)
        if unit.source=='manual':
            if j==0:hard[2*n]=unit.start
            if j==len(unit.highlights)-1:hard[2*n+1]=unit.end
    for point in points:
        if not isinstance(point,dict) or set(point)!={'unit','highlight','edge','time'}:
            raise ValueError('固定位置资料无效。')
        i,j,edge,time=(point[k] for k in ('unit','highlight','edge','time'))
        if type(i) is not int or type(j) is not int or (i,j) not in index or edge not in ('start','end') or type(time) is not int or not line.start<=time<=line.end:
            raise ValueError('固定位置必须指向本句音节，且位于整句演唱范围内。')
        key=(i,j,edge)
        if key in seen:raise ValueError('同一边界只能固定一次。')
        seen.add(key);rank=2*index[i,j]+(edge=='end')
        if rank in hard and hard[rank]!=time:
            raise ValueError('已有人工音节、固定点或锁定范围受保护；请先在主编辑区调整或解除固定。')
        hard[rank]=time;normalized.append(copy.deepcopy(point))
    normalized.sort(key=lambda p:2*index[p['unit'],p['highlight']]+(p['edge']=='end'))
    ranks=[2*index[p['unit'],p['highlight']]+(p['edge']=='end') for p in normalized]
    if scope=='between' and len(ranks)<2:raise ValueError('只重算固定点之间需要至少两个位置，请再固定一个起点或终点。')
    low,high=(ranks[0],ranks[-1]) if scope=='between' else (0,len(rows)*2-1)
    ordered=sorted(hard)
    if any(hard[a]>hard[b] for a,b in zip(ordered,ordered[1:])):
        raise ValueError('固定位置顺序冲突，原轴保留；请按歌词顺序检查时间。')
    working=copy.deepcopy(line);leaves=mora_rows(working)
    old_times={-1:line.start,len(rows)*2:line.end}
    old_times.update({2*n:getattr(h,'start') for n,(_,_,h) in enumerate(rows)})
    old_times.update({2*n+1:getattr(h,'end') for n,(_,_,h) in enumerate(rows)})
    for n,(_,_,h) in enumerate(leaves):
        for edge,rank in [('start',2*n),('end',2*n+1)]:
            if rank in hard:value=hard[rank]
            elif low<=rank<=high:
                stop=bisect_left(ordered,rank);a,b=ordered[stop-1:stop+1]
                proportion=Fraction(old_times[rank]-old_times[a],old_times[b]-old_times[a]) if old_times[b]>old_times[a] else Fraction(rank-a,b-a)
                value=hard[a]+round(proportion*(hard[b]-hard[a]))
            else:continue
            setattr(h,edge,value)
    for p in normalized:
        h=working.units[p['unit']].highlights[p['highlight']]
        h.fixed_edges=sorted(set(h.fixed_edges)|{p['edge']})
        before=line.units[p['unit']].highlights[p['highlight']]
        from .provenance import record
        record(before,h,'manual_boundary')
    for unit in working.units:
        if unit.highlights and not unit.locked and unit.source!='manual':
            unit.start=unit.highlights[0].start;unit.end=unit.highlights[-1].end
    try:working.validate()
    except ValueError as error:
        raise ValueError('固定点与范围外保留的音节冲突；请扩大重算范围，或先手工调整邻音。原轴没有改动。') from error
    prepared=plan(working)
    allowed={(i,j) for n,(i,j,_) in enumerate(rows) if low<=2*n and 2*n+1<=high}
    jobs=[]
    for job in prepared['jobs']:
        keys={(m['unit'],m['highlight']) for m in job['mora']}
        if keys&allowed:
            if not keys<=allowed:raise ValueError('固定点未能完整隔开重算范围，请检查位置。')
            jobs.append(job)
    if not jobs:raise ValueError('固定位置之间没有未固定的完整音节，请扩大范围。')
    prepared.update(original=line.to_dict(),jobs=jobs,guide_points=normalized,guide_scope=scope,
                    guide_mora=[list(v) for v in sorted(allowed)])
    return prepared


def validate_result(prepared,candidate):
    """An adoption must match the exact request, including untouched outside mora."""
    baseline=LyricLine.from_dict(prepared['baseline'])
    if len(candidate.units)!=len(baseline.units):raise ValueError('固定位置任务不能更改分词。')
    computed={(m['unit'],m['highlight']) for job in prepared['jobs'] for m in job['mora']}
    for i,(before,after) in enumerate(zip(baseline.units,candidate.units)):
        if len(before.highlights)!=len(after.highlights):raise ValueError('固定位置任务不能更改音节数量。')
        for j,(a,b) in enumerate(zip(before.highlights,after.highlights)):
            if a.fixed_edges!=b.fixed_edges or a.kana!=b.kana:
                raise ValueError('固定位置或音节读音已变化，拒绝采用。')
            if (i,j) not in computed and a!=b:raise ValueError('重算范围之外的音节已变化，拒绝采用。')
            for edge in a.fixed_edges:
                if getattr(a,edge)!=getattr(b,edge):raise ValueError('人工固定点未保留，拒绝采用。')
    for p in prepared['guide_points']:
        if getattr(candidate.units[p['unit']].highlights[p['highlight']],p['edge'])!=p['time']:
            raise ValueError('人工给定位置未保留，拒绝采用。')
