"""Cancelable sound review with persistent results and stale-edit protection."""
from pathlib import Path
import copy
import uuid
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog
from studio_backend import sound_gaps
from studio_backend.settings import atomic_json
from . import jobs,sound_gap_audio
from .project import file_stamp
from .sound_gap_dialog import SoundGapOptions,SoundGapDialog


class SoundGapWorkflow:
    def refresh_sound_gap_tools(self):
        if not hasattr(self,'sound_gap_review'):return
        pending=bool(self.pending and self.pending.get('action')=='sound_gaps')
        busy=self.api.busy or self.source_job or self.local_job or self.analysis_job
        self.cleanup_gaps_button.setEnabled(bool(self.line and self.project.media and not busy and not self.pending))
        self.sound_gap_review.setVisible(pending);self.sound_gap_review.setEnabled(pending and not busy)

    def start_sound_gaps(self):
        if self.api.busy or self.source_job or self.local_job or self.analysis_job:self.message('请先等待或取消当前素材任务。');return False
        if self.pending:self.message('请先审核或暂不采用当前建议；原始结果会保留在任务记录。');return False
        if not self.line or not self.flush_edits():return False
        if not file_stamp(self.project.media):self.message('请先添加可读取的音视频素材。');return False
        selected=[i for i,line in enumerate(self.project.lines) if line.id in self._selected_lyric_ids]
        dialog=SoundGapOptions(self.project,self.current,selected,self.audition_role,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return False
        options=dialog.options()
        if dialog.prepare_vocals:
            uid=self.project.uid;source=self.project.media
            def ready():
                if self.project.uid==uid and self.project.media==source:self.run_sound_gaps(options)
            return self.generate_vocals(after_ready=ready)
        return self.run_sound_gaps(options)

    def run_sound_gaps(self,options):
        if not self.flush_edits() or self.api.busy or self.source_job or self.local_job or self.pending:return False
        if not options.get('indices'):self.message('没有可检查的歌词范围。');return False
        lines=copy.deepcopy(self.project.lines);source=self.project.media;role=self.audition_role
        track=copy.deepcopy(self.project.vocal_track);stamp=file_stamp(source);uid=self.project.uid
        folder=self.home/'desktop-tasks'/uuid.uuid4().hex;folder.mkdir(parents=True)
        context={'project':uid,'media':stamp};snapshots={line.id:line.to_dict() for line in lines}
        request={'action':'sound_gaps','lines':list(snapshots.values()),'options':options,'audio_role':role,
                 '_studio_context':context,'_studio_snapshots':snapshots}
        atomic_json(folder/'request.json',request)
        self._source_serial+=1;serial=self._source_serial;self.source_job_kind='sound_gaps'
        def valid():return not self.closing and serial==self._source_serial
        def work(cancel,progress):
            try:
                report=sound_gap_audio.generate(lines,source,track,role,self.home,cancel,progress,**options)
                result={'ok':True,'action':'sound_gaps','gap_report':report,
                        'suggestions':[lines[i].to_dict() for i in options['indices']],
                        'message':'声音空隙已检查，原时间未改动。请逐项试听、保留或采用。'}
                atomic_json(folder/'result.json',result);return result
            except Exception as error:
                atomic_json(folder/'result.json',{'ok':False,'message':str(error)});raise
        def failed(message):
            if not valid():return
            self.source_job=None;self.busy_changed();self.message('声音空隙检查未采用，原时间保留。'+str(message))
        def done(result):
            if not valid():return
            cancelled=self.source_job is not None and self.source_job.cancel.is_set();self.source_job=None;self.busy_changed()
            if cancelled:self.message('已取消检查；已完成结果保留在任务记录，时间未改动。');return
            if self.project.uid!=uid or file_stamp(self.project.media)!=stamp:self.message('工程或素材已变化，结果留在任务记录，未采用。');return
            loaded=str(self.original_audio.get('source_sha256','')) if self.original_audio is not None else ''
            if loaded and loaded!=result['gap_report']['binding']['source_sha256']:
                self.message('素材内容与播放缓存不同，请在视频源菜单选择“重新载入当前源”后再检查；结果已留存，时间未改动。');return
            if not result['gap_report']['gaps']:
                self.message('范围内没有独立空隙，原时间保持；仍需按声音核对起音和尾音。');return
            self.pending={'result':result,'snapshots':snapshots,'folder':str(folder),'action':'sound_gaps','context':context}
            self.save_recovery();self.update_workflow();self.message('声音检查已返回，点击“试听并审核空隙建议”；编辑中的内容保持。')
        def progress(value):
            if not valid():return
            text=value if isinstance(value,str) else f'声音空隙 {value["completed"]}/{value["total"]} 处'
            atomic_json(folder/'progress.json',{'message':text});self.message(text)
        self.source_job=jobs.run(work,done,failed,progress);self.busy_changed();return True

    def review_sound_gaps(self):
        if not self.pending or self.pending.get('action')!='sound_gaps':return
        if self.source_job or self.api.busy or self.local_job:self.message('请等待当前素材任务完成后审核。');return
        if not self.flush_edits():return
        context=self.pending.get('context',{})
        if context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media):self.message('此结果对应另一素材或工程，请切回原素材；任务记录保留。');return
        try:
            report=self.pending['result']['gap_report'];sound_gaps.validate_report(report)
            assert isinstance(report['gaps'],list) and isinstance(report['binding'],dict) and isinstance(report['signature'],str)
        except (KeyError,TypeError,ValueError,AssertionError):self.message('空隙记录不完整，请重新检查；原时间保留。');return
        self._gap_listen_serial=getattr(self,'_gap_listen_serial',0)+1;token=self._gap_listen_serial
        dialog=SoundGapDialog(self.project,report,self.playback,lambda a,b:self.audition_sound_gap(a,b,report,token),self)
        dialog.finished.connect(lambda _:setattr(self,'_gap_listen_serial',self._gap_listen_serial+1))
        answer=dialog.exec()
        if dialog.calibrate:
            gap=dialog.calibrate;row=next((i for i,line in enumerate(self.project.lines) if line.id==gap['left_id']),None)
            if row is None:self.message('原歌词已不存在，旧结果保留在任务记录。');return
            self.pending=None;self.current=row;self.time_scope.setCurrentIndex(0);self.set_stage(2);self.refresh(True)
            if sound_gaps.signature(self.project.lines)==report['signature']:
                self.drag_line.setChecked(False);self.calibration_tabs.setCurrentIndex(0)
                self.granularity.setCurrentIndex(self.granularity.findData('words' if gap['left'][2] is None else 'mora'))
                self.select_target(gap['left'][1],-1 if gap['left'][2] is None else gap['left'][2])
            else:self.select_entire_line()
            self.timeline.focus_selection();self.seek_selection_preview();self.show_editor_widget(self.begin);self.save_recovery()
            self.message('声音结果已保存在任务记录，当前间隔未改动。现在可手工校准，之后重新检查。');return
        if dialog.recheck:
            self.pending=None;self.save_recovery();self.update_workflow();QTimer.singleShot(0,self.start_sound_gaps);return
        if answer==QDialog.DialogCode.Accepted:self.adopt_sound_gaps(report,dialog.selected,dialog.manual)

    def audition_sound_gap(self,start,end,report,token=None):
        role=report['binding']['audio_role']
        def play():
            if token is not None and token!=getattr(self,'_gap_listen_serial',None):return
            if role=='vocals' and self.project.vocal_track.get('sha256')!=report['binding']['audio_sha256']:
                self.message('当前人声与分析结果不同，请重新检查空隙。');return
            self.playback.audition(start,end)
        if role==self.audition_role:play();return
        if role=='original':
            if self.select_vocal_audition(role):play()
        else:self.generate_vocals(after_ready=play)

    def adopt_sound_gaps(self,report,selected,manual):
        if self.source_job or self.api.busy or self.local_job:return False
        if not self.flush_edits():return False
        try:sound_gaps.apply(self.project.lines,report,selected,manual)
        except (ValueError,KeyError,TypeError) as error:self.message(str(error));return False
        source=self.project.media;track=copy.deepcopy(self.project.vocal_track);uid=self.project.uid
        self._source_serial+=1;serial=self._source_serial;self.source_job_kind='sound_gaps'
        def valid():return not self.closing and serial==self._source_serial
        def failed(message):
            if valid():self.source_job=None;self.busy_changed();self.message('原时间保留，声音建议仍可审核。'+str(message))
        def done(stamp):
            if not valid():return
            cancelled=self.source_job is not None and self.source_job.cancel.is_set();self.source_job=None;self.busy_changed()
            if cancelled:self.message('已取消采用，原时间保留。');return
            if self.project.uid!=uid or self.project.media!=source or file_stamp(source)!=stamp:self.message('素材或工程已变化，原时间保留。');return
            if not self.flush_edits():return
            try:values,changes=sound_gaps.apply(self.project.lines,report,selected,manual)
            except (ValueError,KeyError,TypeError) as error:self.message(str(error));return
            if not changes:return
            def commit(project):project.lines=values;project.source_ass_active=False
            if not self.edit('按声音处理空隙',commit):return
            self.pending=None;self.save_recovery();self.refresh();self.message(f'已处理 {len(changes)} 处空隙，下一音节起点保持；可一步撤销。读音与时间尚未自动确认。')
        self.source_job=jobs.run(lambda cancel,progress:sound_gap_audio.verify(source,track,report['binding'],cancel),done,failed)
        self.busy_changed();self.message('正在核对分析音轨后采用；可以继续编辑，变更会受保护。');return True
