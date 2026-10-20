"""Video-only entry: review recognized wording before it becomes source lyrics."""
import copy
from pathlib import Path
from PySide6.QtCore import Qt,QSignalBlocker,QTimer,Signal,QEvent
from PySide6.QtGui import QKeySequence,QShortcut
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QLineEdit,
    QPlainTextEdit,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QDialogButtonBox,QWidget,QScrollArea)
from studio_backend import recognition
from studio_backend.model import LyricLine
from .dialogs import button
from .project import file_stamp
from .timeline import stamp


def note(text):
    widget=QLabel(text);widget.setTextFormat(Qt.TextFormat.PlainText);widget.setWordWrap(True);return widget


class RecognitionChoiceDialog(QDialog):
    def __init__(self,parent,reusable):
        super().__init__(parent);self.setWindowTitle('先识别歌词初稿');self.resize(570,350);layout=QVBoxLayout(self)
        layout.addWidget(note('没有原歌词时，先得到一份待确认文字。识别可能漏字、错字或混入伴奏内容；先核对原文，再做注音和时间校准。'))
        self.mode=QComboBox();self.mode.addItem('使用本工程已有识别 · 不重新上传','reuse');self.mode.addItem('联网识别音轨 · 使用服务额度','cloud')
        self.mode.model().item(0).setEnabled(reusable);self.mode.setCurrentIndex(0 if reusable else 1);layout.addWidget(self.mode)
        self.provider=QComboBox();self.provider.addItem('ElevenLabs · Scribe','elevenlabs');self.provider.addItem('Microsoft AI','mai');layout.addWidget(self.provider)
        self.mode.currentIndexChanged.connect(lambda _:self.provider.setVisible(self.mode.currentData()=='cloud'));self.provider.setVisible(not reusable)
        layout.addWidget(note('联网会上传音轨，请先在“服务设置”配置所选服务。程序不自动重试未拿到结果的请求；已有结果可反复本地使用。'))
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('准备待确认初稿');controls.button(QDialogButtonBox.StandardButton.Cancel).setText('暂不识别')
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)


