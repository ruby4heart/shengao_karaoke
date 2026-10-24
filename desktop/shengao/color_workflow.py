"""A private video-frame preview, then one atomic colour edit."""
import copy
from PySide6.QtCore import Qt,QSize,QTimer
from PySide6.QtGui import QColor,QImage,QPainter,QPixmap
from PySide6.QtWidgets import QLabel,QVBoxLayout,QWidget,QPushButton,QDialog,QSizePolicy
from .color_dialog import ColorDialog
from .color_states import validate_settings
from .presentation import display_windows
from .render import AssRenderer
from .subtitles import compose


class FramePreview(QLabel):
    def __init__(self):
        super().__init__();self.source_pixmap=None;self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(160);self.setMinimumWidth(0);self.setMaximumHeight(340);self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding)
    def set_image(self,image):self.source_pixmap=QPixmap.fromImage(image);self.fit_image()
    def fit_image(self):
        if self.source_pixmap is not None:self.setPixmap(self.source_pixmap.scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def resizeEvent(self,event):super().resizeEvent(event);self.fit_image()


class ColorWorkflow:
    def build_color_tools(self,layout):
        self.color_states_button=QPushButton('颜色与演唱状态…')
        self.color_states_button.setToolTip('待唱、演唱中、唱完：正文、假名、罗马音、译文，以及描边、阴影和背景底板；支持指定歌词。')
        self.color_states_button.clicked.connect(lambda checked=False:self.edit_color_states());layout.addWidget(self.color_states_button)

    def edit_color_states(self,quick=None):
        if not self.flush_edits():return False
        original=copy.deepcopy(self.project);uid=original.uid
        selected=[v.id for v in original.lines if v.id in self._selected_lyric_ids]
        panel=QWidget();box=QVBoxLayout(panel);box.setContentsMargins(0,0,0,0)
        picture=FramePreview()
        caption=QLabel('当前视频帧上的配色预览；播放位置保持。');caption.setWordWrap(True);box.addWidget(picture);box.addWidget(caption)
        renderer=AssRenderer()
        draft={'settings':copy.deepcopy(original.color_styles),'phase':'middle'}
        def render():
            if not original.lines:picture.setText('添加歌词后，可用当前视频帧查看配色。');return
            p=copy.deepcopy(original);p.color_styles=copy.deepcopy(draft['settings']);p.source_ass_active=False
            index=max(0,min(self.current,len(p.lines)-1));ids=dialog.ids() if dialog is not None else None
            if ids and p.lines[index].id not in ids:index=next(i for i,line in enumerate(p.lines) if line.id==ids[0])
            line=p.lines[index];window=display_windows(p)[index]
            when=line.start+(line.end-line.start)//2;phase_name={'waiting':'待唱','middle':'演唱中','sung':'唱完留屏'}[draft['phase']]
            notice=f'第 {index+1} 句 · {phase_name} · 当前视频帧上的配色样片；播放位置保持。'
            if draft['phase']=='waiting':
                if window.start<line.start:when=(window.start+line.start)//2
                else:notice='本句没有待唱显示区间：可在校轴中设置提前出现。此处仍显示演唱中。'
            elif draft['phase']=='sung':
                if window.end>line.end:when=(line.end+window.end)//2
                else:notice='本句唱完立即消失：延长显示结束时间后可看到唱完配色。此处仍显示演唱中。'
            try:
                renderer.set_text(compose(p));frame=self.playback.canvas.frame
                source=frame.size() if not frame.isNull() else QSize(p.width,p.height)
                size=source.scaled(QSize(620,300),Qt.AspectRatioMode.KeepAspectRatio)
                image=QImage(size,QImage.Format.Format_RGB32);image.fill(QColor('#0c1423'))
                if frame.isNull():notice=notice.replace('当前视频帧','默认深色背景')
                painter=QPainter(image)
                try:
                    if not frame.isNull():painter.drawImage(0,0,frame.scaled(size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation))
                    painter.drawImage(0,0,renderer.image(size.width(),size.height(),when))
                finally:painter.end()
                picture.set_image(image);caption.setText(notice)
            except (ValueError,OSError) as error:caption.setText('配色预览暂不可用：'+str(error))
        def update(settings):draft['settings']=copy.deepcopy(settings);preview_timer.start(60)
        def phase(value):draft['phase']=value;render()
        dialog=None
        try:
            renderer.add_fonts([original.style.font_file,original.style.ruby_font_file,original.style.translation_font_file,*original.font_assets.values()])
            dialog=ColorDialog(original,self.current,selected,self,panel)
            preview_timer=QTimer(dialog);preview_timer.setSingleShot(True);preview_timer.timeout.connect(render)
            if quick:
                if self.line and self.line.id in original.color_styles.get('lines',{}):dialog.scope.setCurrentIndex(dialog.scope.findData('current'))
                state,channel={'color':('waiting','primary'),'highlight':('singing','primary'),'outline_color':('singing','outline')}[quick]
                dialog.state.setCurrentIndex(dialog.state.findData(state));dialog.fields[channel].hex.setFocus();dialog.fields[channel].hex.selectAll()
                draft['phase']='middle' if state=='singing' else state
            else:dialog.state.setCurrentIndex(dialog.state.findData('singing'))
            dialog.candidateChanged.connect(update);dialog.previewRequested.connect(phase);render()
            accepted=dialog.exec()==QDialog.DialogCode.Accepted
            result=copy.deepcopy(dialog.result_settings)
            preview_timer.stop()
        except (ValueError,OSError) as error:
            self.message('颜色设置未采用：'+str(error));return False
        finally:
            renderer.close()
            if dialog is not None:dialog.deleteLater()
        if not accepted or result is None:return False
        if self.project.uid!=uid or self.project.color_styles!=original.color_styles:
            self.message('工程或配色已变化，当前内容保留，请按当前版本重新打开颜色设置。');return False
        try:validate_settings(result,{line.id for line in self.project.lines})
        except ValueError as error:self.message(str(error));return False
        def apply(project):project.color_styles=copy.deepcopy(result);project.source_ass_active=False
        changed=self.edit('修改字幕状态颜色',apply)
        if changed:self.render_subtitles();self.message('配色已采用，可一步撤销；时间轴、读音和确认状态保持。')
        return changed
