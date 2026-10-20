"""Display windows are derived from singing times; they never edit the axis."""
from dataclasses import dataclass

@dataclass
class DisplayWindow:
    start:int
    end:int
    slot:int=0


def _automatic_windows(project):
    lines=project.lines;s=project.style
    if s.display_mode!='alternating':return [DisplayWindow(line.start,line.end) for line in lines]
    windows=[];last_slots={}
    for i,line in enumerate(lines):
        if i:
            previous=lines[i-1]
            midpoint=previous.start+round((previous.end-previous.start)*s.preview_percent/100)
            start=min(line.start,max(0,midpoint,line.start-s.preview_lead_ms))
        else:start=max(0,line.start-s.preview_lead_ms)
        slot=i%2
        # Prefer the alternating row. Short phrases can shorten the visual hold
        # to make room, but an unfinished sung phrase is never erased.
        occupied=last_slots.get(slot)
        if occupied and occupied[1].end>start:
            owner_index,occupied=occupied;owner=lines[owner_index]
            start=min(line.start,max(start,min(occupied.end,line.start)))
            if owner.end<=start:occupied.end=start
            else:
                used={w.slot for w in windows if w.end>start}
                slot=next(n for n in range(len(used)+1) if n not in used)
        if windows:windows[-1].end=max(lines[i-1].end,min(start+s.previous_hold_ms,lines[i-1].end+s.previous_hold_ms))
        end=line.end+s.previous_hold_ms
        windows.append(DisplayWindow(start,max(start+10,end),slot))
        last_slots[slot]=(i,windows[-1])
    # Bounds are clamped only to real media; never invent extra video duration.
    if project.duration:
        for line,w in zip(lines,windows):w.end=max(line.end,min(w.end,project.duration))
    return windows


def display_windows(project):
    windows=_automatic_windows(project)
    if not any(line.display_start is not None or line.display_end is not None for line in project.lines):return windows
    for line,w in zip(project.lines,windows):
        if line.display_start is not None:w.start=line.display_start
        if line.display_end is not None:w.end=line.display_end
        if project.duration:w.end=max(line.end,min(w.end,project.duration))
    if project.style.display_mode=='alternating':
        for index,w in enumerate(windows):
            occupied={old.slot for old in windows[:index] if old.start<w.end and w.start<old.end}
            preferred=index%2
            w.slot=preferred if preferred not in occupied else next(n for n in range(len(occupied)+1) if n not in occupied)
    return windows
