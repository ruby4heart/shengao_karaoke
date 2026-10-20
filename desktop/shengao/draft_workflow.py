"""Novice-facing staged generation and explicit recovery of saved draft work."""
import copy
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
    QCheckBox,QDialogButtonBox,QTableWidget,QTableWidgetItem,QHeaderView,QScrollArea,QWidget,QApplication,QFrame)
from studio_backend import draft
from .dialogs import button
from .project import file_stamp
from .vocal_audio import bound


def note(text):
    widget=QLabel(text);widget.setTextFormat(Qt.TextFormat.PlainText);widget.setWordWrap(True);return widget


class DraftDialog(QDialog):
    def __init__(self,parent,eligible,protected,reusable):
        super().__init__(parent);self.setWindowTitle('按步骤生成初稿')
        height=min(710,max(420,QApplication.primaryScreen().availableGeometry().height()-80));self.resize(660,height)
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll,1)
        layout.addWidget(note(f'处理 {eligible} 句；保留 {protected} 句已确认、锁定或人工校准的内容。原歌词保持，所有结果先审核。'))
        layout.addWidget(note('1. 用什么帮助确定歌词位置？'))
        self.source=QComboBox();self.source.addItem('离线开始 · 使用现有整句范围（估算）','offline')
        self.source.addItem('使用本工程已有转录 · 不重新上传','reuse');self.source.addItem('联网识别音轨 · 使用服务额度','cloud')
        self.source.model().item(1).setEnabled(reusable);self.source.setCurrentIndex(1 if reusable else 0);layout.addWidget(self.source)
        self.provider=QComboBox();self.provider.addItem('ElevenLabs · Scribe','elevenlabs');self.provider.addItem('Microsoft AI','mai');layout.addWidget(self.provider)
        self.source.currentIndexChanged.connect(lambda _:self.provider.setVisible(self.source.currentData()=='cloud'));self.provider.hide()
        layout.addWidget(note('2. 按原歌词匹配／分词 · 在本机完成，转录空格不会替换原文。'))
        self.llm=QCheckBox('3. 另用 DeepSeek 复核假名与译文（发送文字、使用额度）');layout.addWidget(self.llm)
        layout.addWidget(note('不勾选时使用本地词典与可用的转录文字。已确认读音和已有译文保留，特殊唱法仍需试听。'))
        self.align=QCheckBox('4. 另用 ElevenLabs 做文字对齐（上传音轨、使用额度）');layout.addWidget(self.align)
        layout.addWidget(note('字符／词组时间不等于演唱音节边界。未获得声音证据的细音节仍为均分估算。'))
        media_ready=bool(parent.project.media and file_stamp(parent.project.media))
        self.acoustic=QCheckBox('5. 本机按歌声细分音节（TIFA，不上传、无需密钥）');self.acoustic.setEnabled(media_ready);layout.addWidget(self.acoustic)
        self.audio=QComboBox()
        for title,key in [('自动：优先已有对应人声，否则原声','auto'),('使用当前视频原声','original'),('使用已生成的人声辅助','vocals')]:self.audio.addItem(title,key)
        self.audio.model().item(2).setEnabled(bound(parent.project.vocal_track,parent.project.media));layout.addWidget(self.audio)
        self.fit=QCheckBox('微调粗略句首句尾；已确认、锁定和人工校准的行保留');self.fit.setChecked(True);layout.addWidget(self.fit)
        layout.addWidget(note('TIFA 模型限个人非商业用途（CC BY-NC-SA 4.0）。以本次假名为输入，不自动确认读音。仅有等分范围时，建议先复用转录或联网识别，避免对到错误唱段。'))
        def update_audio():self.audio.setEnabled(self.acoustic.isChecked());self.fit.setEnabled(self.acoustic.isChecked())
        self.acoustic.toggled.connect(update_audio)
        self.source.currentIndexChanged.connect(lambda _:self.acoustic.setChecked(media_ready and self.source.currentData()!='offline'))
        self.acoustic.setChecked(media_ready and self.source.currentData()!='offline');update_audio()
        layout.addWidget(note('6. 准备审核 · 每句歌声结果立即保留，取消后可继续；未获得声音边界的行保留初稿并显示原因。已完成联网步骤不重复运行，状态不明的付费请求仍需手动决定重试。'))
        self.error=note('');layout.addWidget(self.error)
        self.overview=note('');outer.addWidget(self.overview)
        def overview():
            source={'offline':'本地粗稿','reuse':'复用转录','cloud':'联网转录（上传音轨、使用额度）'}[self.source.currentData()]
            steps=[source,'DeepSeek 读音（使用额度）' if self.llm.isChecked() else '本地读音']
            if self.align.isChecked():steps.append('联网文字对齐（使用额度）')
            if self.acoustic.isChecked():steps.append('本机歌声音节（限非商业）')
            self.overview.setText('本次：'+' → '.join(steps)+' → 审核')
        for widget in (self.llm,self.align,self.acoustic):widget.toggled.connect(overview)
        self.source.currentIndexChanged.connect(overview);overview()
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('开始这条流程')
        controls.button(QDialogButtonBox.StandardButton.Ok).setEnabled(eligible>0)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('暂不开始')
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);outer.addWidget(controls)

    def options(self):
        result={'source':self.source.currentData(),'provider':self.provider.currentData(),
                'readings':'deepseek' if self.llm.isChecked() else 'dictionary','align':self.align.isChecked()}
        if self.acoustic.isChecked():result.update(acoustic=True,acoustic_audio=self.audio.currentData(),fit_range=self.fit.isChecked())
        return result


