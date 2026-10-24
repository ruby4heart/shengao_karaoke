"""Choose whether old estimate protection may be recalculated, before inference."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QCheckBox,QPushButton,
    QTableWidget,QTableWidgetItem,QHeaderView,QDialogButtonBox,QScrollArea,QWidget,QApplication)
from studio_backend.acoustic import plan
from studio_backend.recalculation import inspect,prepare
from .widgets import time_text


class RecalculationDialog(QDialog):
    def __init__(self,line,playback,parent=None,options=None):
        super().__init__(parent);self.setWindowTitle('重新计算旧估算内部')
        options={} if options is None else options
        if not isinstance(options,dict) or any(k in options and type(options[k]) is not bool for k in ('allow_reviewed','release_old_protection')):
            raise ValueError('内部重算选择格式无效，当前时间与保护保持。')
        if 'version' in options and (type(options['version']) is not int or options['version']!=1):raise ValueError('内部重算请求版本较新或无效，请使用对应版本。')
        screen=QApplication.primaryScreen().availableGeometry();self.resize(min(800,screen.width()-30),min(650,screen.height()-40))
        self.line=copy.deepcopy(line);self.playback=playback;self.details=inspect(line);self.prepared=None;self.manual=False
        root=QVBoxLayout(self);intro=QLabel('整体移动或确认过时间后，旧估算也可能被保护。这里先说明将计算哪些音节；原文、读音、整句与人工词组范围保持，真正人工调整、锁定和固定点保留。')
        intro.setWordWrap(True);root.addWidget(intro)
        text=QLabel(line.text);text.setTextFormat(Qt.TextFormat.PlainText);text.setWordWrap(True);root.addWidget(text)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);root.addWidget(scroll,1)
        n=len(self.details['released']);self.release=QCheckBox(f'允许重新计算这些旧估算保护（{n} 个音节）')
        self.release.setChecked(bool((options or {}).get('release_old_protection',False)));self.release.setEnabled(n>0);layout.addWidget(self.release)
        self.reviewed=QCheckBox('允许重新计算已确认的本句；采用后时间恢复为待确认，读音确认保持')
        self.reviewed.setChecked(bool((options or {}).get('allow_reviewed',False)));self.reviewed.setVisible(line.reviewed);layout.addWidget(self.reviewed)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['音节','当前位置','处理依据']);self.table.setColumnWidth(0,100);self.table.setColumnWidth(1,200);self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch);self.table.setMinimumHeight(160);layout.addWidget(self.table)
        self.explanation=QLabel();self.explanation.setWordWrap(True);layout.addWidget(self.explanation)
        row=QHBoxLayout();listen=QPushButton('试听本句');listen.clicked.connect(lambda:playback.audition(line.start,line.end));row.addWidget(listen)
        stop=QPushButton('停止试听');stop.clicked.connect(playback.stop);row.addWidget(stop);layout.addLayout(row)
        note=QLabel('本机 TIFA，无需 API；模型仅限个人非商业用途。生成失败或取消不会解除任何保护，返回后仍要试听、勾选采用；采用与撤销一起恢复。');note.setWordWrap(True);layout.addWidget(note)
        if parent is not None and parent.project.source_ass_active:
            ass=QLabel('采用后使用声稿样式；原 ASS 保留，可撤销。');ass.setWordWrap(True);layout.addWidget(ass)
        self.status=QLabel();self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setWordWrap(True);layout.addWidget(self.status)
        footer=QVBoxLayout() if screen.width()<750 else QHBoxLayout()
        manual=QPushButton('返回本句手工校对');manual.clicked.connect(self.go_manual);footer.addWidget(manual)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);self.run=self.buttons.button(QDialogButtonBox.StandardButton.Ok);self.run.setObjectName('primary');self.run.setText('生成重算候选')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('保留当前时间');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);footer.addWidget(self.buttons);root.addLayout(footer)
        self.release.toggled.connect(self.refresh);self.reviewed.toggled.connect(self.refresh);self.finished.connect(lambda _:playback.stop());self.refresh()

    def options(self):return {'allow_reviewed':bool(self.line.reviewed and self.reviewed.isChecked()),'release_old_protection':self.release.isEnabled() and self.release.isChecked()}
    def refresh(self,*_):
        allowed={(p['unit'],p['highlight']) for p in self.details['released']}
        kept={(p['unit'],p['highlight']):p['reason'] for p in self.details['kept']};rows=[]
        for i,u in enumerate(self.line.units):
            for j,h in enumerate(u.highlights):
                if (i,j) in allowed:reason='重新计算旧估算内部' if self.release.isChecked() else '保留旧估算保护（未勾选）'
                elif (i,j) in kept:reason=kept[i,j]
                else:reason='未固定的一端可按声音重算' if h.fixed_edges else '普通未固定音节，可按声音重算'
                if len(h.fixed_edges)==1:reason+=' · 保留固定'+('起点' if h.fixed_edges==['start'] else '终点')
                rows.append((i,j,h,reason))
        self.table.setRowCount(len(rows))
        for row,(i,j,h,reason) in enumerate(rows):
            for column,text in enumerate([f'{i+1}.{j+1} · '+h.kana,time_text(h.start)+'—'+time_text(h.end),reason]):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);item.setToolTip(self.line.units[i].text+'\n'+text);self.table.setItem(row,column,item)
        self.explanation.setText(f'{len(self.details["released"])} 个旧估算保护可选择重算，{len(self.details["kept"])} 个音节保留，锁定词组 {self.details["locked_units"]} 个。单边固定点只约束所选一端；来源不明的旧人工记录继续保守保留。')
        self.prepared=None;opt=self.options()
        try:
            if self.line.reviewed and not opt['allow_reviewed']:raise ValueError('本句时间已确认；如需重算，请明确勾选允许，生成时仍不修改工程。')
            if opt['release_old_protection'] or self.line.reviewed:self.prepared=prepare(self.line,**opt)
            else:self.prepared=plan(self.line)
            count=sum(len(j['mora']) for j in self.prepared['jobs'])
            self.status.setText(f'将计算 {count} 个音节、{len(self.prepared["jobs"])} 个声音区间。先生成建议再审核；当前时间与确认状态保持。')
        except ValueError as error:
            self.status.setText('若要重算旧估算内部，请勾选上面的允许项。'+str(error) if allowed and not self.release.isChecked() else str(error))
        self.run.setEnabled(self.prepared is not None)
    def accept(self):
        self.refresh()
        if self.prepared is not None:super().accept()
    def go_manual(self):self.manual=True;self.reject()
