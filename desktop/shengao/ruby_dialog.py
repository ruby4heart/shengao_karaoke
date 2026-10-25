"""Choose visual kanji/kana correspondence with the actual ASS renderer."""
import copy
from PySide6.QtCore import Qt,QSize,QTimer,QSignalBlocker
from PySide6.QtGui import QImage,QPainter,QColor,QPixmap,QBitmap,QRegion
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QSpinBox,QTableWidget,QTableWidgetItem,QPushButton,QDialogButtonBox,QScrollArea,QWidget,QSizePolicy
from studio_backend.reading_options import set_ruby
from .furigana import ruby_spans,unit_ruby_spans
from .render import AssRenderer
from .subtitles import compose


class RubyDialog(QDialog):
    def __init__(self,project,line_index,word,parent=None):
        super().__init__(parent);self.setWindowTitle('汉字与假名对应');self.original=copy.deepcopy(project);self.row=line_index;self.word=word;self.line=self.original.lines[line_index];self.unit=self.line.units[word];self.result_line=None;self.candidate=None
        screen=self.screen().availableGeometry();self.resize(min(820,screen.width()-30),min(740,screen.height()-40));self.renderer=AssRenderer();self.renderer.add_fonts([project.style.font_file,project.style.ruby_font_file,*project.font_assets.values()])
        self.spans=copy.deepcopy(self.unit.reading_options.get('ruby',{}).get('spans',list(map(list,ruby_spans(self.unit.text,self.unit.kana)))))
        root=QVBoxLayout(self);intro=QLabel('只调整假名显示在原文哪里；歌词、实际读音、演唱时间和固定点保持。熟字训可选整词注音。');intro.setWordWrap(True);root.addWidget(intro)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);root.addWidget(scroll,1)
        self.picture=QLabel();self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter);self.picture.setMinimumHeight(130);self.picture.setMaximumHeight(230);self.picture.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding);layout.addWidget(self.picture)
        self.caption=QLabel('当前视频帧上的对应预览，播放位置保持；无视频帧时使用深色背景。');self.caption.setWordWrap(True);layout.addWidget(self.caption)
        original=QLabel('原文：'+self.unit.text+'\n假名：'+self.unit.kana);original.setTextFormat(Qt.TextFormat.PlainText);original.setWordWrap(True);layout.addWidget(original)
        self.mode=QComboBox()
        for text,value in [('自动对应送假名','auto'),('整词注音（熟字训／特殊读法）','whole'),('手工指定原文与假名范围','custom'),('不显示本词注音','off')]:self.mode.addItem(text,value)
        self.mode.setCurrentIndex(self.mode.findData(self.unit.reading_options.get('ruby',{}).get('mode','auto')));layout.addWidget(self.mode)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['原文范围','原文','假名范围','假名']);self.table.setMaximumHeight(150);layout.addWidget(self.table)
        fields=QHBoxLayout();self.fields=[]
        for title,length,default in [('原文从',len(self.unit.text),1),('到',len(self.unit.text),len(self.unit.text)),('假名从',len(self.unit.kana),1),('到',len(self.unit.kana),len(self.unit.kana))]:
            fields.addWidget(QLabel(title));field=QSpinBox();field.setRange(1,max(1,length));field.setValue(max(1,default));fields.addWidget(field);self.fields.append(field)
        layout.addLayout(fields);row=QHBoxLayout();self.add=QPushButton('加入新段');self.add.setToolTip('按上面的字符范围加入一段对应；不能拆开拗音、重叠或漏掉送假名。');self.add.clicked.connect(self.add_span);row.addWidget(self.add)
        self.update=QPushButton('更新选中段');self.update.setToolTip('用上面的范围替换表格中选中的一段，先预览再应用。');self.update.clicked.connect(self.update_span);row.addWidget(self.update)
        self.remove=QPushButton('移除选中段');self.remove.setToolTip('只移除当前手工对应草稿中的选中段，不修改工程。');self.remove.clicked.connect(self.remove_span);row.addWidget(self.remove);layout.addLayout(row)
        self.status=QLabel();self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setWordWrap(True);layout.addWidget(self.status)
        if project.source_ass_active:
            note=QLabel('采用后使用声稿排版；原 ASS 保留，可撤销。');note.setWordWrap(True);layout.addWidget(note)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);self.apply=self.buttons.button(QDialogButtonBox.StandardButton.Ok);self.apply.setText('应用本词注音对应');self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('保留原对应');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);root.addWidget(self.buttons)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.render_preview);self.mode.currentIndexChanged.connect(self.refresh);self.table.currentCellChanged.connect(self.select_span);self.finished.connect(lambda _:self.renderer.close());self.refresh()

    def setting(self):return {'mode':'custom','spans':copy.deepcopy(self.spans)} if self.mode.currentData()=='custom' else {'mode':self.mode.currentData()}
    def refresh(self,*_):
        custom=self.mode.currentData()=='custom'
        for field in [*self.fields,self.add,self.update,self.remove]:field.setEnabled(custom)
        self.candidate=None
        try:
            self.candidate=set_ruby(self.line,self.word,self.setting());spans=unit_ruby_spans(self.candidate.units[self.word]);self.status.setText('对应预览有效。原文、假名、音节起止、确认和固定点保持，应用后可一步撤销。')
        except ValueError as error:spans=self.spans if custom else [];self.status.setText(str(error))
        blocker=QSignalBlocker(self.table);self.table.setRowCount(len(spans))
        for row,(a,b,c,d) in enumerate(spans):
            for col,text in enumerate([f'{a+1}–{b}',self.unit.text[a:b],f'{c+1}–{d}',self.unit.kana[c:d]]):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(row,col,item)
        del blocker;self.apply.setEnabled(self.candidate is not None);self.timer.start(60)
    def add_span(self):
        a,b,c,d=[f.value() for f in self.fields];self.spans.append([a-1,b,c-1,d])
        self.spans.sort(key=lambda v:(v[0],v[2]));self.refresh()
    def update_span(self):
        row=self.table.currentRow()
        if 0<=row<len(self.spans):
            a,b,c,d=[f.value() for f in self.fields];self.spans[row]=[a-1,b,c-1,d];self.spans.sort(key=lambda v:(v[0],v[2]));self.refresh()
    def select_span(self,row,*_):
        if self.mode.currentData()=='custom' and 0<=row<len(self.spans):
            a,b,c,d=self.spans[row]
            for field,value in zip(self.fields,[a+1,b,c+1,d]):field.setValue(value)
    def remove_span(self):
        row=self.table.currentRow()
        if 0<=row<len(self.spans):self.spans.pop(row);self.refresh()
    def render_preview(self):
        if self.candidate is None:return
        p=copy.deepcopy(self.original);p.lines[self.row]=copy.deepcopy(self.candidate);p.source_ass_active=False
        try:
            self.renderer.set_text(compose(p));frame=self.parent().playback.canvas.frame if self.parent() is not None else QImage();source=frame.size() if not frame.isNull() else QSize(p.width,p.height);size=QSize(1920,max(1,round(1920*source.height()/max(1,source.width()))))
            unit=self.candidate.units[self.word];overlay=self.renderer.image(size.width(),size.height(),(unit.start+unit.end)//2)
            bounds=QRegion(QBitmap.fromImage(overlay.createAlphaMask())).boundingRect()
            image=QImage(size,QImage.Format.Format_RGB32);image.fill(QColor('#142238'));painter=QPainter(image)
            try:
                if not frame.isNull():painter.drawImage(0,0,frame.scaled(size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation))
                painter.drawImage(0,0,overlay)
            finally:painter.end()
            if not bounds.isEmpty():image=image.copy(bounds.adjusted(-24,-24,24,24).intersected(image.rect()))
            image=image.scaled(QSize(600,220),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            self.picture.setPixmap(QPixmap.fromImage(image));self.caption.setText('实际字幕区域放大，仅用于检查注音；成片字号、位置、播放点与工程保持。')
        except (ValueError,OSError) as error:self.caption.setText('对应预览暂不可用：'+str(error))
    def accept(self):
        self.refresh()
        if self.candidate is not None:self.result_line=copy.deepcopy(self.candidate);super().accept()
