"""Edit one clearly named dictionary draft; source data changes only on save."""
import copy,json
from pathlib import Path
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,QPushButton,QDialogButtonBox,QFileDialog,QApplication
from studio_backend.analysis import kana_only
from studio_backend.reading_dictionary import validate,merge
from studio_backend.settings import atomic_json


class DictionaryDialog(QDialog):
    def __init__(self,document,scope,parent=None,blocked_exports=()):
        super().__init__(parent);validate(document);self.original=copy.deepcopy(document);self.document=None;self.blocked={Path(p).resolve() for p in blocked_exports if p}
        self.setWindowTitle('本歌读音词典' if scope=='song' else '个人读音词典 · 跨工程复用');screen=QApplication.primaryScreen().availableGeometry();self.resize(min(800,screen.width()-30),min(620,screen.height()-40))
        root=QVBoxLayout(self);intro=QLabel('本歌条目随工程保存，可用主界面撤销。' if scope=='song' else '个人条目仅保存在本机，不随工程或发行包分享。保存后可撤销本次个人词典保存。');intro.setWordWrap(True);root.addWidget(intro)
        note=QLabel('每行保存原文、实际假名和备注。同一原文可有多个唱法，候选需要再试听；这里不会修改歌词或时间。');note.setWordWrap(True);root.addWidget(note)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['原文','假名读音','备注（可选）']);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);root.addWidget(self.table,1)
        row=QHBoxLayout();self.add=QPushButton('新增条目');self.add.setToolTip('在草稿中增加一行原文与实际日语假名，保存前不影响词典。');self.add.clicked.connect(self.append);row.addWidget(self.add)
        self.delete=QPushButton('删除选中');self.delete.setToolTip('只从当前词典草稿移除选中条目，取消可保留原词典。');self.delete.clicked.connect(self.remove_rows);row.addWidget(self.delete)
        self.import_button=QPushButton('导入合并…');self.import_button.setToolTip('读取声稿读音词典 JSON 并合并到当前草稿；同原文同假名更新备注，保存前不改现有文件。');self.import_button.clicked.connect(self.import_file);row.addWidget(self.import_button)
        self.export_button=QPushButton('导出…');self.export_button.setToolTip('导出当前词典草稿为 JSON，不包含媒体、工程、密钥或另一范围的词典。');self.export_button.clicked.connect(self.export_file);row.addWidget(self.export_button);root.addLayout(row)
        self.status=QLabel();self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setWordWrap(True);root.addWidget(self.status)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存当前词典');self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('保留原词典');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);root.addWidget(self.buttons)
        self.fill(document)

    def fill(self,document):
        blocker=QSignalBlocker(self.table);entries=document.get('entries',[]);self.table.setRowCount(len(entries))
        for row,entry in enumerate(entries):
            for col,key in enumerate(('text','kana','note')):self.table.setItem(row,col,QTableWidgetItem(entry[key]))
    def append(self):
        row=self.table.rowCount();self.table.insertRow(row)
        for col in range(3):self.table.setItem(row,col,QTableWidgetItem(''))
        self.table.setCurrentCell(row,0);self.table.editItem(self.table.item(row,0))
    def remove_rows(self):
        for row in sorted({i.row() for i in self.table.selectedIndexes()},reverse=True):self.table.removeRow(row)
    def collect(self):
        self.buttons.setFocus();entries=[]
        for row in range(self.table.rowCount()):
            text,kana,note=[self.table.item(row,col).text() if self.table.item(row,col) else '' for col in range(3)]
            if not any((text,kana,note)):continue
            entries.append({'text':text,'kana':kana_only(kana),'note':note})
        value={'version':1,'entries':entries};validate(value);return value
    def import_file(self):
        path,_=QFileDialog.getOpenFileName(self,'导入读音词典','','读音词典 (*.json)')
        if not path:return
        try:
            imported=json.loads(Path(path).read_text(encoding='utf-8-sig'));validate(imported);value=merge(self.collect(),imported);self.fill(value);self.status.setText(f'合并后共 {len(value["entries"])} 条，点击保存才会写入。')
        except (ValueError,OSError,UnicodeError) as error:self.status.setText('未导入，原草稿保持。'+str(error))
    def export_file(self):
        try:value=self.collect()
        except ValueError as error:self.status.setText(str(error));return
        path,_=QFileDialog.getSaveFileName(self,'导出当前读音词典','读音词典.json','读音词典 (*.json)')
        if not path:return
        if Path(path).resolve() in self.blocked:self.status.setText('导出请选择另一文件；保存当前词典请使用下方保存按钮。');return
        try:atomic_json(Path(path),value);self.status.setText('已导出当前草稿，原词典保持。')
        except OSError as error:self.status.setText('导出失败：'+str(error))
    def accept(self):
        try:self.document=self.collect()
        except ValueError as error:self.status.setText(str(error));return
        super().accept()
