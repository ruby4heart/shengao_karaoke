"""Front-end entry and immutable-source guard for local chorus reuse."""
import copy
import uuid
from PySide6.QtWidgets import QPushButton,QDialog
from studio_backend.chorus_reuse import reference_matches,signature
from .chorus_dialog import ChorusDialog
from .project import file_stamp


class ChorusWorkflow:
    def build_chorus_tools(self,layout):
        self.chorus_button=QPushButton('复用已校对副歌…');self.chorus_button.setToolTip('复用人工确认过的相同原文分词和读音，按目标声音重算时间；本地运行，先审核。')
        self.chorus_button.clicked.connect(self.reuse_chorus);layout.addWidget(self.chorus_button)
    def refresh_chorus_tools(self):
        if hasattr(self,'chorus_button'):self.chorus_button.setEnabled(bool(self.project.lines) and not (self.api.busy or self.source_job or self.analysis_job or self.local_job or self.pending))
    def chorus_reference_valid(self,result):
        reference=result.get('reading_reuse',{});source=next((v for v in self.project.lines if v.id==reference.get('source_id')),None)
        return bool(source and reference_matches(reference,source,self.project.checks.get(source.id,{}).get('reading')))
    def reuse_chorus(self):
        if not self.flush_edits():return
        if self.api.busy or self.source_job or self.analysis_job or self.local_job or self.pending:self.message('先处理已有任务或建议，再复用副歌。');return
        dialog=ChorusDialog(self.project,self.current,self.playback,self);accepted=dialog.exec()==QDialog.DialogCode.Accepted
        if dialog.manual_uid:
            self.current=next((i for i,v in enumerate(self.project.lines) if v.id==dialog.manual_uid),self.current);self.set_stage(2);self.refresh(True);self.select_entire_line();return
        if not accepted:return
        source=next((v for v in self.project.lines if v.id==dialog.source.currentData()),None);ids=dialog.selected_ids()
        if source is None or not ids:return
        request={'action':'chorus_reuse','workflow_id':uuid.uuid4().hex,'source_line':source.to_dict(),
            'source_reading_confirmed':self.project.checks.get(source.id,{}).get('reading') is True,
            'lines':[v.to_dict() for v in self.project.lines if v.id in ids],
            'reading_confirmed_ids':[uid for uid in ids if self.project.checks.get(uid,{}).get('reading')],
            'neighbor_lines':[v.to_dict() for v in self.project.lines],'chorus_options':dialog.options(),
            'media':self.project.media,'vocal_track':copy.deepcopy(self.project.vocal_track),
            '_studio_context':{'project':self.project.uid,'media':file_stamp(self.project.media)}}
        self.start_chorus_request(request)
    def start_chorus_request(self,request):
        self.snapshots={v['id']:copy.deepcopy(v) for v in request['lines']}
        request={**request,'_studio_snapshots':copy.deepcopy(self.snapshots),'_studio_checks':copy.deepcopy(self.project.checks)}
        self.api.start(request);self.message('正在本机生成副歌复用候选，不使用 API 额度；结果先审核。')
    def resume_chorus_workflow(self,uid):
        if not self.flush_edits():return
        if self.api.busy or self.source_job or self.local_job or self.pending:self.message('先处理当前任务或建议，再继续复用。');return
        from studio_backend.chorus_workflow import load
        try:state=load(self.home,uid)
        except (OSError,ValueError,KeyError,TypeError):self.message('副歌检查点无法读取，原有结果保留，请检查任务记录。');return
        request=copy.deepcopy(state['request']);source=next((v for v in self.project.lines if v.id==request['source_line']['id']),None)
        context=request['_studio_context']
        if not source or not source.reviewed or not self.project.checks.get(source.id,{}).get('reading') or signature(source)!=state['source_signature']:
            self.message('来源句或确认状态已变化，旧候选保留；请重新选择复用。');return
        if context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media) or request['neighbor_lines']!=[v.to_dict() for v in self.project.lines]:
            self.message('工程、歌词或素材已变化，旧候选保留；请按当前内容重新选择复用，本机声音缓存仍可复用。');return
        now=sorted(v['id'] for v in request['lines'] if self.project.checks.get(v['id'],{}).get('reading'))
        if now!=request['reading_confirmed_ids']:self.message('目标句的读音确认状态已变化，旧候选保留；请重新选择复用范围。');return
        self.start_chorus_request({**request,'action':'chorus_reuse','workflow_id':uid,'resume':True})
