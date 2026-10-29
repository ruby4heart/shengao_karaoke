"""Edit a private key-profile draft; apply only after validation and saving."""
from pathlib import Path
import json
from PySide6.QtCore import Qt,QEvent,Signal,QSignalBlocker
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,
    QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QPushButton,QCheckBox,
    QDialogButtonBox,QPlainTextEdit,QFileDialog,QScrollArea,QWidget)
from studio_backend.settings import atomic_json
from .audio_shortcuts import Profile,COMMANDS,CONTEXTS,event_key,normalise_key,import_preview


def display_key(key):
    return key.replace('Num+Return','小键盘 Enter').replace('Return','主键盘 Enter').replace('Num+','小键盘 ')


def note(text):
    label=QLabel(text);label.setWordWrap(True);label.setTextFormat(Qt.TextFormat.PlainText);return label


def push(text,slot):
    b=QPushButton(text);b.setAutoDefault(False);b.clicked.connect(slot);return b


class KeyCapture(QLineEdit):
    captured=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.value=None;self.setReadOnly(True)
        self.setPlaceholderText('点击这里，按下新快捷键；Esc清除录入')
        self.setAccessibleName('录入快捷键')

    def event(self,event):
        if event.type()==QEvent.Type.ShortcutOverride:event.accept();return True
        return super().event(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.value=None;self.clear();self.captured.emit('');event.accept();return
        if event.isAutoRepeat():event.accept();return
        value=event_key(event)
        if value:
            self.value=value;self.setText(display_key(value));self.captured.emit(value)
        else:self.value=None;self.clear();self.captured.emit('')
        event.accept()


class ImportReview(QDialog):
    def __init__(self,preview,parent=None):
        super().__init__(parent);self.setWindowTitle('核对要导入的键位');self.resize(640,460)
        layout=QVBoxLayout(self);layout.addWidget(note('先载入编辑草稿，确认并保存后才会启用。未提到的Aegisub命令保留当前键位。'))
        details=[]
        if preview.ignored_contexts:details.append('其他窗口上下文（不导入）：\n'+'、'.join(preview.ignored_contexts))
        if preview.unsupported:details.append('未支持的命令或按键（不导入）：\n'+'\n'.join(preview.unsupported))
        text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText('\n\n'.join(details) or '此配置的命令与按键均受支持。');layout.addWidget(text,1)
        self.acknowledge=QCheckBox('我已核对，仅载入受支持的音频键位');self.acknowledge.setVisible(preview.needs_acknowledgement);layout.addWidget(self.acknowledge)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('载入草稿')
        controls.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not preview.needs_acknowledgement)
        self.acknowledge.toggled.connect(lambda value:controls.button(QDialogButtonBox.StandardButton.Ok).setEnabled(value))
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)


