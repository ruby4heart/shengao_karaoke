"""Atomic timing changes for a phrase, a selection, a suffix or an entire song."""
import copy
from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
from .timing import manual
from studio_backend.provenance import record_tree


def scope_indices(project, scope, current, selected=()):
    if scope == 'all': values = list(range(len(project.lines)))
    elif scope == 'following': values = list(range(max(0, current), len(project.lines))) if current >= 0 else []
    elif scope == 'current': values = [current] if 0 <= current < len(project.lines) else []
    elif scope == 'selected':
        values=list(selected)
        if any(type(i) is not int for i in values):raise ValueError('歌词选择须为有效行号')
        values=sorted(set(values))
    else: raise ValueError('请选择修改范围')
    if not values: raise ValueError('这个范围没有歌词，请先选择要修改的句子')
    if any(type(i) is not int or not 0 <= i < len(project.lines) for i in values): raise ValueError('歌词选择已变化，请重新选择范围')
    return values


def locked_rows(project, indices):
    return [i for i in indices if project.lines[i].locked or any(u.locked for u in project.lines[i].units)]


def shift_limits(project, indices):
    lower = -min(project.lines[i].start for i in indices)
    upper = project.duration-max(project.lines[i].end for i in indices) if project.duration else None
    if upper is not None and lower > upper: raise ValueError('所选歌词跨度超过素材时长，请先修正范围或使用分段校正')
    return lower, upper


@dataclass(frozen=True)
class TimeTransform:
    offset: int = 0
    anchors: tuple = ()

    def __post_init__(self):
        if type(self.offset) is not int: raise ValueError('偏移量须为整数毫秒')
        if self.anchors:
            if self.offset: raise ValueError('整体偏移与分段校正不能同时设置')
            if len(self.anchors) < 2: raise ValueError('至少需要两个对齐位置')
            previous = None
            for point in self.anchors:
                if len(point) != 2 or any(type(t) is not int or t < 0 for t in point): raise ValueError('对齐位置须为非负整数毫秒')
                if previous and (point[0] <= previous[0] or point[1] <= previous[1]): raise ValueError('原字幕位置和歌声位置都必须依次向后，不能相同或倒序')
                previous = point

    def at(self, time):
        if not self.anchors: return time+self.offset
        points = self.anchors
        if time <= points[0][0]: return time+points[0][1]-points[0][0]
        if time >= points[-1][0]: return time+points[-1][1]-points[-1][0]
        index = bisect_right([p[0] for p in points], time)-1
        (a, x), (b, y) = points[index:index+2]
        return x+round(Fraction((time-a)*(y-x), b-a))


@dataclass
class TimingResult:
    project: object
    rows: list
    warnings: list


def transform_project(original, indices, transform):
    indices = scope_indices(original, 'selected', -1, indices)
    protected = locked_rows(original, indices)
    if protected:
        labels = '、'.join(str(i+1) for i in protected[:12])
        raise ValueError(f'第 {labels} 句或其中词组已锁定；本次没有修改任何句子，请先解除锁定或重新选择范围')
    project = copy.deepcopy(original); rows = []
    full_scope=len(indices)==len(original.lines)
    from .presentation import display_windows
    old_windows=display_windows(original) if full_scope and original.style.display_mode=='alternating' and not original.source_ass_active else None
    for index in indices:
        before = original.lines[index]; line = project.lines[index]
        def change(item):
            start, end = transform.at(item.start), transform.at(item.end)
            if start < 0: raise ValueError(f'第 {index+1} 句将移到素材开始之前，请减少提前量')
            if end < start or (item.end > item.start and end == start): raise ValueError(f'第 {index+1} 句的时间被压缩成零或倒序，请调整对齐位置')
            if project.duration and end > project.duration: raise ValueError(f'第 {index+1} 句将超出素材结尾，请减少延后量或调整对齐位置')
            changed = (start, end) != (item.start, item.end)
            item.start, item.end = start, end
            return changed
        changed = change(line)
        for unit in line.units:
            unit_changed = change(unit)
            for part in unit.highlights:
                part_changed = change(part)
                if part_changed: part.source = 'manual'
                unit_changed |= part_changed
            if unit_changed: unit.source = 'manual'
            changed |= unit_changed
        if changed:
            def operation(item):
                points=[item.start,item.end,*[a for a,b in transform.anchors if item.start<a<item.end]]
                return 'shift' if len({transform.at(t)-t for t in points})==1 else 'stretch'
            record_tree(before,line,operation)
            if old_windows is not None:
                window=old_windows[index]
                line.display_start=max(0,min(line.start,transform.at(window.start)))
                line.display_end=max(line.end,transform.at(window.end))
                if project.duration:line.display_end=min(line.display_end,project.duration)
            else:
                if line.display_start is not None:line.display_start=max(0,min(line.start,transform.at(before.display_start)))
                if line.display_end is not None:
                    line.display_end=max(line.end,transform.at(before.display_end))
                    if project.duration:line.display_end=min(line.display_end,project.duration)
            manual(line); line.validate()
            rows.append({'index': index, 'id': line.id, 'before': (before.start, before.end), 'after': (line.start, line.end)})
    warnings = []
    affected = set(indices)
    for i in range(1, len(project.lines)):
        if i not in affected and i-1 not in affected: continue
        old_a, old_b = original.lines[i-1:i+1]; a, b = project.lines[i-1:i+1]
        old_overlap = max(0, min(old_a.end, old_b.end)-max(old_a.start, old_b.start))
        overlap = max(0, min(a.end, b.end)-max(a.start, b.start))
        if overlap > old_overlap: warnings.append(f'第 {i}／{i+1} 句演唱重叠变为 {overlap}ms，请试听确认是否合唱')
        if b.start < a.start and old_b.start >= old_a.start: warnings.append(f'第 {i+1} 句将比前一句更早开始，请确认是否选错段')
    if rows and project.source_ass_active and project.source_ass:
        if not project.ass_rows: raise ValueError('这份旧 ASS 没有可编辑的事件对应信息，请先选择声稿样式后校正时间；原 ASS 会保留')
        if transform.anchors: warnings.append('外部 ASS 的复杂相对动画未自动拉伸，请检查实际预览和样片')
    project.validate()
    return TimingResult(project, rows, warnings)
