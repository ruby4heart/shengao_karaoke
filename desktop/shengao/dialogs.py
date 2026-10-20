import copy
from pathlib import Path
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPlainTextEdit,QDialogButtonBox,
    QComboBox,QListWidget,QListWidgetItem,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,
    QLineEdit,QFormLayout,QCheckBox,QMessageBox,QApplication)
from .timing import pauses,leaves,merge_pauses
from .timeline import stamp

def button(text,fn=None):
    widget=QPushButton(text)
    from .action_help import HELP
    if text in HELP:widget.setToolTip(HELP[text])
    if fn:widget.clicked.connect(fn)
    return widget

class LyricsDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('准备原歌词');self.resize(600,540)
        layout=QVBoxLayout(self);label=QLabel('粘贴原歌词，每行一句。分词和匹配会以这里的原文为准。');label.setWordWrap(True);layout.addWidget(label)
        self.text=QPlainTextEdit();self.text.setPlaceholderText('真夜中のネオンサインが君を抱きしめて\n遠く隠してしまうよ');layout.addWidget(self.text)
        self.append=QCheckBox('追加到现有歌词后面');layout.addWidget(self.append)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('加入工程');controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)

class PauseDialog(QDialog):
    def __init__(self,line,playback,parent=None):
        super().__init__(parent);self.setWindowTitle('停顿与高亮时间');self.resize(700,570)
        self.original=line;self.playback=playback;self.result=line
        layout=QVBoxLayout(self);label=QLabel('停顿会占用真实演唱时间。先试听，再决定高亮是否延续；长间奏默认保留。');label.setWordWrap(True);layout.addWidget(label)
        self.policy=QComboBox();self.policy.addItem('保留停顿，保持当前时间','keep');self.policy.addItem('并入前一音节：高亮延续到停顿结束','previous');self.policy.addItem('并入后一音节：提前开始下一音节高亮','next');layout.addWidget(self.policy)
        self.edges=QCheckBox('同时显示整句开头和结尾的空白');layout.addWidget(self.edges)
        self.list=QListWidget();layout.addWidget(self.list,1);self.preview=QLabel();self.preview.setWordWrap(True);layout.addWidget(self.preview)
        row=QHBoxLayout();row.addWidget(button('试听所选停顿',self.listen));row.addWidget(button('停止试听',playback.stop));layout.addLayout(row)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(controls)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('应用所选处理');controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        controls.accepted.connect(self.apply);controls.rejected.connect(self.reject)
        self.edges.toggled.connect(self.refresh);self.policy.currentIndexChanged.connect(self.describe);self.list.currentRowChanged.connect(self.describe)
        self.finished.connect(lambda _:playback.stop());self.refresh()

    def refresh(self):
        self.gaps=pauses(self.original,self.edges.isChecked());parts=leaves(self.original);self.list.clear()
        for a,b,left,right in self.gaps:
            def text(index):
                if index is None:return '句首／句尾'
                i,j,h=parts[index];return h.kana if j is not None else self.original.units[i].text
            item=QListWidgetItem(f'{stamp(a)} — {stamp(b)}　{b-a} ms　{text(left)} → {text(right)}')
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if b-a<=120 and left is not None and right is not None else Qt.CheckState.Unchecked);self.list.addItem(item)
        if self.gaps:self.list.setCurrentRow(0)
        else:self.preview.setText('当前句没有独立停顿；可先生成词组和音节，再进行校准。')

    def describe(self,*args):
        row=self.list.currentRow()
        if row<0 or row>=len(self.gaps):return
        a,b,left,right=self.gaps[row];policy=self.policy.currentData()
        self.preview.setText('保留当前时间。' if policy=='keep' else f'前一音节结束将延长到 {stamp(b)}。' if policy=='previous' and left is not None else f'后一音节开始将提前到 {stamp(a)}。' if right is not None else f'将句尾空白并入最后一个音节，结束为 {stamp(b)}。')

    def listen(self):
        row=self.list.currentRow()
        if row>=0:a,b,_,_=self.gaps[row];self.playback.audition(max(0,a-350),b+350)

    def apply(self):
        indices=[i for i in range(self.list.count()) if self.list.item(i).checkState()==Qt.CheckState.Checked]
        try:self.result=merge_pauses(self.original,indices,self.policy.currentData(),self.edges.isChecked())
        except ValueError as error:QMessageBox.warning(self,'无法应用',str(error));return
        self.accept()

