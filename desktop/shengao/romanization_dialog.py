"""Compare automatic spelling and deliberate per-word Roman overrides."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QLineEdit,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QDialogButtonBox,QApplication,QPlainTextEdit,QScrollArea,QWidget,QSizePolicy
from studio_backend.romanization import DEFAULT,state,set_manual,apply_rules


class RomanizationDialog(QDialog):
    def __init__(self,project,row,word,parent=None):
        super().__init__(parent);self.setWindowTitle('罗马音规则与手写覆盖');self.original=copy.deepcopy(project);self.row=row;self.word=word;self.result_lines={};self.result_preferences=None
        screen=QApplication.primaryScreen().availableGeometry();self.resize(min(850,screen.width()-30),min(660,screen.height()-40));unit=project.lines[row].units[word];source=state(unit,project.reading_preferences.get('romaji'))
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();root=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll,1);intro=QLabel('按已经填写的假名生成罗马音，或只为当前词组手写覆盖。只改显示，原文、假名、译文、演唱轴和确认保持。');intro.setWordWrap(True);root.addWidget(intro)
        current=QPlainTextEdit('原文：'+unit.text+'\n假名：'+unit.kana+'\n当前罗马音：'+unit.romaji);current.setReadOnly(True);current.setTabChangesFocus(True);current.setMinimumHeight(64);current.setMaximumHeight(96);current.setAccessibleName('本词原文、假名和当前罗马音');root.addWidget(current)
        self.source=QLabel({'auto':'当前为自动拼写。','manual':'当前为手写覆盖，切回自动可明确恢复。','legacy':'旧拼法没有完整来源记录，默认保留；可明确恢复自动。'}[source['mode']]);self.source.setWordWrap(True);root.addWidget(self.source)
        rowbox=QHBoxLayout();self.scope=QComboBox()
        for title,key in [('当前词组','word'),('本句所有词组','line'),('整首所有词组','all')]:self.scope.addItem(title,key)
        rowbox.addWidget(self.scope);self.mode=QComboBox();self.mode.addItem('按假名自动生成','auto');self.mode.addItem('手写当前词组','manual');self.mode.setCurrentIndex(0 if source['mode']=='auto' else 1);rowbox.addWidget(self.mode);root.addLayout(rowbox)
        rowbox=QHBoxLayout();self.system=QComboBox();self.system.addItem('实用ヘボン式','hepburn');self.system.addItem('训令式（旧式拼写）','kunrei');self.system.setCurrentIndex(self.system.findData(source['system']));rowbox.addWidget(self.system)
        self.long_vowels=QComboBox();self.long_vowels.addItem('长音保留假名拼写（ou／oo 等）','literal');self.long_vowels.addItem('按词典长音使用 ā／ī／ū／ē／ō','macron');self.long_vowels.setCurrentIndex(self.long_vowels.findData(source['long_vowels']));rowbox.addWidget(self.long_vowels);root.addLayout(rowbox)
        self.particles=QCheckBox('助词 は／へ／を 写作 wa／e／o');self.particles.setChecked(source['particles']);root.addWidget(self.particles)
        self.manual=QLineEdit(unit.romaji);self.manual.setMaxLength(20000);self.manual.setPlaceholderText('手写本词罗马音；留空可省略本词');root.addWidget(self.manual)
        self.replace=QCheckBox('批量时也替换手写或来源未记录的罗马音');root.addWidget(self.replace)
        self.default=QCheckBox('将这条自动规则设为本工程新词默认');root.addWidget(self.default)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['原文','当前罗马音','修改后','处理依据']);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.table.setMinimumHeight(100);self.table.setMaximumHeight(240);root.addWidget(self.table,1)
        self.status=QLabel();self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setWordWrap(True);root.addWidget(self.status)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);self.apply=self.buttons.button(QDialogButtonBox.StandardButton.Ok);self.apply.setText('应用罗马音设置');self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('保留当前拼写');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);outer.addWidget(self.buttons)
        for combo in [self.scope,self.mode,self.system,self.long_vowels]:combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);combo.setMinimumContentsLength(10);combo.setMinimumWidth(0);combo.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        for combo in [self.scope,self.mode,self.system,self.long_vowels]:combo.currentIndexChanged.connect(self.refresh)
        for checkbox in [self.particles,self.replace,self.default]:checkbox.toggled.connect(self.refresh)
        self.manual.textChanged.connect(self.refresh);self.refresh()

    def rules(self):return {'system':self.system.currentData(),'long_vowels':self.long_vowels.currentData(),'particles':self.particles.isChecked()}
    def refresh(self,*_):
        manual=self.mode.currentData()=='manual'
        if manual and self.scope.currentData()!='word':self.scope.setCurrentIndex(0)
        self.scope.setEnabled(not manual)
        for widget in [self.system,self.long_vowels,self.particles,self.default]:widget.setEnabled(not manual)
        self.manual.setVisible(manual);self.replace.setVisible(not manual and self.scope.currentData()!='word');self.result_lines={};self.result_preferences=copy.deepcopy(self.original.reading_preferences);rows=[];kept_count=0
        try:
            indices=list(range(len(self.original.lines))) if self.scope.currentData()=='all' else [self.row]
            for row in indices:
                line=self.original.lines[row];words=[self.word] if self.scope.currentData()=='word' else list(range(len(line.units)))
                if manual:
                    candidate=set_manual(line,self.word,self.manual.text(),self.original.reading_preferences.get('romaji'));changed=[self.word] if candidate.to_dict()!=line.to_dict() else [];kept=[]
                else:
                    result=apply_rules(line,words,self.rules(),self.replace.isChecked() or self.scope.currentData()=='word');candidate=result['line'];changed=result['changed'];kept=result['kept']
                if changed:self.result_lines[row]=candidate
                reasons={v['word']:v['reason'] for v in kept};kept_count+=len(kept)
                for i in words:rows.append((line.units[i].text,line.units[i].romaji,candidate.units[i].romaji,'手写覆盖' if manual else reasons.get(i,'按选定规则自动生成')))
            if not manual and self.default.isChecked():self.result_preferences['romaji']=self.rules()
            self.status.setText(f'本次修改 {len(self.result_lines)} 句，保留 {kept_count} 个锁定、手写或已符合规则的词组。'+('手写值只用于当前词组。' if manual else '词典无法核对的特殊唱法保留假名拼写，手写值可单独覆盖。'))
        except ValueError as error:self.result_lines={};self.result_preferences=None;self.status.setText(str(error))
        self.table.setRowCount(len(rows))
        for row,values in enumerate(rows):
            for col,text in enumerate(values):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(row,col,item)
        changed=bool(self.result_lines) or self.result_preferences is not None and self.result_preferences!=self.original.reading_preferences;self.apply.setEnabled(changed)
    def accept(self):
        self.refresh()
        if self.apply.isEnabled():super().accept()