class AudioShortcutDialog(QDialog):
    def __init__(self,profile,reserved,commit,parent=None):
        super().__init__(parent);self.setWindowTitle('打轴快捷键设置');self.resize(820,720);self.setMinimumSize(540,480)
        self.reserved=reserved;self.commit=commit;self.edited=profile.to_data();self.original=Profile.defaults().to_data();self.selected=None;self.accepted_profile=None
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);self.body=QWidget();layout=QVBoxLayout(self.body);scroll.setWidget(self.body);outer.addWidget(scroll,1);self.scroll=scroll
        layout.addWidget(note('默认与Aegisub 3.5.0的音频键位一致。选择命令录入按键；主键盘和小键盘分别记录。修改先留在这里，点“保存并启用”才生效。'))
        row=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('搜索操作或按键');row.addWidget(self.search,1)
        self.context=QComboBox();self.context.addItem('时间轴获得焦点','Audio');self.context.addItem('Medusa主窗口模式','Always');row.addWidget(self.context);layout.addLayout(row)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['操作','当前按键','原版默认']);self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(180)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);layout.addWidget(self.table,1)
        self.selected_label=note('选择一个操作');layout.addWidget(self.selected_label)
        row=QHBoxLayout();self.capture=KeyCapture();row.addWidget(self.capture,1);self.add_button=push('添加按键',self.add_captured);row.addWidget(self.add_button);layout.addLayout(row)
        row=QHBoxLayout();self.existing=QComboBox();self.existing.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.existing.setMinimumContentsLength(8);row.addWidget(self.existing,1);self.remove_button=push('移除此键',self.remove_selected_key);row.addWidget(self.remove_button)
        self.reset_row_button=push('本项恢复默认',self.reset_selected);row.addWidget(self.reset_row_button);layout.addLayout(row)
        self.medusa=QCheckBox('启用Medusa：小键盘在主窗口其他区域也能打轴');self.medusa.setChecked(profile.medusa);layout.addWidget(self.medusa)
        self.protect=QCheckBox('在文字、时间和表格编辑框内暂停Medusa键位');self.protect.setChecked(profile.protect_text);layout.addWidget(self.protect)
        layout.addWidget(note('不勾选输入保护时使用原版Always兼容行为；输入法正在组词时仍暂停打轴。弹窗内不触发主窗口打轴。'))
        row=QHBoxLayout();row.addWidget(push('导入配置…',self.import_dialog));row.addWidget(push('导出配置…',self.export_dialog));row.addWidget(push('全部恢复原版默认',self.reset_all));layout.addLayout(row)
        self.status=note('');self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);layout.addWidget(self.status)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.save_button=controls.button(QDialogButtonBox.StandardButton.Save);self.save_button.setText('保存并启用');self.save_button.setAutoDefault(False)
        controls.accepted.connect(self.apply);controls.rejected.connect(self.reject);outer.addWidget(controls)
        self.search.textChanged.connect(self.rebuild);self.context.currentIndexChanged.connect(self.rebuild);self.table.itemSelectionChanged.connect(self.selection_changed)
        self.medusa.toggled.connect(self.validate);self.protect.toggled.connect(self.validate);self.rebuild()
        self.capture.captured.connect(lambda value:self.add_button.setEnabled(bool(value and self.selected)))

    def candidate(self):
        data={**self.edited,'medusa':self.medusa.isChecked(),'protect_text':self.protect.isChecked()}
        return Profile.from_data(data)

    def rebuild(self,*args):
        previous=self.selected;context=self.context.currentData();query=self.search.text().casefold().strip()
        blocker=QSignalBlocker(self.table);self.table.setRowCount(0)
        for command,(_,title) in COMMANDS.items():
            keys=self.edited['contexts'][context].get(command,[]);defaults=self.original['contexts'][context].get(command,[])
            if query and query not in (title+' '+command+' '+' '.join(keys)).casefold():continue
            row=self.table.rowCount();self.table.insertRow(row)
            for column,value in enumerate((title,' / '.join(map(display_key,keys)) or '未设置',' / '.join(map(display_key,defaults)) or '未设置')):
                item=QTableWidgetItem(value);item.setData(Qt.ItemDataRole.UserRole,(context,command));self.table.setItem(row,column,item)
            if previous==(context,command):self.table.selectRow(row)
        if self.table.currentRow()<0 and self.table.rowCount():self.table.selectRow(0)
        del blocker;self.selection_changed();self.validate()

    def selection_changed(self):
        row=self.table.currentRow();self.selected=tuple(self.table.item(row,0).data(Qt.ItemDataRole.UserRole)) if row>=0 else None
        self.existing.clear()
        if self.selected:
            context,command=self.selected;self.selected_label.setText(COMMANDS[command][1]+' · '+('时间轴焦点' if context=='Audio' else 'Medusa主窗口'))
            for key in self.edited['contexts'][context].get(command,[]):self.existing.addItem(display_key(key),key)
        else:self.selected_label.setText('没有匹配的操作')
        for control in (self.capture,self.reset_row_button):control.setEnabled(self.selected is not None)
        self.add_button.setEnabled(bool(self.selected and self.capture.value))
        self.remove_button.setEnabled(self.existing.count()>0)

    def set_binding(self,context,command,keys):
        candidate=self.candidate().to_data();candidate['contexts'][context][command]=list(keys)
        validated=Profile.from_data(candidate);self.edited=validated.to_data();self.selected=(context,command);self.rebuild()

    def add_captured(self):
        if not self.selected or not self.capture.value:return
        context,command=self.selected;keys=list(self.edited['contexts'][context].get(command,[]))
        try:self.set_binding(context,command,[*keys,self.capture.value])
        except ValueError as error:self.status.setText(str(error))

    def remove_selected_key(self):
        if self.selected and self.existing.currentData():
            context,command=self.selected;key=self.existing.currentData()
            self.set_binding(context,command,[v for v in self.edited['contexts'][context].get(command,[]) if v!=key])

    def reset_selected(self):
        if self.selected:
            context,command=self.selected;self.set_binding(context,command,self.original['contexts'][context].get(command,[]))

    def reset_all(self):
        self.edited=Profile.defaults(protect_text=self.protect.isChecked(),medusa=self.medusa.isChecked()).to_data();self.rebuild()

    def validate(self,*args):
        try:
            profile=self.candidate();conflicts=profile.conflicts(self.reserved)
            text='\n'.join(display_key(c.key)+'：'+'、'.join(COMMANDS[v][1] for v in c.commands)+('／'+c.reserved if c.reserved else '') for c in conflicts)
            self.status.setText('请先解决冲突（包括Medusa开启时）：\n'+text if conflicts else '没有冲突。保存后启用；取消会保留当前使用的配置。')
            self.save_button.setEnabled(not conflicts);return not conflicts
        except ValueError as error:self.status.setText(str(error));self.save_button.setEnabled(False);return False

    def review_import(self,preview):
        dialog=ImportReview(preview,self)
        return dialog.exec()==QDialog.DialogCode.Accepted and (not preview.needs_acknowledgement or dialog.acknowledge.isChecked())

    def import_file(self,path):
        path=Path(path)
        with path.open('rb') as stream:raw=stream.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('配置文件过大，最多1MiB')
        preview=import_preview(json.loads(raw.decode('utf-8-sig')),self.candidate())
        if not self.review_import(preview):return False
        draft=preview.to_draft(acknowledge_unsupported=True);self.edited=draft.to_data()
        self.medusa.setChecked(draft.medusa);self.protect.setChecked(draft.protect_text);self.rebuild();return True

    def export_file(self,path):
        profile=self.candidate();profile.require_ready(self.reserved);atomic_json(Path(path),profile.to_data())

    def import_dialog(self):
        path,_=QFileDialog.getOpenFileName(self,'导入声稿或Aegisub键位配置','','JSON配置 (*.json)')
        if path:
            try:self.import_file(path)
            except (OSError,ValueError) as error:self.status.setText('未导入：'+str(error))

    def export_dialog(self):
        path,_=QFileDialog.getSaveFileName(self,'导出打轴键位','声稿快捷键.json','JSON配置 (*.json)')
        if path:
            try:self.export_file(path)
            except (OSError,ValueError) as error:self.status.setText('未导出：'+str(error))

    def apply(self):
        try:
            profile=self.candidate();profile.require_ready(self.reserved);self.commit(profile)
        except (OSError,ValueError) as error:self.status.setText('未启用，原配置保留：'+str(error));return
        self.accepted_profile=profile;self.accept()
