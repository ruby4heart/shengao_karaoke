"""Three visible audio controls with Aegisub zoom and cubic display gain."""
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QSlider


class ResetSlider(QSlider):
    def __init__(self,minimum,maximum,default,parent=None):
        super().__init__(Qt.Orientation.Vertical,parent);self.setRange(minimum,maximum);self.default=default;self.setValue(default)
    def mouseDoubleClickEvent(self,event):self.setValue(self.default);event.accept()


class AudioControls(QWidget):
    def __init__(self,timeline,volume,parent=None):
        super().__init__(parent);self.timeline=timeline;self.volume=volume;self.setFixedWidth(144)
        row=QHBoxLayout(self);row.setContentsMargins(4,0,0,0);row.setSpacing(4)
        self.zoom=ResetSlider(-30,200,0,self);self.gain=ResetSlider(1,100,50,self)
        volume.setOrientation(Qt.Orientation.Vertical);volume.setMaximumWidth(38)
        self.values=[]
        for title,slider,help_text in [
            ('时宽',self.zoom,'时间缩放：往上拖，看更短的时间、更清楚的音节。双击恢复默认。Ctrl＋滚轮也能缩放。'),
            ('高度',self.gain,'波形／频谱显示增益：往上拖能看清较弱的尾音，不改变试听音量。50 为 1 倍，100 为 8 倍；双击恢复。'),
            ('音量',volume,'试听音量：只改变听到的声音，不改变视频文件、时间轴或导出。')]:
            box=QVBoxLayout();box.setSpacing(4);label=QLabel(title);label.setAlignment(Qt.AlignmentFlag.AlignCenter);label.setToolTip(help_text);box.addWidget(label);slider.setToolTip(help_text);slider.setAccessibleName(title);box.addWidget(slider,1);value=QLabel();value.setAlignment(Qt.AlignmentFlag.AlignCenter);box.addWidget(value);row.addLayout(box,1);self.values.append(value)
        self.zoom.valueChanged.connect(timeline.set_zoom);self.gain.valueChanged.connect(self.set_gain);volume.valueChanged.connect(self.sync)
        timeline.viewChanged.connect(self.sync);self.sync()

    def set_gain(self,position):
        self.timeline.amplitude=(max(1,position)/50.)**3;self.timeline.cache_key=None;self.timeline.update();self.sync()

    def sync(self,*args):
        z=QSignalBlocker(self.zoom);g=QSignalBlocker(self.gain)
        self.zoom.setValue(self.timeline.zoom_level);self.gain.setValue(round(50*max(0,self.timeline.amplitude)**(1/3)))
        self.values[0].setText(f'{self.timeline.span/1000:.2f}s');self.values[1].setText(f'{self.timeline.amplitude:.2g}×');self.values[2].setText(f'{self.volume.value()}%')
