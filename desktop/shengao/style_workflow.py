"""Compare fonts against real lyrics, then adopt display-only edits once."""
import copy
from dataclasses import asdict
from PySide6.QtCore import Qt,QSize,QTimer
from PySide6.QtGui import QImage,QPainter,QColor,QIcon,QPixmap,QBitmap,QRegion
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,
    QFormLayout,QScrollArea,QLabel,QPushButton,QToolButton,QComboBox,QSpinBox,
    QDoubleSpinBox,QCheckBox,QListWidget,QListWidgetItem,QDialogButtonBox,QSizePolicy)
from .fonts import bundled_fonts,project_font_files
from .color_workflow import FramePreview
from .line_layout import make_setting,available_breaks,break_status
from .presentation import display_windows
from .render import AssRenderer
from .subtitles import compose,layout_issues


FONT_PAIRS=(('清晰黑体',0,0,'正文和假名统一，适合小字号与复杂背景。'),
            ('明朝＋黑体注音',1,0,'正文有明朝笔形，假名保持黑体。'),
            ('特粗明朝＋粗注音',3,2,'较大正文更醒目，细密歌词需检查假名。'),
            ('高可读粗黑体',2,2,'正文与假名都用粗黑体，适合快速接唱。'))
FONT_FIELDS=('font','font_file','ruby_font','ruby_font_file')


def font_pair(style,index):
    if type(index) is not int or not 0<=index<len(FONT_PAIRS):raise ValueError('请选择有效的内置字体组合')
    fonts=bundled_fonts();_,main,ruby,_=FONT_PAIRS[index];value=copy.copy(style)
    value.font,value.font_file=fonts[main].family,fonts[main].path
    value.ruby_font,value.ruby_font_file=fonts[ruby].family,fonts[ruby].path
    return value


def note(text):
    label=QLabel(text);label.setWordWrap(True);label.setTextFormat(Qt.TextFormat.PlainText);return label


