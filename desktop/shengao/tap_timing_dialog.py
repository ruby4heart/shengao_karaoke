"""Opt-in, modeless tapping on the existing source playback clock."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QCheckBox,
    QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QDialogButtonBox,QScrollArea,QWidget)
from .tap_timing import TapDraft
from .project import file_stamp
from .native_slots import invoke_native_slot
from .widgets import time_text


def note(text):
    label=QLabel(text);label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);return label


def push(text,slot):
    button=QPushButton(text);button.setAutoDefault(False);button.clicked.connect(slot);return button


class TapButton(QPushButton):
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Space:
            if not event.isAutoRepeat():self.click()
            event.accept();return
        super().keyPressEvent(event)

    def keyReleaseEvent(self,event):
        if event.key()==Qt.Key.Key_Space:event.accept();return
        super().keyReleaseEvent(event)


class TapTimingDialog(QDialog):
    def __init__(self,studio):
        super().__init__(studio);self.studio=studio;self.playback=studio.playback;self.recording=False;self.applied=False;self.stale=False
        self.setWindowTitle('跟唱打点 · 本句草稿');self.resize(700,650);self.setMinimumSize(480,440);self.setModal(False)
        self.context=self.current_context();self.draft=TapDraft(studio.line);self.saved_loop=self.playback.loop
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll,1)
        layout.addWidget(note(studio.line.text));layout.addWidget(note('跟着演唱记录音节；先留草稿，比较后一次应用。'))
        self.source_label=note(('人声辅助' if studio.audition_role=='vocals' else '原声')+' · 本句 '+time_text(studio.line.start)+' — '+time_text(studio.line.end)+' · 使用当前播放速度。');layout.addWidget(self.source_label)
        self.mode=QComboBox();self.mode.addItem('逐音起止：每音开始、结束各一次，保留休止','paired');self.mode.addItem('连续分界：每个交界一次，相邻音节连接','continuous');layout.addWidget(self.mode)
        self.gaps=QCheckBox('连续分界时，允许连接原来音节之间的间隔');layout.addWidget(self.gaps)
        layout.addWidget(note('固定点保持；已有人工时间需勾选允许替换。'))
        row=QHBoxLayout();self.start_button=push('开始／继续试听',self.start);row.addWidget(self.start_button);row.addWidget(push('暂停',self.pause));row.addWidget(push('停止并回句首',self.stop_at_start));layout.addLayout(row)
        self.target=note('');layout.addWidget(self.target)
        self.capture=TapButton('记录这一点（按钮聚焦时按空格）');self.capture.setAutoDefault(False);self.capture.clicked.connect(self.tap);layout.addWidget(self.capture)
        self.capture.setToolTip('只有此按钮获得焦点时，空格才录制。按提示依次记录，不自动填平休止；关闭面板恢复普通键位。')
        row=QHBoxLayout();row.addWidget(push('退回上一点',self.back));row.addWidget(push('全部重录',self.restart));layout.addLayout(row)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['音节','原时间','新草稿（固定点保持）']);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.table.verticalHeader().hide();self.table.setMinimumHeight(140);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);layout.addWidget(self.table,1)
        self.allow_manual=QCheckBox('允许替换本句已有的人工／已确认时间；固定点仍保持');layout.addWidget(self.allow_manual)
        self.status=note('');layout.addWidget(self.status)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel);self.apply_button=controls.button(QDialogButtonBox.StandardButton.Apply);self.apply_button.setText('应用草稿（可撤销）');self.apply_button.setAutoDefault(False);self.apply_button.clicked.connect(self.apply);controls.rejected.connect(self.reject);outer.addWidget(controls)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.mode.currentIndexChanged.connect(self.change_mode);self.gaps.toggled.connect(self.change_mode);self.allow_manual.toggled.connect(self.render)
        self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self.check_context);self.timer.start();self.render()

    def current_context(self):
        w=self.studio
        return (w.project.uid,w.project.media,file_stamp(w.project.media),w.project.media_role,w.audition_role,
                self.playback.player.source().toString(),w.line.to_dict() if w.line else None)

    def check_context(self):
        if self.studio.closing or self.context!=self.current_context():
            if not self.stale:self.stale=True;self.pause();self.render()
            self.status.setText('工程、歌词或试听源已变化，草稿保留供查看；请关闭后对当前句重新录制，避免覆盖新内容。')
        elif self.recording and self.playback.player.playbackState()!=QMediaPlayer.PlaybackState.PlayingState:
            self.pause();self.render();self.status.setText('试听已暂停或到达句尾；草稿保留，可退回重录或继续试听。')

    def change_mode(self,*args):
        self.pause()
        if self.draft.points:
            self.status.setText('已有打点；先点“全部重录”再应用所选模式，旧草稿保持。');return
        self.new_draft()

    def new_draft(self):
        try:self.draft=TapDraft(self.draft.original,self.mode.currentData(),self.gaps.isChecked());self.status.setText('');self.render();return True
        except ValueError as error:self.status.setText(str(error));return False

    def start(self):
        self.check_context()
        if self.stale:return
        if self.draft.complete:self.status.setText('已经录满；可应用草稿或退回重录。');return
        if not self.draft.points and not self.new_draft():return
        p=self.playback
        if p.player.source().isEmpty() or self.studio.analysis_job or self.studio.source_job or p.preview_pending or p.pending_seek is not None:
            self.status.setText('请等待素材与预览载入完成，再开始试听。');return
        start=max(0,self.draft.original.start-700) if not self.draft.points else max(self.draft.points[-1],p.canvas.position)
        if start>=self.draft.original.end:self.status.setText('已到句尾，请退回上一点或全部重录。');return
        self.pause()
        if not p.audition(start,self.draft.original.end,False):return
        p.begin_temporary(self,self.interrupted);self.recording=True;self.status.setText('正在试听；按提示依次记录。');self.render();self.capture.setFocus()

    def interrupted(self):
        self.recording=False;self.playback.range=None;invoke_native_slot(self.playback.player,'pause');self.render()
        self.status.setText('其他播放操作中断了录制，已有草稿保留。')

    def pause(self):
        owned=self.playback.temporary_owner is self;self.playback.end_temporary(self)
        if owned:self.playback.stop()
        self.recording=False;self.render()

    def tap(self):
        self.check_context()
        if self.stale or not self.recording:return
        try:self.playback.tick();self.draft.add(int(self.playback.canvas.position));self.status.setText('已记录；应用前不修改原轴。')
        except ValueError as error:self.status.setText(str(error));return
        if self.draft.complete:self.pause()
        self.render()

    def stop_at_start(self):
        self.pause();self.check_context()
        if not self.stale:self.playback.seek(self.draft.original.start)
        self.status.setText('试听已停止并回到句首，打点草稿保持。' if not self.stale else '试听源已变化，草稿保留；没有移动新素材的播放点。')

    def back(self):
        self.pause();self.draft.back()
        if not self.stale:self.playback.seek(self.draft.points[-1] if self.draft.points else max(0,self.draft.original.start-700))
        self.status.setText('已退回一点，可继续试听重录。');self.render()

    def restart(self):
        self.pause()
        # Invalid mode choices must not discard the old recorded draft.
        try:candidate=TapDraft(self.draft.original,self.mode.currentData(),self.gaps.isChecked())
        except ValueError as error:self.status.setText(str(error));return
        self.draft=candidate;self.status.setText('已清空本面板草稿，原轴保持。');self.render()

    def render(self,*args):
        if not hasattr(self,'table'):return
        d=self.draft;n=len(d.points);notes=d.notes
        if d.complete:target='本句录满，请比较新旧时间后应用。'
        elif d.mode=='paired':target=f'下一点：第{n//2+1}音「{notes[n//2][2].kana}」的'+('结束' if n%2 else '开始')
        else:target='下一点：'+(f'第{n+1}音「{notes[n][2].kana}」开始／上一音结束' if n<len(notes) else '最后一音结束')
        self.target.setText(f'{n} / {d.required} 点 · '+target)
        ranges=d.ranges() if d.complete else None;self.table.setRowCount(len(notes))
        for row,(_,_,h) in enumerate(notes):
            old=time_text(h.start)+'–'+time_text(h.end)
            if ranges:new=time_text(ranges[row][0])+'–'+time_text(ranges[row][1])
            else:
                a,b=(row*2,row*2+1) if d.mode=='paired' else (row,row+1)
                start=(h.start if 'start' in h.fixed_edges else d.points[a]) if a<n else None
                end=(h.end if 'end' in h.fixed_edges else d.points[b]) if b<n else None
                new=(time_text(start) if start is not None else '待开始')+'–'+(time_text(end) if end is not None else '待结束')
            for col,value in enumerate((h.kana+('（固定）' if h.fixed_edges else ''),old,new)):self.table.setItem(row,col,QTableWidgetItem(value))
        valid=d.complete and not self.stale and not self.recording
        if valid:
            try:d.candidate(allow_manual=self.allow_manual.isChecked())
            except ValueError as error:self.status.setText(str(error));valid=False
            else:self.status.setText('草稿可应用；这仍是手工初稿，应用后请试听微调再确认。')
        self.apply_button.setEnabled(valid);self.capture.setEnabled(self.recording and not self.stale and not d.complete);self.start_button.setEnabled(not self.stale and not d.complete)
        self.mode.setEnabled(not self.recording and not d.points);self.gaps.setEnabled(not self.recording and not d.points)
        self.gaps.setVisible(self.mode.currentData()=='continuous')
        self.mode.setToolTip('已有打点时，先全部重录清空草稿，再更换模式。')

    def apply(self):
        self.check_context()
        if self.stale or self.recording:return
        try:candidate=self.draft.candidate(allow_manual=self.allow_manual.isChecked())
        except ValueError as error:self.status.setText(str(error));return
        w=self.studio
        if not w.flush_edits():self.status.setText('请先完成主编辑区尚未应用的修改，草稿保持。');return
        self.check_context()
        if self.stale:return
        row=w.current
        if candidate.to_dict()==self.draft.original.to_dict():self.status.setText('新旧时间相同，无需应用。');return
        if w.edit('应用本句跟唱打点草稿',lambda project:project.lines.__setitem__(row,candidate)):
            self.applied=True;w.message('跟唱打点已作为人工时间应用，可一步撤销；请试听微调后再确认本句。');self.accept()

    def done(self,result):
        self.timer.stop();self.pause();self.playback.loop=self.saved_loop;super().done(result)


class TapTimingWorkflow:
    def open_tap_timing(self):
        previous=getattr(self,'tap_dialog',None)
        if previous is not None and previous.isVisible():previous.raise_();previous.activateWindow();return previous
        if not self.flush_edits() or not self.line:return
        try:dialog=TapTimingDialog(self)
        except ValueError as error:self.message(str(error));return
        self.tap_dialog=dialog;dialog.show();return dialog
