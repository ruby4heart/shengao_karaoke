"""One reviewable correction for an explicit set of lyric lines."""
import copy
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
    QComboBox, QDoubleSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QDialogButtonBox, QStackedWidget, QScrollArea)
from .widgets import TimeEdit, time_text
from .timeline import Timeline
from .time_transform import TimeTransform, transform_project


class TimeCorrectionDialog(QDialog):
    def __init__(self, project, indices, playback, source_timeline, title, mode='offset', parent=None):
        super().__init__(parent)
        self.original = copy.deepcopy(project); self.indices = list(indices); self.playback = playback
        self.preview_result = None; self.result = None; self.closed = False; self.updating = False
        self.setWindowTitle('统一校轴 · '+title); self.resize(1040, 740); self.setMinimumSize(820, 600)
        root = QVBoxLayout(self); root.setSpacing(8)
        heading = QLabel(f'修改范围：{title}。这里只预览，应用后整次可一步撤销。')
        heading.setWordWrap(True); root.addWidget(heading)
        scroll = QScrollArea(); self.controls_scroll=scroll; scroll.setWidgetResizable(True); scroll.setMinimumHeight(130); scroll.setMaximumHeight(290)
        controls = QWidget(); layout = QVBoxLayout(controls); layout.setContentsMargins(0, 0, 6, 0); layout.setSpacing(6); scroll.setWidget(controls); root.addWidget(scroll)
        self.mode = QComboBox(); self.mode.addItem('整段早了／晚了：整体提前或延后', 'offset'); self.mode.addItem('开头对、后面越来越偏：对齐两个或更多位置', 'drift'); layout.addWidget(self.mode)
        self.pages = QStackedWidget(); layout.addWidget(self.pages)
        offset_page = QWidget(); box = QVBoxLayout(offset_page); box.setContentsMargins(0, 0, 0, 0)
        note = QLabel('全部词组和音节一起移动，相对时长与读音保留。'); note.setWordWrap(True); box.addWidget(note)
        row = QHBoxLayout(); self.direction = QComboBox(); self.direction.addItems(['提前', '延后']); self.direction.setCurrentIndex(1); row.addWidget(self.direction)
        self.amount = QDoubleSpinBox(); self.amount.setRange(0, 2147483); self.amount.setDecimals(3); self.amount.setSingleStep(.01); self.amount.setSuffix(' 秒'); row.addWidget(self.amount, 1)
        playhead = QPushButton('把范围开始移到播放点'); playhead.clicked.connect(self.pin_to_playhead); row.addWidget(playhead); box.addLayout(row)
        row = QHBoxLayout()
        for title_, delta in [('提前 100ms', -100), ('提前 10ms', -10), ('延后 10ms', 10), ('延后 100ms', 100)]:
            button = QPushButton(title_); button.clicked.connect(lambda checked=False, d=delta: self.set_shift(self.offset()+d)); row.addWidget(button)
        box.addLayout(row); box.addStretch(); self.pages.addWidget(offset_page)
        drift_page = QWidget(); box = QVBoxLayout(drift_page); box.setContentsMargins(0, 0, 0, 0)
        note = QLabel('找到至少两个听得准的位置：左边填原字幕时间，右边填实际歌声时间。中间跟着校正；范围内两端之外只平移。'); note.setWordWrap(True); box.addWidget(note)
        self.anchors = QTableWidget(0, 4); self.anchors.setHorizontalHeaderLabels(['原字幕位置', '实际歌声位置', '定位原位置', '记录歌声位置'])
        self.anchors.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.anchors.verticalHeader().show(); self.anchors.setMinimumHeight(112); self.anchors.setMaximumHeight(190); box.addWidget(self.anchors)
        row = QHBoxLayout(); add = QPushButton('加入对齐位置'); add.clicked.connect(self.add_anchor); row.addWidget(add); remove = QPushButton('删除所选位置'); remove.clicked.connect(self.remove_anchor); row.addWidget(remove); row.addStretch(); box.addLayout(row); self.pages.addWidget(drift_page)
        body = QHBoxLayout(); self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(['歌词', '原起止', '调整后起止']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.table.verticalHeader().setDefaultSectionSize(44); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.setMinimumWidth(320); body.addWidget(self.table, 1)
        self.timeline = Timeline(); self.timeline.setMinimumSize(280, 180); self.timeline.editing_enabled = False; self.timeline.granularity = 'mora'
        if source_timeline.audio:
            audio = source_timeline.audio
            self.timeline.set_audio({'pcm': str(audio.samples.filename), 'sample_rate': audio.rate, 'duration': source_timeline.duration, 'peaks': source_timeline.peaks, 'keyframes': source_timeline.keyframes})
        body.addWidget(self.timeline, 1); root.addLayout(body, 1)
        row = QHBoxLayout()
        for title_, action in [('试听原位置', lambda: self.listen(False)), ('试听调整后', lambda: self.listen(True)), ('停止试听', playback.stop)]:
            button = QPushButton(title_); button.clicked.connect(action); row.addWidget(button)
        root.addLayout(row); self.status = QLabel(); self.status.setWordWrap(True); self.status.setTextFormat(Qt.TextFormat.PlainText); root.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply); self.apply_button.setText('应用范围修改'); self.apply_button.clicked.connect(self.apply)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消修改'); self.buttons.rejected.connect(self.reject); root.addWidget(self.buttons)
        self.mode.currentIndexChanged.connect(self.change_mode); self.direction.currentIndexChanged.connect(self.preview); self.amount.valueChanged.connect(self.preview); self.table.itemSelectionChanged.connect(self.show_selected)
        self.timeline.seek.connect(playback.seek); self.timeline.audition.connect(lambda a, b: playback.audition(a, b, False)); playback.positionChanged.connect(self.timeline.follow_position); self.finished.connect(self.cleanup)
        self.timeline.action.connect(self.audio_action)
        first = min(project.lines[i].start for i in indices); last = max(project.lines[i].end for i in indices)
        self.set_anchors([(first, first), (last, last)])
        self.mode.setCurrentIndex(1 if mode == 'drift' else 0); self.change_mode()

    def offset(self): return round(self.amount.value()*1000)*(-1 if self.direction.currentIndex() == 0 else 1)

    def set_shift(self, value):
        self.updating = True
        try: self.direction.setCurrentIndex(0 if value < 0 else 1); self.amount.setValue(abs(value)/1000)
        finally: self.updating = False
        self.preview()

    def pin_to_playhead(self):
        first = min(self.original.lines[i].start for i in self.indices)
        self.set_shift(round(self.playback.canvas.position)-first)

    def change_mode(self, *args):
        self.pages.setCurrentIndex(self.mode.currentIndex());self.controls_scroll.setMaximumHeight(290 if self.mode.currentIndex() else 150);self.preview()

    def anchor_values(self):
        return [(self.anchors.cellWidget(row, 0).value(), self.anchors.cellWidget(row, 1).value()) for row in range(self.anchors.rowCount())]

    def set_anchors(self, points):
        self.updating = True
        try:
            self.anchors.setRowCount(0)
            for row, (old, new) in enumerate(points):
                self.anchors.insertRow(row)
                self.anchors.setRowHeight(row,42)
                for col, value in enumerate((old, new)):
                    edit = TimeEdit(); edit.setValue(value); edit.valueChanged.connect(self.preview); self.anchors.setCellWidget(row, col, edit)
                locate = QPushButton('试听原位置'); locate.clicked.connect(lambda checked=False, f=self.anchors.cellWidget(row, 0): self.playback.audition(max(0, f.value()-250), f.value()+750, False)); self.anchors.setCellWidget(row, 2, locate)
                record = QPushButton('使用播放点'); record.clicked.connect(lambda checked=False, f=self.anchors.cellWidget(row, 1): f.setValue(round(self.playback.canvas.position))); self.anchors.setCellWidget(row, 3, record)
            self.anchors.setFixedHeight(min(190,36+42*len(points)))
        finally: self.updating = False
        if hasattr(self, 'apply_button'): self.preview()

    def add_anchor(self):
        points = self.anchor_values(); gaps = [(b[0]-a[0], i) for i, (a, b) in enumerate(zip(points, points[1:]))]
        if not gaps: return
        _, index = max(gaps); a, b = points[index:index+2]
        points.insert(index+1, ((a[0]+b[0])//2, (a[1]+b[1])//2)); self.set_anchors(points)

    def remove_anchor(self):
        if self.anchors.rowCount() <= 2: self.status.setText('至少保留两个对齐位置。'); return
        points = self.anchor_values(); row = self.anchors.currentRow(); points.pop(row if row >= 0 else -1); self.set_anchors(points)

    def preview(self, *args):
        if self.updating: return
        current = self.table.currentRow(); self.preview_result = None; self.apply_button.setEnabled(False)
        try:
            transform = TimeTransform(anchors=tuple(self.anchor_values())) if self.mode.currentData() == 'drift' else TimeTransform(offset=self.offset())
            result = transform_project(self.original, self.indices, transform)
            self.preview_result = result; self.apply_button.setEnabled(bool(result.rows))
            self.status.setText(f'将调整 {len(result.rows)} 句；原文、读音和范围外内容保留。'+ ('\n'+'\n'.join(result.warnings[:3]) if result.warnings else ''))
        except ValueError as error: self.status.setText(str(error))
        blocker = QSignalBlocker(self.table); self.table.setRowCount(len(self.indices))
        for row, index in enumerate(self.indices):
            before = self.original.lines[index]; after = self.preview_result.project.lines[index] if self.preview_result else before
            for col, value in enumerate((f'{index+1} · {before.text}', f'{time_text(before.start)}\n{time_text(before.end)}', f'{time_text(after.start)}\n{time_text(after.end)}')):
                item = QTableWidgetItem(value); item.setToolTip(value); self.table.setItem(row, col, item)
        self.table.selectRow(max(0, min(current, len(self.indices)-1))); self.show_selected()

    def show_selected(self):
        row = max(0, self.table.currentRow()); index = self.indices[min(row, len(self.indices)-1)]
        project = self.preview_result.project if self.preview_result else self.original
        self.timeline.set_neighbors(project.lines[index-1] if index else None, project.lines[index+1] if index+1 < len(project.lines) else None); self.timeline.set_line(project.lines[index])

    def listen(self, changed):
        if changed and not self.preview_result: return
        index = self.indices[max(0, self.table.currentRow())]; line = (self.preview_result.project if changed else self.original).lines[index]
        self.playback.audition(max(0, line.start-200), line.end+200, False)

    def audio_action(self,name):
        if name=='stop':self.playback.stop()
        elif name in ('line','selection','toggle'):self.listen(True)
        elif name in ('next','previous'):
            row=max(0,min(len(self.indices)-1,self.table.currentRow()+(1 if name=='next' else -1)));self.table.selectRow(row)
        elif name in ('confirm','confirm_default'):self.apply()
        elif name.startswith('scroll_'):
            self.timeline.left+=128*self.timeline.pixel_ms/self.timeline.devicePixelRatioF()*(-1 if name=='scroll_left' else 1);self.timeline.invalidate()

    def apply(self):
        self.amount.interpretText()
        for row in range(self.anchors.rowCount()):
            for col in (0,1):self.anchors.cellWidget(row,col).interpretText()
        self.preview()
        if self.preview_result and self.preview_result.rows: self.result = self.preview_result; self.accept()

    def cleanup(self, *args):
        if self.closed: return
        self.closed = True; self.playback.stop(); self.timeline.cancel_drag()
        try: self.playback.positionChanged.disconnect(self.timeline.follow_position)
        except RuntimeError: pass
        if self.timeline.audio: self.timeline.audio.close(); self.timeline.audio = None
