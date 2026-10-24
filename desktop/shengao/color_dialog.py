"""Draft-only colour editing; the caller owns preview and one-step adoption."""
import copy
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox,QColorDialog,QComboBox,QDialog,QDialogButtonBox,
    QFormLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QScrollArea,QSpinBox,QVBoxLayout,QWidget)
from .color_states import (CHANNELS,PRESETS,default_profile,preset_profile,effective_profile,update_settings,validate_ink,validate_settings)


class InkField(QWidget):
    changed=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self._setting=False
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0)
        self.hex=QLineEdit();self.hex.setMaxLength(7);self.hex.setPlaceholderText('#RRGGBB');self.hex.setMaximumWidth(110)
        self.pick=QPushButton('选色');self.opacity=QSpinBox();self.opacity.setRange(0,100);self.opacity.setSuffix(' % 不透明')
        row.addWidget(self.pick);row.addWidget(self.hex);row.addWidget(self.opacity)
        self.hex.textChanged.connect(self.notify);self.opacity.valueChanged.connect(self.notify);self.pick.clicked.connect(self.choose)
    def value(self):
        value={'color':self.hex.text(),'opacity':self.opacity.value()};validate_ink(value);return value
    def set_value(self,value):
        validate_ink(value);self._setting=True
        try:self.hex.setText(value['color']);self.opacity.setValue(value['opacity']);self.swatch()
        finally:self._setting=False
    def swatch(self):
        if QColor(self.hex.text()).isValid():
            c=QColor(self.hex.text());foreground='#000000' if c.lightness()>140 else '#ffffff'
            self.pick.setStyleSheet('background:'+c.name()+';color:'+foreground+';')
    def notify(self,*args):
        if not self._setting:self.swatch();self.changed.emit()
    def choose(self):
        color=QColorDialog.getColor(QColor(self.hex.text()),self,'选择字幕颜色')
        if color.isValid():self.hex.setText(color.name())