class StyleWorkbenchDialog(QDialog):
    def __init__(self,project,current=0,parent=None):
        super().__init__(parent);self.setWindowTitle('字体比较与本句排版')
        self.original=copy.deepcopy(project);self.current=max(0,min(current,len(project.lines)-1))
        self.line=self.original.lines[self.current] if project.lines else None
        self.result_style=None;self.result_setting=None;self.result_ready=False;self.open_segmentation=False
        self.candidate=None;self.loading=True;self.layout_dirty=False;self.breaks_touched=False;self.card_key=None
        self.renderer=AssRenderer();self.frame=parent.playback.canvas.frame.copy() if parent is not None and hasattr(parent,'playback') else QImage()
        area=self.screen().availableGeometry();self.resize(min(900,area.width()-30),min(850,area.height()-40))
        root=QVBoxLayout(self);root.addWidget(note('先用实际歌词与当前静止视频帧比较，再采用。字体和全局字号作用于整首；本句比例和换行只影响这一句。'))
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);body=QWidget();box=QVBoxLayout(body);self.scroll.setWidget(body);root.addWidget(self.scroll,1)
        self.picture=FramePreview();self.picture.setFixedHeight(240);box.addWidget(self.picture)
        self.detail=FramePreview();self.detail.setFixedHeight(150);box.addWidget(self.detail)
        self.caption=note('');box.addWidget(self.caption)
        time_row=QHBoxLayout();self.phase=QComboBox();self.phase.addItem('演唱中','singing');self.phase.addItem('提前接唱／待唱','waiting');self.phase.addItem('唱完留屏','sung');time_row.addWidget(self.phase)
        self.refresh_button=QPushButton('刷新当前比较');self.refresh_button.clicked.connect(self.render_preview);time_row.addWidget(self.refresh_button);box.addLayout(time_row)
        grid=QGridLayout();self.cards=[]
        for i,(title,_,_,why) in enumerate(FONT_PAIRS):
            card=QToolButton();card.setText(title);card.setToolTip(why+' 仅比较／选择字体，已有配色和接唱时间保持。');card.setCheckable(True)
            card.setMinimumWidth(0);card.setMinimumHeight(128);card.setIconSize(QSize(250,92));card.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed);card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            card.clicked.connect(lambda checked=False,n=i:self.font_choice.setCurrentIndex(n+1));self.cards.append(card);grid.addWidget(card,i//2,i%2)
        box.addLayout(grid);box.addWidget(note('内置字体的许可随软件提供；四图使用同一歌词、显示时刻、字号和已有配色。字体观感仍需结合样片确认。'))
        form=QFormLayout();form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow);box.addLayout(form)
        self.font_choice=QComboBox();self.font_choice.addItem('保留当前正文／假名字体',-1)
        for i,(title,_,_,_) in enumerate(FONT_PAIRS):self.font_choice.addItem(title,i)
        form.addRow('整首字体组合',self.font_choice);self.fields={}
        for key,title,maximum in [('size','整首原文字号',180),('ruby_size','整首假名字号',180),('romaji_size','整首罗马音字号',180),('translation_size','整首译文字号',180)]:
            edit=QSpinBox();edit.setRange(8,maximum);edit.setValue(getattr(project.style,key));self.fields[key]=edit;form.addRow(title,edit);edit.valueChanged.connect(self.refresh)
        for key,title in [('outline','整首描边粗细'),('shadow','整首阴影距离')]:
            edit=QDoubleSpinBox();edit.setRange(0,12);edit.setSingleStep(.5);edit.setValue(getattr(project.style,key));self.fields[key]=edit;form.addRow(title,edit);edit.valueChanged.connect(self.refresh)
        self.local_title=note(f'只改第 {self.current+1} 句：{self.line.text}' if self.line else '添加歌词后可调整本句外观');box.addWidget(self.local_title)
        old=project.layout_styles.get(self.line.id,{}) if self.line else {}
        self.local_fields={};local_form=QFormLayout();box.addLayout(local_form)
        for key,title in [('size_percent','本句整体字号 %'),('ruby_percent','本句假名额外比例 %')]:
            edit=QSpinBox();edit.setRange(25,200);edit.setValue(old.get(key,100));edit.setEnabled(self.line is not None);self.local_fields[key]=edit;local_form.addRow(title,edit);edit.valueChanged.connect(self.local_changed)
        self.breaks=QListWidget();self.breaks.setMaximumHeight(180);self.breaks.setMinimumHeight(76);self.breaks.setWordWrap(True);self.breaks.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);box.addWidget(self.breaks)
        active,inactive=break_status(self.line,old) if self.line else ((),())
        for position in available_breaks(self.line) if self.line else ():
            text=self.line.text;item=QListWidgetItem(f'{text[max(0,position-12):position]} │ {text[position:position+12]}')
            item.setData(Qt.ItemDataRole.UserRole,position);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if position in active else Qt.CheckState.Unchecked);self.breaks.addItem(item)
        self.wrap_note=note('勾选词组之间的换行位置，最多8处。原歌词、注音、音节及人工轴保持。' if self.line and self.line.units else '此句尚未分词，可在完整字符之间选择显示换行；不会生成词组或音节。');box.addWidget(self.wrap_note)
        self.stale_note=note('旧换行依据已变化，原设置仍保留待复核。选择新词界会替换旧换行；只改字体或比例仍保留旧依据。' if inactive else '');self.stale_note.setVisible(bool(inactive));box.addWidget(self.stale_note)
        row=QHBoxLayout();self.reset=QPushButton('本句恢复全局排版');self.reset.setEnabled(self.line is not None);self.reset.clicked.connect(self.reset_line);row.addWidget(self.reset)
        self.segment=QPushButton('到本句分词处调整词界…');self.segment.setEnabled(self.line is not None);self.segment.setToolTip('关闭未采用的排版预览，进入本句分词；当前工程保持。');self.segment.clicked.connect(self.request_segmentation);row.addWidget(self.segment);box.addLayout(row)
        self.use_shengao=QCheckBox('采用声稿排版（原 ASS 及特效源文保留在工程中）');self.use_shengao.setVisible(project.source_ass_active);box.addWidget(self.use_shengao)
        self.warning=note('');box.addWidget(self.warning)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);self.apply=self.buttons.button(QDialogButtonBox.StandardButton.Ok);self.apply.setText('采用字体与本句排版');self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消并保留当前');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);root.addWidget(self.buttons)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.render_preview)
        self.font_choice.currentIndexChanged.connect(self.refresh);self.phase.currentIndexChanged.connect(self.refresh);self.use_shengao.toggled.connect(self.refresh);self.breaks.itemChanged.connect(self.break_changed)
        self.finished.connect(self.cleanup);self.loading=False;self.refresh()

    def local_changed(self,*_):
        if self.loading:return
        self.layout_dirty=True;self.refresh()

    def break_changed(self,*_):
        if self.loading:return
        self.breaks_touched=True;self.local_changed()

    def reset_line(self):
        self.loading=True
        try:
            for field in self.local_fields.values():field.setValue(100)
            for i in range(self.breaks.count()):self.breaks.item(i).setCheckState(Qt.CheckState.Unchecked)
        finally:self.loading=False
        self.breaks_touched=True;self.local_changed()

    def local_setting(self):
        if self.line is None:return None
        old=copy.deepcopy(self.original.layout_styles.get(self.line.id))
        if not self.layout_dirty:return old
        values={key:field.value() for key,field in self.local_fields.items()}
        if not self.breaks_touched and old:
            old.update(values)
            return None if not old['breaks'] and old['size_percent']==old['ruby_percent']==100 else old
        positions=[self.breaks.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.breaks.count()) if self.breaks.item(i).checkState()==Qt.CheckState.Checked]
        return make_setting(self.line,**values,breaks=positions)

    def draft(self):
        p=copy.copy(self.original);index=self.font_choice.currentData();p.style=font_pair(p.style,index) if index!=-1 else copy.copy(p.style)
        for key,field in self.fields.items():setattr(p.style,key,field.value())
        p.layout_styles=dict(p.layout_styles)
        if self.line is not None:
            value=self.local_setting()
            if value is None:p.layout_styles.pop(self.line.id,None)
            else:p.layout_styles[self.line.id]=value
        p.source_ass_active=False;p.validate();return p

    def refresh(self,*_):
        if self.loading:return
        self.candidate=None;self.apply.setEnabled(False)
        try:
            self.candidate=self.draft();allowed=not self.original.source_ass_active or self.use_shengao.isChecked();self.apply.setEnabled(allowed)
            stale=bool(self.line and break_status(self.line,self.candidate.layout_styles.get(self.line.id))[1]);self.stale_note.setVisible(stale)
            messages=[message for _,message in layout_issues(self.candidate,{self.line.id} if self.line else set(),include_song=False)]
            if not allowed:messages.insert(0,'当前是保留原 ASS 的工程；此处为声稿样式预览，勾选上方选项后才能采用。')
            self.warning.setText('\n'.join(messages[:12]) or '本句未发现文字排版提示；请继续检查样片。采用后可一步撤销。')
        except (ValueError,OSError) as error:self.warning.setText(str(error))
        for i,card in enumerate(self.cards):card.setChecked(i==self.font_choice.currentData())
        self.timer.start(120)

    def when(self):
        if self.line is None:return 0,'当前没有歌词，添加后可比较实际注音。'
        line=self.line;window=display_windows(self.candidate)[self.current];phase=self.phase.currentData()
        if phase=='waiting' and window.start<line.start:return (window.start+line.start)//2,'待唱'
        if phase=='sung' and window.end>line.end:return (line.end+window.end)//2,'唱完留屏'
        return (line.start+line.end)//2,'演唱中' if phase=='singing' else '本句没有所选显示区间，当前比较演唱中'

    def image(self,p,when):
        self.renderer.add_fonts(project_font_files(p));self.renderer.set_text(compose(p,preview_time=when))
        source=self.frame.size() if not self.frame.isNull() else QSize(p.width,p.height)
        size=QSize(1280,max(1,round(1280*source.height()/max(1,source.width()))));overlay=self.renderer.image(size.width(),size.height(),when)
        image=QImage(size,QImage.Format.Format_RGB32);image.fill(QColor('#142238'));paint=QPainter(image)
        try:
            if not self.frame.isNull():paint.drawImage(0,0,self.frame.scaled(size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation))
            paint.drawImage(0,0,overlay)
        finally:paint.end()
        if self.line is not None:
            # Keep full-project lanes, but use only this lyric's alpha to
            # find the close-up. A distant upcoming line or song credit
            # must not shrink the comparison into an unreadable overview.
            self.renderer.set_text(compose(p,preview_time=when,preview_line_id=self.line.id));focus=self.renderer.image(size.width(),size.height(),when)
        else:focus=overlay
        bounds=QRegion(QBitmap.fromImage(focus.createAlphaMask())).boundingRect()
        detail=image.copy(bounds.adjusted(-16,-12,16,12).intersected(image.rect())) if not bounds.isEmpty() else QImage()
        return image,detail

    def render_preview(self):
        self.timer.stop()
        if self.candidate is None or self.renderer.closed:return
        try:
            when,phase=self.when();image,detail=self.image(self.candidate,when);self.picture.set_image(image)
            self.detail.set_image(detail if not detail.isNull() else image)
            self.caption.setText(f'第 {self.current+1} 句 · {phase} · 字幕时刻 {when/1000:.3f} 秒。上图为完整画面，下图放大本句；背景为当前静止视频帧，主播放位置保持。')
            key=(repr(asdict(self.candidate.style)),repr(self.candidate.layout_styles),when)
            if key!=self.card_key:
                for i,card in enumerate(self.cards):
                    p=copy.copy(self.candidate);p.style=font_pair(p.style,i);_,crop=self.image(p,when)
                    if crop.isNull():crop=image
                    pixmap=QPixmap(290,92);pixmap.fill(QColor('#142238'));paint=QPainter(pixmap)
                    try:
                        fitted=crop.scaled(QSize(282,88),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation);paint.drawImage((290-fitted.width())//2,(92-fitted.height())//2,fitted)
                    finally:paint.end()
                    card.setIcon(QIcon(pixmap))
                self.card_key=key
        except (ValueError,OSError) as error:self.warning.setText('预览暂不可用：'+str(error));self.apply.setEnabled(False)

    def request_segmentation(self):self.open_segmentation=True;self.reject()

    def cleanup(self,*_):self.timer.stop();self.renderer.close()

    def accept(self):
        for field in [*self.fields.values(),*self.local_fields.values()]:field.interpretText()
        self.refresh();self.timer.stop();self.render_preview()
        if self.candidate is not None and self.apply.isEnabled():
            self.result_style=copy.deepcopy(self.candidate.style);self.result_setting=copy.deepcopy(self.candidate.layout_styles.get(self.line.id)) if self.line else None;self.result_ready=True;super().accept()


class StyleWorkflow:
    def build_style_workbench(self,layout):
        self.style_workbench_button=QPushButton('比较字体／修正本句排版…');self.style_workbench_button.setToolTip('用实际歌词、假名和当前视频帧比较四种内置字体组合；本句字号与词界换行保持原文、读音和全部轴。');self.style_workbench_button.clicked.connect(lambda checked=False:self.edit_style_workbench());layout.addWidget(self.style_workbench_button)

    def edit_style_workbench(self):
        if not self.flush_edits():return False
        from .project import file_stamp
        before=self.project.to_dict();source_stamp=file_stamp(self.project.media);dialog=StyleWorkbenchDialog(self.project,self.current,self)
        try:
            accepted=dialog.exec()==QDialog.DialogCode.Accepted and dialog.result_ready
            style=dialog.result_style;setting=dialog.result_setting;segment=dialog.open_segmentation;uid=dialog.line.id if dialog.line else None
        finally:dialog.cleanup();dialog.deleteLater()
        if not accepted and not segment:return False
        if self.project.to_dict()!=before or file_stamp(self.project.media)!=source_stamp:
            self.message('工程、样式或素材已变化，旧排版预览未采用；当前编辑保持，请重新打开比较。');return False
        if segment:self.set_stage(2);self.resegment_current();return False
        def apply(p):
            p.style=copy.deepcopy(style);p.source_ass_active=False
            if uid:
                if setting is None:p.layout_styles.pop(uid,None)
                else:p.layout_styles[uid]=copy.deepcopy(setting)
        self.cards_key=None;changed=self.edit('采用字体与本句排版',apply)
        if changed:self.render_subtitles();self.message('字体与本句排版已采用，可一步撤销；原歌词、注音、演唱及音节时间保持。')
        return changed
