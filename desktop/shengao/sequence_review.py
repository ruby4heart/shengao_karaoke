"""Review text-sequence issues without treating ASR as confirmed singing."""
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton
from .timeline import stamp


TITLES={'missing_lyric_candidate':'漏识别／缺唱候选','repeat_ambiguity':'重复段位置待定',
        'weak_correspondence':'文字对应较弱','order_conflict':'段落顺序不同',
        'protected_overlap':'人工位置重叠','unassigned_transcript':'未分配转录／多唱候选'}


class SequenceReview(QWidget):
    focus_requested=Signal(str)
    manual_requested=Signal(str)
    rematch_requested=Signal(str)

    def __init__(self,report,values,project,playback,parent=None):
        super().__init__(parent);self.playback=playback;self.project=project
        self.rows={v['id']:v for v in values};self.indices={v.id:i+1 for i,v in enumerate(project.lines)}
        self.items=[*report.get('issues',[]),*report.get('unassigned_transcript',[])]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        summary=QLabel(f'整首顺序检查（匹配时） · {len(report.get("issues",[]))} 项歌词疑点 · {len(report.get("unassigned_transcript",[]))} 段未分配转录。均需试听。')
        summary.setWordWrap(True);layout.addWidget(summary)
        self.selector=QComboBox();self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.selector.setMinimumContentsLength(12)
        for issue in self.items:
            numbers='、'.join(str(self.indices[uid]) for uid in issue.get('line_ids',[]) if uid in self.indices)
            text=issue.get('text','');label=TITLES.get(issue['kind'],'待校对')+(' · 第 '+numbers+' 句' if numbers else '')
            self.selector.addItem(label+(' · '+text[:48] if text else ''),issue)
        layout.addWidget(self.selector)
        self.reason=QLabel();self.reason.setTextFormat(Qt.TextFormat.PlainText);self.reason.setWordWrap(True);layout.addWidget(self.reason)
        row=QHBoxLayout();self.listen=QPushButton('试听疑点（最多 12 秒）');self.listen.clicked.connect(self.audition);row.addWidget(self.listen)
        self.manual=QPushButton('定位到主界面校对');self.manual.clicked.connect(lambda:self.emit_target(self.manual_requested));row.addWidget(self.manual)
        self.rematch=QPushButton('限定正确时段重匹配');self.rematch.clicked.connect(lambda:self.emit_target(self.rematch_requested));row.addWidget(self.rematch);layout.addLayout(row)
        self.rematch.setToolTip('先保留本次结果，再用已有转录局部匹配；不会重新上传或提交付费转录。')
        self.selector.currentIndexChanged.connect(self.changed);self.changed()

    def target(self):
        issue=self.selector.currentData() or {}
        return next((uid for uid in issue.get('line_ids',[]) if uid in self.indices),None)

    def emit_target(self,signal):
        uid=self.target()
        if uid:signal.emit(uid)

    def interval(self):
        issue=self.selector.currentData() or {};value=self.rows.get(self.target(),{})
        interval=value.get('match',{}).get('context_range',[value.get('start',0),value.get('end',10)])
        ranges=issue.get('ranges',[])
        a=issue.get('start',ranges[0]['start'] if ranges else interval[0]);b=issue.get('end',ranges[0]['end'] if ranges else interval[1])
        maximum=self.project.duration or max(b,10)
        a=min(maximum-10,max(0,a-350));b=min(maximum,max(a+10,b+350),a+12000)
        return max(0,a),max(a+10,b)

    def changed(self):
        issue=self.selector.currentData() or {};uid=self.target();a,b=self.interval()
        self.reason.setText((issue.get('reason','没有发现文字顺序疑点，仍需试听读音与时间。'))+f' 试听：{stamp(a)}—{stamp(b)}。')
        self.selector.setEnabled(bool(self.items));self.listen.setEnabled(bool(issue));self.manual.setEnabled(bool(uid));self.rematch.setEnabled(bool(uid and self.project.transcript))
        if uid:self.focus_requested.emit(uid)

    def audition(self):
        if self.selector.currentData():self.playback.audition(*self.interval())
