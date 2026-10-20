"""Review local cleanup of auto-generated gaps, without another API call."""
import copy
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
    QSpinBox,QCheckBox,QListWidget,QDialogButtonBox,QPushButton)
from studio_backend.continuity import continuous_lines,DEFAULT_GAP_MS
from .widgets import time_text


class ContinuityDialog(QDialog):
    def __init__(self,project,current,playback,parent=None):
        super().__init__(parent);self.setWindowTitle('收拢自动分轴的空白时间');self.resize(690,510)
        self.project=project;self.current=current;self.playback=playback;self.result_lines=project.lines;self.changes=[]
        layout=QVBoxLayout(self);notice=QLabel('延长前一音节尾部，接到后一音节的起点；起音不移动。保护已确认、锁定和人工校准时间。此操作不上传音频，应用后可整体撤销。');notice.setWordWrap(True);layout.addWidget(notice)
        row=QHBoxLayout();self.scope=QComboBox();self.scope.addItem('整首的自动轴','all');self.scope.addItem('仅当前句','current');row.addWidget(self.scope,1)
        row.addWidget(QLabel('收拢不超过'));self.maximum=QSpinBox();self.maximum.setRange(10,2000);self.maximum.setSingleStep(50);self.maximum.setSuffix(' ms');self.maximum.setValue(DEFAULT_GAP_MS);row.addWidget(self.maximum);layout.addLayout(row)
        self.join_lines=QCheckBox('同时处理相邻两句之间的短空白');self.join_lines.setChecked(True);layout.addWidget(self.join_lines)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary);self.list=QListWidget();layout.addWidget(self.list,1)
        note=QLabel('阈值只按时间长度判断，不代表已检测真实静音。长休止默认保留；不确定时可试听，仍可用原来的“试听并处理空白时间”逐项处理。');note.setWordWrap(True);layout.addWidget(note)
        self.listen=QPushButton('试听所选空白及两侧音节');self.listen.clicked.connect(self.listen_selected);layout.addWidget(self.listen)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel);self.apply_button=controls.button(QDialogButtonBox.StandardButton.Apply);self.apply_button.setText('应用连续边界');controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');self.apply_button.clicked.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)
        self.scope.currentIndexChanged.connect(self.refresh);self.maximum.valueChanged.connect(self.refresh);self.join_lines.toggled.connect(self.refresh);self.finished.connect(lambda _:playback.stop());self.refresh()

    def refresh(self,*args):
        all_lines=self.scope.currentData()=='all';self.join_lines.setEnabled(all_lines)
        original=self.project.lines if all_lines else [self.project.lines[self.current]]
        values,self.changes=continuous_lines(original,self.maximum.value(),all_lines and self.join_lines.isChecked())
        self.result_lines=values if all_lines else [values[0] if i==self.current else copy.deepcopy(line) for i,line in enumerate(self.project.lines)]
        labels={line.id:f'第 {i+1} 句' for i,line in enumerate(self.project.lines)};self.list.clear()
        for item in self.changes:
            kind={'word':'词组间','mora':'音节间','line':'两句间'}[item['kind']]
            self.list.addItem(f'{labels[item["id"]]} · {kind} · {item["end"]-item["start"]} ms · {item["text"]}\n{time_text(item["start"])} → {time_text(item["end"])}')
        duration=sum(c['end']-c['start'] for c in self.changes)
        self.summary.setText(f'将收拢 {len(self.changes)} 处短空白，共 {duration} ms；后一音节起音均保持不变。' if self.changes else '没有符合阈值的可调整自动轴空白。人工时间、已确认歌词和锁定内容已保护。')
        self.apply_button.setEnabled(bool(self.changes));self.listen.setEnabled(bool(self.changes))
        if self.changes:self.list.setCurrentRow(0)

    def listen_selected(self):
        row=self.list.currentRow()
        if 0<=row<len(self.changes):
            item=self.changes[row];self.playback.audition(max(0,item['start']-350),item['end']+350)
