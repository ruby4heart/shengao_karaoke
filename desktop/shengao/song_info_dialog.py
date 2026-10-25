"""Private song-credit draft with actual libass preview and one undoable adoption."""
import copy
from PySide6.QtCore import Qt,QSize,QTimer
from PySide6.QtGui import QImage,QPainter,QColor,QBitmap,QRegion
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QScrollArea,QWidget,
    QLabel,QCheckBox,QPlainTextEdit,QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QPushButton,
    QDialogButtonBox,QColorDialog,QFileDialog,QInputDialog)
from fontTools.ttLib import TTLibError
from .color_workflow import FramePreview
from .fonts import bundled_fonts,fonts_in_file,project_font_files
from .song_info import settings,validate,period,issues,overlap_issues,event_parts,own_event
from .subtitles import compose
from .render import AssRenderer
from .widgets import TimeEdit


def note(text):
    label=QLabel(text);label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);return label


class SongInfoDialog(QDialog):
    def __init__(self,project,parent=None):
        super().__init__(parent);self.setWindowTitle('歌名与歌手 · 左上角标识')
        self.original=copy.deepcopy(project);self.result_settings=None;self.candidate=None
        self.renderer=AssRenderer();self.fields={};self.loading=True
        area=self.screen().availableGeometry();self.resize(min(820,area.width()-30),min(840,area.height()-40))
        self.frame=parent.playback.canvas.frame.copy() if parent is not None and hasattr(parent,'playback') else QImage()
        root=QVBoxLayout(self);root.addWidget(note('独立画面标识，不占歌词行或演唱时间。采用前只改草稿，取消保留原设置；原 ASS 的样式与特效保持。'))
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);self.scroll.setWidget(body);root.addWidget(self.scroll,1)
        self.picture=FramePreview();self.picture.setFixedHeight(220);layout.addWidget(self.picture)
        self.detail=FramePreview();self.detail.setFixedHeight(110);layout.addWidget(self.detail)
        self.caption=note('当前静止视频帧叠加所选时刻字幕；主播放器保持原位置。下图仅放大标识区域，不改变输出字号。');layout.addWidget(self.caption)
        form=QFormLayout();form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow);layout.addLayout(form)
        s=settings(project);self.enabled=QCheckBox('显示歌名／歌手');self.enabled.setChecked(s['enabled']);form.addRow(self.enabled)
        for key,title in [('title','歌名'),('artist','歌手')]:
            edit=QPlainTextEdit(s[key]);edit.setMaximumHeight(66);edit.setPlaceholderText('可留空；最多三行，不自动截断');edit.setTabChangesFocus(True);self.fields[key]=edit;form.addRow(title,edit);edit.textChanged.connect(self.refresh)
        self.font=QComboBox();self.font.setMinimumContentsLength(16);self.font.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font.addItem('跟随正文的字体（字号独立）',('',''))
        for font in bundled_fonts():self.font.addItem(font.kind+' · '+font.family,(font.family,font.path))
        chosen=next((i for i in range(self.font.count()) if tuple(self.font.itemData(i))==(s['font'],s['font_file'])),-1)
        if chosen<0:self.font.addItem(s['font'] or '当前本地字体',(s['font'],s['font_file']));chosen=self.font.count()-1
        self.font.setCurrentIndex(chosen);form.addRow('标识字体',self.font)
        self.add_font=QPushButton('添加本地字体…');form.addRow(self.add_font);self.add_font.clicked.connect(self.choose_font)
        for key,title,lo,hi in [('title_size','歌名字号',8,180),('artist_size','歌手字号',8,180),('x','左边距',0,1856),('y','上边距',0,1016),('gap','两项间距',0,100),('opacity','不透明度 %',0,100)]:
            field=QSpinBox();field.setRange(lo,hi);field.setValue(s[key]);self.fields[key]=field;form.addRow(title,field);field.valueChanged.connect(self.refresh)
        for key,title in [('outline','描边粗细'),('shadow','阴影距离')]:
            field=QDoubleSpinBox();field.setRange(0,20);field.setSingleStep(.5);field.setValue(s[key]);self.fields[key]=field;form.addRow(title,field);field.valueChanged.connect(self.refresh)
        for key,title in [('title_color','歌名颜色'),('artist_color','歌手颜色'),('outline_color','描边颜色'),('shadow_color','阴影颜色')]:
            row=QWidget();box=QHBoxLayout(row);box.setContentsMargins(0,0,0,0);edit=QLineEdit(s[key]);edit.setMaxLength(7);edit.setPlaceholderText('#RRGGBB');self.fields[key]=edit;box.addWidget(edit)
            pick=QPushButton('选色');pick.clicked.connect(lambda checked=False,k=key:self.choose_color(k));box.addWidget(pick);form.addRow(title,row);edit.textChanged.connect(self.refresh)
        self.period=QComboBox();self.period.addItem('全片显示','all');self.period.addItem('指定显示时段','range');self.period.setCurrentIndex(self.period.findData(s['period']));form.addRow('显示时段',self.period)
        for key,title in [('start','出现'),('end','消失')]:
            field=TimeEdit();field.setMaximum(360000000);field.setValue(s[key]);self.fields[key]=field;form.addRow(title,field);field.valueChanged.connect(self.refresh)
        self.preview_time=TimeEdit();self.preview_time.setMaximum(360000000)
        position=parent.playback.canvas.position if parent is not None and hasattr(parent,'playback') else period(project)[0]
        if s['period']=='range' and not s['start']<=position<s['end']:position=s['start']
        self.preview_time.setValue(position);form.addRow('只预览这个时刻',self.preview_time);self.preview_time.valueChanged.connect(self.refresh)
        layout.addWidget(note('尺寸按 1920×1080 设计，随 ASS 分辨率缩放。空白项不显示；长文字请手工换行或减小字号。'))
        self.check_overlap=QPushButton('检查与歌词重叠');self.check_overlap.clicked.connect(self.inspect_overlap);layout.addWidget(self.check_overlap)
        self.warning=note('');layout.addWidget(self.warning)
        layout.addWidget(note('重叠检查在每句显示的起／中／末抽查，最多 100 句；复杂 ASS 动画仍需预览。'))
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.apply=self.buttons.button(QDialogButtonBox.StandardButton.Ok);self.apply.setText('采用歌名／歌手设置')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消并保留原设置');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);root.addWidget(self.buttons)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.render_preview)
        self.enabled.toggled.connect(self.refresh);self.font.currentIndexChanged.connect(self.refresh);self.period.currentIndexChanged.connect(self.refresh)
        self.finished.connect(self.cleanup);self.loading=False;self.refresh()

    def draft(self):
        value=settings(self.original)
        for key,field in self.fields.items():
            value[key]=field.toPlainText() if isinstance(field,QPlainTextEdit) else field.text().strip() if isinstance(field,QLineEdit) else field.value()
        value['font'],value['font_file']=self.font.currentData();value['enabled']=self.enabled.isChecked();value['period']=self.period.currentData()
        validate(value);return value

    def refresh(self,*_):
        if self.loading:return
        self.candidate=None;self.apply.setEnabled(False)
        for key in ('start','end'):self.fields[key].setEnabled(self.period.currentData()=='range')
        try:
            value=self.draft();p=copy.deepcopy(self.original);p.song_info=copy.deepcopy(value);p.validate()
            compose(p)  # Reject an unsupported original ASS before it can be adopted.
            self.candidate=p;self.apply.setEnabled(True);self.warning.setText('\n'.join(v for _,v in issues(p)) or '设置有效；采用后可一步撤销，歌词、时间及确认状态保持。')
        except (ValueError,OSError) as error:self.warning.setText(str(error))
        self.timer.start(120)

    def choose_color(self,key):
        selected=QColorDialog.getColor(QColor(self.fields[key].text()),self,'选择颜色')
        if selected.isValid():self.fields[key].setText(selected.name())

    def choose_font(self):
        path,_=QFileDialog.getOpenFileName(self,'选择标识字体','','字体文件 (*.otf *.ttf *.ttc)')
        if not path:return
        try:
            fonts=fonts_in_file(path)
            if not fonts:raise ValueError('字体文件没有可用字面')
            if len(fonts)>1:
                family,accepted=QInputDialog.getItem(self,'选择字面','字体集合中的字面',[v.family for v in fonts],0,False)
                if not accepted:return
                chosen=next(v for v in fonts if v.family==family)
            else:chosen=fonts[0]
            self.font.addItem('本地 · '+chosen.family,(chosen.family,chosen.path));self.font.setCurrentIndex(self.font.count()-1)
        except (ValueError,OSError,KeyError,TTLibError) as error:self.warning.setText('字体未添加：'+str(error))

    def render_preview(self):
        if self.candidate is None or self.renderer.closed:return
        try:
            p=self.candidate;self.renderer.add_fonts(project_font_files(p));text=compose(p);self.renderer.set_text(text)
            # Fixed design resolution keeps the actual glyph region readable.
            source=self.frame.size() if not self.frame.isNull() else QSize(p.width,p.height)
            size=QSize(1280,max(1,round(1280*source.height()/max(1,source.width()))));when=self.preview_time.value()
            overlay=self.renderer.image(size.width(),size.height(),when);image=QImage(size,QImage.Format.Format_RGB32);image.fill(QColor('#142238'));paint=QPainter(image)
            try:
                if not self.frame.isNull():paint.drawImage(0,0,self.frame.scaled(size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation))
                paint.drawImage(0,0,overlay)
            finally:paint.end()
            self.picture.set_image(image)
            events=dict(event_parts(text));logo='\n'.join(row for i,row in enumerate(text.splitlines()) if i not in events or own_event(events[i]))+'\n'
            self.renderer.set_text(logo);mask=self.renderer.image(size.width(),size.height(),when)
            bounds=QRegion(QBitmap.fromImage(mask.createAlphaMask())).boundingRect()
            if bounds.isEmpty():self.detail.clear();self.detail.source_pixmap=None;self.detail.setText('此预览时刻没有可见歌名／歌手；请检查开关、显示时段、位置及透明度。')
            else:self.detail.setText('');self.detail.set_image(image.copy(bounds.adjusted(-12,-12,12,12).intersected(image.rect())))
        except (ValueError,OSError) as error:self.warning.setText('预览暂不可用：'+str(error));self.apply.setEnabled(False)

    def inspect_overlap(self):
        self.refresh();self.timer.stop()
        if self.candidate is None:return
        try:
            found=issues(self.candidate)+overlap_issues(self.candidate)
            rows={v.id:i+1 for i,v in enumerate(self.candidate.lines)}
            self.warning.setText('\n'.join((f'第 {rows[uid]} 句：' if uid in rows else '')+message for uid,message in found) or '抽查未检测到重叠；复杂动画请继续预览。')
        except (ValueError,OSError) as error:self.warning.setText('重叠检查未完成：'+str(error))
        self.render_preview()

    def cleanup(self,*_):
        self.timer.stop();self.renderer.close()

    def accept(self):
        for field in self.fields.values():
            if isinstance(field,(QSpinBox,QDoubleSpinBox)):field.interpretText()
        self.preview_time.interpretText()
        self.refresh();self.timer.stop();self.render_preview()
        if self.candidate is not None and self.apply.isEnabled():
            self.result_settings=copy.deepcopy(self.candidate.song_info);super().accept()


class SongInfoWorkflow:
    def build_song_info_tools(self,layout):
        self.song_info_button=QPushButton('歌名与歌手（左上角）…');self.song_info_button.setToolTip('独立画面标识：填写歌名与歌手，设置字体、配色、边距和显示时段；先预览，采用可一步撤销，歌词与原 ASS 保持。');self.song_info_button.clicked.connect(lambda checked=False:self.edit_song_info());layout.addWidget(self.song_info_button)

    def edit_song_info(self):
        if not self.flush_edits():return False
        before=self.project.to_dict();dialog=SongInfoDialog(self.project,self)
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted or dialog.result_settings is None:return False
            result=copy.deepcopy(dialog.result_settings)
        finally:dialog.cleanup();dialog.deleteLater()
        if self.project.to_dict()!=before:
            self.message('工程、样式或素材已变化，歌名设置未采用；当前内容保留，请重新打开比较。');return False
        changed=self.edit('修改歌名与歌手标识',lambda p:setattr(p,'song_info',result))
        if changed:self.render_subtitles();self.message('歌名／歌手已采用，可一步撤销；歌词、演唱轴与原 ASS 保持。')
        return changed