class ColorDialog(QDialog):
    candidateChanged=Signal(dict)
    previewRequested=Signal(str)
    def __init__(self,project,current=-1,selected_ids=(),parent=None,preview_widget=None):
        super().__init__(parent);project.validate();self.setWindowTitle('颜色与演唱状态')
        screen=self.screen().availableGeometry();self.resize(min(800,screen.width()-32),min(760,screen.height()-64))
        self.original=copy.deepcopy(project.color_styles);self.style=copy.deepcopy(project.style);self.result_settings=None
        self._loading=False;self._dirty=False;self._profile=None;self.candidate=copy.deepcopy(self.original)
        valid={v.id for v in project.lines};selected=list(selected_ids)
        if len(selected)!=len(set(selected)) or any(v not in valid for v in selected):raise ValueError('所选配色歌词已变化')
        current_id=project.lines[current].id if 0<=current<len(project.lines) else None
        self.preview_has_units=bool(project.lines[current].units) if current_id else False
        self.targets={'global':None,'current':[current_id] if current_id else [],'selected':selected}
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll)
        title=QLabel('分别设置待唱、演唱中和唱完留屏的颜色。只改配色，歌词、读音和时间保持。');title.setWordWrap(True);layout.addWidget(title)
        self.scope=QComboBox();self.scope.addItem('全曲模板（指定行自定义保持）','global');self.scope.addItem('本句 · 1 句' if current_id else '本句 · 没有选中歌词','current');self.scope.addItem(f'选中歌词 · {len(selected)} 句','selected')
        self.scope.model().item(1).setEnabled(bool(current_id));self.scope.model().item(2).setEnabled(bool(selected));layout.addWidget(self.scope)
        note=QLabel('先选作用范围，再改颜色；切换范围会重置本窗口尚未采用的修改。取消会恢复原配色。');note.setWordWrap(True);layout.addWidget(note)
        if project.source_ass_active:
            warning=QLabel('原 ASS 当前按原样显示。采用新配色后将使用声稿排版；原 ASS 保留，可撤销。');warning.setWordWrap(True);layout.addWidget(warning)
        self.scope_hint=QLabel();self.scope_hint.setWordWrap(True);layout.addWidget(self.scope_hint)
        presets=QHBoxLayout();self.preset=QComboBox()
        for key,title in PRESETS:self.preset.addItem(title,key)
        self.apply_preset=QPushButton('用预设替换当前配色');presets.addWidget(self.preset);presets.addWidget(self.apply_preset);layout.addLayout(presets)
        form=QFormLayout();self.role=QComboBox();self.state=QComboBox()
        for key,label in [('lyrics','正文'),('ruby','假名注音'),('romaji','罗马音'),('translation','译文')]:self.role.addItem(label,key)
        for key,label in [('waiting','待唱'),('singing','演唱中'),('sung','唱完留屏')]:self.state.addItem(label,key)
        form.addRow('文字层',self.role);form.addRow('演唱状态',self.state);self.fields={}
        for key,title in [('primary','文字／扫亮后'),('secondary','尚未扫亮底色'),('outline','描边'),('shadow','阴影')]:
            field=InkField();self.fields[key]=field;form.addRow(title,field);field.changed.connect(self.changed)
        layout.addLayout(form)
        self.explanation=QLabel('次色用于正在演唱时尚未扫亮的正文／假名。罗马音和译文按整句状态变色，不编造逐词时间。');self.explanation.setWordWrap(True);layout.addWidget(self.explanation)
        motion=QFormLayout();self.motion={}
        for key,title,choices in [('fill','文字变色',[('sweep','连续扫亮'),('instant','到达音节时切换')]),('outline','演唱中描边',[('line','整句状态切换'),('sweep','跟随扫亮')]),('shadow','演唱中阴影',[('line','整句状态切换'),('sweep','跟随扫亮')])]:
            combo=QComboBox()
            for value,text in choices:combo.addItem(text,value)
            self.motion[key]=combo;motion.addRow(title,combo);combo.currentIndexChanged.connect(self.changed)
        layout.addLayout(motion);self.box_enabled=QCheckBox('显示独立背景底板');layout.addWidget(self.box_enabled)
        box=QFormLayout();self.box_color=InkField();self.padding=QSpinBox();self.radius=QSpinBox()
        for spin in (self.padding,self.radius):spin.setRange(0,100)
        box.addRow('本状态底板颜色',self.box_color);box.addRow('底板边距',self.padding);box.addRow('底板圆角',self.radius);layout.addLayout(box)
        for signal in (self.box_enabled.toggled,self.box_color.changed,self.padding.valueChanged,self.radius.valueChanged):signal.connect(self.changed)
        if preview_widget is not None:layout.addWidget(preview_widget)
        row=QHBoxLayout()
        for key,title in [('waiting','看待唱'),('middle','看唱到一半'),('sung','看唱完留屏')]:
            button=QPushButton(title);button.clicked.connect(lambda checked=False,value=key:self.previewRequested.emit(value));row.addWidget(button)
        layout.addLayout(row);layout.addStretch()
        self.status=QLabel('尚未采用；修改会先预览。');self.status.setWordWrap(True);outer.addWidget(self.status)
        footer=QHBoxLayout();self.restore=QPushButton();self.reset=QPushButton('重置本次修改');footer.addWidget(self.restore);footer.addWidget(self.reset);footer.addStretch()
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('采用颜色设置');self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');footer.addWidget(self.buttons);outer.addLayout(footer)
        self.scope.currentIndexChanged.connect(self.load_scope);self.role.currentIndexChanged.connect(self.load_layer);self.state.currentIndexChanged.connect(self.load_layer)
        self.restore.clicked.connect(self.restore_inheritance);self.reset.clicked.connect(self.load_scope);self.buttons.accepted.connect(self.accept_changes);self.buttons.rejected.connect(self.reject)
        self.apply_preset.clicked.connect(self.use_preset)
        self.load_scope()
    def ids(self):return self.targets[self.scope.currentData()]
    def load_scope(self,*args):
        ids=self.ids();profile=self.original.get('global') if ids is None and self.original else effective_profile(self.original,ids[0]) if ids else None
        self._profile=copy.deepcopy(profile) if profile is not None else default_profile(self.style)
        mixed=bool(ids and any(effective_profile(self.original,uid)!=effective_profile(self.original,ids[0]) for uid in ids[1:]))
        self.scope_hint.setText('所选歌词当前配色不同：以第一句为起点，采用会统一所选行。' if mixed else '当前范围使用独立配色。' if profile else '当前范围沿用原有模板颜色；未采用前不转换。')
        self.candidate=copy.deepcopy(self.original);self._dirty=False;self.restore.setText('使用原有三色模板' if ids is None else '恢复继承全曲模板');self.load_layer();self.status.setText('尚未采用；只修改当前所示范围。');self.candidateChanged.emit(copy.deepcopy(self.candidate))
    def load_layer(self,*args):
        self._loading=True
        try:
            role,state=self.role.currentData(),self.state.currentData()
            hidden=role!='lyrics' and not getattr(self.style,{'ruby':'show_ruby','romaji':'show_romaji','translation':'show_translation'}[role])
            note='该文字层当前在样式中关闭，开启显示后才可看到。' if hidden else ''
            if not self.preview_has_units:note+='当前句未分词，先按整句状态变色；分词打轴后才可扫亮。'
            self.explanation.setText(note+'次色用于演唱中尚未扫亮的正文／假名。罗马音和译文按整句状态变色，不编造逐词时间。')
            for key in CHANNELS:self.fields[key].set_value(self._profile['layers'][role][state][key])
            self.fields['secondary'].setEnabled(state=='singing' and role in {'lyrics','ruby'})
            for key,combo in self.motion.items():combo.setCurrentIndex(combo.findData(self._profile['motion'][key]))
            box=self._profile['box'];self.box_enabled.setChecked(box['enabled']);self.box_color.set_value(box['states'][state]);self.padding.setValue(box['padding']);self.radius.setValue(box['radius'])
            self.set_valid(True)
        finally:self._loading=False
    def set_valid(self,value):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(value);self.role.setEnabled(value);self.state.setEnabled(value)
    def changed(self,*args):
        if self._loading:return
        try:
            channels={key:self.fields[key].value() for key in CHANNELS};box_color=self.box_color.value()
            role,state=self.role.currentData(),self.state.currentData();profile=copy.deepcopy(self._profile)
            profile['layers'][role][state]=channels;profile['motion']={key:combo.currentData() for key,combo in self.motion.items()}
            profile['box'].update(enabled=self.box_enabled.isChecked(),padding=self.padding.value(),radius=self.radius.value());profile['box']['states'][state]=box_color
            candidate=update_settings(self.original,profile,self.ids());validate_settings(candidate)
        except ValueError as error:self.set_valid(False);self.status.setText(str(error)+'；请修正后采用，原工程保持。');return
        self._profile=profile;self.candidate=candidate;self._dirty=True;self.set_valid(True);self.status.setText('临时预览，尚未采用；采用后可一步撤销。');self.candidateChanged.emit(copy.deepcopy(candidate))
    def restore_inheritance(self):
        self.candidate=update_settings(self.original,None,self.ids());self._dirty=True
        global_profile=self.original.get('global') if self.original and self.ids() is not None else None
        self._profile=copy.deepcopy(global_profile) if global_profile is not None else default_profile(self.style);self.load_layer();self.status.setText('将恢复继承，尚未采用。');self.candidateChanged.emit(copy.deepcopy(self.candidate))
    def use_preset(self):
        self._profile=preset_profile(self.style,self.preset.currentData());self.load_layer();self.changed()
    def accept_changes(self):
        validate_settings(self.candidate);self.result_settings=copy.deepcopy(self.candidate);self.accept()
