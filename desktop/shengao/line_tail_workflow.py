"""Cancelable line-tail review with persistent results and stale-edit protection."""
import copy
import uuid
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog
from studio_backend import line_tails
from studio_backend.settings import atomic_json
from . import jobs,sound_gap_audio
from .project import file_stamp
from .line_tail_dialog import LineTailOptions,LineTailDialog


class LineTailWorkflow:
    def refresh_line_tail_tools(self):
        if not hasattr(self,'line_tail_review'):return
        pending=bool(self.pending and self.pending.get('action')=='line_tails')
        busy=self.api.busy or self.source_job or self.local_job or self.analysis_job
        self.line_tails_button.setEnabled(bool(self.line and self.project.media and not busy and not self.pending))
        self.line_tail_review.setVisible(pending);self.line_tail_review.setEnabled(pending and not busy)

    def start_line_tails(self):
        if self.api.busy or self.source_job or self.local_job or self.analysis_job:self.message('请先等待或取消当前素材任务。');return False
        if self.pending:self.message('请先审核或暂不采用当前建议；原始结果会保留在任务记录。');return False
        if not self.line or not self.flush_edits():return False
        if not file_stamp(self.project.media):self.message('请先添加可读取的音视频素材。');return False
        selected=[i for i,line in enumerate(self.project.lines) if line.id in self._selected_lyric_ids]
        dialog=LineTailOptions(self.project,self.current,selected,self.audition_role,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return False
        options=dialog.options()
        if dialog.prepare_vocals:
            uid=self.project.uid;source=self.project.media
            def ready():
                if self.project.uid==uid and self.project.media==source:self.run_line_tails(options)
            return self.generate_vocals(after_ready=ready)
        return self.run_line_tails(options)

    def run_line_tails(self,options):
        if not self.flush_edits() or self.api.busy or self.source_job or self.local_job or self.pending:return False
        if not options.get('indices'):self.message('没有可检查的歌词范围。');return False
        lines=copy.deepcopy(self.project.lines);source=self.project.media;role=self.audition_role
        track=copy.deepcopy(self.project.vocal_track);stamp=file_stamp(source);uid=self.project.uid
        folder=self.home/'desktop-tasks'/uuid.uuid4().hex;folder.mkdir(parents=True)
        context={'project':uid,'media':stamp};snapshots={line.id:line.to_dict() for line in lines}
        request={'action':'line_tails','lines':list(snapshots.values()),'options':options,'audio_role':role,
                 '_studio_context':context,'_studio_snapshots':snapshots}
        atomic_json(folder/'request.json',request)
        self._source_serial+=1;serial=self._source_serial;self.source_job_kind='line_tails'
        def valid():return not self.closing and serial==self._source_serial
        def work(cancel,progress):
            try:
                report=sound_gap_audio.generate_tails(lines,source,track,role,self.home,cancel,progress,options['indices'])
                flagged=sorted({v['row'] for v in report['tails'] if v['status']=='flagged'})
                result={'ok':True,'action':'line_tails','tail_report':report,
                        'suggestions':[lines[i].to_dict() for i in (flagged or options['indices'])],
                        'message':'句尾已检查，原时间未改动。请逐句试听、保持或选择候选。'}
                atomic_json(folder/'result.json',result);return result
            except Exception as error:
                atomic_json(folder/'result.json',{'ok':False,'message':str(error)});raise
        def failed(message):
            if not valid():return
            self.source_job=None;self.busy_changed();self.message('句尾检查未完成，原时间保留。'+str(message))
        def done(result):
            if not valid():return
            cancelled=self.source_job is not None and self.source_job.cancel.is_set();self.source_job=None;self.busy_changed()
            if cancelled:self.message('已取消检查；已完成结果保留在任务记录，时间未改动。');return
            if self.project.uid!=uid or file_stamp(self.project.media)!=stamp:self.message('工程或素材已变化，结果留在任务记录，未采用。');return
            loaded=str(self.original_audio.get('source_sha256','')) if self.original_audio is not None else ''
            if loaded and loaded!=result['tail_report']['binding']['source_sha256']:
                self.message('素材内容与播放缓存不同，请在视频源菜单选择“重新载入当前源”后再检查；结果已留存，时间未改动。');return
            tails=result['tail_report']['tails']
            if not tails:self.message('范围内没有可检查的句尾（没有演唱音节），原时间保持。');return
            flagged=sum(v['status']=='flagged' for v in tails)
            self.pending={'result':result,'snapshots':snapshots,'folder':str(folder),'action':'line_tails','context':context}
            self.save_recovery();self.update_workflow()
            self.message(f'句尾检查完成：{len(tails)} 句中 {flagged} 句有疑点。点击“试听并审核句尾”；编辑中的内容保持。')
        def progress(value):
            if not valid():return
            text=value if isinstance(value,str) else f'句尾 {value["completed"]}/{value["total"]} 句'
            atomic_json(folder/'progress.json',{'message':text});self.message(text)
        self.source_job=jobs.run(work,done,failed,progress);self.busy_changed();return True

    def review_line_tails(self):
        if not self.pending or self.pending.get('action')!='line_tails':return
        if self.source_job or self.api.busy or self.local_job:self.message('请等待当前素材任务完成后审核。');return
        if not self.flush_edits():return
        context=self.pending.get('context',{})
        if context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media):self.message('此结果对应另一素材或工程，请切回原素材；任务记录保留。');return
        try:
            report=self.pending['result']['tail_report'];line_tails.validate_report(report)
            assert isinstance(report['tails'],list) and isinstance(report['binding'],dict) and isinstance(report['signature'],str)
        except (KeyError,TypeError,ValueError,AssertionError):self.message('句尾记录不完整，请重新检查；原时间保留。');return
        self._gap_listen_serial=getattr(self,'_gap_listen_serial',0)+1;token=self._gap_listen_serial
        dialog=LineTailDialog(self.project,report,self.playback,lambda a,b:self.audition_sound_gap(a,b,report,token),self)
        dialog.finished.connect(lambda _:setattr(self,'_gap_listen_serial',self._gap_listen_serial+1))
        answer=dialog.exec()
        if dialog.calibrate:
            tail=dialog.calibrate;row=next((i for i,line in enumerate(self.project.lines) if line.id==tail['line_id']),None)
            if row is None:self.message('原歌词已不存在，旧结果保留在任务记录。');return
            self.pending=None;self.current=row;self.time_scope.setCurrentIndex(0);self.set_stage(2);self.refresh(True)
            if tail['key'] not in line_tails.stale_rows(self.project.lines,report):
                word,part=tail['position'][1],tail['position'][2]
                self.drag_line.setChecked(False);self.calibration_tabs.setCurrentIndex(0)
                self.granularity.setCurrentIndex(self.granularity.findData('words' if part is None else 'mora'))
                self.select_target(word,-1 if part is None else part)
            else:self.select_entire_line()
            self.timeline.focus_selection();self.seek_selection_preview();self.show_editor_widget(self.end);self.save_recovery()
            self.message('句尾检查结果已保存在任务记录，当前时间未改动。现在可手工校准句尾，之后重新检查。');return
        if dialog.recheck:
            self.pending=None;self.save_recovery();self.update_workflow();QTimer.singleShot(0,self.start_line_tails);return
        if answer==QDialog.DialogCode.Accepted:self.adopt_line_tails(report,dialog.choices)

    def adopt_line_tails(self,report,choices):
        if self.source_job or self.api.busy or self.local_job:return False
        if not self.flush_edits():return False
        try:line_tails.apply(self.project.lines,report,choices)
        except (ValueError,KeyError,TypeError) as error:self.message(str(error));return False
        source=self.project.media;track=copy.deepcopy(self.project.vocal_track);uid=self.project.uid
        self._source_serial+=1;serial=self._source_serial;self.source_job_kind='line_tails'
        def valid():return not self.closing and serial==self._source_serial
        def failed(message):
            if valid():self.source_job=None;self.busy_changed();self.message('原时间保留，句尾建议仍可审核。'+str(message))
        def done(stamp):
            if not valid():return
            cancelled=self.source_job is not None and self.source_job.cancel.is_set();self.source_job=None;self.busy_changed()
            if cancelled:self.message('已取消采用，原时间保留。');return
            if self.project.uid!=uid or self.project.media!=source or file_stamp(source)!=stamp:self.message('素材或工程已变化，原时间保留。');return
            if not self.flush_edits():return
            try:values,changes=line_tails.apply(self.project.lines,report,choices)
            except (ValueError,KeyError,TypeError) as error:self.message(str(error));return
            if not changes:return
            def commit(project):project.lines=values;project.source_ass_active=False
            if not self.edit('按声音调整句尾',commit):return
            self.pending=None;self.save_recovery();self.refresh();self.message(f'已调整 {len(changes)} 句的句尾，起点保持；可一步撤销。时间尚未自动确认。')
        self.source_job=jobs.run(lambda cancel,progress:sound_gap_audio.verify(source,track,report['binding'],cancel),done,failed)
        self.busy_changed();self.message('正在核对分析音轨后采用；可以继续编辑，变更会受保护。');return True
