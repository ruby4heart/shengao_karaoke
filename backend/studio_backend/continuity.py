"""Continuous automatic karaoke edges without moving following vocal onsets."""
import copy
from .provenance import change,remember

DEFAULT_GAP_MS=500


def protected(line):
    return line.locked or line.reviewed or any(u.locked for u in line.units) or line.match.get('status') in {'protected','unmatched','manual'}


def automatic(unit,edge=None):
    return not unit.locked and unit.source not in {'manual','acoustic'} and (edge is None or not edge.fixed_edges and edge.source not in {'manual','acoustic'})


def continuous_lines(lines,maximum=DEFAULT_GAP_MS,join_lines=True):
    """Return new lines and a reviewable list of closed gaps; input is untouched.

    Thresholds are timing heuristics, not acoustic silence detection. Actual
    long rests and manually calibrated edges are kept. No starts are moved.
    """
    if type(maximum) is not int or not 0<=maximum<=2000:raise ValueError('收拢空白阈值应为 0 到 2000 毫秒')
    values=copy.deepcopy(lines);changes=[]
    def eligible(gap):return 0<gap<=maximum
    def record(line,a,b,kind,text):changes.append({'id':line.id,'start':a,'end':b,'kind':kind,'text':text})
    for line in values:
        if protected(line):continue
        for unit in line.units:
            for left,right in zip(unit.highlights,unit.highlights[1:]):
                if eligible(right.start-left.end) and automatic(unit,left) and automatic(unit,right):
                    record(line,left.end,right.start,'mora',left.kana+' → '+right.kana)
                    change(left,left.start,right.start,'automatic_gap');remember(unit);left.source='estimated';unit.source='estimated'
        for left,right in zip(line.units,line.units[1:]):
            tail=left.highlights[-1] if left.highlights else None
            head=right.highlights[0] if right.highlights else None
            if eligible(right.start-left.end) and automatic(left,tail) and automatic(right,head):
                # An explicit trailing gap inside the left word is independent;
                # avoid consuming an unreviewed long pause through its envelope.
                if tail and tail.end!=left.end:continue
                record(line,left.end,right.start,'word',left.text+' → '+right.text)
                change(left,left.start,right.start,'automatic_gap');left.source='estimated'
                if tail:change(tail,tail.start,left.end,'automatic_gap');tail.source='estimated'
        line.validate()
    if join_lines:
        for left,right in zip(values,values[1:]):
            if protected(left) or protected(right) or not left.units or not right.units:continue
            last,first=left.units[-1],right.units[0]
            tail=last.highlights[-1] if last.highlights else None
            head=first.highlights[0] if first.highlights else None
            if not eligible(right.start-left.end) or last.end!=left.end or first.start!=right.start:continue
            if not automatic(last,tail) or not automatic(first,head) or (tail and tail.end!=last.end):continue
            record(left,left.end,right.start,'line',last.text+' → '+first.text)
            change(left,left.start,right.start,'automatic_gap');change(last,last.start,right.start,'automatic_gap');last.source='estimated'
            if tail:change(tail,tail.start,left.end,'automatic_gap');tail.source='estimated'
            left.validate()
    changed_ids={c['id'] for c in changes}
    for line in values:
        if line.id in changed_ids:
            line.reviewed=False
            if line.reading_review:line.reading_review['stale']=True
    return values,changes


def continuous_result(result,maximum=DEFAULT_GAP_MS,join_lines=True):
    from .model import LyricLine
    result=copy.deepcopy(result)
    values,changes=continuous_lines([LyricLine.from_dict(v) for v in result.get('suggestions',[])],maximum,join_lines)
    for line in values:
        for candidate in ([] if protected(line) else line.match.get('candidates',[])):
            alternate=LyricLine.from_dict({**line.to_dict(),'start':candidate['start'],'end':candidate['end'],'units':candidate['units'],'match':{}})
            aligned,adjustments=continuous_lines([alternate],maximum,False)
            candidate['units']=aligned[0].to_dict()['units']
            candidate['closed_gaps']=len(adjustments)
        count=sum(c['id']==line.id for c in changes)
        if count and line.match:line.match['reason']=line.match.get('reason','')+f'；收拢 {count} 处自动轴短空白，起音保持不变，需试听确认'
    result['suggestions']=[v.to_dict() for v in values]
    result['closed_gaps']=len(changes);result['timing_changes']=changes
    if changes:result['message']=(result.get('message','')+' 已收拢 '+str(len(changes))+' 处自动轴短空白；后一音节起音保持不变，请试听后采用。').strip()
    result['timing_policy']={'mode':'continuous' if maximum else 'preserve','maximum_ms':maximum,'join_lines':join_lines,'onsets_preserved':True}
    return result
