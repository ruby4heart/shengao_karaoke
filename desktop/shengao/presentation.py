"""Display windows are derived from singing times; they never edit the axis."""
from dataclasses import dataclass
from bisect import bisect_left,bisect_right

@dataclass
class DisplayWindow:
    start:int
    end:int
    slot:int=0


class WindowIndex:
    """Overlap queries preserve the exact strict boundary comparisons."""
    def __init__(self,windows):
        self.order=sorted(range(len(windows)),key=lambda i:windows[i].start)
        self.starts=[windows[i].start for i in self.order];self.size=1
        while self.size<len(self.order):self.size*=2
        self.ends=[-1]*(2*self.size)
        for n,i in enumerate(self.order):self.ends[self.size+n]=windows[i].end
        for n in range(self.size-1,0,-1):self.ends[n]=max(self.ends[n*2],self.ends[n*2+1])

    def overlapping(self,window):
        limit=bisect_left(self.starts,window.end);stack=[(1,0,self.size)];result=[]
        while stack:
            node,a,b=stack.pop()
            if a>=limit or self.ends[node]<=window.start:continue
            if b-a==1:result.append(self.order[a]);continue
            middle=(a+b)//2;stack.append((node*2+1,middle,b));stack.append((node*2,a,middle))
        return sorted(result)


def display_windows(project):
    lines=project.lines;s=project.style;alternating=s.display_mode=='alternating';starts=[]
    for i,line in enumerate(lines):
        if line.display_start is not None:start=line.display_start
        elif not alternating:start=line.start
        elif not i:start=max(0,line.start-s.preview_lead_ms)
        else:
            previous=lines[i-1];midpoint=previous.start+round((previous.end-previous.start)*s.preview_percent/100)
            start=min(line.start,max(0,midpoint,line.start-s.preview_lead_ms))
        starts.append(start)
    windows=[]
    for i,line in enumerate(lines):
        if line.display_end is not None:end=line.display_end
        elif not alternating:end=line.end
        elif i+1<len(lines):end=max(line.end,min(starts[i+1]+s.previous_hold_ms,line.end+s.previous_hold_ms))
        else:end=line.end+s.previous_hold_ms
        if project.duration:end=max(line.end,min(end,project.duration))
        windows.append(DisplayWindow(starts[i],end))
    if not alternating:return windows
    # Each lane contains disjoint intervals sorted by start. The matching end
    # array is also sorted, so even manual out-of-order appearances can query
    # the entire overlap range without scanning all preceding lyric lines.
    lanes={}
    for index,w in enumerate(windows):
        preferred=index%2
        for slot in [preferred]+[n for n in range(len(lanes)+1) if n!=preferred]:
            starts_in_lane,ends_in_lane,owners=lanes.setdefault(slot,([],[],[]))
            lo=bisect_right(ends_in_lane,w.start);hi=bisect_left(starts_in_lane,w.end)
            overlaps=list(range(lo,hi))
            if overlaps:
                # Only shorten an automatic hold after its real singing ends.
                # Explicit disappearance times and unfinished singing survive.
                if not all(lines[owners[j]].display_end is None and lines[owners[j]].end<=w.start for j in overlaps):continue
                for j in overlaps:windows[owners[j]].end=w.start;ends_in_lane[j]=w.start
            w.slot=slot;position=bisect_right(starts_in_lane,w.start)
            starts_in_lane.insert(position,w.start);ends_in_lane.insert(position,w.end);owners.insert(position,index)
            break
    return windows
