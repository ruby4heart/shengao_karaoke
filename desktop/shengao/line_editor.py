"""In-place lyric boundary previews and a shared selectable mora strip."""
import copy,html
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QCheckBox,QPushButton,QLabel,QTextBrowser
from studio_backend.japanese import word_groups
from .editor_model import segmentation_preview,cuts_for,missing_mora_preview
from .widgets import time_text

def plain(text):return html.escape(text).replace(' ','&nbsp;').replace('\n','<br>')

class InlineSegmentation(QWidget):
    selected=Signal(int)
    pendingChanged=Signal(bool)
    applyRequested=Signal(object,object,str)
    def __init__(self,parent=None):
        super().__init__(parent);self.base=None;self.project_uid='';self.cuts=[];self.preview=None;self.selected_word=-1;self.error=''
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(6)
        self.mode=QCheckBox('直接点击原文切分／合并');self.mode.setToolTip('开启后点击某字，在它前面增加分界；点击已有分界可合并。先预览，再应用。关闭时点原文选择词组。');layout.addWidget(self.mode)
        self.text=QTextBrowser();self.text.setOpenLinks(False);self.text.setMinimumSize(0,76);self.text.setFixedHeight(76);self.text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.text.anchorClicked.connect(self.clicked);layout.addWidget(self.text)
        self.tools=QWidget();row=QHBoxLayout(self.tools);row.setContentsMargins(0,0,0,0);row.setSpacing(5)
        self.dictionary=QPushButton('按词典分词');self.dictionary.setToolTip('在本地预览词典切分；保留相同词组的人工读音和音节。');self.dictionary.clicked.connect(self.dictionary_cuts);row.addWidget(self.dictionary)
        self.whole=QPushButton('合为整句');self.whole.setToolTip('预览合并词组；已有音节和实际间隔保留，不重新转录。');self.whole.clicked.connect(lambda:self.propose([]));row.addWidget(self.whole);layout.addWidget(self.tools)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setObjectName('muted');layout.addWidget(self.status)
        self.actions=QWidget();row=QHBoxLayout(self.actions);row.setContentsMargins(0,0,0,0)
        self.apply=QPushButton('应用这次分词');self.apply.setObjectName('primary');self.apply.setToolTip('只应用此处预览的本句分词；一次操作一步撤销。');self.apply.clicked.connect(self.accept);row.addWidget(self.apply)
        self.cancel=QPushButton('取消预览');self.cancel.setToolTip('取消分词草稿，人工数据与原时间轴保持。');self.cancel.clicked.connect(self.reset);row.addWidget(self.cancel);layout.addWidget(self.actions)
        self.mode.toggled.connect(self.render);self.render()

    @property
    def pending(self):return self.preview is not None

    def set_line(self,line,uid,selected=-1):
        changed=self.project_uid!=uid or (line.to_dict() if line else None)!=(self.base.to_dict() if self.base else None)
        self.selected_word=selected
        if changed:
            was=self.pending;self.base=copy.deepcopy(line);self.project_uid=uid;self.cuts=cuts_for(line) if line else [];self.preview=None;self.error=''
            if was:self.pendingChanged.emit(False)
        self.render()

    def reset(self):
        was=self.pending;self.preview=None;self.error='';self.cuts=cuts_for(self.base) if self.base else [];self.render()
        if was:self.pendingChanged.emit(False)

    def clicked(self,url):
        try:position=int(url.toString().split(':')[-1])
        except ValueError:return
        if self.preview and self.preview.kind=='mora':return
        if not self.mode.isChecked():self.selected.emit(position);return
        if not self.base or not 0<position<len(self.base.text):return
        cuts=list(self.cuts)
        if position in cuts:cuts.remove(position)
        else:cuts.append(position)
        self.propose(cuts)

    def dictionary_cuts(self):
        if self.base:self.propose([g.begin for g in word_groups(self.base.text) if g.begin])

    def propose(self,cuts):
        if not self.base:return
        was=self.pending
        try:
            value=segmentation_preview(self.base,cuts);self.error=''
            self.preview=value if value.line.to_dict()!=self.base.to_dict() else None;self.cuts=sorted(cuts)
        except ValueError as error:self.error=str(error)
        self.render()
        if self.pending!=was:self.pendingChanged.emit(self.pending)

    def propose_mora(self):
        if not self.base or self.pending:return
        try:self.preview=missing_mora_preview(self.base);self.error=''
        except ValueError as error:self.error=str(error)
        self.render()
        if self.pending:self.pendingChanged.emit(True)

    def accept(self):
        if self.preview and not self.error:self.applyRequested.emit(copy.deepcopy(self.preview.line),self.base.to_dict(),self.project_uid)

    def render(self,*args):
        line=self.preview.line if self.preview else self.base;mode=self.mode.isChecked();self.tools.setVisible(mode);self.actions.setVisible(self.pending)
        self.status.setVisible(bool(mode or self.pending or self.error))
        editable=bool(self.base and not self.base.locked);mora_pending=bool(self.preview and self.preview.kind=='mora');self.mode.setEnabled(editable and not mora_pending);self.dictionary.setEnabled(editable and not mora_pending);self.whole.setEnabled(editable and not mora_pending);self.apply.setEnabled(self.pending and not self.error);self.apply.setText('应用估算音节' if mora_pending else '应用这次分词')
        if not line:self.text.setPlainText('加入原歌词后，在这里分词、改假名和调音节。');self.status.setText('');return
        selected=set();cursor=0
        for index,unit in enumerate(line.units):
            if index==self.selected_word:selected=set(range(cursor,cursor+len(unit.text)))
            cursor+=len(unit.text)
        pieces=[]
        for position,char in enumerate(line.text):
            if selected and position==min(selected) and not self.pending:pieces.append('<a name="selected-word"></a>')
            if position in self.cuts:pieces.append(f'<a href="char:{position}" style="color:#6070dd;text-decoration:none">│</a>')
            background='background:#e9edff;' if position in selected and not self.pending else ''
            pieces.append(f'<a href="char:{position}" style="{background}color:#27364e;text-decoration:none">{plain(char)}</a>')
        self.text.setHtml('<div style="font-size:20px;line-height:150%">'+''.join(pieces)+'</div>')
        if selected and not self.pending:self.text.scrollToAnchor('selected-word')
        if self.error:self.status.setText(self.error)
        elif self.preview:
            words='、'.join(self.preview.affected)
            if mora_pending:self.status.setText('将按已有假名与词组范围均分缺失音节（估算）：'+words+'。读音、词组时间和已有人工音节保留。'+(f'另有 {self.preview.skipped} 个缺音节词组因锁定、假名无效或范围过短未处理。' if self.preview.skipped else ''))
            else:self.status.setText(('将重估这些词组的读音与音节：' if self.preview.reestimated else '只合并词组，保留已有音节和间隔：')+words+'。其他词组保留；应用前不会改时间轴。')
            if getattr(self,'raw_ass',False):self.status.setText(self.status.text()+' 应用后使用声稿排版，原 ASS 仍保留。')
        else:self.status.setText('点击字前加分界、点分界合并；先预览再应用。' if mode else '点原文或下表选词组；假名可直接编辑。')

