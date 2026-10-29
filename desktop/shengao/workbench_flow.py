"""Present the shared workflow decision without modifying the project."""
from pathlib import Path
from .project import file_stamp
from .workflow_state import Facts,decide,primary_for_stage


class WorkbenchFlow:
    def reset_output_context(self):
        self.last_output='';self._last_output_snapshot=None;self._last_output_stamp={};self._last_output_full=False

    def workbench_facts(self,summary,media_ready,*,snapshot=None):
        p=self.project;current_output=False
        if self.last_output and Path(self.last_output).is_file() and self._last_output_snapshot is not None:
            current_output=(self._last_output_snapshot==(p.to_dict() if snapshot is None else snapshot)
                            and self._last_output_stamp==file_stamp(p.media))
        return Facts(media_selected=bool(p.media),media_ready=media_ready,
            media_loading=bool(self.analysis_job or self.source_job),line_count=summary['lines'],
            unsegmented_count=sum(not line.units for line in p.lines),timing_confirmed=summary['timing'],
            reading_confirmed=summary['readings'],recognition_pending=bool(p.recognition_draft),
            suggestion_count=len(self.pending.get('result',{}).get('suggestions',[])) if self.pending else 0,
            task_running=bool(self.api.busy),resumable_draft=bool(self._draft_summary),
            current_output=current_output,full_output=bool(current_output and self._last_output_full),
            source_ass_active=p.source_ass_active,inline_pending=bool(self.inline_segment.pending))

    def execute_workbench_action(self,command):
        routes={'add_media':self.add_media,'original_lyrics':self.paste_lyrics,
            'recognize':self.begin_recognition,'review_recognition':self.review_recognition,
            'review_suggestions':self.review_pending,'missing_segmentation':self.go_missing_segmentation,
            'draft_options':lambda:self.set_stage(1),'resume_draft':self.draft_resume_button.click,
            'pending_timing':self.go_timing,'pending_reading':self.show_pending_readings,
            'style':lambda:self.set_stage(3),'export':lambda:self.set_stage(4),
            'play_output':lambda:self.open_last_output(False),'tasks':self.task_history,
            'pending_edit':lambda:self.show_editor_widget(self.inline_segment)}
        if command not in routes:raise ValueError('未知的工作台操作')
        routes[command]()

    @staticmethod
    def _primary_style(widget,primary):
        name='primary' if primary else 'secondary'
        if widget.objectName()!=name:
            widget.setObjectName(name);widget.style().unpolish(widget);widget.style().polish(widget);widget.update()

    def refresh_workbench_flow(self,summary,media_ready,*,snapshot=None):
        facts=self.workbench_facts(summary,media_ready,snapshot=snapshot)
        decision=decide(facts);self.workbench_decision=decision
        primary=primary_for_stage(decision,self.stage,current_output=facts.current_output)
        self.next_hint.setText(decision.detail)
        self.next_button.setText(primary.text+' →')
        self.next_callback=lambda:self.execute_workbench_action(primary.command)
        # The current calibration page already has its explicit confirmation
        # footer. Do not add a second button that only reopens the same task.
        current_task=(self.stage==2 and (
            decision.key=='pending_edit' or
            decision.key=='timing' and self.calibration_tabs.currentIndex()==0 or
            decision.key=='reading' and self.calibration_tabs.currentIndex()==1))
        self.next_button.setVisible(not current_task)
        for button,state,caption in zip(self.steps,decision.stages,decision.captions):button.set_status(state,caption)
        self.prepare_heading.setText(decision.heading);self.prepare_detail.setText(decision.detail)
        self.prepare_media_button.setText('更换视频／音频…' if facts.media_selected else '① 添加视频／音频')
        self.prepare_lyrics_button.setText('编辑原歌词…' if facts.line_count else '② 粘贴原歌词')
        self._primary_style(self.prepare_media_button,primary.command=='add_media')
        self._primary_style(self.prepare_lyrics_button,primary.command=='original_lyrics')
        self.prepare_next.setVisible(primary.command not in ('add_media','original_lyrics'))
        self.prepare_next.setText(primary.text+' →')
        # The prepare page uses the same recommendation even when the compact
        # navigation banner is folded. Existing common buttons avoid duplication.
        self.prepare_next_command=primary.command
        choices=tuple((a.command,a.text) for a in decision.secondary if a.command not in ('add_media','original_lyrics','recognize'))
        if getattr(self,'_prepare_menu_signature',None)!=choices:
            self._prepare_menu_signature=choices;self.prepare_other_menu.clear()
            for command,text in choices:self.prepare_other_menu.addAction(text,lambda checked=False,value=command:self.execute_workbench_action(value))
        self.prepare_other.setVisible(bool(choices))
        self.generation_context.setText(decision.heading+'。'+decision.detail)
