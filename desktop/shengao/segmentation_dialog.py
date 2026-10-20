"""Local, reviewable segmentation even when recognition did not match a line."""
import copy
import html
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QTextBrowser,
    QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QDialogButtonBox)
from studio_backend.japanese import Group,word_groups,retime_groups,add_mora
from .widgets import TimeEdit
from .timing import manual


def regroup(original,cuts,start=None,end=None):
    if original.locked or any(u.locked for u in original.units):raise ValueError('本句或词组已锁定，请先解除锁定')
    line=copy.deepcopy(original);start=line.start if start is None else start;end=line.end if end is None else end
    if not 0<=start<end:raise ValueError('本句开始须早于结束')
    bounds=[0,*sorted(set(cuts)),len(line.text)]
    if any(type(n) is not int or not 0<n<len(line.text) for n in bounds[1:-1]):raise ValueError('分界位置无效')
    groups=[]
    for a,b in zip(bounds,bounds[1:]):
        text=line.text[a:b];parts=word_groups(text)
        groups.append(Group(text,a,b,''.join(g.kana for g in parts),' '.join(g.romaji for g in parts if g.romaji)))
    changed_range=(start,end)!=(line.start,line.end)
    old={};cursor=0
    for u in line.units:old[(cursor,cursor+len(u.text))]=u;cursor+=len(u.text)
    if changed_range:
        # Explicitly selecting a new range estimates a new axis, without
        # throwing away an unchanged group's approved pronunciation.
        line.units=[];line.start,line.end=start,end
        from studio_backend.provenance import record
        record(original,line,'manual_boundary')
        groups=[Group(g.text,g.begin,g.end,old[(g.begin,g.end)].kana,old[(g.begin,g.end)].romaji) if (g.begin,g.end) in old else g for g in groups]
    line.units=retime_groups(line,groups)
    for g,u in zip(groups,line.units):
        if changed_range and (g.begin,g.end) in old:u.reading_source=old[(g.begin,g.end)].reading_source
        add_mora(u)
    line.kana=''.join(u.kana for u in line.units);line.romaji=' '.join(u.romaji for u in line.units if u.romaji)
    manual(line);line.validate();return line


class SegmentationDialog(QDialog):
    def __init__(self,line,playback,parent=None):
        super().__init__(parent);self.original=copy.deepcopy(line);self.playback=playback;self.result_line=None
        self.cuts=set();cursor=0
        for u in line.units[:-1]:cursor+=len(u.text);self.cuts.add(cursor)
        self.setWindowTitle('本句重新分词 · 不需要识别成功');self.resize(690,540)
        layout=QVBoxLayout(self)
        info=QLabel('点击原文中的某个字，在它前面切分；再点一次合并。原歌词不会改写，也不会调用 API。');info.setWordWrap(True);layout.addWidget(info)
        self.text=QTextBrowser();self.text.setOpenLinks(False);self.text.setMinimumHeight(110);self.text.setMaximumHeight(180);self.text.anchorClicked.connect(lambda url:self.toggle_cut(int(url.toString().split(':')[-1])));layout.addWidget(self.text)
        row=QHBoxLayout();self.dictionary=QPushButton('按词典重新分词');self.dictionary.clicked.connect(self.dictionary_cuts);row.addWidget(self.dictionary)
        self.clear=QPushButton('合为整句，再手动切分');self.clear.clicked.connect(lambda:self.set_cuts([]));row.addWidget(self.clear);layout.addLayout(row)
        row=QHBoxLayout();self.begin=TimeEdit();self.end=TimeEdit();self.begin.setValue(line.start);self.end.setValue(line.end)
        row.addWidget(QLabel('本句开始'));row.addWidget(self.begin);row.addWidget(QLabel('结束'));row.addWidget(self.end);layout.addLayout(row)
        row=QHBoxLayout()
        for title,field in [('以播放位置设开始',self.begin),('以播放位置设结束',self.end)]:
            b=QPushButton(title);b.clicked.connect(lambda checked=False,f=field:f.setValue(self.playback.canvas.position));row.addWidget(b)
        b=QPushButton('试听本句范围');b.clicked.connect(lambda:self.playback.audition(self.begin.value(),self.end.value()));row.addWidget(b);layout.addLayout(row)
        note=QLabel('未匹配的句子可在这里先定范围，再分词。范围不变时保留已有边界；改变范围会重新估算时间，之后需要试听校轴。');note.setWordWrap(True);layout.addWidget(note)
        self.table=QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['切分预览','词典／已有读音']);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);layout.addWidget(self.table,1)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel);self.buttons.button(QDialogButtonBox.StandardButton.Apply).setText('应用本句分词');self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        self.begin.valueChanged.connect(self.preview);self.end.valueChanged.connect(self.preview);self.preview()

    def set_cuts(self,cuts):self.cuts=set(cuts);self.preview()
    def toggle_cut(self,position):
        if not 0<position<len(self.original.text):return
        if position in self.cuts:self.cuts.remove(position)
        else:self.cuts.add(position)
        self.preview()
    def dictionary_cuts(self):
        try:self.set_cuts([g.begin for g in word_groups(self.original.text) if g.begin])
        except ValueError as error:self.summary.setText(str(error))
    def preview(self,*args):
        parts=[]
        for n,char in enumerate(self.original.text):
            if n in self.cuts:parts.append('<span style="color:#5f6dea">┃</span>')
            if char=='\n':parts.append('<br>')
            else:parts.append(f'<a href="cut:{n}" style="color:#17263b;text-decoration:none">{html.escape(char).replace(" ","&nbsp;")}</a>')
        self.text.setHtml('<div style="font-size:23px;line-height:180%">'+''.join(parts)+'</div>')
        try:
            candidate=regroup(self.original,self.cuts,self.begin.value(),self.end.value());self.table.setRowCount(len(candidate.units))
            for row,u in enumerate(candidate.units):
                self.table.setItem(row,0,QTableWidgetItem(u.text));self.table.setItem(row,1,QTableWidgetItem(u.kana or '待手动填写读音'))
            self.summary.setText(f'{len(candidate.units)} 个词组。应用后仅本句的时间和读音改为待确认；可一步撤销。');self.buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(True)
        except ValueError as error:self.summary.setText(str(error));self.buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(False)
    def apply(self):
        try:self.result_line=regroup(self.original,self.cuts,self.begin.value(),self.end.value())
        except ValueError as error:self.summary.setText(str(error));return
        self.accept()
