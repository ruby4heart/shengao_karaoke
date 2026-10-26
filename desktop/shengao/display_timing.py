"""Guarded display-window edits; singing, readings and confirmations stay put."""
import copy
from .project import file_stamp


def edit_context(project,row):
    if type(row) is not int or not 0<=row<len(project.lines):raise ValueError('请先选择歌词')
    s=project.style;line=project.lines[row]
    return {'project':project.uid,'media':project.media,'stamp':file_stamp(project.media),'role':project.media_role,
            'duration':project.duration,'source_ass_active':project.source_ass_active,
            'automatic':(s.display_mode,s.preview_percent,s.preview_lead_ms,s.previous_hold_ms),
            'timing':[(v.id,v.start,v.end,v.display_start,v.display_end) for v in project.lines],
            'line':copy.deepcopy(line.to_dict()),'checks':copy.deepcopy(project.checks.get(line.id,{}))}


def bounded_window(line,window,duration,part,value):
    """Clamp an edge or a translation without clipping any sung content."""
    if type(value) is not int:raise ValueError('显示时间须为整数毫秒')
    if part not in {'start','end','move'}:raise ValueError('显示时间操作无效')
    if duration and line.end>duration:raise ValueError('演唱已超出素材结尾，请先修正演唱范围')
    a,b=window.start,window.end
    if part=='start':a=max(0,min(value,line.start))
    elif part=='end':b=max(line.end,min(value,duration) if duration else value)
    else:
        low=max(-a,line.end-b);high=line.start-a
        if duration:high=min(high,duration-b)
        delta=max(low,min(value,high));a+=delta;b+=delta
    return a,b


def change_display(project,row,start,end,*,part='move',context=None):
    if context is not None and edit_context(project,row)!=context:raise ValueError('歌词、确认、素材或接唱设置已变化，本次留屏调整未采用，请重新拖动')
    if type(row) is not int or not 0<=row<len(project.lines):raise ValueError('请先选择歌词')
    line=project.lines[row]
    if line.locked:raise ValueError('本句已锁定，请先解除锁定')
    if project.source_ass_active:raise ValueError('请先明确选择声稿样式，再调整字幕留屏；原 ASS 继续保留')
    if part not in {'start','end','move'}:raise ValueError('显示时间操作无效')
    if type(start) is not int or type(end) is not int or not 0<=start<=line.start<line.end<=end:raise ValueError('出现／消失时间必须包含完整演唱，不会裁掉音节')
    if project.duration and end>project.duration:raise ValueError('消失时间不能超出素材结尾，请先修正演唱范围')
    if part in {'start','move'}:line.display_start=start
    if part in {'end','move'}:line.display_end=end
