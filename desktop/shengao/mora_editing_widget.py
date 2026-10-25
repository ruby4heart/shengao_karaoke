"""Preview highlight split/merge in the main editor without rewriting readings."""
import copy
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QCheckBox,QPushButton,QTextBrowser
from studio_backend.mora_editing import split,merge,reset
from studio_backend.japanese import morae
from .widgets import TimeEdit,time_text,Collapsible
from .project import file_stamp


class MoraEditingPanel(QWidget):
    applyRequested=Signal(object)
    auditionRequested=Signal(int,int)

    def __init__(self,playhead,parent=None):
        super().__init__(parent);self.playhead=playhead;self.context=None;self.base=None;self.word=self.part=-1;self.candidate=None;self.payload=None;self.loading=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.title=QLabel('选择音节后拆分或合并；只改演唱划分，原文和整词读音保持。');self.title.setTextFormat(Qt.TextFormat.PlainText);self.title.setWordWrap(True);layout.addWidget(self.title)
        self.advanced=QCheckBox('高级：允许在拗音内部按字符拆分');layout.addWidget(self.advanced)
        row=QHBoxLayout();self.cut=QComboBox();self.cut.setMinimumContentsLength(8);self.cut.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);row.addWidget(self.cut,1)
        self.split=QPushButton('预览拆分');row.addWidget(self.split);layout.addLayout(row)
        self.fixed=QCheckBox('用所填时间建立内部人工固定点');layout.addWidget(self.fixed)
        row=QHBoxLayout();self.time=TimeEdit();row.addWidget(self.time,1);self.use_playhead=QPushButton('填入播放点');row.addWidget(self.use_playhead);layout.addLayout(row)
        row=QHBoxLayout();self.merge_end=QComboBox();self.merge_end.setMinimumContentsLength(8);self.merge_end.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);row.addWidget(self.merge_end,1)
        self.merge=QPushButton('预览合并');row.addWidget(self.merge);layout.addLayout(row)
        self.reset=QPushButton('预览本词默认摩拉划分');layout.addWidget(self.reset)
        self.allow_manual=QCheckBox('允许移除本次范围内的人工内部边界');self.allow_manual.setToolTip('原有人工外缘和绿色固定点继续保留；固定点须从原有入口明确解除。');layout.addWidget(self.allow_manual)
        self.allow_gaps=QCheckBox('试听后，允许将本次范围内的空白并入高亮');self.allow_gaps.setToolTip('默认保留真实停顿；仅这次明确选中的合并或重置允许闭合间隔。');layout.addWidget(self.allow_gaps)
        self.compare=QTextBrowser();self.compare.setMinimumWidth(0);self.compare.setMinimumHeight(75);self.compare.setMaximumHeight(130);layout.addWidget(self.compare)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.status)
        row=QHBoxLayout();self.listen=QPushButton('试听这段范围');row.addWidget(self.listen);self.apply=QPushButton('采用这次划分');self.apply.setObjectName('primary');row.addWidget(self.apply);layout.addLayout(row)
        for control,tip in [(self.split,'只预览当前音节的拆分，原文与整词读音保持；采用前不改工程。'),
                            (self.merge,'从所选音节合并到右侧指定终点；人工边界和空白各自说明，固定点不静默移除。'),
                            (self.reset,'预览仅此词组恢复标准摩拉划分；相同边界和其他词组保持，新增内部位置为估算。'),
                            (self.use_playhead,'将当前播放位置填入拆分时间，并明确将该内部位置设为人工固定点；先预览再采用。'),
                            (self.listen,'按当前试听音轨播放预览所涉及范围，并加前后各 120 毫秒；不修改音轨或时间。'),
                            (self.apply,'仅采用本次预览的音节划分，一步撤销；时间恢复待确认，原文、整词读音、读音确认及邻音保持。')]:control.setToolTip(tip)
        self.split.clicked.connect(lambda:self.preview('split'));self.merge.clicked.connect(lambda:self.preview('merge'));self.reset.clicked.connect(lambda:self.preview('reset'))
        self.apply.clicked.connect(self.adopt);self.listen.clicked.connect(self.audition);self.use_playhead.clicked.connect(self.from_playhead);self.advanced.toggled.connect(self.populate_cuts)
        for field in (self.fixed,self.allow_manual,self.allow_gaps):field.toggled.connect(self.invalidate)
        self.time.valueChanged.connect(self.invalidate);self.cut.currentIndexChanged.connect(self.invalidate);self.merge_end.currentIndexChanged.connect(self.invalidate)
        self.time.setEnabled(False);self.fixed.toggled.connect(self.time.setEnabled);self.invalidate()

    def set_line(self,line,word,part,context,raw_ass=False):
        identity={'line':line.to_dict() if line else None,'word':word,'part':part,'context':context,'raw_ass':raw_ass}
        if identity==getattr(self,'identity',None):return
        self.identity=copy.deepcopy(identity);self.loading=True;self.base=copy.deepcopy(line);self.word=word;self.part=part;self.context=copy.deepcopy(context);self.raw_ass=raw_ass
        self.advanced.setChecked(False);self.fixed.setChecked(False);self.allow_manual.setChecked(False);self.allow_gaps.setChecked(False);self.merge_end.clear()
        unit=line.units[word] if line and 0<=word<len(line.units) else None
        item=unit.highlights[part] if unit and 0<=part<len(unit.highlights) else None
        self.mutable=bool(unit and unit.highlights and not line.locked and not unit.locked)
        self.title.setText(f'本词「{unit.text}」· 整词假名「{unit.kana}」'+(f' · 第 {part+1} 段「{item.kana}」' if item else ' · 点上方音节选择拆合起点') if unit else '先选择词组或演唱音节；没有读音时先填写假名、补全音节。')
        if item:
            self.time.setValue(round((item.start+item.end)/20)*10)
            for i in range(part+1,len(unit.highlights)):
                self.merge_end.addItem(f'合并到第 {i+1} 段 · {unit.highlights[i].kana}',i)
        for field in (self.advanced,self.fixed,self.use_playhead):field.setEnabled(self.mutable and item is not None)
        self.time.setEnabled(self.mutable and item is not None and self.fixed.isChecked())
        for field in (self.reset,self.allow_manual,self.allow_gaps):field.setEnabled(self.mutable)
        self.merge_end.setEnabled(self.mutable and self.merge_end.count()>0);self.merge.setEnabled(self.mutable and self.merge_end.count()>0)
        self.loading=False;self.populate_cuts();self.invalidate()

    def populate_cuts(self,*_):
        self.loading=True;self.cut.clear()
        unit=self.base.units[self.word] if self.base and 0<=self.word<len(self.base.units) else None
        item=unit.highlights[self.part] if unit and 0<=self.part<len(unit.highlights) else None
        if item:
            cursor=0;canonical=set()
            for text in morae(item.kana):cursor+=len(text);canonical.add(cursor)
            for cut in range(1,len(item.kana)):
                if cut in canonical or self.advanced.isChecked():self.cut.addItem(item.kana[:cut]+' │ '+item.kana[cut:],cut)
        self.split.setEnabled(bool(getattr(self,'mutable',False) and self.cut.count()));self.cut.setEnabled(self.split.isEnabled());self.loading=False;self.invalidate()

    def invalidate(self,*_):
        if self.loading:return
        self.candidate=None;self.payload=None;self.apply.setEnabled(False);self.listen.setEnabled(False);self.compare.clear()
        text='先预览再采用；新内部位置为估算，明确给定的播放点才固定。'
        if not getattr(self,'mutable',False):text='所选歌词／词组锁定、缺读音或缺音节时不能拆合；先补全或解除目标锁定。'
        elif self.part<0:text='点上方音节选择拆合起点；也可直接预览恢复本词默认摩拉。'
        if getattr(self,'raw_ass',False):text+=' 采用后使用声稿排版，原 ASS 保留，可撤销。'
        self.status.setText(text)

    def from_playhead(self):
        self.time.setValue(int(self.playhead()));self.fixed.setChecked(True);self.invalidate()

    def preview(self,operation):
        self.time.interpretText()
        self.invalidate()
        if not self.base:return
        try:
            options={'word':self.word}
            if operation=='split':
                if self.cut.currentData() is None:raise ValueError('选择可拆分的音节；单个假名请改时长或与邻音合并。')
                options.update(part=self.part,cut=self.cut.currentData(),at=self.time.value() if self.fixed.isChecked() else None,allow_character=self.advanced.isChecked())
                result=split(self.base,**options)
            else:
                options.update(allow_manual=self.allow_manual.isChecked(),allow_gaps=self.allow_gaps.isChecked())
                if operation=='merge':options.update(first=self.part,last=self.merge_end.currentData());result=merge(self.base,**options)
                elif operation=='reset':result=reset(self.base,**options)
                else:raise ValueError('不支持的音节操作')
            self.candidate=result
            def describe(parts):
                return ' · '.join(f'{h.kana} [{time_text(h.start)}–{time_text(h.end)}]'+(' 固定'+('/'.join({'start':'起点','end':'终点'}[edge] for edge in h.fixed_edges)) if h.fixed_edges else '') for h in parts[:32])+(' …' if len(parts)>32 else '')
            self.compare.setPlainText('当前：'+describe(self.base.units[self.word].highlights)+'\n预览：'+describe(result['line'].units[self.word].highlights))
            self.status.setText((f'新增 {result["estimated_new_boundaries"]} 个估算内部位置；移除 {result["removed_manual_boundaries"]} 个人工内部边界；并入 {result["closed_gap_ms"]} ms 空白。采用后时间待确认，读音确认保持。' if result['changed'] else '已是当前划分，不需要采用。')+(' 采用后使用声稿排版，原 ASS 可撤销。' if self.raw_ass else ''))
            self.payload={'context':copy.deepcopy(self.context),'original':self.base.to_dict(),'operation':operation,'options':options,'preview':result['line'].to_dict()}
            self.apply.setEnabled(result['changed']);self.listen.setEnabled(True)
        except (ValueError,TypeError) as error:self.status.setText(str(error))

    def audition(self):
        if self.candidate:
            first,last=self.candidate['selected'];parts=self.candidate['line'].units[self.word].highlights
            self.auditionRequested.emit(max(0,parts[first].start-120),parts[last].end+120)

    def adopt(self):
        if self.payload and self.apply.isEnabled():self.applyRequested.emit(copy.deepcopy(self.payload))