class ResumeDraftDialog(QDialog):
    def __init__(self,parent,state,changed=0):
        super().__init__(parent);self.setWindowTitle('继续上次初稿流程');self.resize(640,510);self.review_only=False
        layout=QVBoxLayout(self);layout.addWidget(note(f'原流程包含 {len(state["request"]["lines"])} 句。'+(f'其中 {changed} 句已被人工修改；这些行会保留当前内容，不直接采用旧建议。' if changed else '完成的步骤将直接复用。')))
        self.table=QTableWidget(len(state['stages']),3);self.table.setHorizontalHeaderLabels(['步骤','状态','处理位置']);self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row,stage in enumerate(state['stages']):
            status='上次未返回／状态待查' if stage['state']=='running' else draft.STATES.get(stage['state'],'未知')
            for col,text in enumerate([stage['title'],status,'联网服务' if stage['paid'] else '本机／已有结果']):
                self.table.setItem(row,col,QTableWidgetItem(text))
        layout.addWidget(self.table);layout.addWidget(note(state.get('message','') or '结果先审核，不会自动写入工程。'))
        incomplete=next((s for s in state['stages'] if s['state'] not in {'completed','skipped'}),None)
        self.retry_stage=incomplete['key'] if incomplete and incomplete['paid'] and incomplete['state'] in {'running','failed','cancelled','partial'} else ''
        self.retry=QCheckBox('我已检查服务记录，仍要手动重试这个未完成的联网阶段');self.retry.setVisible(bool(self.retry_stage));layout.addWidget(self.retry)
        if self.retry_stage:layout.addWidget(note('上次请求可能已由服务端处理；程序无法恢复未收到的响应。这里只重试此阶段，已完成的步骤保持。'))
        self.review_button=button('先审核已完成的初稿',self.review);self.review_button.setEnabled(bool(draft.result(state)['suggestions']));layout.addWidget(self.review_button)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.continue_button=controls.button(QDialogButtonBox.StandardButton.Ok);self.continue_button.setText('继续未完成步骤' if incomplete else '复用完整结果')
        self.continue_button.setEnabled(not self.retry_stage);self.retry.toggled.connect(self.continue_button.setEnabled)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('关闭');controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)

    def review(self):self.review_only=True;self.accept()


