"""Human edge positions are a saved draft until a reviewed result is adopted."""
import copy
from PySide6.QtCore import Qt,QSignalBlocker,QPointF
from PySide6.QtGui import QPainter,QPen,QColor
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,
    QTableWidget,QTableWidgetItem,QHeaderView,QScrollArea,QWidget,QDialogButtonBox,QSlider)
from studio_backend.acoustic_guides import mora_rows,prepare
from studio_backend.acoustic import manual_highlight
from .timeline import Timeline
from .widgets import TimeEdit,time_text


class GuideTimeline(Timeline):
    def __init__(self):super().__init__();self.guide_points=[]
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self)
        try:
            painter.setPen(QPen(QColor('#39dfae'),1,Qt.PenStyle.DashLine))
            for point in self.guide_points:
                x=self.tx(point['time'])
                if 0<=x<self.width():
                    painter.drawLine(QPointF(x,self.audio_top),QPointF(x,self.audio_bottom))
                    painter.drawText(QPointF(min(x+3,max(0,self.width()-95)),self.audio_top+15),time_text(point['time']))
        finally:painter.end()


class GuideDialog(QDialog):
    def __init__(self,line,playback,parent=None,draft=None,save=None,word=0,part=0):
        super().__init__(parent);self.setWindowTitle('固定位置后局部重算');self.resize(900,730)
        self.line=copy.deepcopy(line);self.playback=playback;self.rows=mora_rows(line)
        self.points=copy.deepcopy((draft or {}).get('points',[]));self.save_draft=save
        if not isinstance(self.points,list):raise ValueError('定位草稿格式无效。')
        known={(i,j) for i,j,h in self.rows};seen=set()
        for p in self.points:
            if not isinstance(p,dict) or set(p)!={'unit','highlight','edge','time'} or type(p['unit']) is not int or type(p['highlight']) is not int or (p['unit'],p['highlight']) not in known or p['edge'] not in ('start','end') or type(p['time']) is not int or not line.start<=p['time']<=line.end:
                raise ValueError('定位草稿与本句音节不一致。')
            key=(p['unit'],p['highlight'],p['edge'])
            if key in seen:raise ValueError('定位草稿有重复边界。')
            seen.add(key)
        existing={(i,j,e):getattr(h,e) for i,j,h in self.rows for e in h.fixed_edges}
        for p in self.points:
            key=(p['unit'],p['highlight'],p['edge'])
            if key in existing and existing[key]!=p['time']:raise ValueError('旧定位与已采用固定点不一致。')
        self.points=[p for p in self.points if (p['unit'],p['highlight'],p['edge']) not in existing]
        self.prepared=None;self.manual=False;self._closed=False;self.draft_saved=False
        root=QVBoxLayout(self)
        tip=QLabel('① 选音节的起点或终点 → ② 试听并定位 → ③ 加入固定位置。至少给两个位置，只重算它们之间。\n每个点只固定所选的一端，另一端仍需审核；失败保留原轴与定位草稿。')
        tip.setWordWrap(True);root.addWidget(tip)
        text=QLabel(line.text);text.setTextFormat(Qt.TextFormat.PlainText);text.setWordWrap(True);root.addWidget(text)
        body=QWidget();layout=QVBoxLayout(body);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(body);root.addWidget(scroll,1)
        self.timeline=GuideTimeline();self.timeline.granularity='mora';self.timeline.editing_enabled=False;self.timeline.set_line(self.line)
        self.timeline.setToolTip('左键选音节，右键试听，中键定位播放点；滚轮平移，Ctrl＋滚轮缩放。绿色虚线表示固定位置，原轴在审核前保持。')
        original=getattr(parent,'timeline',None)
        if original:
            self.timeline.set_neighbors(original.previous_line,original.next_line)
            for name in ('duration','show_spectrum','quality','curve','amplitude','medusa_hotkeys'):
                setattr(self.timeline,name,getattr(original,name))
            if original.audio:
                from .audio_render import AudioRenderer
                self.timeline.audio=AudioRenderer(original.audio.samples.filename,original.audio.rate)
                self.timeline.peaks=original.peaks;self.timeline.spectrum=original.spectrum
        layout.addWidget(self.timeline)
        view=QHBoxLayout();self.mode=QComboBox();self.mode.addItems(['频谱','波形']);self.mode.setCurrentIndex(0 if self.timeline.show_spectrum else 1)
        self.mode.currentIndexChanged.connect(self.change_view);view.addWidget(self.mode)
        focus=QPushButton('定位本句');focus.clicked.connect(self.timeline.focus_line);view.addWidget(focus)
        listen=QPushButton('试听本句 R');listen.clicked.connect(lambda:self.playback.audition(self.line.start,self.line.end));view.addWidget(listen)
        self.listen=QPushButton('试听所选（带前后音） S');self.listen.clicked.connect(self.audition);view.addWidget(self.listen)
        stop=QPushButton('停止 H');stop.clicked.connect(playback.stop);view.addWidget(stop);layout.addLayout(view)
        self.seek=QSlider(Qt.Orientation.Horizontal);self.seek.setRange(line.start,line.end);self.seek.setValue(max(line.start,min(line.end,playback.canvas.position)))
        self.seek.sliderMoved.connect(self.seek_to);layout.addWidget(self.seek)
        nav=QHBoxLayout();self.mora=QComboBox()
        self.mora.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.mora.setMinimumContentsLength(10);self.mora.setMinimumWidth(0)
        for i,j,h in self.rows:
            self.mora.addItem(f'词组 {i+1} · 音节 {j+1} · {h.kana}',(i,j));self.mora.setItemData(self.mora.count()-1,line.units[i].text,Qt.ItemDataRole.ToolTipRole)
        self.edge=QComboBox();self.edge.addItem('起点','start');self.edge.addItem('终点','end')
        self.time=TimeEdit();self.time.setRange(line.start,line.end)
        nav.addWidget(self.mora,2);nav.addWidget(self.edge);nav.addWidget(self.time);layout.addLayout(nav)
        controls=QHBoxLayout();self.use_playhead=QPushButton('读取当前播放位置');self.use_playhead.clicked.connect(self.read_playhead);controls.addWidget(self.use_playhead)
        locate=QPushButton('定位到输入时间');locate.clicked.connect(lambda:self.seek_to(self.time.value()));controls.addWidget(locate)
        self.add=QPushButton('加入／更新固定位置');self.add.clicked.connect(self.add_point);controls.addWidget(self.add);layout.addLayout(controls)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['音节','固定边界','时间','状态']);self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(130);self.table.setColumnWidth(1,75);self.table.setColumnWidth(2,115);self.table.setColumnWidth(3,160);self.table.cellClicked.connect(self.choose_point);layout.addWidget(self.table)
        remove=QPushButton('移除所选草稿点');remove.clicked.connect(self.remove_point);layout.addWidget(remove)
        self.scope=QComboBox();self.scope.addItem('只重算首尾固定位置之间（保留范围外音节）','between');self.scope.addItem('重算本句所有未固定部分','line')
        self.scope.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.scope.setMinimumContentsLength(15);self.scope.setMinimumWidth(0)
        self.scope.setCurrentIndex(max(0,self.scope.findData((draft or {}).get('scope','between'))));layout.addWidget(self.scope)
        self.status=QLabel();self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setWordWrap(True);layout.addWidget(self.status)
        from PySide6.QtWidgets import QApplication
        available=QApplication.primaryScreen().availableGeometry()
        self.resize(min(900,available.width()-30),min(730,available.height()-40))
        footer=QVBoxLayout() if available.width()<750 else QHBoxLayout();self.manual_button=QPushButton('返回本句手工校对');self.manual_button.clicked.connect(self.go_manual);footer.addWidget(self.manual_button)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.run=self.buttons.button(QDialogButtonBox.StandardButton.Ok);self.run.setText('生成局部重算候选')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('保留草稿，稍后继续');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons);root.addLayout(footer)
        self.mora.currentIndexChanged.connect(self.selection);self.edge.currentIndexChanged.connect(self.selection)
        self.scope.currentIndexChanged.connect(self.refresh);self.timeline.select.connect(self.select_mora)
        self.timeline.seek.connect(self.seek_to);self.timeline.audition.connect(playback.audition);self.timeline.action.connect(self.audio_action)
        playback.positionChanged.connect(self.position);self.finished.connect(self.cleanup)
        self.mora.setCurrentIndex(max(0,self.mora.findData((word,max(0,part)))));self.selection();self.refresh()

    def change_view(self,index):self.timeline.show_spectrum=index==0;self.timeline.invalidate()
    def selection(self,*_):
        key=self.mora.currentData()
        if key is None:return
        i,j=key;self.timeline.word=i;self.timeline.part=j;self.timeline.update()
        edge=self.edge.currentData();point=next((p for p in self.points if (p['unit'],p['highlight'],p['edge'])==(i,j,edge)),None)
        self.time.setValue(point['time'] if point else getattr(self.line.units[i].highlights[j],edge))
        h=self.line.units[i].highlights[j];hard=self.line.units[i].locked or manual_highlight(h)
        immutable=hard or edge in h.fixed_edges;self.time.setReadOnly(immutable);self.use_playhead.setEnabled(not immutable)
        if immutable:self.time.setValue(getattr(h,edge))
        self.add.setEnabled(edge not in h.fixed_edges);self.add.setText('使用已有边界作范围点' if hard else '加入／更新固定位置')
        self.add.setToolTip('保留已有人工或锁定时间，只用于限定重算范围。' if hard else '此边界已经固定；在主编辑区调整或解除固定。' if not self.add.isEnabled() else '只固定这一端，另一端仍为待审核候选。')
    def select_mora(self,i,j):
        index=self.mora.findData((i,j))
        if index>=0:self.mora.setCurrentIndex(index)
    def read_playhead(self):
        value=self.playback.canvas.position
        if not self.line.start<=value<=self.line.end:
            self.status.setText('播放位置超出本句演唱范围；请先回主编辑区修正整句范围。输入位置未改变。');return
        self.time.setValue(value)
    def seek_to(self,time):self.playback.seek(time);self.position(time)
    def position(self,time):
        if self._closed:return
        with QSignalBlocker(self.seek):self.seek.setValue(time)
        self.timeline.follow_position(time)
    def audition(self):
        i,j=self.mora.currentData();h=self.line.units[i].highlights[j]
        self.playback.audition(max(0,h.start-200),h.end+200)
    def audio_action(self,name):
        if name=='line':self.playback.audition(self.line.start,self.line.end)
        elif name in {'selection','toggle'}:self.audition()
        elif name=='stop':self.playback.stop()
        elif name in {'next','previous'}:self.mora.setCurrentIndex(max(0,min(self.mora.count()-1,self.mora.currentIndex()+(1 if name=='next' else -1))))
        elif name in {'scroll_left','scroll_right'}:
            self.timeline.left=max(0,self.timeline.left+self.timeline.span*.15*(1 if name=='scroll_right' else -1));self.timeline.invalidate()
    def add_point(self):
        i,j=self.mora.currentData();edge=self.edge.currentData()
        h=self.line.units[i].highlights[j]
        if edge in h.fixed_edges:
            self.status.setText('这个位置已经固定并列在范围点中；如需改变，请先回主编辑区调整。');return
        if (self.line.units[i].locked or manual_highlight(h)) and self.time.value()!=getattr(h,edge):
            self.status.setText('已有人工或锁定边界只作范围参考，不能在这里移动。');return
        self.time.interpretText();self.points=[p for p in self.points if (p['unit'],p['highlight'],p['edge'])!=(i,j,edge)]
        self.points.append(dict(unit=i,highlight=j,edge=edge,time=self.time.value()));self.refresh()
    def remove_point(self):
        row=self.table.currentRow()
        if row<0 or row>=len(self.entries):return
        p,existing=self.entries[row]
        if existing:self.status.setText('这是已采用的固定点；请回主编辑区解除，操作可撤销。');return
        self.points.remove(p);self.refresh()
    def choose_point(self,row,column):
        if not 0<=row<len(self.entries):return
        p,_=self.entries[row];self.mora.setCurrentIndex(self.mora.findData((p['unit'],p['highlight'])))
        self.edge.setCurrentIndex(self.edge.findData(p['edge']));self.time.setValue(p['time'])
        self.timeline.left=max(0,p['time']-self.timeline.span/2);self.timeline.invalidate()
    def refresh(self,*_):
        existing=[dict(unit=i,highlight=j,edge=e,time=getattr(h,e)) for i,j,h in self.rows for e in h.fixed_edges]
        self.entries=sorted([(p,True) for p in existing]+[(p,False) for p in self.points],key=lambda v:(v[0]['unit'],v[0]['highlight'],v[0]['edge']=='end'))
        self.timeline.guide_points=[p for p,_ in self.entries];self.timeline.update()
        self.table.setRowCount(len(self.entries))
        for row,(p,fixed) in enumerate(self.entries):
            i,j=p['unit'],p['highlight'];h=self.line.units[i].highlights[j]
            for col,text in enumerate([f'{i+1}.{j+1} · '+h.kana,'起点' if p['edge']=='start' else '终点',time_text(p['time']),'已采用固定' if fixed else '人工边界作范围参考' if self.line.units[i].locked or manual_highlight(h) else '定位草稿']):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(row,col,item)
        all_points=existing+[p for p in self.points if not any((q['unit'],q['highlight'],q['edge'])==(p['unit'],p['highlight'],p['edge']) for q in existing)]
        self.prepared=None
        try:
            self.prepared=prepare(self.line,all_points,self.scope.currentData())
            count=sum(len(job['mora']) for job in self.prepared['jobs'])
            self.status.setText(f'{len(all_points)} 个固定点，重算 {count} 个未固定音节、{len(self.prepared["jobs"])} 段。原文、读音、人工音节与范围外时间保持；本机运行，无需 API；TIFA 仅限个人非商业用途。')
        except ValueError as error:self.status.setText(str(error))
        self.run.setEnabled(self.prepared is not None)
        if self.save_draft:
            try:self.save_draft({'points':self.points,'scope':self.scope.currentData()});self.draft_saved=True
            except OSError:self.draft_saved=False;self.prepared=None;self.run.setEnabled(False);self.status.setText('定位草稿无法保存，请检查磁盘空间或写入权限；原轴保持。')
    def accept(self):
        self.refresh()
        if self.prepared is not None:super().accept()
    def go_manual(self):self.manual=True;self.reject()
    def cleanup(self,*_):
        if self._closed:return
        self._closed=True;self.playback.positionChanged.disconnect(self.position);self.playback.stop()
        self.timeline.cancel_drag()
        if self.timeline.audio:self.timeline.audio.close();self.timeline.audio=None
