"""Line-tail scope and per-line decisions; the current end is always the default."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,
    QDialogButtonBox,QTableWidget,QTableWidgetItem,QHeaderView,QPlainTextEdit,QScrollArea,QWidget,QFrame)
from studio_backend.line_tails import TYPES,stale_rows
from .time_transform import scope_indices
from .widgets import time_text

STATUS={'flagged':'有疑点，请试听','ok':'未见明显问题','unavailable':'声音依据不足','protected':'句尾已保护'}


class LineTailOptions(QDialog):
    def __init__(self,project,current,selected,role,parent=None):
        super().__init__(parent);self.setWindowTitle('检查句尾');self.prepare_vocals=False
        area=QApplication.primaryScreen().availableGeometry();self.resize(min(620,area.width()-50),min(440,area.height()-50))
        self.project=project;self.current=current;self.selected=selected
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);body=QWidget();layout=QVBoxLayout(body);layout.setAlignment(Qt.AlignmentFlag.AlignTop);scroll.setWidget(body);outer.addWidget(scroll,1)
        note=QLabel('逐句看最后一个音节的收尾：截短、拖进静音、顶到范围末端、同一句歌词收法不一致会列为疑点，并给出“声音降落／音高结束／下一句开口前”几个参考位置。默认保持当前句尾，不自动选择；人工、锁定和已确认的句尾不动。')
        note.setWordWrap(True);layout.addWidget(note)
        self.scope=QComboBox()
        for title,key in [('这一句','current'),('选中多句','selected'),('从这里到结尾','following'),('整首','all')]:self.scope.addItem(title,key)
        self.scope.model().item(1).setEnabled(bool(selected));layout.addWidget(self.scope)
        self.count=QLabel();layout.addWidget(self.count);self.scope.currentIndexChanged.connect(self.describe)
        audio=QLabel('当前分析／试听音轨：'+('人声辅助' if role=='vocals' else '视频原声。伴奏会掩盖收尾，不会据此判断“高亮后仍有歌声”。'));audio.setWordWrap(True);layout.addWidget(audio)
        if role!='vocals':
            vocals=QPushButton('先准备人声辅助，再检查这个范围');vocals.clicked.connect(self.vocals);layout.addWidget(vocals)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('按当前音轨检查');controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);outer.addWidget(controls);self.describe()

    def describe(self,*args):self.count.setText(f'本次检查 {len(self.indices())} 句；只在本机分析，完成后先审核，不自动写入时间轴。')
    def indices(self):return scope_indices(self.project,self.scope.currentData(),self.current,self.selected)
    def options(self):return {'indices':self.indices()}
    def vocals(self):self.prepare_vocals=True;self.accept()


class LineTailDialog(QDialog):
    def __init__(self,project,report,playback,audition=None,parent=None):
        super().__init__(parent);self.setWindowTitle('句尾检查 · 试听与选择');self.report=report;self.playback=playback;self.audition=audition
        self.choices={};self.recheck=False;self.calibrate=None;self.controls=[]
        area=QApplication.primaryScreen().availableGeometry();self.resize(min(1080,area.width()-50),min(740,area.height()-50))
        self.changed=stale_rows(project.lines,report);self.stale=bool(report['tails']) and len(self.changed)==len(report['tails'])
        layout=QVBoxLayout(self)
        note='歌词或时间已改变：旧结果只供对照，请重新检查。' if self.stale else report['notice']+' 起点、原文和假名不变。'
        if self.changed and not self.stale:note+=f' 其中 {len(self.changed)} 句在检查后已修改，只供对照。'
        self.note=QLabel(note)
        self.note.setWordWrap(True);layout.addWidget(self.note)
        if project.source_ass_active:self.note.setText(self.note.text()+' 采用后使用声稿样式，原 ASS 保留，可撤销。')
        self.filter=QComboBox()
        for title,key in [('全部句尾','all'),('有疑点','flagged'),('未见明显问题','ok'),('已保护／依据不足','other')]:self.filter.addItem(title,key)
        layout.addWidget(self.filter)
        tails=report['tails'];self.table=QTableWidget(len(tails),4);self.table.setHorizontalHeaderLabels(['位置与时间','句尾音节 · 类型','疑点／提示','本次决定']);self.table.setWordWrap(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.table.horizontalHeader().setMinimumSectionSize(65)
        for row,tail in enumerate(tails):
            kind=TYPES.get(tail.get('type'),'—')
            changed=tail['key'] in self.changed
            texts=[f'第 {tail["row"]+1} 句 · 收尾 {time_text(tail["end"])}'+('（已修改）' if changed else '')+f'\n音节 {tail["end"]-tail["start"]} ms',f'{tail["text"]} · {kind}\n{tail["line_text"]}',STATUS[tail['status']]+('\n'+tail['flags'][0]['message'] if tail.get('flags') else '')]
            for col,text in enumerate(texts):
                item=QTableWidgetItem(text);item.setToolTip(text);self.table.setItem(row,col,item)
            choice=QComboBox();choice.addItem('保持当前句尾','keep')
            for option in tail.get('candidates',[]):
                mark='（优先试听）' if option['name']==tail.get('recommended') else ''
                choice.addItem(f'{option["label"]} {time_text(option["end"])}（{option["delta"]:+d} ms）{mark}',option['name'])
            choice.setToolTip('默认保持当前句尾。候选只是声音参考位置，试听后自行决定；“优先试听”只表示与疑点方向一致，不代表更准。')
            choice.setEnabled(not changed and not tail['protected'] and bool(tail.get('candidates')))
            choice.currentIndexChanged.connect(self.update_apply);self.controls.append(choice)
            cell=QWidget();box=QHBoxLayout(cell);box.setContentsMargins(3,3,3,3);box.addWidget(choice,1,Qt.AlignmentFlag.AlignVCenter);self.table.setCellWidget(row,3,cell)
            self.table.setRowHeight(row,max(58,self.table.fontMetrics().height()*3+10))
        layout.addWidget(self.table,1)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(150);layout.addWidget(self.details)
        row=QHBoxLayout()
        self.listen_button=QPushButton('试听句尾（带前后音）');self.listen_button.clicked.connect(self.listen);row.addWidget(self.listen_button)
        self.listen_choice=QPushButton('试听到所选收尾');self.listen_choice.setToolTip('从句尾前一点播放到所选位置后停止，听收尾是否被截断或拖进静音。');self.listen_choice.clicked.connect(self.listen_to_choice);row.addWidget(self.listen_choice)
        stop=QPushButton('停止');stop.clicked.connect(playback.stop);row.addWidget(stop)
        redo=QPushButton('重新检查');redo.clicked.connect(self.again);row.addWidget(redo)
        self.calibrate_button=QPushButton('去这处校准');self.calibrate_button.clicked.connect(self.handoff);row.addWidget(self.calibrate_button);layout.addLayout(row)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Close);self.apply_button=buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText('采用所选句尾');self.apply_button.clicked.connect(self.choose);buttons.button(QDialogButtonBox.StandardButton.Close).setText('稍后处理');buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.table.currentCellChanged.connect(self.explain);self.filter.currentIndexChanged.connect(self.apply_filter);self.finished.connect(lambda _:playback.stop())
        self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.update_apply);self.timer.start();self.finished.connect(self.timer.stop)
        if tails:self.table.setCurrentCell(0,0)
        self.update_apply()

    def update_apply(self,*args):
        if not hasattr(self,'apply_button'):return
        count=sum(c.currentData()!='keep' for c in self.controls)
        parent=self.parent();busy=bool(parent and (getattr(parent,'source_job',None) or getattr(parent,'local_job',None) or getattr(getattr(parent,'api',None),'busy',False)))
        self.apply_button.setEnabled(bool(count) and not self.stale and not busy)
        hidden=sum(c.currentData()!='keep' and self.table.isRowHidden(i) for i,c in enumerate(self.controls))
        flagged=sum(v['status']=='flagged' for v in self.report['tails'])
        self.summary.setText((f'将调整 {count} 句的句尾'+(f'（含筛选外 {hidden} 句）' if hidden else '')+'；其余保持，可一步撤销。') if count else f'当前全部保持。{flagged} 句有疑点，可逐句试听后决定，或稍后继续。')

    def apply_filter(self,*args):
        key=self.filter.currentData()
        for i,value in enumerate(self.report['tails']):
            show=key=='all' or key==value['status'] or key=='other' and value['status'] in {'protected','unavailable'}
            self.table.setRowHidden(i,not show)
        visible=[i for i in range(self.table.rowCount()) if not self.table.isRowHidden(i)]
        self.table.setCurrentCell(visible[0],0) if visible else self.table.setCurrentCell(-1,-1)
        self.explain();self.update_apply()

    def explain(self,*args):
        i=self.table.currentRow();active=i>=0 and not self.table.isRowHidden(i)
        for button in (self.listen_button,self.listen_choice,self.calibrate_button):button.setEnabled(active)
        if not active:self.details.setPlainText('当前筛选没有对应句尾。');return
        value=self.report['tails'][i];metrics=value.get('metrics',{});role='人声辅助' if self.report['binding']['audio_role']=='vocals' else '原声'
        text=[value['reason']]
        if value.get('rule'):text.append('收尾方式：'+value['rule'])
        for flag in value.get('flags',[])[1:]:text.append('另：'+flag['message'])
        text.append(f'分析音轨：{role}。当前句尾 {time_text(value["end"])}；最多可延到 {time_text(value["limit"])}'+(f'；下一句开口 {time_text(value["next_start"])}' if value.get('next_start') is not None else '')+'。')
        if value.get('release_span'):text.append(f'歌声模型判断的余韵：{time_text(value["release_span"][0])}–{time_text(value["release_span"][1])}，未算进高亮。')
        for option in value.get('candidates',[]):text.append(f'候选 · {option["label"]}：{time_text(option["end"])}（{option["delta"]:+d} ms）'+('，与疑点方向一致，可优先试听' if option['name']==value.get('recommended') else ''))
        if metrics.get('available'):text.append(f'声音参考：有音高的比例 {metrics["voiced_fraction"]:.0%}，句尾音量走向 {metrics["slope_db_per_100ms"]:+.1f} dB/100 ms。')
        text.append('采用后句尾时间记为按声音调整，仍需试听确认；起点不动。')
        self.details.setPlainText('\n'.join(text))

    def play(self,a,b):
        a=max(0,a)
        if self.audition:self.audition(a,b)
        else:self.playback.audition(a,b)

    def listen(self):
        i=self.table.currentRow()
        if i<0:return
        value=self.report['tails'][i];ends=[value['end'],*(c['end'] for c in value.get('candidates',[]))]
        self.play(value['start']-400,min(value['limit'],max(ends))+400)

    def listen_to_choice(self):
        i=self.table.currentRow()
        if i<0:return
        value=self.report['tails'][i];name=self.controls[i].currentData()
        end=next((c['end'] for c in value.get('candidates',[]) if c['name']==name),value['end'])
        self.play(value['start']-600,end)

    def choose(self):
        if self.stale or not self.apply_button.isEnabled():return
        self.choices={v['key']:c.currentData() for v,c in zip(self.report['tails'],self.controls) if c.currentData()!='keep'};self.accept()

    def again(self):self.recheck=True;self.reject()

    def handoff(self):
        i=self.table.currentRow()
        if i>=0:self.calibrate=self.report['tails'][i];self.reject()
