"""Choose an approved chorus and explicit target rows; timing stays separate."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QTableWidget,QTableWidgetItem,QHeaderView,QCheckBox,QDialogButtonBox,QScrollArea,QWidget,QPushButton
from studio_backend.chorus_reuse import prepare,source_valid
from .timeline import stamp


class ChorusDialog(QDialog):
    def __init__(self,project,current,playback,parent=None):
        super().__init__(parent);self.setWindowTitle('复用已校对副歌');self.resize(820,600)
        self.project=project;self.current=current;self.playback=playback;self.manual_uid=None
        root=QVBoxLayout(self);body=QWidget();layout=QVBoxLayout(body);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(body);root.addWidget(scroll,1)
        notice=QLabel('选择读音和时间都已确认的来源句，只复用分词、假名和罗马音；按目标段的声音重新生成时间候选。不同唱段可能有不同唱法，仍需审核。');notice.setWordWrap(True);layout.addWidget(notice)
        self.source=QComboBox();layout.addWidget(self.source);self.sources={}
        for index,line in enumerate(project.lines):
            try:source_valid(line,project.checks.get(line.id,{}).get('reading'))
            except ValueError:continue
            if not any(v.id!=line.id and v.text==line.text for v in project.lines):continue
            self.sources[line.id]=line;self.source.addItem(f'第 {index+1} 句 · {stamp(line.start)} · '+line.text[:55],line.id)
        self.source_detail=QLabel();self.source_detail.setTextFormat(Qt.TextFormat.PlainText);self.source_detail.setWordWrap(True);layout.addWidget(self.source_detail)
        self.source_listen=QPushButton('试听来源句');self.source_listen.clicked.connect(self.listen_source);layout.addWidget(self.source_listen)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['处理','目标句','当前演唱范围','当前读音／保护原因']);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch);self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch);self.table.setColumnWidth(0,45);self.table.setColumnWidth(2,170);self.table.setMinimumHeight(180);layout.addWidget(self.table,1)
        row=QHBoxLayout();self.target_listen=QPushButton('试听所选目标');self.target_listen.clicked.connect(self.listen_target);row.addWidget(self.target_listen)
        manual=QPushButton('去主界面校对这一句');manual.clicked.connect(self.open_manual);row.addWidget(manual);layout.addLayout(row)
        self.voice=QCheckBox('按目标段歌声重新计算音节时间（本机，不使用 API 额度）');self.voice.setChecked(Path(project.media).is_file());self.voice.setEnabled(Path(project.media).is_file());layout.addWidget(self.voice)
        self.audio=QComboBox();self.audio.addItem('自动选择对应人声／当前原声','auto');self.audio.addItem('当前视频原声','original')
        if project.vocal_track:self.audio.addItem('已有的人声辅助','vocals')
        layout.addWidget(self.audio);self.fit=QCheckBox('允许按本段声音微调句首句尾');self.fit.setChecked(True);layout.addWidget(self.fit)
        self.count=QLabel();self.count.setWordWrap(True);layout.addWidget(self.count)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);self.apply=self.buttons.button(QDialogButtonBox.StandardButton.Ok);self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);root.addWidget(self.buttons)
        self.source.currentIndexChanged.connect(self.refresh);self.table.itemChanged.connect(self.selection_changed);self.voice.toggled.connect(self.selection_changed)
        current_line=project.lines[current] if 0<=current<len(project.lines) else None
        if current_line:
            preferred=next((uid for uid,line in self.sources.items() if uid==current_line.id),None) or next((uid for uid,line in self.sources.items() if line.text==current_line.text and line.start<=current_line.start),None)
            if preferred:self.source.setCurrentIndex(self.source.findData(preferred))
        self.refresh();self.finished.connect(lambda _:playback.stop())

    def refresh(self):
        self.table.blockSignals(True);self.table.setRowCount(0);self.targets=[];source=self.sources.get(self.source.currentData())
        self.source_listen.setEnabled(source is not None and Path(self.project.media).is_file())
        if source is None:self.source_detail.setText('先给相同原文中的一句完成分词，并分别确认读音和时间，再复用到其他唱段。');self.table.blockSignals(False);self.selection_changed();return
        self.source_detail.setText('来源词组：'+' ｜ '.join(u.text+'【'+u.kana+'】' for u in source.units)+'\n来源的音节时间、确认和锁定状态不会复制到目标。')
        eligible_current=0<=self.current<len(self.project.lines) and self.project.lines[self.current].id!=source.id
        for index,target in enumerate(self.project.lines):
            if target.id==source.id or target.text!=source.text:continue
            reason='可复用；另一遍读音仍需试听。';allowed=True
            try:prepare(source,target,True,self.project.checks.get(target.id,{}).get('reading',False))
            except ValueError as error:reason=str(error);allowed=False
            row=self.table.rowCount();self.table.insertRow(row);self.targets.append(target)
            check=QTableWidgetItem();check.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable if allowed else Qt.ItemFlag.NoItemFlags)
            check.setCheckState(Qt.CheckState.Checked if allowed and (not eligible_current or index==self.current) else Qt.CheckState.Unchecked);self.table.setItem(row,0,check)
            for col,text in [(1,f'第 {index+1} 句 · '+target.text),(2,f'{stamp(target.start)}—{stamp(target.end)}'),(3,(target.kana or ''.join(u.kana for u in target.units))+'\n'+reason)]:
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);item.setToolTip(text);self.table.setItem(row,col,item)
            self.table.setRowHeight(row,66)
        self.table.blockSignals(False)
        if self.targets:self.table.setCurrentCell(0,1)
        self.selection_changed()

    def selected_ids(self):return [line.id for i,line in enumerate(self.targets) if self.table.item(i,0).flags()&Qt.ItemFlag.ItemIsUserCheckable and self.table.item(i,0).checkState()==Qt.CheckState.Checked]
    def options(self):return {'align':self.voice.isChecked(),'fit_range':self.fit.isChecked(),'audio_role':self.audio.currentData()}
    def selection_changed(self,*args):
        count=len(self.selected_ids());self.apply.setEnabled(count>0);self.apply.setText(f'生成 {count} 句复用候选' if count else '先选择可处理的目标句')
        self.audio.setEnabled(self.voice.isChecked());self.fit.setEnabled(self.voice.isChecked());self.target_listen.setEnabled(bool(self.targets) and Path(self.project.media).is_file())
        self.count.setText(f'将处理 {count} 句，先审核再采用。'+('会按目标实际声音重算，不复制来源节奏；失败保留读音候选和手工入口。TIFA 模型限个人非商业用途。' if self.voice.isChecked() else '仅生成分词读音候选，音节时间仍为本句范围内的估算，尚未按声音校准。'))
    def listen_source(self):
        line=self.sources.get(self.source.currentData())
        if line:self.playback.audition(line.start,line.end)
    def listen_target(self):
        row=self.table.currentRow()
        if row>=0:self.playback.audition(self.targets[row].start,self.targets[row].end)
    def open_manual(self):
        row=self.table.currentRow()
        if row>=0:self.manual_uid=self.targets[row].id;self.reject()
