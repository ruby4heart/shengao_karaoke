"""Read-only time basis, local checks, audition and direct calibration handoff."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
    QTableWidget,QTableWidgetItem,QHeaderView,QPlainTextEdit,QPushButton,QDialogButtonBox)
from studio_backend.provenance import rows,line_summary
from .widgets import time_text

PROVIDERS={'local':'本机计算','elevenlabs':'ElevenLabs','microsoft':'Microsoft AI','tifa':'本地歌声模型',
           'ass':'ASS 字幕','srt':'SRT 字幕','lrc':'LRC 标签','mixed':'多种来源','unknown':'旧记录／未记录服务'}


class TimingSourceDialog(QDialog):
    def __init__(self,line,playback,word=-1,part=-1,parent=None):
        super().__init__(parent);self.setWindowTitle('本句时间来源与提示');self.playback=playback;self.selection=None;self.values=rows(line);self.audio_role=line.timing_evidence.get('audio_role')
        screen=QApplication.primaryScreen().availableGeometry();self.resize(min(1080,max(760,screen.width()-80)),min(720,max(420,screen.height()-80)))
        layout=QVBoxLayout(self);notice=QLabel(line.text+'\n'+line_summary(line));notice.setWordWrap(True);notice.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(notice)
        note=QLabel('时间依据、后续调整、人工确认分开记录。词组参考不能证明内部音节；估算、短音和长音提示仅用于试听检查。');note.setWordWrap(True);layout.addWidget(note)
        self.filter=QComboBox()
        for title,key in [('查看全部层级','all'),('只看未确认提示','issues'),('只看估算','estimated'),('只看歌声候选','acoustic'),('只看人工调整','manual')]:self.filter.addItem(title,key)
        layout.addWidget(self.filter)
        self.table=QTableWidget(len(self.values),5);self.table.setHorizontalHeaderLabels(['位置','原文／音节','当前范围','时间依据','提示'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        for col in [1,4]:self.table.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0,78);self.table.setColumnWidth(2,180);self.table.setColumnWidth(3,180)
        selected=0
        for n,value in enumerate(self.values):
            i,j=value['word'],value['part'];where='整句' if i<0 else f'词组 {i+1}' if j<0 else f'音 {i+1}.{j+1}'
            texts=[where,value['text'],f'{time_text(value["start"])} — {time_text(value["end"])}',value['title'],'\n'.join(value['issues']) or '—']
            for col,text in enumerate(texts):item=QTableWidgetItem(text);item.setToolTip(text);self.table.setItem(n,col,item)
            if (i,j)==(word,part):selected=n
        self.table.resizeRowsToContents();layout.addWidget(self.table,1)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(140);layout.addWidget(self.details)
        row=QHBoxLayout();self.listen=QPushButton('试听所选（带前后音）');self.listen.clicked.connect(self.audition);row.addWidget(self.listen)
        stop=QPushButton('停止');stop.clicked.connect(playback.stop);row.addWidget(stop);self.edit=QPushButton('去校准所选');self.edit.setObjectName('primary');self.edit.clicked.connect(self.choose);row.addWidget(self.edit);layout.addLayout(row)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);controls.button(QDialogButtonBox.StandardButton.Close).setText('关闭');controls.rejected.connect(self.reject);layout.addWidget(controls)
        self.table.currentCellChanged.connect(self.explain);self.filter.currentIndexChanged.connect(self.apply_filter);self.table.setCurrentCell(selected,1)
        self.finished.connect(lambda _:playback.stop())

    def current(self):
        row=self.table.currentRow()
        return self.values[row] if row>=0 and not self.table.isRowHidden(row) else None

    def explain(self,*args):
        value=self.current();self.listen.setEnabled(bool(value));self.edit.setEnabled(bool(value))
        if not value:self.details.setPlainText('当前筛选没有对应内容。');return
        origin=value['origin'];a,b=origin['reference']
        text=[value['title'],'来源：'+PROVIDERS[origin['provider']],f'原始依据范围：{time_text(a)} — {time_text(b)}',
              f'当前范围：{time_text(value["start"])} — {time_text(value["end"])}',*value['detail']]
        if value['kind']=='acoustic' and self.audio_role in {'vocals','original'}:
            text.append('声音依据使用：'+('人声辅助' if self.audio_role=='vocals' else '原声')+'；试听跟随工作台当前音轨。')
        if origin.get('reading'):text.append('这份声音依据使用的假名：'+origin['reading'])
        text+=['提示：'+issue for issue in value['issues']];self.details.setPlainText('\n'.join(text))

    def apply_filter(self,*args):
        key=self.filter.currentData();visible=[]
        for i,value in enumerate(self.values):
            show=key=='all' or key=='issues' and bool(value['issues']) and not value['confirmed'] or key==value['display_kind']
            self.table.setRowHidden(i,not show)
            if show:visible.append(i)
        if self.table.currentRow() not in visible:
            if visible:self.table.setCurrentCell(visible[0],1)
            else:self.table.clearSelection();self.table.setCurrentCell(-1,-1)
        self.explain()

    def audition(self):
        value=self.current()
        if value:self.playback.audition(max(0,value['start']-120),max(value['start']+10,value['end'])+120)

    def choose(self):
        value=self.current()
        if value:self.selection=(value['word'],value['part']);self.accept()
