"""Locate a wrongly matched phrase or group using the existing transcript."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QDialogButtonBox
from .widgets import TimeEdit


class MatchRangeDialog(QDialog):
    def __init__(self,project,indices,playback,parent=None):
        super().__init__(parent);self.setWindowTitle('这一段配到了别处 · 选择正确演唱范围');self.resize(620,250)
        self.range=None;self.playback=playback
        root=QVBoxLayout(self);note=QLabel(f'将复用已有转录重新匹配 {len(indices)} 句。先播放找到正确段落，填写该段开始与结束；返回结果先审核。');note.setWordWrap(True);root.addWidget(note)
        self.begin=TimeEdit();self.end=TimeEdit();maximum=project.duration or 2147480000
        self.begin.setMaximum(maximum);self.end.setMaximum(maximum)
        self.begin.setValue(max(0,min(project.lines[i].start for i in indices)-3000));self.end.setValue(min(maximum,max(project.lines[i].end for i in indices)+3000))
        for title,field in [('正确段落开始',self.begin),('结束',self.end)]:
            row=QHBoxLayout();row.addWidget(QLabel(title));row.addWidget(field,1);button=QPushButton('使用播放点');button.clicked.connect(lambda checked=False,f=field:f.setValue(round(playback.canvas.position)));row.addWidget(button);root.addLayout(row)
        listen=QPushButton('试听这个范围');listen.clicked.connect(lambda:playback.audition(self.begin.value(),self.end.value(),False));root.addWidget(listen)
        self.status=QLabel();root.addWidget(self.status);self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setText('本地重新匹配并审核');self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');self.buttons.rejected.connect(self.reject);root.addWidget(self.buttons);self.finished.connect(lambda _:playback.stop())

    def apply(self):
        self.begin.interpretText();self.end.interpretText()
        if self.end.value()<=self.begin.value():self.status.setText('结束时间须晚于开始时间。');return
        self.range=[self.begin.value(),self.end.value()];self.accept()