class ReviewDialog(QDialog):
    def __init__(self,project,result,playback,parent=None):
        super().__init__(parent);self.setWindowTitle('审核建议，再加入工程');screen=QApplication.primaryScreen().availableGeometry();self.resize(min(1020,max(720,screen.width()-40)),min(760,max(420,screen.height()-80)));self.result=result;self.project=project;self.playback=playback;self.manual_uid=None
        layout=QVBoxLayout(self);message=result.get('message') or '原歌词保持不变；自动生成的时间和读音仍需试听确认。勾选需要采用的行。'
        if project.source_ass_active and (result.get('action')=='acoustic' or result.get('acoustic')):message+=' 采用歌声候选后使用声稿样式，原 ASS 保留，可撤销。'
        notice=QLabel(message);notice.setWordWrap(True);layout.addWidget(notice)
        self.values=copy.deepcopy(result.get('suggestions',[]));self.recommended=copy.deepcopy(self.values);self.table=QTableWidget(len(self.values),4);self.table.setHorizontalHeaderLabels(['采用','原歌词','建议时间','建议读音／译文']);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch);self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        old={x.id:x for x in project.lines}
        acoustic_status=result.get('acoustic',{}).get('lines',{})
        from studio_backend.model import LyricLine
        from studio_backend.provenance import line_summary
        self.table.setColumnCount(5);self.table.setHorizontalHeaderLabels(['采用','原歌词','建议时间','建议读音／译文','时间依据']);self.table.setColumnWidth(4,190)
        self.table.setColumnWidth(0,42);self.table.setColumnWidth(2,145)
        if result.get('acoustic'):
            self.table.setColumnCount(5);self.table.setHorizontalHeaderLabels(['采用','原歌词','建议时间','建议读音／译文','音节状态']);self.table.setColumnWidth(4,190)
        for row,line in enumerate(self.values):
            check=QTableWidgetItem();check.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable);check.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row,0,check)
            for col,text in [(1,line['text']),(2,f'{stamp(line["start"])} → {stamp(line["end"])}'),(3,(line.get('kana') or ' '.join(u.get('kana','') for u in line.get('units',[])))+'\n'+line.get('translation',''))]:
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(row,col,item)
            evidence=line.get('reading_review',{})
            self.table.item(row,3).setToolTip('当前：'+(old[line['id']].kana if line['id'] in old else '')+'\n'+str(evidence.get('notice',''))+'\n'+str(line.get('match',{}).get('reason','')))
            self.table.setRowHeight(row,58)
            origin_text=line_summary(LyricLine.from_dict(line));origin_item=QTableWidgetItem(origin_text);origin_item.setToolTip(origin_text);origin_item.setFlags(origin_item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(row,4,origin_item)
            if result.get('acoustic'):
                status=acoustic_status.get(line['id'],{});kind=status.get('status','pending');text={'aligned':'歌声候选 · 待试听','needs_manual':'保留初稿 · 需手工','pending':'尚未完成 · 保留初稿'}.get(kind,'保留当前内容')
                text+='\n'+origin_text
                if status.get('reason') and kind!='aligned':text+='\n'+status['reason']
                item=QTableWidgetItem(text);item.setToolTip(text+'\n'+status.get('reason',''));item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(row,4,item);self.table.setRowHeight(row,94)
        layout.addWidget(self.table,1)
        row=QHBoxLayout();row.addWidget(button('全选',lambda:self.check_all(True)));row.addWidget(button('清空',lambda:self.check_all(False)));row.addStretch();row.addWidget(button('试听所选行',self.listen));row.addWidget(button('停止',playback.stop));layout.addLayout(row)
        self.evidence=QLabel('读音依据显示在单元格提示中。转录与原文相同的汉字，并不能证明实际唱法。');self.evidence.setWordWrap(True);layout.addWidget(self.evidence)
        self.candidates=QComboBox();self.candidates.setToolTip('重复副歌可能匹配到多个位置；选择后先试听再决定采用。分数是文字相似度，不是声音识别置信度。');layout.addWidget(self.candidates)
        self.details_toggle=QPushButton('展开音节对照与读音依据');self.details_toggle.setCheckable(True);self.details_toggle.setChecked(not bool(result.get('acoustic')));self.details_toggle.setVisible(bool(result.get('acoustic')));layout.addWidget(self.details_toggle)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(150);self.details.setVisible(self.details_toggle.isChecked());layout.addWidget(self.details)
        self.details_toggle.toggled.connect(lambda visible:(self.details.setVisible(visible),self.details_toggle.setText('收起音节对照与读音依据' if visible else '展开音节对照与读音依据')))
        self.manual_button=button('本句先手工校对（建议留在任务记录）',self.open_manual);self.manual_button.setVisible(bool(result.get('acoustic')));layout.addWidget(self.manual_button)
        row=QHBoxLayout();self.acoustic_mora=QComboBox();row.addWidget(self.acoustic_mora,1);self.acoustic_listen=button('试听这个音节（带前后音）',self.listen_acoustic_mora);row.addWidget(self.acoustic_listen);layout.addLayout(row)
        self.table.currentCellChanged.connect(lambda *_:self.show_evidence());self.candidates.currentIndexChanged.connect(self.choose_candidate)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);self.apply_button=controls.button(QDialogButtonBox.StandardButton.Ok);self.apply_button.setText('先勾选需要采用的行');self.apply_button.setEnabled(False);controls.button(QDialogButtonBox.StandardButton.Cancel).setText('稍后审核');controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)
        self.table.itemChanged.connect(self.selection_count)
        self.finished.connect(lambda _:playback.stop())
        if self.values:self.table.setCurrentCell(0,1)
    def check_all(self,checked):
        for i in range(self.table.rowCount()):self.table.item(i,0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    def selection_count(self,*args):
        count=len(self.selected());self.apply_button.setEnabled(count>0);self.apply_button.setText(f'采用 {count} 行建议' if count else '先勾选需要采用的行')
    def selected(self):return [value for i,value in enumerate(self.values) if self.table.item(i,0).checkState()==Qt.CheckState.Checked]
    def listen(self):
        row=self.table.currentRow()
        if row>=0:self.playback.audition(self.values[row]['start'],self.values[row]['end'])
    def listen_acoustic_mora(self):
        value=self.acoustic_mora.currentData()
        if value:self.playback.audition(max(0,value[0]-120),value[1]+120)
    def open_manual(self):
        row=self.table.currentRow()
        if row>=0:self.manual_uid=self.values[row]['id'];self.reject()
    def show_evidence(self):
        row=self.table.currentRow()
        if row<0:return
        data=self.values[row];old=next((x for x in self.project.lines if x.id==data['id']),None)
        review=data.get('reading_review',{});match=data.get('match',{});parts=[];timing=data.get('timing_evidence',{})
        status=self.result.get('acoustic',{}).get('lines',{}).get(data['id'],{})
        self.manual_button.setEnabled(bool(self.result.get('acoustic')) and status.get('status')!='aligned')
        self.manual_button.setVisible(bool(self.result.get('acoustic')) and status.get('status')!='aligned')
        acoustic=bool(timing and (self.result.get('action')=='acoustic' or status.get('status')=='aligned'))
        self.acoustic_mora.setVisible(acoustic);self.acoustic_listen.setVisible(acoustic);self.acoustic_mora.clear()
        self.candidates.setVisible(not acoustic)
        if acoustic:
            parts=[timing.get('notice',''),'输入音轨：'+('人声辅助' if timing.get('audio_role')=='vocals' else '当前视频原声'),f'建议整句：{stamp(data["start"])}—{stamp(data["end"])}；以下为音节旧时间 → 歌声建议时间：']
            if old:parts+=['当前读音：'+(old.kana or ''.join(u.kana for u in old.units))]
            parts+=['建议读音：'+(data.get('kana') or ''.join(u.get('kana','') for u in data['units']))]
            review=data.get('reading_review',{})
            if review.get('notice'):parts.append(review['notice'])
            for word in review.get('words',[]):
                parts.append(f'{word.get("text","")}：{word.get("before","")} → {word.get("suggested","")}；'+word.get('reason','')+' '+str(word.get('basis','')))
            for i,unit in enumerate(data['units']):
                prior=old.units[i] if old and i<len(old.units) and old.units[i].text==unit['text'] else None
                for j,h in enumerate(unit.get('highlights',[])):
                    before=prior.highlights[j] if prior and j<len(prior.highlights) and prior.highlights[j].kana==h['kana'] else None
                    a,b=h['start'],h['end'];fixed=h.get('source')=='manual' or unit.get('locked')
                    from studio_backend.model import Highlight
                    from studio_backend.provenance import summary
                    origin=summary(Highlight(**h),mora=True)
                    text=h['kana']+' · '+(f'{stamp(before.start)}—{stamp(before.end)}' if before else '原来没有音节轴')+f' → {stamp(a)}—{stamp(b)} · '+origin['title']+(' · 人工固定保留' if fixed else '')
                    parts.append(text);self.acoustic_mora.addItem(text,(a,b))
            parts+=['疑点：'+text for text in timing.get('notes',[])]
            self.details.setPlainText('\n'.join(parts));self.evidence.setText('本地歌声强制对齐；假名本身不由此确认。用音节试听比较，确认后勾选采用，采用可一步撤销。')
            blocker=QSignalBlocker(self.candidates);self.candidates.clear();self.candidates.addItem('已按歌声微调粗略句首句尾' if timing.get('fit_range') else '整句范围保持不变');self.candidates.setEnabled(False);return
        if status:parts.append('歌声处理：'+status.get('reason','此句尚未处理，保留初稿。'))
        if old:parts.append('当前读音：'+(old.kana or ' '.join(u.kana for u in old.units)))
        parts.append('建议读音：'+(data.get('kana') or ' '.join(u.get('kana','') for u in data.get('units',[]))))
        if review.get('notice'):parts.append(review['notice'])
        for word in review.get('words',[]):
            text=word.get('text','');before=word.get('before','');after=word.get('suggested','')
            parts.append(f'{text}：{before} → {after}；'+word.get('reason','')+' '+str(word.get('basis','')))
        if match:parts.extend(['识别原文：'+match.get('recognized',''),'匹配依据：'+match.get('reason','')])
        if not review and not match:parts.append('词典／LLM 生成的建议仍需结合实际演唱试听。')
        from studio_backend.model import LyricLine
        from studio_backend.provenance import line_summary,summary
        proposed=LyricLine.from_dict(data);parts.insert(0,'时间依据：'+line_summary(proposed))
        for i,unit in enumerate(proposed.units):
            origin=summary(unit);parts.append(f'词组 {i+1} · {unit.text}：'+origin['title'])
            for j,h in enumerate(unit.highlights):
                state=summary(h,mora=True);self.acoustic_mora.addItem(f'{i+1}.{j+1} {h.kana} · '+state['title']+f' · {stamp(h.start)}—{stamp(h.end)}',(h.start,h.end))
        self.acoustic_mora.setVisible(self.acoustic_mora.count()>0);self.acoustic_listen.setVisible(self.acoustic_mora.count()>0)
        self.details.setPlainText('\n'.join(parts));blocker=QSignalBlocker(self.candidates);self.candidates.clear()
        self.candidates.addItem('推荐时段：'+stamp(self.recommended[row]['start'])+' — '+stamp(self.recommended[row]['end']),-1)
        for i,candidate in enumerate(self.recommended[row].get('match',{}).get('candidates',[])):
            self.candidates.addItem(f'候选 {i+1}：{stamp(candidate["start"])} — {stamp(candidate["end"])} · 文字相似度 {candidate.get("score",0):.0%}',i)
        self.candidates.setEnabled(self.candidates.count()>1)
    def choose_candidate(self):
        row=self.table.currentRow();choice=self.candidates.currentData()
        if row<0 or choice is None:return
        if self.result.get('action')=='acoustic' or self.result.get('acoustic',{}).get('lines',{}).get(self.values[row]['id'],{}).get('status')=='aligned':return
        value=copy.deepcopy(self.recommended[row])
        if choice>=0:
            candidate=value['match']['candidates'][choice]
            for key in ('start','end','units'):value[key]=copy.deepcopy(candidate[key])
            for key in ('score','coverage','recognized','method'):value['match'][key]=candidate.get(key,value['match'].get(key))
            value['match']['reason']='人工选择的候选时段；仍需试听校准。'
        from studio_backend.model import LyricLine
        try:LyricLine.from_dict(value)
        except ValueError as error:QMessageBox.warning(self,'候选无效',str(error));return
        self.values[row]=value;self.table.item(row,2).setText(f'{stamp(value["start"])} → {stamp(value["end"])}')

class SettingsDialog(QDialog):
    def __init__(self,parent=None,settings=None):
        super().__init__(parent);self.setWindowTitle('API 设置');self.resize(560,370)
        from studio_backend.settings import Settings
        public=(settings or Settings()).public();self.public=public
        layout=QVBoxLayout(self);label=QLabel('密钥加密保存在本机，不进入工程。保存设置不会发起转录或付费请求。');label.setWordWrap(True);layout.addWidget(label)
        form=QFormLayout();self.provider=QComboBox()
        for title,key in [('ElevenLabs · 转录／对齐','elevenlabs'),('Microsoft AI · 转录','mai'),('DeepSeek · 注音／翻译','deepseek')]:self.provider.addItem(title,key)
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password);self.endpoint=QLineEdit();self.model=QLineEdit();self.forget=QCheckBox('删除已保存的密钥')
        form.addRow('服务',self.provider);form.addRow('API 密钥',self.key);form.addRow('Microsoft 接口地址',self.endpoint);form.addRow('DeepSeek 模型',self.model);layout.addLayout(form);layout.addWidget(self.forget)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);controls.button(QDialogButtonBox.StandardButton.Save).setText('保存本机设置');controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)
        self.provider.currentIndexChanged.connect(self.refresh);self.refresh()
    def refresh(self):
        name=self.provider.currentData();config=self.public.get(name,{})
        self.key.clear();self.key.setPlaceholderText('已配置；留空保留原密钥' if config.get('has_key') else '在这里粘贴密钥')
        self.endpoint.setText(config.get('endpoint',''));self.endpoint.setEnabled(name=='mai');self.model.setText(config.get('model',''));self.model.setEnabled(name=='deepseek');self.forget.setChecked(False)
    def request(self):
        value={'action':'configure','provider':self.provider.currentData(),'key':self.key.text().strip(),'forget':self.forget.isChecked()}
        if value['provider']=='mai':value['endpoint']=self.endpoint.text().strip()
        if value['provider']=='deepseek' and self.model.text().strip():value['model']=self.model.text().strip()
        return value
