"""Manual tap drafts; no acoustic inference or project mutation during recording."""
from dataclasses import dataclass,field
import copy
from studio_backend.provenance import record_tree
from .timing import manual


@dataclass
class TapDraft:
    original: object
    mode: str='paired'
    acknowledge_gaps: bool=False
    points: list[int]=field(default_factory=list)

    def __post_init__(self):
        self.original=copy.deepcopy(self.original);self.points=list(self.points)
        if self.mode not in ('paired','continuous'):raise ValueError('请选择逐音起止或连续分界')
        line=self.original;line.validate()
        if line.locked or any(u.locked for u in line.units):raise ValueError('本句或词组已锁定；请先解除需要修改的锁定，再跟唱打点。')
        if not line.units or any(not u.highlights for u in line.units):raise ValueError('请先完成本句分词、假名与演唱音节，再跟唱打点。')
        if self.mode=='continuous' and self.has_gaps and not self.acknowledge_gaps:
            raise ValueError('连续分界会连接相邻音节；请确认，或使用可保留休止的逐音起止模式。')
        previous=list(self.points);self.points=[]
        for point in previous:self.add(point)

    @property
    def notes(self):return [(i,j,h) for i,u in enumerate(self.original.units) for j,h in enumerate(u.highlights)]

    @property
    def has_gaps(self):return any(a[2].end<b[2].start for a,b in zip(self.notes,self.notes[1:]))

    @property
    def required(self):return len(self.notes)*2 if self.mode=='paired' else len(self.notes)+1

    @property
    def complete(self):return len(self.points)==self.required

    def add(self,position):
        if self.complete:raise ValueError('本句已经录满；请先退回上一点或应用草稿。')
        if type(position) is not int:raise ValueError('播放位置无效')
        value=round(position/10)*10
        if not self.original.start<=position<=self.original.end or not self.original.start<=value<=self.original.end:raise ValueError('打点须在本句演唱范围内；先调整整句范围可扩大录制区间。')
        gap=10 if self.mode=='continuous' or len(self.points)%2 else 0
        if self.points and value<self.points[-1]+gap:raise ValueError('新点早于上一点，或音节短于10毫秒；可退回上一点重录。')
        self.points.append(value);return value

    def back(self):
        if self.points:return self.points.pop()

    def ranges(self):
        if not self.complete:raise ValueError('打点尚未录满，不能应用。')
        ranges=list(zip(self.points[::2],self.points[1::2])) if self.mode=='paired' else list(zip(self.points,self.points[1:]))
        # The comparison and committed candidate both retain actual fixed edges.
        return [(h.start if 'start' in h.fixed_edges else a,h.end if 'end' in h.fixed_edges else b)
                for (_,_,h),(a,b) in zip(self.notes,ranges)]

    def candidate(self,*,allow_manual=False):
        result=copy.deepcopy(self.original);ranges=self.ranges()
        for (i,j,_),(a,b) in zip(self.notes,ranges):
            if b-a<10:raise ValueError('新打点与固定边界冲突，或音节短于10毫秒；请退回修正，固定点保持。')
            h=result.units[i].highlights[j];h.start,h.end=a,b
            if (a,b)!=(self.original.units[i].highlights[j].start,self.original.units[i].highlights[j].end):h.source='manual'
        for before,u in zip(self.original.units,result.units):
            first,last=u.highlights[0].start,u.highlights[-1].end
            u.start=first if before.start==before.highlights[0].start else min(before.start,first)
            u.end=last if before.end==before.highlights[-1].end else max(before.end,last)
            changed=(u.start,u.end)!=(before.start,before.end) or any((a.start,a.end)!=(b.start,b.end) for a,b in zip(before.highlights,u.highlights))
            protected=before.source=='manual' or self.original.reviewed or any(h.source=='manual' for h in before.highlights)
            if changed and protected and not allow_manual:raise ValueError('本句含已确认或人工时间；请明确允许替换人工时间后再应用。固定点仍保持。')
            if changed:u.source='manual'
        try:result.validate()
        except ValueError as error:raise ValueError('新打点的顺序、范围或固定点有冲突：'+str(error)) from error
        changed=any((a.start,a.end)!=(b.start,b.end) or any((x.start,x.end)!=(y.start,y.end) for x,y in zip(a.highlights,b.highlights)) for a,b in zip(self.original.units,result.units))
        if changed:
            record_tree(self.original,result,'manual_boundary');manual(result);result.validate()
        return result
