"""A modeless issue workbench using the existing guarded editing workflows."""
import copy
from PySide6.QtCore import Qt,QTimer,QSignalBlocker
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QLineEdit,QCheckBox,
    QPushButton,QTableWidget,QTableWidgetItem,QAbstractItemView,QHeaderView,QPlainTextEdit,QSplitter,QScrollArea,QWidget)
from .review_issues import KINDS,SEVERITIES,collect,state,progress,current_issue,proposed_line,record_decision

STATES={'open':'待检查','changed':'需重新检查','keep':'保留当前','defer':'暂缓','adopted':'已采用'}


def label(text=''):
    control=QLabel(text);control.setWordWrap(True);control.setTextFormat(Qt.TextFormat.PlainText);return control


def button(text,tip,fn):
    control=QPushButton(text);control.setAutoDefault(False);control.setDefault(False);control.setToolTip(tip);control.clicked.connect(fn);return control


def describe(line):
    parts='；'.join(f'{h.kana} {h.start}–{h.end} ms'+(' 固定'+('/'.join({'start':'起点','end':'终点'}[edge] for edge in h.fixed_edges)) if h.fixed_edges else '') for unit in line.units for h in unit.highlights)
    return f'原文：{line.text}\n假名：'+''.join(u.kana for u in line.units)+f'\n演唱：{line.start}–{line.end} ms\n'+parts[:14000]


class IssuesDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.studio=window;self.setWindowTitle('集中疑点校对');self.setModal(False)
        area=self.screen().availableGeometry();self.resize(min(960,area.width()-30),min(850,area.height()-40));self.setMinimumSize(600,480)
        self.items=[];self.filtered=[];self.baseline=None;self.candidate=None;self.adoption=None;self.loading=False
        root=QVBoxLayout(self);root.addWidget(label('按问题校对：先比较与试听，再采用、手改、保留或暂缓。处理疑点与确认时间／读音分别记录。'))
        row=QHBoxLayout();self.kind=QComboBox();self.kind.addItem('全部类型','all')
        for key,title in KINDS.items():self.kind.addItem(title,key)
        self.severity=QComboBox();self.severity.addItem('全部程度','all')
        for key,title in SEVERITIES.items():self.severity.addItem(title,key)
        self.status_filter=QComboBox()
        for title,key in [('待处理（含暂缓）','pending'),('全部状态','all'),('保留当前','keep'),('暂缓','defer'),('需重新检查','changed')]:self.status_filter.addItem(title,key)
        self.order=QComboBox();self.order.addItem('歌词顺序','lyrics');self.order.addItem('严重优先','severity')
        for control in (self.kind,self.severity,self.status_filter,self.order):control.setMinimumContentsLength(6);control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);row.addWidget(control)
        root.addLayout(row);row=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('搜索歌词、当前值或提示');row.addWidget(self.search,1)
        self.layout_check=QCheckBox('含排版');self.layout_check.setChecked(True);self.layout_check.setToolTip('包括实际字体、安全区及歌名区域的重叠抽查；不调用 API。');row.addWidget(self.layout_check)
        self.refresh_button=button('重新检查','重新读取当前工程和已存任务结果；不重跑转录、LLM 或付费请求。',self.refresh);row.addWidget(self.refresh_button);root.addLayout(row)
        self.undo_button=button('撤销上一步','撤销主工程的上一步操作，包含疑点处理；搜索文字的撤销仍在输入框内。',self.undo_project);row.addWidget(self.undo_button)
        self.summary=label();root.addWidget(self.summary);self.message=label();root.addWidget(self.message);self.message.hide()
        self.splitter=QSplitter(Qt.Orientation.Vertical);root.addWidget(self.splitter,1)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['程度','歌词','问题','状态']);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.table.setMinimumHeight(100);self.table.verticalHeader().hide();self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        for col,width in [(0,82),(1,70),(3,90)]:self.table.setColumnWidth(col,width)
        self.splitter.addWidget(self.table);self.detail_scroll=QScrollArea();self.detail_scroll.setWidgetResizable(True);body=QWidget();detail=QVBoxLayout(body);self.detail_scroll.setWidget(body);self.splitter.addWidget(self.detail_scroll);self.splitter.setSizes([220,330])
        self.title=label();self.why=label();detail.addWidget(self.title);detail.addWidget(self.why)
        comparison=QWidget();columns=QHBoxLayout(comparison);columns.setContentsMargins(0,0,0,0)
        self.current=QPlainTextEdit();self.suggested=QPlainTextEdit()
        for title,control in [('当前值',self.current),('建议／试听后决定',self.suggested)]:
            control.setReadOnly(True);control.setMinimumWidth(0);control.setMinimumHeight(65);control.setMaximumHeight(130)
            column=QVBoxLayout();column.addWidget(label(title));column.addWidget(control);columns.addLayout(column,1)
        detail.addWidget(comparison)
        self.old=QPlainTextEdit();self.old.setReadOnly(True);self.old.setMinimumWidth(0);self.old.setMaximumHeight(110);detail.addWidget(self.old);self.old.hide()
        row=QHBoxLayout();self.locate=button('定位到编辑处','定位当前歌词、词组或音节；不采用建议。',lambda:self.jump(False));self.listen=button('带前音试听','定位后用主界面细听播放上下文；不修改原文、轴或确认。',lambda:self.jump(True));self.stop=button('停止试听','停止临时细听并恢复常规播放设置。',lambda:self.studio.playback.stop())
        for control in (self.locate,self.listen,self.stop):row.addWidget(control)
        root.addLayout(row);row=QHBoxLayout();self.tool=button('打开对应工具','按问题打开读音、分词、声音空隙、局部匹配、样式或确认入口，不自动确认。',self.open_tool);row.addWidget(self.tool)
        self.pending=button('待审任务审核…','保留原审核流程的快照、锁定及人工保护；过期任务仍可在本清单比较。',self.review_task);row.addWidget(self.pending);root.addLayout(row)
        row=QHBoxLayout();self.adopt=button('采用这条建议','只采用上面明确比较的本地建议；与处理记录同一步撤销，不自动确认时间或读音。',self.adopt_selected);self.adopt.setObjectName('primary')
        self.manual=button('前往手改','收起清单并定位相应编辑入口；修改后可重新打开疑点清单。',self.manual_selected)
        self.keep=button('保留当前','只记住对这条依据的保留决定；不修改歌词、时间或确认，新依据会重新待查。',lambda:self.decide('keep'))
        self.defer=button('暂缓','稍后处理此疑点；仍计入待处理，不自动确认。',lambda:self.decide('defer'))
        self.close_button=button('关闭','关闭疑点清单；已采用的编辑与处理记录留在工程，仍需保存。',self.close)
        for control in (self.adopt,self.manual,self.keep,self.defer,self.close_button):row.addWidget(control)
        root.addLayout(row)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.refresh)
        self.detail_timer=QTimer(self);self.detail_timer.setSingleShot(True);self.detail_timer.timeout.connect(self.focus_comparison)
        for control in (self.kind,self.severity,self.status_filter,self.order):control.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters);self.layout_check.toggled.connect(self.refresh);self.table.currentCellChanged.connect(self.select);self.table.cellDoubleClicked.connect(lambda *_:self.manual_selected())
        self.refresh()

    def selected(self):
        row=self.table.currentRow();return self.filtered[row] if 0<=row<len(self.filtered) else None

    def schedule_refresh(self):
        if not self.isVisible():return
        current=(self.studio.project.to_dict(),copy.deepcopy(self.studio.pending))
        if current!=self.baseline:
            self.message.setText('工程或待审结果已变化，正在按当前内容重新检查；旧比较尚未采用。');self.message.show();self.adopt.setEnabled(False);self.keep.setEnabled(False);self.defer.setEnabled(False);self.timer.start(150)

    def refresh(self,*_):
        self.timer.stop();selected=self.selected();uid=selected.id if selected else None
        try:
            self.items=collect(self.studio.project,self.layout_check.isChecked(),self.studio.pending);self.baseline=(self.studio.project.to_dict(),copy.deepcopy(self.studio.pending));self.message.clear();self.message.hide()
            counts=progress(self.items,self.studio.project.review_states);confirmed=self.studio.project.summary()
            self.summary.setText(f'当前 {counts["total"]} 项，待处理 {counts["pending"]}（暂缓 {counts["defer"]}），保留 {counts["keep"]}；已直接采用 {counts["saved_adoptions"]} 条记录。\n时间确认 {confirmed["timing"]}/{confirmed["lines"]}，读音确认 {confirmed["readings"]}/{confirmed["lines"]}；自动生成不会自动确认。')
        except (ValueError,OSError,TypeError,KeyError) as error:self.items=[];self.message.setText('疑点检查未完成，工程与任务结果保留：'+str(error));self.message.show()
        self.pending.setEnabled(bool(self.studio.pending));self.undo_button.setEnabled(bool(self.studio.history.undo_stack));self.apply_filters(preferred=uid)

    def apply_filters(self,*_,preferred=None):
        if self.loading:return
        previous=self.selected();uid=preferred or (previous.id if previous else None);records=self.studio.project.review_states;search=self.search.text().casefold();wanted=self.status_filter.currentData()
        def accepted(item):
            status=state(item,records)
            return (self.kind.currentData() in ('all',item.kind) and self.severity.currentData() in ('all',item.severity)
                    and (wanted=='all' or wanted=='pending' and status in {'open','changed','defer'} or wanted==status)
                    and (not search or search in (' '.join((item.title,item.why,item.current,item.suggested))).casefold()))
        self.filtered=[v for v in self.items if accepted(v)]
        if self.order.currentData()=='severity':self.filtered.sort(key=lambda v:(list(SEVERITIES).index(v.severity),v.row,v.word,v.part))
        else:self.filtered.sort(key=lambda v:(v.row,v.word,v.part,list(SEVERITIES).index(v.severity)))
        self.loading=True;blocker=QSignalBlocker(self.table);self.table.setRowCount(len(self.filtered))
        for row,item in enumerate(self.filtered):
            for col,text in enumerate((SEVERITIES[item.severity],f'第 {item.row+1} 句' if item.row>=0 else '工程',item.title,STATES[state(item,records)])):
                cell=QTableWidgetItem(text);cell.setToolTip(item.why);self.table.setItem(row,col,cell)
        del blocker;self.loading=False
        target=next((i for i,v in enumerate(self.filtered) if v.id==uid),0 if self.filtered else -1)
        if target>=0:self.table.setCurrentCell(target,0)
        self.select()

    def select(self,*_):
        if self.loading:return
        item=self.selected();self.candidate=None;self.adoption=None;self.adopt.setEnabled(False)
        for control in (self.locate,self.listen,self.tool,self.manual,self.keep,self.defer):control.setEnabled(item is not None)
        self.old.hide()
        if item is None:self.title.setText('当前筛选没有疑点。可切换类型／状态，或返回编辑。');self.why.clear();self.current.clear();self.suggested.clear();return
        self.title.setText((f'第 {item.row+1} 句 · ' if item.row>=0 else '')+KINDS[item.kind]+' · '+item.title);self.why.setText(item.why);self.current.setPlainText(item.current);self.suggested.setPlainText(item.suggested)
        self.listen.setEnabled(item.row>=0)
        old=self.studio.project.review_states.get(item.id)
        if old and state(item,self.studio.project.review_states)=='changed':
            notice='上次采用后，此疑点再次出现，请重新检查。' if old['decision']=='adopted' else '上次决定仅属于旧依据。'
            self.old.setPlainText('上次决定：'+STATES[old['decision']]+'\n'+notice+'\n旧当前值：'+old['current']+'\n旧建议：'+old['suggested']);self.old.show()
        if item.proposal:
            try:
                candidate=proposed_line(self.studio.project,item);original=self.studio.project.lines[item.row]
                if candidate.to_dict()!=original.to_dict():
                    self.candidate=candidate;self.adoption={'line':original.to_dict(),'checks':copy.deepcopy(self.studio.project.checks.get(original.id,{})),'preview':candidate.to_dict()};self.adopt.setEnabled(True)
                    self.current.setPlainText(item.current+'\n\n'+describe(original));self.suggested.setPlainText(item.suggested+'\n\n'+describe(candidate))
                    if self.studio.project.source_ass_active:self.why.setText(self.why.text()+' 采用后使用声稿排版，原 ASS 保留，可一步撤销。')
            except (ValueError,OSError) as error:self.why.setText(self.why.text()+' 当前不能直接采用：'+str(error))
        self.detail_timer.start(0)

    def focus_comparison(self):
        if self.isVisible() and self.selected() is not None:
            self.detail_scroll.ensureWidgetVisible(self.current,0,4)
            point=self.current.mapTo(self.detail_scroll.viewport(),self.current.rect().topLeft());bar=self.detail_scroll.verticalScrollBar()
            extra=point.y()+self.current.height()+4-self.detail_scroll.viewport().height()
            if extra>0:bar.setValue(bar.value()+extra)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'detail_timer'):self.detail_timer.start(0)

    def decide(self,decision):
        item=self.selected()
        if item and self.studio.decide_review_issue(item,decision):self.refresh()

    def adopt_selected(self):
        item=self.selected()
        if item and self.adoption and self.studio.adopt_review_issue(item,copy.deepcopy(self.adoption)):self.refresh()

    def jump(self,listen=False):
        item=self.selected()
        if item:self.studio.locate_review_issue(item,listen)

    def manual_selected(self):
        if self.selected():self.hide();self.studio.manual_review_issue(self.selected())

    def open_tool(self):
        if self.selected():self.hide();self.studio.manual_review_issue(self.selected(),specific=True)

    def review_task(self):
        pending=self.studio.pending
        if not isinstance(pending,dict) or not isinstance(pending.get('result'),dict) or not pending['result'].get('suggestions'):
            self.message.setText('待审任务没有可用建议，原记录保持；请查看任务记录，不自动重复提交。');self.message.show();return
        self.hide();self.studio.review_pending();self.refresh();self.show()

    def undo_project(self):
        before=self.studio.project.to_dict();self.studio.undo();self.refresh()
        if self.studio.project.to_dict()==before:self.message.setText(self.studio.status.text() or '当前没有可撤销的工程操作。');self.message.show()

    def closeEvent(self,event):self.timer.stop();self.detail_timer.stop();super().closeEvent(event)