class RecognitionDialog(QDialog):
    draftChanged=Signal(dict)
    def __init__(self,parent,value,raw,playback,duration=0):
        super().__init__(parent);recognition.validate(value,raw);self.setWindowTitle('核对识别原文 · 读音和时间稍后校准');self.resize(min(920,max(760,parent.width()-24)),min(690,max(520,parent.height()-24)))
        self.value=copy.deepcopy(value);self.raw=copy.deepcopy(raw);self.playback=playback;self.duration=duration
        self.confirmed=False;self.index=0 if value['rows'] else -1;self.undo_stack=[];self.redo_stack=[];self.merge_key=None;self.refreshing=False
        self.old_speed=playback.player.playbackRate();self.old_loop=playback.loop
        self.change_timer=QTimer(self);self.change_timer.setSingleShot(True);self.change_timer.setInterval(350);self.change_timer.timeout.connect(self.flush)
        outer=QVBoxLayout(self);outer.addWidget(note('这是待确认文字，不会直接成为字幕。先听、改字和分行，核对好了再加入歌词。日语识别空格已收拢，英文空格与之后手工输入的空格保留。'))
        self.controls_scroll=QScrollArea();self.controls_scroll.setWidgetResizable(True);self.controls_scroll.setMinimumSize(0,0);body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(0,0,0,0);layout.setSpacing(6);self.controls_scroll.setWidget(body);outer.addWidget(self.controls_scroll,1)
        self.table=QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['识别参考范围','待确认原文']);self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.setMinimumHeight(120);layout.addWidget(self.table,1)
        self.editor=QLineEdit();self.editor.setPlaceholderText('在这里改字；将光标放在两句之间，再点“拆句”');layout.addWidget(self.editor)
        self.editor.installEventFilter(self)
        row=QHBoxLayout();self.split_button=button('在光标处拆句',self.split_current);self.merge_button=button('与下一句合并',self.merge_current);self.add_button=button('添加一句',self.insert_current);self.delete_button=button('删除此句',self.delete_current)
        for widget in [self.split_button,self.merge_button,self.add_button,self.delete_button]:row.addWidget(widget)
        layout.addLayout(row);self.original=QPlainTextEdit();self.original.setReadOnly(True);self.original.setMaximumHeight(68);self.original.setPlaceholderText('原始识别文字会显示在这里，不会被改写');layout.addWidget(self.original)
        row=QHBoxLayout();self.listen_button=button('试听这一句',lambda:self.listen(False));self.context_button=button('带前后试听',lambda:self.listen(True));row.addWidget(self.listen_button);row.addWidget(self.context_button);row.addWidget(button('停止',playback.stop))
        self.loop=QCheckBox('循环');row.addWidget(self.loop);self.speed=QComboBox()
        for value in [1.,.75,.5]:self.speed.addItem(f'{value:g}×',value)
        self.speed.setCurrentIndex(max(0,self.speed.findData(self.old_speed)))
        row.addWidget(self.speed);layout.addLayout(row)
        row=QHBoxLayout();self.undo_button=button('撤销修改',self.undo);self.redo_button=button('重做修改',self.redo);row.addWidget(self.undo_button);row.addWidget(self.redo_button);row.addWidget(button('还原识别文字',self.reset));layout.addLayout(row)
        self.notice=note('改字和拆合句子在本地完成。拆句范围可能是估算；加入后仍需试听校轴。稍后继续会保留这些修改。');layout.addWidget(self.notice)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Close);self.confirm_button=controls.button(QDialogButtonBox.StandardButton.Ok);self.confirm_button.setText('原文核对好了，加入歌词');controls.button(QDialogButtonBox.StandardButton.Close).setText('稍后继续')
        controls.accepted.connect(self.confirm);controls.rejected.connect(self.reject);outer.addWidget(controls)
        self.table.currentCellChanged.connect(self.select_row);self.editor.textEdited.connect(self.edit_text);self.speed.currentIndexChanged.connect(lambda _:self.playback.player.setPlaybackRate(self.speed.currentData()))
        self.finished.connect(self.finish)
        for key,fn in [('Ctrl+Z',self.undo),('Ctrl+Y',self.redo)]:shortcut=QShortcut(QKeySequence(key),self);shortcut.activated.connect(fn)
        self.refresh()

    def flush(self):
        if self.change_timer.isActive():self.change_timer.stop()
        self.draftChanged.emit(copy.deepcopy(self.value))

    def commit(self,value,key=None):
        try:recognition.validate(value,self.raw)
        except (ValueError,IndexError,KeyError) as error:self.notice.setText(str(error));return False
        if value==self.value:return False
        if key is None or key!=self.merge_key:self.undo_stack.append(copy.deepcopy(self.value))
        self.undo_stack=self.undo_stack[-100:];self.redo_stack=[];self.merge_key=key;self.value=copy.deepcopy(value);self.refresh()
        if key:self.change_timer.start()
        else:self.flush()
        return True

    def refresh(self):
        self.refreshing=True
        try:
            rows=self.value['rows'];self.index=max(0,min(self.index,len(rows)-1)) if rows else -1
            block=QSignalBlocker(self.table);self.table.setRowCount(len(rows))
            for i,row in enumerate(rows):
                for j,text in enumerate([f'{stamp(row["start"])} — {stamp(row["end"])}',row['text']]):
                    item=QTableWidgetItem(text);item.setToolTip('识别粗范围' if row['range_source']=='recognition' else '参考范围为估算，稍后校轴');self.table.setItem(i,j,item)
            if self.index>=0:self.table.setCurrentCell(self.index,1)
            self.refresh_selected();self.undo_button.setEnabled(bool(self.undo_stack));self.redo_button.setEnabled(bool(self.redo_stack))
            self.confirm_button.setEnabled(bool(rows) and all(r['text'].strip() for r in rows))
        finally:self.refreshing=False

    def refresh_selected(self):
        valid=0<=self.index<len(self.value['rows']);row=self.value['rows'][self.index] if valid else None
        if self.editor.text()!=(row['text'] if row else ''):self.editor.setText(row['text'] if row else '')
        self.original.setPlainText('原始识别：'+recognition.source_text(row,self.raw) if row and row['spans'] else '手工补充：没有对应的识别原文。')
        for widget in [self.editor,self.split_button,self.delete_button,self.listen_button,self.context_button]:widget.setEnabled(valid)
        self.merge_button.setEnabled(valid and self.index<len(self.value['rows'])-1)

    def select_row(self,row,*args):
        if self.refreshing:return
        self.flush();self.index=row;self.merge_key=None;self.refresh_selected()

    def edit_text(self,text):
        if self.refreshing or self.index<0:return
        value=copy.deepcopy(self.value);value['rows'][self.index]['text']=text;self.commit(value,'text:'+value['rows'][self.index]['id'])

    def split_current(self):
        position=len(self.editor.text().encode('utf-16-le')[:self.editor.cursorPosition()*2].decode('utf-16-le',errors='ignore'))
        try:self.commit(recognition.split(self.value,self.index,position,self.raw))
        except (ValueError,IndexError,KeyError) as error:self.notice.setText(str(error))

    def merge_current(self):
        try:self.commit(recognition.merge(self.value,self.index,self.raw))
        except (ValueError,IndexError,KeyError) as error:self.notice.setText(str(error))

    def insert_current(self):
        value=recognition.insert(self.value,self.index,self.raw);self.index=max(0,self.index+1);self.commit(value);self.editor.setFocus()

    def delete_current(self):
        if self.index<0:return
        value=copy.deepcopy(self.value);del value['rows'][self.index];self.commit(value)

    def reset(self):
        value=recognition.create(self.raw,self.value['media_stamp'],self.value.get('media_fingerprint',''));value['id']=self.value['id'];self.commit(value)

    def undo(self):
        if not self.undo_stack:return
        self.redo_stack.append(self.value);self.value=self.undo_stack.pop();self.merge_key=None;self.refresh();self.flush()

    def redo(self):
        if not self.redo_stack:return
        self.undo_stack.append(self.value);self.value=self.redo_stack.pop();self.merge_key=None;self.refresh();self.flush()

    def listen(self,context):
        if self.index<0:return
        row=self.value['rows'][self.index];start=max(0,row['start']-(350 if context else 0));end=row['end']+(350 if context else 0)
        duration=self.duration or self.playback.player.duration()
        if duration>0:end=min(end,duration)
        if end<=start:self.notice.setText('此参考范围超出素材；可先改原文，加入后在时间轴校准');return
        self.playback.player.setPlaybackRate(self.speed.currentData())
        self.playback.audition(start,end,self.loop.isChecked())

    def eventFilter(self,obj,event):
        if obj is self.editor and event.type() in (QEvent.Type.ShortcutOverride,QEvent.Type.KeyPress):
            undo=event.matches(QKeySequence.StandardKey.Undo);redo=event.matches(QKeySequence.StandardKey.Redo)
            if undo or redo:
                event.accept()
                if event.type()==QEvent.Type.KeyPress:(self.undo if undo else self.redo)()
                return True
        return super().eventFilter(obj,event)

    def confirm(self):
        try:recognition.validate(self.value,self.raw,require_text=True)
        except ValueError as error:self.notice.setText(str(error));return
        self.flush();self.confirmed=True;self.accept()

    def finish(self,*args):
        self.flush();self.playback.stop();self.playback.player.setPlaybackRate(self.old_speed);self.playback.loop=self.old_loop


