"""Optional translation editing, comparison and measured display width."""
import copy
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import QLabel,QPlainTextEdit,QPushButton,QCheckBox,QHBoxLayout
from studio_backend import translation as model
from .fonts import resolve_font,metric_font
from .subtitles import text_width


class TranslationWorkflow:
    def build_translation_tools(self,layout):
        self.translation_source=QLabel();self.translation_source.setTextFormat(Qt.TextFormat.PlainText);self.translation_source.setWordWrap(True);layout.addWidget(self.translation_source)
        self.translation_length=QLabel();self.translation_length.setWordWrap(True);layout.addWidget(self.translation_length)
        self.translation_confirm=QCheckBox('译文已核对（可选）');self.translation_confirm.toggled.connect(self.confirm_translation);layout.addWidget(self.translation_confirm)
        self.translation_draft=QPlainTextEdit();self.translation_draft.setReadOnly(True);self.translation_draft.setTabChangesFocus(True);self.translation_draft.setMaximumHeight(90);self.translation_draft.setAccessibleName('已保存的 DeepSeek 译文建议');layout.addWidget(self.translation_draft)
        row=QHBoxLayout();self.accept_translation_button=QPushButton('采用已保存译文建议');self.accept_translation_button.setToolTip('先比较当前译文与上方建议，只替换译文；原文、读音、时间与它们的确认保持，可撤销。');self.accept_translation_button.clicked.connect(self.accept_translation);row.addWidget(self.accept_translation_button)
        self.keep_translation_button=QPushButton('保留当前译文');self.keep_translation_button.setToolTip('保留当前译文并暂不显示这条建议；任务记录仍保留原结果，可撤销。');self.keep_translation_button.clicked.connect(self.keep_translation);row.addWidget(self.keep_translation_button);layout.addLayout(row)
        self.translation.textChanged.connect(self.refresh_translation_tools)

    def refresh_translation_tools(self,*_):
        if not hasattr(self,'translation_source'):return
        line=self.line
        if not line:
            self.translation_source.clear();self.translation_length.clear();self.translation_draft.hide();self.accept_translation_button.hide();self.keep_translation_button.hide();return
        source=model.info(line);changed=bool(line.reading_review.get('translation_original_changed') or source['for_text'] and source['for_text']!=line.text)
        self.translation.setReadOnly(line.locked)
        label={'manual':'手工修改','deepseek':'DeepSeek 初稿','legacy':'旧译文，来源未记录','empty':'未填写（可选）'}[source['source']]
        self.translation_source.setText(label+(' · 原文已改，请复核' if changed else ' · 已核对' if source['confirmed'] else ''))
        text=self.translation.text()
        try:
            style=self.project.style;font=metric_font(str(resolve_font(style.translation_font_file,style.translation_font)),style.translation_size,style.translation_font);width=text_width(font,text);ratio=round(width/1792*100)
            self.translation_length.setText(f'{len(text)} 字符 · 按当前译文字号约占安全宽度 {ratio}%'+('；较长，可精简译文或调整译文字号。' if width>1792 else '。'))
        except (OSError,ValueError):self.translation_length.setText(f'{len(text)} 字符 · 字体测量暂不可用。')
        blocker=QSignalBlocker(self.translation_confirm);self.translation_confirm.setChecked(source['confirmed'] and not changed);self.translation_confirm.setEnabled(bool(line.translation and not line.locked));del blocker
        proposed=model.suggestion(line);available=bool(proposed and proposed['text']!=line.translation)
        self.translation_draft.setVisible(available);self.accept_translation_button.setVisible(available);self.keep_translation_button.setVisible(available)
        if available:
            self.translation_draft.setPlainText(proposed['text']);self.accept_translation_button.setEnabled(proposed['for_text']==line.text and not line.locked);self.keep_translation_button.setEnabled(not line.locked)
            if proposed['for_text']!=line.text:self.translation_source.setText(self.translation_source.text()+' · 已存建议属于旧原文，当前不可采用')
        self._translation_context={'project':self.project.uid,'line':line.to_dict()}

    def accept_translation(self):
        expected=copy.deepcopy(getattr(self,'_translation_context',{}))
        if not self.flush_edits():return False
        if not self.line or expected.get('project')!=self.project.uid or expected.get('line')!=self.line.to_dict():self.message('本句或译文已变化，旧选择未覆盖；请重新比较。');return False
        if self.line.locked:self.message('本句已锁定，译文保持。');return False
        try:candidate=model.accept_suggestion(self.line)
        except ValueError as error:self.message(str(error));return False
        row=self.current;return self.edit('采用已保存译文建议',lambda p:p.lines.__setitem__(row,candidate))

    def keep_translation(self):
        if not self.flush_edits() or not self.line or self.line.locked:return False
        row=self.current
        def apply(project):project.lines[row].reading_review.pop('translation_suggestion',None)
        return self.edit('保留当前译文',apply)

    def confirm_translation(self,checked):
        if self.refreshing or not self.line or not self.flush_edits() or self.line.locked:return
        row=self.current
        try:candidate=model.confirm(self.line,bool(checked))
        except ValueError as error:self.message(str(error));return
        self.edit('确认译文' if checked else '标记译文待核对',lambda p:p.lines.__setitem__(row,candidate))
