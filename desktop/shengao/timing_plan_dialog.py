"""Choose sources, then compare timing plans syllable by syllable; keeping the current time is the default."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QCheckBox,
    QDialogButtonBox,QTableWidget,QTableWidgetItem,QHeaderView,QPlainTextEdit,QScrollArea,QWidget,QFrame,QSplitter)
from studio_backend.timing_plans import KINDS,STATUS,DIFF_MS,stale_rows,overlaps
from .time_transform import scope_indices
from .timing_plan_sources import SOURCES
from .widgets import time_text

HINTS={'scribe':'用已保存的 Scribe 转录在本机重新匹配，看转录认为这句从哪里唱。',
       'alignment':'本工程初稿流程里已完成的文字对齐结果；只读取，不再请求。',
       'local_original':'内置歌声模型按视频原声对齐；伴奏响时可能偏。',
       'local_vocals':'内置歌声模型按人声辅助音轨对齐；通常更少受伴奏影响。',
       'reading':'只对有分歧的句子，把某个词换成其他读音再让本机模型对齐；采用会同时改变读音。',
       'chorus':'读音和时间都已人工确认的相同歌词，把它的音节节奏放到本句的位置作参考。'}


class TimingPlanOptions(QDialog):
    def __init__(self,project,current,selected,notes,parent=None):
        super().__init__(parent);self.setWindowTitle('多方案比对时间')
        area=QApplication.primaryScreen().availableGeometry();self.resize(min(660,area.width()-50),min(560,area.height()-50))
        self.project=project;self.current=current;self.selected=selected;self.boxes={}
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);body=QWidget();layout=QVBoxLayout(body);layout.setAlignment(Qt.AlignmentFlag.AlignTop);scroll.setWidget(body);outer.addWidget(scroll,1)
        note=QLabel('把同一句的几种时间来源并排比较：各来源差得多、或位置匹配不确定的句子会单独列出，标明哪些音节不一致，可分别试听。'
                    '默认保持当前时间，不自动选择；锁定、已确认和人工调整的句子只列出，不改动。全部在本机完成，没有联网或付费请求。')
        note.setWordWrap(True);layout.addWidget(note)
        self.scope=QComboBox()
        for title,key in [('这一句','current'),('选中多句','selected'),('从这里到结尾','following'),('整首','all')]:self.scope.addItem(title,key)
        self.scope.model().item(1).setEnabled(bool(selected));layout.addWidget(self.scope)
        heading=QLabel('参与比较的来源：');layout.addWidget(heading)
        for kind in SOURCES:
            reason=notes.get(kind,'');box=QCheckBox(KINDS[kind]+(f'（不可用：{reason}）' if reason else ''))
            box.setToolTip(HINTS[kind]+(f'\n现在不可用：{reason}' if reason else ''));box.setEnabled(not reason);box.setChecked(not reason)
            box.toggled.connect(self.describe);self.boxes[kind]=box;layout.addWidget(box)
        self.count=QLabel();self.count.setWordWrap(True);layout.addWidget(self.count);self.scope.currentIndexChanged.connect(self.describe)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.ok=controls.button(QDialogButtonBox.StandardButton.Ok);self.ok.setText('开始比对');controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);outer.addWidget(controls);self.describe()

    def sources(self):return [kind for kind,box in self.boxes.items() if box.isEnabled() and box.isChecked()]
    def indices(self):return scope_indices(self.project,self.scope.currentData(),self.current,self.selected)

    def describe(self,*args):
        chosen=self.sources();local=sum(k in chosen for k in ('local_original','local_vocals','reading'))
        text=f'本次比对 {len(self.indices())} 句，{len(chosen)} 种来源；完成后先审核，不写入时间轴。'
        if local:text+='本机模型要逐句分析，句子多时需要几分钟，可随时取消。'
        if not chosen:text='请至少选择一种来源。'
        self.count.setText(text);self.ok.setEnabled(bool(chosen and self.indices()))

    def options(self):return {'indices':self.indices(),'sources':self.sources()}


class TimingPlanDialog(QDialog):
    def __init__(self,project,report,playback,audition=None,parent=None):
        super().__init__(parent);self.setWindowTitle('多方案比对 · 试听与选择');self.project=project;self.report=report;self.playback=playback;self.audition=audition
        self.choices={};self.recheck=False;self.calibrate=None;self.controls=[];self.columns=[]
        area=QApplication.primaryScreen().availableGeometry();self.resize(min(1180,area.width()-50),min(800,area.height()-50))
        entries=report['lines'];self.changed=stale_rows(project.lines,report);self.stale=bool(entries) and len(self.changed)==len(entries)
        layout=QVBoxLayout(self)
        note='歌词或时间已改变：旧结果只供对照，请重新比对。' if self.stale else report['notice']
        if self.changed and not self.stale:note+=f' 其中 {len(self.changed)} 句在比对后已修改，只供对照。'
        missing=[f'{v["label"]}：{v["note"]}' for k,v in report['sources'].items() if not v['available'] and v['note']!='本次未选择。']
        if missing:note+='\n未参与：'+'；'.join(missing)
        if project.source_ass_active:note+=' 采用后使用声稿样式，原 ASS 保留，可撤销。'
        self.note=QLabel(note);self.note.setWordWrap(True);layout.addWidget(self.note)
        self.filter=QComboBox()
        for title,key in [('需要比较（分歧／不确定）','attention'),('全部句子','all'),('来源一致','agree'),('只有当前时间／已保护','other')]:self.filter.addItem(title,key)
        layout.addWidget(self.filter)
        split=QSplitter(Qt.Orientation.Vertical);layout.addWidget(split,1)
        self.table=QTableWidget(len(entries),4);self.table.setHorizontalHeaderLabels(['位置','歌词','来源一致程度','本次决定']);self.table.setWordWrap(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.table.horizontalHeader().setMinimumSectionSize(65)
        for row,entry in enumerate(entries):
            changed=entry['line_id'] in self.changed
            status=STATUS[entry['status']]+('' if entry['status'] in {'protected','single'} else f' · 最大相差 {entry["spread"]} ms')
            texts=[f'第 {entry["row"]+1} 句'+('（已修改）' if changed else '')+f'\n{time_text(entry["start"])}–{time_text(entry["end"])}',entry['text'],
                   status+(f'\n差异：{"、".join(d["text"] for d in entry["differing"][:6])}' if entry['differing'] else '')]
            for col,text in enumerate(texts):
                item=QTableWidgetItem(text);item.setToolTip(text);self.table.setItem(row,col,item)
            choice=QComboBox();choice.addItem('保持当前时间','current')
            for plan in entry['plans']:
                if plan['kind']=='current' or plan['same']:continue
                delta=plan['start']-entry['start']
                choice.addItem(f'{plan["label"]} · {time_text(plan["start"])}（{delta:+d} ms）'+('，改读音' if plan['changes_reading'] else ''),plan['id'])
            choice.setToolTip('默认保持当前时间。没有哪种来源总是更准；请先试听各方案再决定。')
            choice.setEnabled(not changed and not entry['protected'] and choice.count()>1)
            choice.currentIndexChanged.connect(self.choice_changed);self.controls.append(choice)
            cell=QWidget();box=QHBoxLayout(cell);box.setContentsMargins(3,3,3,3);box.addWidget(choice,1,Qt.AlignmentFlag.AlignVCenter);self.table.setCellWidget(row,3,cell)
            self.table.setRowHeight(row,max(58,self.table.fontMetrics().height()*3+10))
        split.addWidget(self.table)
        lower=QWidget();box=QVBoxLayout(lower);box.setContentsMargins(0,0,0,0)
        caption=QLabel(f'逐音节起点（最后一行是句尾）：点一格选中该方案和音节去试听。△ 表示比多数方案差 {DIFF_MS} ms 以上；“—”表示该方案音节划分不同，只比较到词或整句。')
        caption.setWordWrap(True);box.addWidget(caption)
        self.grid=QTableWidget(0,0);self.grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.grid.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.grid.horizontalHeader().setMinimumSectionSize(80);box.addWidget(self.grid,1)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(150);box.addWidget(self.details)
        split.addWidget(lower);split.setSizes([360,360])
        row=QHBoxLayout()
        self.listen_button=QPushButton('试听此方案整句');self.listen_button.setToolTip('按表格里选中的那一列方案，从句首前一点播放到句尾后一点。');self.listen_button.clicked.connect(self.listen_plan);row.addWidget(self.listen_button)
        self.listen_part=QPushButton('试听所选音节（按此方案）');self.listen_part.setToolTip('按选中列的方案时间，只播放选中这一个音节（前后各带一点）。');self.listen_part.clicked.connect(self.listen_syllable);row.addWidget(self.listen_part)
        stop=QPushButton('停止');stop.setToolTip('停止试听。');stop.clicked.connect(playback.stop);row.addWidget(stop)
        redo=QPushButton('重新比对');redo.setToolTip('关闭本结果（任务记录保留），重新选择范围和来源再比对。');redo.clicked.connect(self.again);row.addWidget(redo)
        self.calibrate_button=QPushButton('去这处校准');self.calibrate_button.setToolTip('不采用任何方案，直接到时间轴手工校准这句的所选音节。');self.calibrate_button.clicked.connect(self.handoff);row.addWidget(self.calibrate_button);layout.addLayout(row)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Close);self.apply_button=buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText('采用所选方案');self.apply_button.setToolTip('只改选了方案的句子，作为一步可撤销的修改；时间仍需确认。')
        self.apply_button.clicked.connect(self.choose);close=buttons.button(QDialogButtonBox.StandardButton.Close);close.setText('稍后处理');close.setToolTip('先不采用；结果保留在待审任务里。');buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.table.currentCellChanged.connect(self.show_line);self.grid.currentCellChanged.connect(self.explain);self.filter.currentIndexChanged.connect(self.apply_filter);self.finished.connect(lambda _:playback.stop())
        self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.update_apply);self.timer.start();self.finished.connect(self.timer.stop)
        self.apply_filter()

    def entry(self):
        i=self.table.currentRow()
        return self.report['lines'][i] if i>=0 and not self.table.isRowHidden(i) else None

    def plan(self):
        entry=self.entry();col=self.grid.currentColumn()
        if entry is None:return None
        if 0<=col<len(self.columns):return self.columns[col]
        return entry['plans'][0]

    def update_apply(self,*args):
        if not hasattr(self,'apply_button'):return
        count=sum(c.currentData()!='current' for c in self.controls)
        parent=self.parent();busy=bool(parent and (getattr(parent,'source_job',None) or getattr(parent,'local_job',None) or getattr(getattr(parent,'api',None),'busy',False)))
        self.apply_button.setEnabled(bool(count) and not self.stale and not busy)
        hidden=sum(c.currentData()!='current' and self.table.isRowHidden(i) for i,c in enumerate(self.controls))
        attention=sum(v['status'] in {'conflict','uncertain'} for v in self.report['lines'])
        reading=sum(c.currentData()!='current' and next((p for p in v['plans'] if p['id']==c.currentData()),{}).get('changes_reading',False) for v,c in zip(self.report['lines'],self.controls))
        self.summary.setText((f'将改用所选方案的有 {count} 句'+(f'（含筛选外 {hidden} 句）' if hidden else '')+(f'，其中 {reading} 句会同时改读音' if reading else '')+'；其余保持，可一步撤销。') if count
                             else f'当前全部保持。{attention} 句来源分歧或匹配不确定，可逐句试听后决定，或稍后继续。')

    def apply_filter(self,*args):
        key=self.filter.currentData()
        for i,value in enumerate(self.report['lines']):
            show=key=='all' or key=='attention' and value['status'] in {'conflict','uncertain'} or key==value['status'] or key=='other' and value['status'] in {'protected','single'}
            self.table.setRowHidden(i,not show)
        visible=[i for i in range(self.table.rowCount()) if not self.table.isRowHidden(i)]
        if visible:self.table.setCurrentCell(visible[0],0)
        else:self.table.setCurrentCell(-1,-1)
        self.show_line();self.update_apply()

    def choice_changed(self,*args):
        self.show_line();self.update_apply()

    def show_line(self,*args):
        entry=self.entry();self.grid.blockSignals(True);self.grid.clear()
        if entry is None:
            self.columns=[];self.grid.setRowCount(0);self.grid.setColumnCount(0);self.grid.blockSignals(False)
            for button in (self.listen_button,self.listen_part,self.calibrate_button):button.setEnabled(False)
            self.details.setPlainText('当前筛选没有对应句子。');return
        self.columns=list(entry['plans']);rows=[*entry['grid'],entry['tail']]
        self.grid.setColumnCount(len(self.columns));self.grid.setRowCount(len(rows))
        self.grid.setHorizontalHeaderLabels([p['label'] for p in self.columns]);self.grid.setVerticalHeaderLabels([r['text'] for r in rows])
        bold=QFont();bold.setBold(True)
        for r,value in enumerate(rows):
            for c,plan in enumerate(self.columns):
                v=value['values'].get(plan['id']);odd=plan['id'] in value['outliers']
                item=QTableWidgetItem('—' if v is None else ('△ ' if odd else '')+time_text(v));item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if odd:item.setFont(bold);item.setToolTip(f'比多数方案（{time_text(value["median"])}）差 {v-value["median"]:+d} ms')
                self.grid.setItem(r,c,item)
        pick=self.controls[self.report['lines'].index(entry)].currentData();col=next((c for c,p in enumerate(self.columns) if p['id']==pick),0)
        self.grid.setCurrentCell(0,col);self.grid.blockSignals(False)
        self.listen_button.setEnabled(True);self.listen_part.setEnabled(bool(rows));self.calibrate_button.setEnabled(True)
        self.explain()

    def explain(self,*args):
        entry=self.entry();plan=self.plan()
        if entry is None or plan is None:return
        text=[entry['reason']]
        for item in entry['plans']:
            gap='' if item['deviation'] is None else f'（平均偏离多数 {item["deviation"]} ms）'
            text.append(f'· {item["label"]}{gap}：'+('与当前时间相同。' if item['same'] and item['kind']!='current' else item['note']))
        for item in entry['unavailable']:text.append(f'· {item["label"]} 不可用：{item["reason"]}')
        if plan['kind']!='current':
            near=overlaps(self.project.lines,entry,plan)
            if near:text.append('注意：此方案会与'+'、'.join(f'第 {n+1} 句' for n in near)+'重叠；相邻句已保护时不能采用。')
            if plan['changes_reading']:text.append('此方案改变读音：'+plan['reading']+'；采用后读音也需要确认。')
        text.append('采用后时间记为“多方案比对选用”，本句时间改为未确认；原文、译文不变。')
        self.details.setPlainText('\n'.join(text))

    def play(self,a,b):
        a=max(0,a)
        if self.audition:self.audition(a,b)
        else:self.playback.audition(a,b)

    def listen_plan(self):
        plan=self.plan()
        if plan is not None:self.play(plan['start']-300,plan['end']+300)

    def listen_syllable(self):
        entry=self.entry();plan=self.plan();r=self.grid.currentRow()
        if entry is None or plan is None or r<0:return
        rows=[*entry['grid'],entry['tail']];value=rows[r]['values'].get(plan['id'],rows[r]['median'])
        if value is None:value=plan['start']
        if r==len(rows)-1:self.play(value-600,value+300);return
        later=[v['values'][plan['id']] for v in rows[r+1:] if plan['id'] in v['values']]
        end=later[0] if later else plan['end']
        self.play(value-150,max(end,value+80)+150)

    def choose(self):
        if self.stale or not self.apply_button.isEnabled():return
        self.choices={v['line_id']:c.currentData() for v,c in zip(self.report['lines'],self.controls) if c.currentData()!='current'};self.accept()

    def again(self):self.recheck=True;self.reject()

    def handoff(self):
        entry=self.entry()
        if entry is None:return
        r=max(0,self.grid.currentRow());rows=entry['grid']
        target=rows[r] if r<len(rows) else (rows[-1] if rows else {'word':None,'part':None})
        self.calibrate={'line_id':entry['line_id'],'word':target['word'],'part':target['part'],'tail':r>=len(rows)};self.reject()
