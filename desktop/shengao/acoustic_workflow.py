"""Local singing proposals use the same review, persistence and undo contract."""
import copy
import uuid
from PySide6.QtWidgets import QPushButton
from studio_backend.acoustic import plan
from studio_backend.settings import atomic_json
from . import acoustic_audio,jobs,vocal_audio
from .project import file_stamp

class AcousticWorkflow:
    def build_acoustic_tools(self,layout):
        self.acoustic_button=QPushButton('按本句歌声重算音节')
        self.acoustic_button.setObjectName('acousticAlignment')
        self.acoustic_button.setToolTip('本地 TIFA · 无需密钥。先圈住本句、填写正确假名；整句头尾不动，人工音节和锁定词组作为固定边界，只重算其间音节。采用前可比较与试听。模型限个人非商业用途（CC BY-NC-SA 4.0）。')
        self.acoustic_button.clicked.connect(self.align_acoustic);layout.addWidget(self.acoustic_button)
        self.acoustic_review=QPushButton('比较并审核歌声音节建议');self.acoustic_review.setToolTip('比较每个音节的新旧时间，带前后音试听，再勾选采用；未采用的结果可从任务记录恢复。');self.acoustic_review.clicked.connect(self.review_pending);layout.addWidget(self.acoustic_review)

    def refresh_acoustic_tools(self):
        if not hasattr(self,'acoustic_button'):return
        pending=bool(self.pending and self.pending.get('action')=='acoustic')
        self.acoustic_button.setEnabled(bool(self.line and self.project.media and not (self.api.busy or self.source_job or self.analysis_job or self.local_job or self.pending)))
        self.acoustic_review.setVisible(pending)
        ready=vocal_audio.bound(self.project.vocal_track,self.project.media)
        self.acoustic_button.setText('按本句人声重算音节' if ready else '按本句原声重算音节')

    def align_acoustic(self):
        if self.api.busy or self.source_job or self.analysis_job or self.local_job:self.message('请先等待或取消当前素材任务。');return False
        if self.pending:self.message('请先审核或暂不采用已有建议，再开始新的对齐。');return False
        if not self.flush_edits() or not self.line:return False
        try:prepared=plan(self.line)
        except ValueError as error:self.message(str(error));return False
        source=self.project.media;stamp=file_stamp(source)
        if not stamp:self.message('请先添加可读取的视频或音频素材。');return False
        folder=self.home/'desktop-tasks'/uuid.uuid4().hex;folder.mkdir(parents=True)
        uid=self.project.uid;snapshots={self.line.id:self.line.to_dict()};checks=copy.deepcopy(self.project.checks);raw_ass=self.project.source_ass_active
        context={'project':uid,'media':stamp};track=copy.deepcopy(self.project.vocal_track) if vocal_audio.bound(self.project.vocal_track,source) else {}
        request={'action':'acoustic','lines':[prepared['original']],'_studio_context':context,'_studio_snapshots':snapshots,'_studio_checks':checks,'plan':prepared,'audio_role':'vocals' if track else 'original'}
        atomic_json(folder/'request.json',request)
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
            self.pending={'result':result,'snapshots':snapshots,'folder':str(folder),'action':'acoustic','context':context,'checks':checks}
            # A table editor or time field may still contain unsubmitted input.
            # No model data changed, so avoid rebuilding the editing widgets.
            self.save_recovery();self.update_workflow();self.message('歌声音节已返回；点击“比较并审核歌声音节建议”。尚未写入时间轴，处理中修改的内容会保留。')
        def progress(message):
            atomic_json(folder/'progress.json',{'message':str(message)})
            if valid():self.message(str(message))
        self.source_job=jobs.run(work,done,failed,progress);self.busy_changed();self.message('本句正在本机按歌声对齐，可以继续校对；固定音节保留。');return True