class MoraStrip(QTextBrowser):
    selected=Signal(int,int)
    audition=Signal(int,int)
    def __init__(self,parent=None):
        super().__init__(parent);self.setOpenLinks(False);self.setMinimumSize(0,58);self.setFixedHeight(58);self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.anchorClicked.connect(lambda url:self.emit_anchor(url.toString(),False));self.setToolTip('点击音节选择并定位，右键直接试听；下方起止框与时间轴同步。')
    def emit_anchor(self,anchor,audition):
        try:_,i,j=anchor.split(':');i,j=int(i),int(j)
        except (ValueError,AttributeError):return
        (self.audition if audition else self.selected).emit(i,j)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.RightButton:self.emit_anchor(self.anchorAt(event.position().toPoint()),True);event.accept()
        else:super().mousePressEvent(event)
    def set_line(self,line,word,part):
        pieces=[]
        if line:
            from studio_backend.provenance import describe,voice_lookup
            lookup=voice_lookup(line)
            for i,unit in enumerate(line.units):
                values=list(enumerate(unit.highlights)) if unit.highlights else [(-1,unit)]
                for j,value in values:
                    text=value.kana if j>=0 else unit.kana or unit.text
                    active=i==word and (part<0 or j==part);background='#e5eaff' if active else '#f5f7fb'
                    origin=describe(value,line,i,j,lookup)
                    tip=f'{time_text(value.start)} — {time_text(value.end)} · '+origin['title']+'\n'+'\n'.join(origin['detail']+origin['issues'])
                    pieces.append(f'<a href="mora:{i}:{j}" title="{html.escape(tip)}" style="background:{background};color:#394d78;text-decoration:none">&nbsp;{plain(text)}&nbsp;</a> ')
        self.setHtml('<div style="line-height:170%">'+''.join(pieces)+'</div>' if pieces else '尚无音节：先分词并填写假名；也可先调整整句范围。')
