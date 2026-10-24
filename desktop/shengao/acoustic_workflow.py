"""Local singing proposals use the same review, persistence and undo contract."""
import copy
import uuid
from PySide6.QtWidgets import QPushButton,QHBoxLayout,QDialog
from studio_backend.acoustic import plan
from studio_backend.settings import atomic_json
from . import acoustic_audio,jobs,vocal_audio
from .project import file_stamp

class AcousticWorkflow:
    def guide_draft_path(self):
        import hashlib
        key=hashlib.sha256((self.project.uid+'\0'+self.line.id).encode()).hexdigest()
        return self.home/'alignment-guides'/(key+'.json')

    def open_acoustic_guides(self,draft=None):
        if self.api.busy or self.source_job or self.analysis_job or self.local_job or self.pending:
            self.message('先处理当前任务或已有建议，再设置固定位置。');return False
        if not self.flush_edits() or not self.line:return False
        if self.line.locked or self.line.reviewed:
            self.message('本句已锁定或确认时间；先解除本句时间确认，再局部重算。');return False
        from studio_backend.acoustic_guides import mora_rows
        from .guide_dialog import GuideDialog
        try:mora_rows(self.line)
        except ValueError as error:
            self.set_stage(2);self.select_entire_line();self.message(str(error));return False
        context={'project':self.project.uid,'media':file_stamp(self.project.media)}
        if not context['media']:self.message('先添加可读取的素材，再试听并固定位置。');return False
        before=self.line.to_dict();path=self.guide_draft_path()
        if draft is None:
            import json
            try:
                value=json.loads(path.read_text(encoding='utf-8'))
                if value.get('version')==1 and value.get('context')==context and value.get('line')==before:
                    draft=value.get('draft')
            except (ValueError,OSError,TypeError):pass
        def save(value):
            path.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(path,{'version':1,'context':context,'line':before,'draft':value})
        try:dialog=GuideDialog(self.line,self.playback,self,draft,save,self.timeline.word,self.timeline.part)
        except (ValueError,KeyError,TypeError,IndexError) as error:
            self.message('定位草稿无法读取，原文件保留；请检查本句分词和音节。'+str(error));return False
        accepted=dialog.exec()==QDialog.DialogCode.Accepted
        if self.project.uid!=context['project'] or file_stamp(self.project.media)!=context['media'] or not self.line or self.line.to_dict()!=before:
            self.message('工程、素材或歌词已变化，定位草稿保留，未开始重算。');return False
        if dialog.manual:
            self.set_stage(2);self.select_target(*dialog.mora.currentData());self.timeline.focus_selection()
            self.message(('定位草稿已保留，' if dialog.draft_saved else '定位草稿未能保存，原轴保持；')+'可在这里直接划音，固定点尚未写入工程。');return True
        if not accepted:
            self.message('定位草稿已保存，原轴保持；重新打开可继续。' if dialog.draft_saved else '定位草稿未能保存，原轴保持；请检查磁盘和目录权限。');return False
        return self.align_acoustic(dialog.prepared)

    def resume_acoustic_guides(self,request):
        if not self.flush_edits():return False
        context=request.get('_studio_context',{});prepared=request.get('plan',{})
        uid=prepared.get('original',{}).get('id')
        index=next((i for i,line in enumerate(self.project.lines) if line.id==uid),None)
        if context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media) or index is None or self.project.lines[index].to_dict()!=prepared.get('original'):
            self.message('工程、素材或本句版本已变化，旧定位与结果保留；请按当前内容重新固定位置。');return False
        self.current=index;self.refresh()
        return self.open_acoustic_guides({'points':prepared.get('guide_points',[]),'scope':prepared.get('guide_scope','between')})

    def release_acoustic_guide(self):
        if not self.flush_edits() or not self.line:return False
        if self.api.busy or self.source_job or self.local_job or self.pending:return False
        i,j=self.timeline.word,self.timeline.part
        if not 0<=i<len(self.line.units) or not 0<=j<len(self.line.units[i].highlights):return False
        if self.line.locked or self.line.reviewed or self.line.units[i].locked:
            self.message('先解除本句或词组锁定及时间确认，再取消固定点。');return False
        if not self.line.units[i].highlights[j].fixed_edges:return False
        row=self.current
        self.edit('取消所选音节固定点',lambda p:setattr(p.lines[row].units[i].highlights[j],'fixed_edges',[]))
        self.granularity.setCurrentIndex(self.granularity.findData('mora'));self.select_target(i,j)
        self.message('已取消所选音节的固定起止点；时间没有移动，可一步撤销。');return True

    def build_acoustic_tools(self,layout,secondary=None):
        self.acoustic_button=QPushButton('按本句歌声重算音节')
        self.acoustic_button.setObjectName('acousticAlignment')
        self.acoustic_button.setToolTip('本地 TIFA · 无需密钥。先圈住本句、填写正确假名；整句头尾不动，人工音节和锁定词组作为固定边界，只重算其间音节。采用前可比较与试听。模型限个人非商业用途（CC BY-NC-SA 4.0）。')
        self.acoustic_button.clicked.connect(self.align_acoustic)
        if secondary is None:layout.addWidget(self.acoustic_button)
        else:
            row=QHBoxLayout();row.addWidget(self.acoustic_button,2);row.addWidget(secondary,1);layout.addLayout(row)
        self.guide_button=QPushButton('固定位置后局部重算…');self.guide_button.setObjectName('guidedAlignment');self.guide_button.setToolTip('在频谱上给定音节起点或终点，只重算其间未固定部分。定位草稿可恢复，采用可撤销；本地 TIFA 模型限个人非商业用途。');self.guide_button.clicked.connect(lambda:self.open_acoustic_guides());layout.addWidget(self.guide_button)
        self.release_guide_button=QPushButton('取消所选音节的固定点');self.release_guide_button.setToolTip('只解除当前选中演唱音节的固定起点与终点；不移动时间，不改变其他音节或读音，可一步撤销。');self.release_guide_button.clicked.connect(self.release_acoustic_guide);layout.addWidget(self.release_guide_button)
        self.acoustic_review=QPushButton('比较并审核歌声音节建议');self.acoustic_review.setToolTip('比较每个音节的新旧时间，带前后音试听，再勾选采用；未采用的结果可从任务记录恢复。');self.acoustic_review.clicked.connect(self.review_pending);layout.addWidget(self.acoustic_review)

    def refresh_acoustic_tools(self):
        if not hasattr(self,'acoustic_button'):return
        pending=bool(self.pending and self.pending.get('action')=='acoustic')
        self.acoustic_button.setEnabled(bool(self.line and self.project.media and not (self.api.busy or self.source_job or self.analysis_job or self.local_job or self.pending)))
        self.guide_button.setEnabled(self.acoustic_button.isEnabled())
        i,j=self.timeline.word,self.timeline.part
        fixed=bool(self.line and 0<=i<len(self.line.units) and 0<=j<len(self.line.units[i].highlights) and self.line.units[i].highlights[j].fixed_edges)
        self.release_guide_button.setVisible(fixed);self.release_guide_button.setEnabled(fixed and not (self.api.busy or self.source_job or self.local_job or self.pending))
        self.acoustic_review.setVisible(pending)
        ready=vocal_audio.bound(self.project.vocal_track,self.project.media)
        self.acoustic_button.setText('按本句人声重算音节' if ready else '按本句原声重算音节')

    def align_acoustic(self,prepared=None):
        if self.api.busy or self.source_job or self.analysis_job or self.local_job:self.message('请先等待或取消当前素材任务。');return False
        if self.pending:self.message('请先审核或暂不采用已有建议，再开始新的对齐。');return False
        if not self.flush_edits() or not self.line:return False
        try:
            if prepared is None or type(prepared) is bool:prepared=plan(self.line)
            elif prepared['original']!=self.line.to_dict():raise ValueError('本句已变化，定位草稿保留，请重新打开固定位置。')
        except ValueError as error:self.message(str(error));return False
        source=self.project.media;stamp=file_stamp(source)
        if not stamp:self.message('请先添加可读取的视频或音频素材。');return False
        folder=self.home/'desktop-tasks'/uuid.uuid4().hex
        uid=self.project.uid;snapshots={self.line.id:self.line.to_dict()};checks=copy.deepcopy(self.project.checks);raw_ass=self.project.source_ass_active
        context={'project':uid,'media':stamp};track=copy.deepcopy(self.project.vocal_track) if vocal_audio.bound(self.project.vocal_track,source) else {}
        request={'action':'acoustic','lines':[prepared['original']],'_studio_context':context,'_studio_snapshots':snapshots,'_studio_checks':checks,'plan':prepared,'audio_role':'vocals' if track else 'original'}
        try:
            folder.mkdir(parents=True);atomic_json(folder/'request.json',request)
        except OSError:
            self.message('无法保存歌声对齐请求，尚未开始计算，原轴与已有定位草稿保留；请检查磁盘和目录权限。');return False
        self._source_serial+=1;serial=self._source_serial;self.source_job_kind='acoustic'
        def valid():return not self.closing and serial==self._source_serial
        def work(cancel,report):
            try:
                result=acoustic_audio.generate(prepared,source,track,self.home,cancel,report)
                if raw_ass:result['message']=result.get('message','')+' 采用后将使用声稿样式显示新音节轴；原 ASS 保留，可撤销。'
                atomic_json(folder/'result.json',result);return result
            except Exception as error:
                atomic_json(folder/'result.json',{'ok':False,'message':str(error)});raise
        def failed(message):
            if not valid():return
            self.source_job=None;self.busy_changed();self.message('歌声对齐未采用，原时间和人工校准保留。'+str(message))
        def done(result):
            if not valid():return
            was_cancelled=self.source_job is not None and self.source_job.cancel.is_set();self.source_job=None;self.busy_changed()
            if was_cancelled:self.message('已取消歌声对齐，原时间保留；已完成结果可从任务记录审核。');return
            if self.project.uid!=uid or file_stamp(self.project.media)!=stamp:self.message('工程或素材版本已变化，对齐结果保存在任务记录，未采用。');return
            self.pending={'result':result,'snapshots':snapshots,'folder':str(folder),'action':'acoustic','context':context,'checks':checks,'plan':prepared}
            # A table editor or time field may still contain unsubmitted input.
            # No model data changed, so avoid rebuilding the editing widgets.
            self.save_recovery();self.update_workflow();self.message('歌声音节已返回；点击“比较并审核歌声音节建议”。尚未写入时间轴，处理中修改的内容会保留。')
        def progress(message):
            atomic_json(folder/'progress.json',{'message':str(message)})
            if valid():self.message(str(message))
        self.source_job=jobs.run(work,done,failed,progress);self.busy_changed();self.message('本句正在本机按歌声对齐，可以继续校对；固定音节保留。');return True