class RecognitionWorkflow:
    def build_recognition_entry(self,layout,prepare=False):
        widget=button('没有原歌词？先识别初稿…',self.begin_recognition)
        widget.setToolTip('选择 ElevenLabs 或 Microsoft AI 识别音轨，或复用已有转录；先核对文字，再生成可编辑粗轴。联网会使用服务额度。')
        layout.addWidget(widget)
        if prepare:self.recognition_prepare_button=widget
        else:
            self.recognition_generate_button=widget;self.recognition_hint=note('');layout.addWidget(self.recognition_hint)
            self.recognition_discard_button=button('放弃这份原文草稿',self.discard_recognition);self.recognition_discard_button.setToolTip('只放弃未确认的文字修改；原始转录保留，可重新准备，操作可以撤销。');layout.addWidget(self.recognition_discard_button)

    def refresh_recognition(self):
        p=self.project;available=bool(p.media and Path(p.media).is_file() and not p.lines);idle=not self.api.busy and not self.source_job
        for widget in [self.recognition_prepare_button,self.recognition_generate_button]:
            widget.setVisible(not p.lines);widget.setEnabled(available and idle);widget.setText('继续核对识别原文…' if p.recognition_draft else '没有原歌词？先识别初稿…')
            widget.setToolTip('在本机继续改字、拆合句子与试听，原始转录保留；不重新上传音轨。' if p.recognition_draft else '先得到待确认识别文字，核对后再加入歌词；可复用已有转录，或选择联网并使用服务额度。')
        self.recognition_generate_button.setObjectName('primary' if not p.lines else '')
        draft=p.recognition_draft
        self.recognition_hint.setVisible(bool(draft and not p.lines));self.recognition_hint.setText(f'{len(draft.get("rows",[]))} 句识别原文待核对；尚未成为歌词。可保存工程后继续。' if draft else '')
        self.recognition_discard_button.setVisible(bool(draft and not p.lines));self.recognition_discard_button.setEnabled(idle)

    def begin_recognition(self):
        if not self.flush_edits():return
        if self.api.busy or self.source_job:self.message('请等待当前后台任务完成');return
        if self.project.lines:self.message('已有原歌词时以原文为准，可直接生成初稿或复用转录匹配');return
        if not self.project.media or not Path(self.project.media).is_file():self.message('请先添加有效的视频或音频');return
        if self.project.recognition_draft:self.review_recognition();return
        reusable=bool(self.project.transcript and self.project.transcript_stamp==file_stamp(self.project.media))
        dialog=RecognitionChoiceDialog(self,reusable)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        if dialog.mode.currentData()=='reuse':
            if not reusable:self.message('已有识别不对应当前素材，请重新选择来源');return
            try:value=recognition.create(self.project.transcript,self.project.transcript_stamp,self.project.transcript_fingerprint)
            except (ValueError,TypeError,KeyError):self.message('已有转录无法准备原文草稿，请从任务记录检查结果');return
            if self.edit('准备待确认的识别原文',lambda p:setattr(p,'recognition_draft',value)):
                self.save_recovery();self.set_stage(1);self.review_recognition()
            return
        context={'project':self.project.uid,'media':file_stamp(self.project.media)}
        self.api.start({'action':'transcribe','lines':[],'media':self.project.media,'provider':dialog.provider.currentData(),
                        'language':'ja','_studio_context':context,'_recognition_entry':True})
        self.set_stage(1);self.message('正在识别音轨；文字先进入待确认草稿，不会自动加入字幕。')

    def review_recognition(self):
        if not self.flush_edits() or self.api.busy or self.source_job:return
        p=self.project;value=p.recognition_draft
        if p.lines or not value:self.message('目前没有待确认识别稿；已有原歌词可以直接进入分词与校准');return
        context=(p.uid,file_stamp(p.media),value['id'],value['source_hash'])
        if value['media_stamp']!=context[1]:self.message('请切回这份识别稿对应的素材，再核对原文');return
        dialog=RecognitionDialog(self,value,p.transcript,self.playback,p.duration)
        def save(value):
            current=self.project.recognition_draft
            if (self.project.uid,file_stamp(self.project.media),current.get('id'),current.get('source_hash'))!=context:return
            if self.edit('修改待确认识别原文',lambda p:setattr(p,'recognition_draft',value),merge_key='recognition:'+value['id']):self.save_recovery()
        dialog.draftChanged.connect(save);dialog.exec()
        if dialog.confirmed:self.confirm_recognition()

    def confirm_recognition(self):
        if self.api.busy or self.source_job or self.project.lines or not self.project.recognition_draft:return
        p=self.project;value=copy.deepcopy(p.recognition_draft)
        try:recognition.validate(value,p.transcript,require_text=True)
        except ValueError as error:self.message(str(error));return
        self.api.start({'action':'confirm_recognition','media':p.media,'transcript':copy.deepcopy(p.transcript),
            'recognition_draft':value,'_text_confirmed_by_user':True,
            '_studio_context':{'project':p.uid,'media':file_stamp(p.media)}})
        self.message('在本机按核对后的原文生成粗稿，不重新上传；原文草稿仍保留到成功加入。')

    def handle_recognition_result(self,result,request,folder=None):
        if not self.flush_edits(allow_segmentation=True):self.message('结果已保存在任务记录，请先处理当前输入');return
        context=request.get('_studio_context',{})
        if context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media):
            self.message('任务对应的工程或素材已变化，结果仍保存在任务记录，没有写入当前工程');return
        if request['action']=='transcribe':
            if self.project.recognition_draft:self.message('已有正在核对的识别稿；新结果保存在任务记录，没有替换当前草稿');return
            try:
                raw=[LyricLine.from_dict(x).to_dict() for x in result.get('suggestions',[])]
                if not raw:self.message('没有识别到可用文字；可以准备原歌词，或检查音轨后手动重试');return
                fingerprint=result.get('media_fingerprint','')
                value=recognition.create(raw,context['media'],fingerprint) if not self.project.lines else {}
                def keep(p):p.transcript=raw;p.transcript_stamp=copy.deepcopy(context['media']);p.transcript_fingerprint=fingerprint;p.recognition_draft=value
                if not self.edit('保留待确认的识别原文' if value else '保留原始转录',keep):return
                self.save_recovery()
                if value:self.set_stage(1)
                self.message('识别原文已保留，点击“继续核对识别原文”；核对后才加入歌词。' if value else '已保留识别结果，现有原歌词保持；可以本地匹配，无需再次上传。')
            except (ValueError,TypeError,KeyError) as error:self.message('识别结果无法生成原文草稿；结果在任务记录，原工程保持。')
            return
        value=request.get('recognition_draft',{});current=self.project.recognition_draft
        if self.project.lines or not current or recognition.signature(current)!=recognition.signature(value):
            self.message('原文草稿已修改或已经有歌词，旧结果没有覆盖当前内容；可从任务记录查看');return
        if not request.get('_text_confirmed_by_user') or not result.get('text_confirmed') or result.get('draft_hash')!=recognition.signature(value):
            self.message('此结果缺少完整原文确认记录，未加入歌词');return
        try:
            rows=[LyricLine.from_dict(x) for x in result['suggestions']]
            if [(x.id,x.text) for x in rows]!=[(x['id'],x['text']) for x in value['rows']] or any(x.reviewed or x.locked for x in rows):raise ValueError('本地结果与已核对原文不符')
            def apply(p):p.lines=rows;p.recognition_draft={};p.source_ass_active=False;p.checks.update({x.id:{'reading':False} for x in rows})
            if self.edit('将核对原文加入歌词',apply,True):
                self.current=0;self.set_stage(2);self.seek_selection_preview();self.save_recovery();self.message('原文已加入歌词，接着试听假名与时间；两项都尚未确认。Ctrl+Z 可恢复原文草稿。')
        except (ValueError,KeyError,TypeError) as error:self.message('本地结果不能安全加入，原文草稿保留；可以继续手工修改。')

    def discard_recognition(self):
        if self.api.busy or self.source_job:return
        if self.edit('放弃待确认识别原文',lambda p:setattr(p,'recognition_draft',{})):
            self.save_recovery();self.message('未确认文字修改已放弃，原始识别仍可复用；Ctrl+Z 可撤销。')

    def restore_recognition_result(self,request,result,folder):
        if self.api.busy or self.source_job:self.message('请先等待当前后台任务结束');return
        if request['action']=='transcribe':self.handle_recognition_result(result,request,folder);return
        context=request.get('_studio_context',{})
        if context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media):self.message('请先打开原工程及对应素材，再恢复识别原文');return
        if self.project.lines or self.project.recognition_draft:self.message('当前已有歌词或原文草稿，旧任务不会替换它们');return
        try:
            value=copy.deepcopy(request['recognition_draft']);raw=copy.deepcopy(request['transcript']);recognition.validate(value,raw)
            def restore(p):p.transcript=raw;p.transcript_stamp=value['media_stamp'];p.transcript_fingerprint=value.get('media_fingerprint','');p.recognition_draft=value
            if self.edit('恢复已核对的原文草稿',restore):self.save_recovery();self.set_stage(1);self.review_recognition()
        except (ValueError,KeyError,TypeError):self.message('此任务原文草稿不完整，没有写入当前工程')
