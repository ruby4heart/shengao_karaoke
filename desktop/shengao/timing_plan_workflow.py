"""Cancelable multi-plan comparison with persistent results, stale-edit protection and one-step adoption."""
import copy
import uuid
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog
from studio_backend import timing_plans
from studio_backend.settings import atomic_json
from . import jobs,timing_plan_sources
from .project import file_stamp
from .timing_plan_dialog import TimingPlanOptions,TimingPlanDialog


class TimingPlanWorkflow:
    def refresh_timing_plan_tools(self):
        if not hasattr(self,'timing_plan_review'):return
        pending=bool(self.pending and self.pending.get('action')=='timing_plans')
        busy=self.api.busy or self.source_job or self.local_job or self.analysis_job
        self.timing_plans_button.setEnabled(bool(self.line and self.project.media and not busy and not self.pending))
        self.timing_plan_review.setVisible(pending);self.timing_plan_review.setEnabled(pending and not busy)

    def start_timing_plans(self):
        if self.api.busy or self.source_job or self.local_job or self.analysis_job:self.message('请先等待或取消当前素材任务。');return False
        if self.pending:self.message('请先审核或暂不采用当前建议；原始结果会保留在任务记录。');return False
        if not self.line or not self.flush_edits():return False
        if not file_stamp(self.project.media):self.message('请先添加可读取的音视频素材。');return False
        selected=[i for i,line in enumerate(self.project.lines) if line.id in self._selected_lyric_ids]
        dialog=TimingPlanOptions(self.project,self.current,selected,timing_plan_sources.availability(self.home,self.project),self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return False
        return self.run_timing_plans(dialog.options())

    def run_timing_plans(self,options):
        if not self.flush_edits() or self.api.busy or self.source_job or self.local_job or self.pending:return False
        if not options.get('indices'):self.message('没有可比对的歌词范围。');return False
        if not options.get('sources'):self.message('请至少选择一种时间来源。');return False
        song,personal,_,_=self.dictionary_sources()
        lines=copy.deepcopy(self.project.lines);data=timing_plan_sources.inputs(self.home,self.project,(song,personal))
        stamp=file_stamp(self.project.media);uid=self.project.uid
        folder=self.home/'desktop-tasks'/uuid.uuid4().hex;folder.mkdir(parents=True)
        context={'project':uid,'media':stamp};snapshots={line.id:line.to_dict() for line in lines}
        request={'action':'timing_plans','lines':list(snapshots.values()),'options':options,
                 '_studio_context':context,'_studio_snapshots':snapshots}
        atomic_json(folder/'request.json',request)
        self._source_serial+=1;serial=self._source_serial;self.source_job_kind='timing_plans'
        def valid():return not self.closing and serial==self._source_serial
        def work(cancel,progress):
            try:
                report=timing_plan_sources.collect(lines,options,data,self.home,cancel,progress)
                flagged=[v['row'] for v in report['lines'] if v['status'] in {'conflict','uncertain'}]
                result={'ok':True,'action':'timing_plans','plan_report':report,
                        'suggestions':[lines[i].to_dict() for i in (flagged or options['indices'])],
                        'message':'各方案已并列，原时间未改动。请逐句试听，保持或选择方案。'}
                atomic_json(folder/'result.json',result);return result
            except Exception as error:
                atomic_json(folder/'result.json',{'ok':False,'message':str(error)});raise
        def failed(message):
            if not valid():return
            cancelled=self.source_job is not None and self.source_job.cancel.is_set();self.source_job=None;self.busy_changed()
            if cancelled:self.message('已取消多方案比对，时间未改动。');return
            self.message('多方案比对未完成，原时间保留。'+str(message))
        def done(result):
            if not valid():return
            cancelled=self.source_job is not None and self.source_job.cancel.is_set();self.source_job=None;self.busy_changed()
            if cancelled:self.message('已取消比对；已完成结果保留在任务记录，时间未改动。');return
            if self.project.uid!=uid or file_stamp(self.project.media)!=stamp:self.message('工程或素材已变化，结果留在任务记录，未采用。');return
            entries=result['plan_report']['lines']
            if not entries:self.message('范围内没有可比对的句子，原时间保持。');return
            attention=sum(v['status'] in {'conflict','uncertain'} for v in entries)
            self.pending={'result':result,'snapshots':snapshots,'folder':str(folder),'action':'timing_plans','context':context}
            self.save_recovery();self.update_workflow()
            self.message(f'多方案比对完成：{len(entries)} 句中 {attention} 句来源分歧或匹配不确定。点击“试听并审核时间方案”；编辑中的内容保持。')
        def progress(value):
            if not valid():return
            text=value if isinstance(value,str) else '多方案比对进行中…'
            atomic_json(folder/'progress.json',{'message':text});self.message(text)
        self.source_job=jobs.run(work,done,failed,progress);self.busy_changed();return True

    def timing_plan_report(self):
        try:
            report=self.pending['result']['plan_report'];timing_plans.validate_report(report)
            assert isinstance(report['sources'],dict) and isinstance(report['signature'],str)
            return report
        except (KeyError,TypeError,ValueError,AssertionError):return None

    def review_timing_plans(self):
        if not self.pending or self.pending.get('action')!='timing_plans':return
        if self.source_job or self.api.busy or self.local_job:self.message('请等待当前素材任务完成后审核。');return
        if not self.flush_edits():return
        context=self.pending.get('context',{})
        if context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media):self.message('此结果对应另一素材或工程，请切回原素材；任务记录保留。');return
        report=self.timing_plan_report()
        if report is None:self.message('多方案比对记录不完整，请重新比对；原时间保留。');return
        dialog=TimingPlanDialog(self.project,report,self.playback,None,self)
        answer=dialog.exec()
        if dialog.calibrate:
            target=dialog.calibrate;row=next((i for i,line in enumerate(self.project.lines) if line.id==target['line_id']),None)
            if row is None:self.message('原歌词已不存在，旧结果保留在任务记录。');return
            self.pending=None;self.current=row;self.time_scope.setCurrentIndex(0);self.set_stage(2);self.refresh(True)
            line=self.project.lines[row]
            if target['line_id'] not in timing_plans.stale_rows(self.project.lines,report) and line.units and target['word'] is not None:
                word,part=target['word'],target['part']
                if target['tail']:
                    word=len(line.units)-1;part=len(line.units[word].highlights)-1 if line.units[word].highlights else None
                self.drag_line.setChecked(False);self.calibration_tabs.setCurrentIndex(0)
                self.granularity.setCurrentIndex(self.granularity.findData('words' if part is None else 'mora'))
                self.select_target(word,-1 if part is None else part)
            else:self.select_entire_line()
            self.timeline.focus_selection();self.seek_selection_preview();self.show_editor_widget(self.begin);self.save_recovery()
            self.message('多方案比对结果已保存在任务记录，当前时间未改动。现在可手工校准，之后重新比对。');return
        if dialog.recheck:
            self.pending=None;self.save_recovery();self.update_workflow();QTimer.singleShot(0,self.start_timing_plans);return
        if answer==QDialog.DialogCode.Accepted:self.adopt_timing_plans(report,dialog.choices)

    def adopt_timing_plans(self,report,choices):
        if self.source_job or self.api.busy or self.local_job:return False
        if not self.flush_edits():return False
        context=(self.pending or {}).get('context',{})
        if context and (context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media)):
            self.message('素材或工程已变化，原时间保留。');return False
        try:values,changes=timing_plans.apply(self.project.lines,report,choices)
        except (ValueError,KeyError,TypeError) as error:self.message(str(error));return False
        if not changes:return False
        confirmed=[v['row']+1 for v in changes if v['changes_reading'] and self.project.checks.get(v['line_id'],{}).get('reading')]
        if confirmed:self.message('第 '+'、'.join(map(str,confirmed))+' 句的读音已确认，不能用改读音的方案；原时间保留。');return False
        def commit(project):
            project.lines=values;project.source_ass_active=False
            for value in changes:
                if value['changes_reading']:project.checks.setdefault(value['line_id'],{})['reading']=False
        if not self.edit('采用多方案比对时间',commit):return False
        reading=sum(v['changes_reading'] for v in changes)
        self.pending=None;self.save_recovery();self.refresh()
        self.message(f'已按所选方案改了 {len(changes)} 句的时间'+(f'（其中 {reading} 句同时改了读音）' if reading else '')+'；可一步撤销。时间尚未自动确认。')
        return True