class DraftWorkflow:
    def build_draft_workflow(self,layout):
        self.draft_button=button('按步骤生成初稿…',self.start_draft);self.draft_button.setObjectName('primary');layout.addWidget(self.draft_button)
        self.draft_status=note('转录 → 原歌词匹配 → 读音建议 → 可选文字对齐 → 歌声音节 → 审核\n每句完成会保留；可以取消后继续，也可单独运行某一步。');layout.addWidget(self.draft_status)
        self.draft_resume_button=button('查看／继续上次初稿流程…',self.resume_draft);layout.addWidget(self.draft_resume_button)
        self._draft_summary=None

    def show_draft_progress(self,value):
        if value.get('context',{}).get('project')!=self.project.uid:return
        self._draft_summary=value
        def text(s):
            message=f'{s["title"]}：{draft.STATES.get(s["state"],s["state"])}';a=s.get('acoustic')
            return message+(f' · {a["processed"]}/{a["total"]} 句，{a["aligned"]} 候选，{a["needs_manual"]} 待手工' if a else '')
        self.draft_status.setText('\n'.join(text(s) for s in value['stages']))
        if value.get('status')=='paused' and value.get('message'):
            self.draft_status.setText(self.draft_status.text()+'\n'+value['message'])
        self.draft_status.setToolTip(value.get('message',''))

    def draft_available(self):
        if not self.flush_edits():return False
        if self.api.busy or self.source_job:self.message('请先等待当前后台任务完成');return False
        if not self.project.lines:self.message('请先粘贴并确认原歌词，再生成初稿');return False
        return True

    def start_draft(self):
        if not self.draft_available():return
        if self.pending and self.pending.get('result',{}).get('suggestions'):
            self.message('请先审核或放弃当前建议，再建立新的初稿流程');return
        lines=[line for line in self.project.lines if not draft.protected(line)]
        reusable=bool(self.project.transcript and self.project.transcript_stamp and self.project.transcript_stamp==file_stamp(self.project.media))
        dialog=DraftDialog(self,len(lines),len(self.project.lines)-len(lines),reusable)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        opt=dialog.options()
        if (opt['source']=='cloud' or opt['align'] or opt.get('acoustic')) and not self.project.media:self.message('请先添加音视频；离线流程也能先开始');return
        if opt['source']=='reuse' and not reusable:self.message('已有转录未对应当前素材，请切回原素材或建立新的识别任务');return
        context={'project':self.project.uid,'media':file_stamp(self.project.media)}
        request={'action':'draft','workflow_id':uuid.uuid4().hex,'draft_options':opt,
                 'media':self.project.media,'lines':[x.to_dict() for x in lines],
                 'transcript':self.project.transcript if opt['source']=='reuse' else [],
                 'transcript_stamp':copy.deepcopy(self.project.transcript_stamp) if opt['source']=='reuse' else {},
                 'reading_confirmed_ids':[x.id for x in lines if self.project.checks.get(x.id,{}).get('reading')],
                 'language':'ja','gap_ms':500 if self.continuous_timing.isChecked() else 0,
                 'join_lines':self.continuous_timing.isChecked(),'_studio_context':context}
        request['_studio_checks']={x.id:copy.deepcopy(self.project.checks.get(x.id,{})) for x in lines}
        if opt.get('acoustic'):request['vocal_track']=copy.deepcopy(self.project.vocal_track) if bound(self.project.vocal_track,self.project.media) else {}
        self.submit_draft(request)

    def submit_draft(self,request):
        self.snapshots={x['id']:copy.deepcopy(x) for x in request['lines']}
        request['_studio_snapshots']=copy.deepcopy(self.snapshots)
        self.api.start(request);self.message('初稿流程已开始；每步完成会保存，结果先审核。')

    def resume_draft(self,workflow_id=None):
        if not self.draft_available():return
        try:
            state=draft.load(self.home,workflow_id) if workflow_id else draft.latest(self.home,self.project.uid)
            if not state:self.message('本工程没有保存的初稿流程，可以先建立一条流程');return
            request=copy.deepcopy(state['request']);context=request.get('_studio_context',{})
            if context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media):
                self.message('该流程对应另一工程或素材，请先打开原工程和原素材；检查点保留');return
            pending_id=self.pending.get('result',{}).get('workflow',{}).get('id') if self.pending else None
            if self.pending and self.pending.get('result',{}).get('suggestions') and pending_id!=state['id']:
                self.message('请先审核或放弃另一任务的建议，再继续此流程');return
            current={x.id:x.to_dict() for x in self.project.lines}
            changed=sum(current.get(x['id'])!=x for x in request['lines'])
            dialog=ResumeDraftDialog(self,state,changed)
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            if dialog.review_only:
                self.snapshots={x['id']:x for x in request['lines']};self.api.request={'action':'draft',**request};self.api.folder=draft.checkpoint_path(self.home,state['id']).parent
                self.api_done({'ok':True,**draft.result(state)});self.review_pending();return
            request.update(workflow_id=state['id'],resume=True)
            if dialog.retry_stage and dialog.retry.isChecked():request['retry_stage']=dialog.retry_stage
            self.submit_draft(request)
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.message('无法继续此流程，请检查本机检查点；没有自动重试联网请求。')