class MoraEditingWorkflow:
    def mora_editing_context(self):
        return {'project':self.project.uid,'media':file_stamp(self.project.media),'line':self.line.id if self.line else None,'reading_confirmed':bool(self.project.checks.get(self.line.id,{}).get('reading')) if self.line else False}

    def build_mora_editing_tools(self,layout):
        self.mora_editing=Collapsible('音节拆分、合并与恢复默认')
        self.mora_editor=MoraEditingPanel(lambda:self.playback.canvas.position)
        self.mora_editing.body.addWidget(self.mora_editor);layout.addWidget(self.mora_editing)
        self.mora_editor.applyRequested.connect(self.apply_mora_edit);self.mora_editor.auditionRequested.connect(lambda a,b:self.playback.audition(a,min(b,self.project.duration) if self.project.duration else b,self.loop.isChecked()))

    def refresh_mora_editing(self):
        if hasattr(self,'mora_editor'):self.mora_editor.set_line(self.line,self.timeline.word,self.timeline.part,self.mora_editing_context(),self.project.source_ass_active)

    def apply_mora_edit(self,payload):
        if not self.flush_edits() or not self.line:return False
        if payload.get('context')!=self.mora_editing_context() or payload.get('original')!=self.line.to_dict():
            self.message('工程、素材、本句或确认已变化，旧音节预览未采用；请重新预览。');self.refresh_mora_editing();return False
        try:
            fn={'split':split,'merge':merge,'reset':reset}.get(payload.get('operation'))
            if fn is None:raise ValueError('音节操作无效')
            result=fn(self.line,**payload['options'])
            if result['line'].to_dict()!=payload.get('preview'):raise ValueError('音节预览与操作参数不一致，原轴保持，请重新预览。')
            if not result['changed']:return False
        except (TypeError,KeyError,ValueError) as error:self.message(str(error));return False
        row=self.current;word=payload['options']['word'];part=result['selected'][0]
        def apply(project):project.lines[row]=copy.deepcopy(result['line']);project.source_ass_active=False
        changed=self.edit('修改演唱音节划分',apply)
        if changed:
            self.granularity.setCurrentIndex(self.granularity.findData('mora'));self.select_target(word,part);self.timeline.focus_selection()
            self.message('音节划分已采用，可一步撤销；原文、整词读音、邻音和读音确认保持。内部估算可继续按歌声重算。')
        return changed