class IssuesWorkflow:
    def build_issue_tools(self,layout):
        self.issue_dialog=None;self.issues_button=button('集中疑点清单…','汇总未匹配、读音、缺音节、间隔、时长、范围与排版；筛选、定位、试听和处理。',self.open_review_issues);layout.addWidget(self.issues_button)

    def open_review_issues(self):
        if not self.flush_edits():return False
        if self.issue_dialog is None:self.issue_dialog=IssuesDialog(self)
        else:self.issue_dialog.refresh()
        self.issue_dialog.show();self.issue_dialog.raise_();self.issue_dialog.activateWindow();return True

    def refresh_issue_tools(self):
        if getattr(self,'issue_dialog',None) is not None:self.issue_dialog.schedule_refresh()

    def decide_review_issue(self,item,decision):
        if not isinstance(decision,str) or decision not in {'keep','defer'}:self.message('只有实际采用成功后才能记录采用；这里请选择保留或暂缓。');return False
        if not self.flush_edits():return False
        try:fresh=current_issue(self.project,item,include_layout=item.kind=='layout',pending=self.pending)
        except (ValueError,OSError) as error:self.message(str(error));return False
        changed=self.edit('疑点：'+('保留当前' if decision=='keep' else '暂缓'),lambda p:setattr(p,'review_states',record_decision(p.review_states,fresh,decision)))
        if changed:self.message('疑点处理已记录，可一步撤销；时间和读音确认保持，依据变化后重新待查。')
        return changed

    def adopt_review_issue(self,item,expected):
        if not self.flush_edits():return False
        try:
            fresh=current_issue(self.project,item,include_layout=False,pending=self.pending);original=self.project.lines[fresh.row]
            if original.to_dict()!=expected.get('line') or self.project.checks.get(original.id,{})!=expected.get('checks'):raise ValueError('本句、人工修改或确认已变化，旧比较未采用，请刷新。')
            candidate=proposed_line(self.project,fresh)
            if candidate.to_dict()!=expected.get('preview'):raise ValueError('建议预览与当前计算不同，请重新比较；原内容保持。')
            if candidate.to_dict()==original.to_dict():return False
        except (ValueError,OSError,IndexError) as error:self.message(str(error));return False
        def apply(project):
            project.lines[fresh.row]=copy.deepcopy(candidate);project.source_ass_active=False
            if fresh.proposal['kind']=='reading':project.checks.setdefault(original.id,{})['reading']=False
            project.review_states=record_decision(project.review_states,fresh,'adopted')
        changed=self.edit('采用疑点建议',apply)
        if changed:self.current=fresh.row;self.refresh();self.message('已采用这一条建议，与处理记录同一步撤销；仍需分别确认时间与读音。')
        return changed

    def locate_review_issue(self,item,listen=False):
        if not self.flush_edits():return False
        row=next((i for i,line in enumerate(self.project.lines) if line.id==item.line_id),None)
        if row is None:self.set_stage(3 if item.kind=='layout' else 0);self.message(item.why);return False
        self.current=row;self.refresh();self.set_stage(2);line=self.line
        word=item.word if 0<=item.word<len(line.units) else -1
        part=item.part if word>=0 and 0<=item.part<len(line.units[word].highlights) else -1
        self.granularity.setCurrentIndex(self.granularity.findData('mora' if part>=0 else 'words' if word>=0 else 'line'));self.select_target(word,part);self.timeline.focus_selection();self.show_editor_widget(self.target)
        if listen:
            self.fine_listening.toggle.setChecked(True);self.refresh_fine_listening();self.fine_listener.listen(True)
        return True

    def manual_review_issue(self,item,specific=False):
        if item.kind=='layout':
            if not self.flush_edits():return False
            self.set_stage(3);self.pages.widget(3).ensureWidgetVisible(self.song_info_button if '歌名' in item.why or '歌手' in item.why else self.font_choice);self.message(item.why);return True
        if not self.locate_review_issue(item):return False
        if item.kind=='missing' and not self.line.units:self.resegment_current()
        elif item.kind=='reading' or item.kind=='missing' and 0<=self.timeline.word<len(self.line.units) and not self.line.units[self.timeline.word].kana:
            if '罗马音' in item.title:self.edit_romanization()
            else:self.edit_selected_reading()
        elif item.kind=='translation':self.optional_reading.toggle.setChecked(True);self.show_editor_widget(self.translation);self.translation.setFocus()
        elif item.kind=='confirmation':
            reading='读音' in item.title;self.calibration_tabs.setCurrentIndex(1 if reading else 0);self.show_editor_widget(self.reading_confirm if reading else self.timing_confirm)
        elif specific and item.kind=='gap':self.time_scope.setCurrentIndex(self.time_scope.findData('current'));self.start_sound_gaps()
        elif specific and item.kind=='match':self.local_match()
        elif item.kind=='duration':self.mora_editing.toggle.setChecked(True);self.show_editor_widget(self.mora_editor)
        elif item.kind=='missing':self.show_editor_widget(self.fill_mora_button)
        else:self.show_editor_widget(self.begin)
        self.message(item.why);return True
