"""Scope selection and per-gap decisions with explicit manual overrides."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
    QCheckBox,QSpinBox,QPushButton,QDialogButtonBox,QTableWidget,QTableWidgetItem,QHeaderView,QPlainTextEdit,QScrollArea,QWidget,QFrame)
from studio_backend.sound_gaps import signature
from .time_transform import scope_indices
from .widgets import time_text


class SoundGapOptions(QDialog):
    def __init__(self,project,current,selected,role,parent=None):
        super().__init__(parent);self.setWindowTitle('按声音检查空白');self.prepare_vocals=False
        area=QApplication.primaryScreen().availableGeometry();self.resize(min(650,area.width()-50),min(500,area.height()-50))
        self.project=project;self.current=current;self.selected=selected
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);body=QWidget();layout=QVBoxLayout(body);layout.setAlignment(Qt.AlignmentFlag.AlignTop);scroll.setWidget(body);body.setAutoFillBackground(False);outer.addWidget(scroll,1)
        note=QLabel('先分析间隔中的声音与可用音素依据，再逐项试听采用。不会只因空隙较短就填平；下一音节起点、人工时间和已确认歌词保持。');note.setWordWrap(True);layout.addWidget(note)
        self.scope=QComboBox()
        for title,key in [('这一句','current'),('选中多句','selected'),('从这里到结尾','following'),('整首','all')]:self.scope.addItem(title,key)
        self.scope.model().item(1).setEnabled(bool(selected));layout.addWidget(self.scope)
        self.count=QLabel();layout.addWidget(self.count);self.scope.currentIndexChanged.connect(self.describe)
        self.join=QCheckBox('同时检查范围内相邻两句之间的间隔');self.join.setChecked(True);layout.addWidget(self.join)
        row=QHBoxLayout();row.addWidget(QLabel('最多分析的间隔长度'))
        self.maximum=QSpinBox();self.maximum.setRange(10,5000);self.maximum.setValue(2000);self.maximum.setSuffix(' ms');row.addWidget(self.maximum);layout.addLayout(row)
        audio=QLabel('当前分析／试听音轨：'+('人声辅助' if role=='vocals' else '视频原声。伴奏持续不能证明歌声连续，缺少音素依据时会保留待听。'));audio.setWordWrap(True);layout.addWidget(audio)
        if role!='vocals':
            vocals=QPushButton('先准备人声辅助，再检查这个范围');vocals.clicked.connect(self.vocals);layout.addWidget(vocals)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('按当前音轨检查');controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);outer.addWidget(controls);self.describe()

    def describe(self,*args):
        self.count.setText(f'本次检查 {len(self.indices())} 句；分析完成后先审核，不自动写入时间轴。')

    def indices(self):return scope_indices(self.project,self.scope.currentData(),self.current,self.selected)
    def options(self):return {'indices':self.indices(),'maximum':self.maximum.value(),'join_lines':self.join.isChecked()}
    def vocals(self):self.prepare_vocals=True;self.accept()


class SoundGapDialog(QDialog):
    def __init__(self,project,report,playback,audition=None,parent=None):
        super().__init__(parent);self.setWindowTitle('声音空隙 · 试听与处理');self.report=report;self.playback=playback;self.audition=audition;self.selected=[];self.manual=[];self.recheck=False;self.calibrate=None
        area=QApplication.primaryScreen().availableGeometry();self.resize(min(1080,area.width()-50),min(740,area.height()-50))
        self.stale=signature(project.lines)!=report['signature'];self.controls=[]
        layout=QVBoxLayout(self)
        self.note=QLabel('歌词或时间已改变：旧结果只供对照，请重新检查。' if self.stale else '低能量区间和不明确间隔默认保留。声音连续候选只延续高亮，不确认读音或逐音起点。原文、假名与下一起音保持。');self.note.setWordWrap(True);layout.addWidget(self.note)
        if project.source_ass_active:self.note.setText(self.note.text()+' 采用后使用声稿样式，原 ASS 保留，可撤销。')
        self.filter=QComboBox()
        for title,key in [('全部间隔','all'),('建议延续','continuous'),('低能量／待听','keep'),('已保护','protected')]:self.filter.addItem(title,key)
        layout.addWidget(self.filter)
        self.table=QTableWidget(len(report['gaps']),4);self.table.setHorizontalHeaderLabels(['位置与时间','两侧音节','声音提示','本次决定']);self.table.setWordWrap(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(65)
        names={'continuous':'建议延续后试听','quiet':'低能量，保留待听','uncertain':'声音不明确，保留','unavailable':'依据不足，保留','protected':'边界已保护'}
        for row,gap in enumerate(report['gaps']):
            texts=[f'第 {gap["left"][0]+1} 句 · {gap["end"]-gap["start"]} ms\n{time_text(gap["start"])}\n{time_text(gap["end"])}',gap['left_text']+' → '+gap['right_text'],names[gap['status']],'']
            for col,text in enumerate(texts):
                if col==3:continue
                item=QTableWidgetItem(text);item.setToolTip(text);self.table.setItem(row,col,item)
            choice=QComboBox();choice.addItem('保留','keep')
            if not gap['protected']:
                if gap['status']=='continuous':choice.addItem('声音延续','continuous');choice.setCurrentIndex(1)
                choice.addItem('人工延续','manual')
            choice.setToolTip('声音延续采用本次候选；人工延续由你试听决定并记录为人工时间。保留不改动边界。')
            choice.setEnabled(not self.stale and not gap['protected']);choice.currentIndexChanged.connect(self.update_apply);self.controls.append(choice)
            cell=QWidget();box=QHBoxLayout(cell);box.setContentsMargins(3,3,3,3);box.addWidget(choice,1,Qt.AlignmentFlag.AlignVCenter);self.table.setCellWidget(row,3,cell)
            self.table.setRowHeight(row,max(58,self.table.fontMetrics().height()*3+10))
        layout.addWidget(self.table,1)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(130);layout.addWidget(self.details)
        row=QHBoxLayout();self.listen_button=QPushButton('试听所选（带前后音）');self.listen_button.clicked.connect(self.listen);row.addWidget(self.listen_button);stop=QPushButton('停止');stop.clicked.connect(playback.stop);row.addWidget(stop)
        redo=QPushButton('重新检查');redo.clicked.connect(self.again);row.addWidget(redo);layout.addLayout(row)
        self.calibrate_button=QPushButton('去这处校准');self.calibrate_button.clicked.connect(self.handoff);row.addWidget(self.calibrate_button)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Close);self.apply_button=buttons.button(QDialogButtonBox.StandardButton.Apply);self.apply_button.setText('采用所选处理');self.apply_button.clicked.connect(self.choose);buttons.button(QDialogButtonBox.StandardButton.Close).setText('稍后处理');buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.table.currentCellChanged.connect(self.explain);self.filter.currentIndexChanged.connect(self.apply_filter);self.finished.connect(lambda _:playback.stop())
        self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.update_apply);self.timer.start()
        self.finished.connect(self.timer.stop)
        if report['gaps']:self.table.setCurrentCell(0,0)
        self.update_apply()

    def update_apply(self,*args):
        if not hasattr(self,'apply_button'):return
        count=sum(c.currentData()!='keep' for c in self.controls)
        parent=self.parent();busy=bool(parent and (getattr(parent,'source_job',None) or getattr(parent,'local_job',None) or getattr(getattr(parent,'api',None),'busy',False)))
        self.apply_button.setEnabled(bool(count) and not self.stale and not busy)
        hidden=sum(c.currentData()!='keep' and self.table.isRowHidden(i) for i,c in enumerate(self.controls))
        self.summary.setText((f'将处理 {count} 处'+(f'（含筛选外 {hidden} 处）' if hidden else '')+'；未选择的间隔保持，可一步撤销。') if count else '当前均保留。可以逐项试听后决定，或稍后继续。')

    def apply_filter(self,*args):
        key=self.filter.currentData()
        for i,value in enumerate(self.report['gaps']):
            show=key=='all' or key==value['status'] or key=='keep' and value['status'] in {'quiet','uncertain','unavailable'}
            self.table.setRowHidden(i,not show)
        visible=[i for i in range(self.table.rowCount()) if not self.table.isRowHidden(i)]
        self.table.setCurrentCell(visible[0],0) if visible else self.table.setCurrentCell(-1,-1)
        self.explain();self.update_apply()

    def explain(self,*args):
        i=self.table.currentRow()
        self.listen_button.setEnabled(i>=0 and not self.table.isRowHidden(i))
        self.calibrate_button.setEnabled(i>=0 and not self.table.isRowHidden(i))
        if i<0:self.details.setPlainText('当前筛选没有对应间隔。');return
        value=self.report['gaps'][i];metrics=value['metrics'];role='人声辅助' if self.report['binding']['audio_role']=='vocals' else '原声'
        text=[value['reason'],'分析音轨：'+role,'下一音节起点不移动。'+(' '+value['anchor']+'，只作固定参照。' if value.get('anchor') else '')]
        if metrics.get('available'):text.append(f'低能量连续范围约 {metrics["quiet_ms"]:.0f} ms。此数值用于试听检查，不是休止识别准确率。')
        if value.get('phoneme'):text.append('已有歌声音素区间覆盖这个空隙，且素材／音轨指纹对应。')
        text.append('声音候选采用后仍需校准；人工决定会单独记录并保护。')
        self.details.setPlainText('\n'.join(text))

    def listen(self):
        row=self.table.currentRow()
        if row<0:return
        value=self.report['gaps'][row];a=max(0,value['start']-250);b=value['end']+250
        if self.audition:self.audition(a,b)
        else:self.playback.audition(a,b)

    def choose(self):
        if self.stale or not self.apply_button.isEnabled():return
        self.selected=[v['key'] for v,c in zip(self.report['gaps'],self.controls) if c.currentData()!='keep']
        self.manual=[v['key'] for v,c in zip(self.report['gaps'],self.controls) if c.currentData()=='manual'];self.accept()

    def again(self):self.recheck=True;self.reject()

    def handoff(self):
        i=self.table.currentRow()
        if i>=0:self.calibrate=self.report['gaps'][i];self.reject()
