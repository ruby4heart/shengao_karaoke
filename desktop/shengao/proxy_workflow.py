"""Local preview choice stays independent of source, lyrics and audition role."""
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction,QActionGroup
from PySide6.QtWidgets import QToolButton,QMenu,QLabel
from . import jobs,proxy_video
from .project import file_stamp


class ProxyWorkflow:
    def init_proxy_workflow(self):
        self.proxy_job=None;self._proxy_serial=0;self.proxy_active=False;self.proxy_base=None;self._proxy_base_stamp={}
        self.proxy_display_path='';self._proxy_display_stamp={};self._proxy_vocal_path='';self._proxy_vocal_stamp={}
        self.proxy_pending=None;self.proxy_buttons=[];self.proxy_notices=[];self.proxy_action_sets=[];self.proxy_message=''
        self.proxy_apply_timer=QTimer(self);self.proxy_apply_timer.setSingleShot(True);self.proxy_apply_timer.timeout.connect(self.apply_pending_proxy)

    def build_proxy_controls(self,layout):
        button=QToolButton();button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup);button.setToolTip('本机轻量视频预览：检查时间与音频后采用；输出、转录和工程仍使用原片。原唱／伴奏与原声／人声独立。');button.clicked.connect(self.toggle_proxy)
        menu=QMenu(button);group=QActionGroup(menu);actions={}
        for key,title,callback in [('original','预览原片',self.use_original_preview),('proxy','准备／复用轻量预览（最大720p）',self.prepare_proxy)]:
            action=QAction(title,menu);action.setCheckable(True);group.addAction(action);menu.addAction(action);action.triggered.connect(lambda checked=False,fn=callback:fn());actions[key]=action
        menu.addSeparator();actions['cancel']=menu.addAction('取消轻量预览任务');actions['cancel'].triggered.connect(lambda checked=False:self.cancel_proxy_request());button.setMenu(menu)
        notice=QLabel();notice.setWordWrap(True);layout.addWidget(button);layout.addWidget(notice)
        self.proxy_buttons.append(button);self.proxy_notices.append(notice);self.proxy_action_sets.append(actions);self.refresh_proxy_tools()

    def build_proxy_preview_note(self,layout):
        self.proxy_preview_note=QLabel();self.proxy_preview_note.setWordWrap(True);self.proxy_preview_note.hide();layout.addWidget(self.proxy_preview_note)
        self.playback.temporaryChanged.connect(self.proxy_temporary_changed)

    def open_proxy_settings(self):
        self.set_stage(0)
        if self.proxy_buttons:self.pages.widget(0).ensureWidgetVisible(self.proxy_buttons[0])

    def proxy_context(self):
        return {'uid':self.project.uid,'source':self.project.media,'stamp':file_stamp(self.project.media),'role':self.project.media_role,
                'audition':self.audition_role,'vocal_hash':self.project.vocal_track.get('sha256','') if self.audition_role=='vocals' else '',
                'audition_path':self._proxy_vocal_path if self.audition_role=='vocals' else '',
                'audition_stamp':file_stamp(self._proxy_vocal_path) if self.audition_role=='vocals' else {}}

    def proxy_base_bound(self):
        return bool(self.proxy_base and self.proxy_base['source_path']==self.project.media and self.proxy_base['source_stamp']==file_stamp(self.project.media) and self._proxy_base_stamp==file_stamp(self.proxy_base['path']))

    def cancel_proxy_request(self,notify=True):
        self._proxy_serial+=1
        if self.proxy_job:self.proxy_job.cancel.set()
        self.proxy_job=None;self.proxy_pending=None;self.proxy_apply_timer.stop();self.proxy_message='已取消轻量预览任务，当前试听和字幕保持。';self.refresh_proxy_tools()
        if notify and not self.closing and hasattr(self,'progress'):self.busy_changed()

    def clear_proxy(self):
        self.cancel_proxy_request(False);self.proxy_active=False;self.proxy_base=None;self._proxy_base_stamp={};self.proxy_display_path='';self._proxy_display_stamp={};self._proxy_vocal_path='';self._proxy_vocal_stamp={};self.proxy_message='';self.refresh_proxy_tools()
        if not self.closing and hasattr(self,'progress'):self.busy_changed()

    def refresh_proxy_tools(self):
        if not self.proxy_buttons:return
        ready=bool(self.project.media and self.project.has_video and self.original_audio is not None and not self.analysis_job)
        status=self.proxy_message
        if not status:status='4K 视频卡顿时可在本机生成轻量预览；最终输出仍使用原片。' if ready else '添加含声音的视频并等待波形就绪后，可以准备轻量预览。'
        for button,notice,actions in zip(self.proxy_buttons,self.proxy_notices,self.proxy_action_sets):
            button.setText('轻量预览处理中…' if self.proxy_job else '预览：轻量视频' if self.proxy_active else '预览：原片（可切轻量）')
            button.setEnabled(ready or self.proxy_active);notice.setText(status);actions['original'].setChecked(not self.proxy_active);actions['proxy'].setChecked(self.proxy_active)
            actions['proxy'].setEnabled(ready and not self.proxy_job);actions['cancel'].setEnabled(bool(self.proxy_job or self.proxy_pending))
        if hasattr(self,'proxy_preview_note'):
            self.proxy_preview_note.setVisible(bool(self.proxy_active or self.proxy_pending))
            self.proxy_preview_note.setText(('轻量视频预览 · 最终输出用原片 · '+('人声试听' if self.audition_role=='vocals' else '原声试听')) if self.proxy_display_path else status)

    def toggle_proxy(self):
        if self.proxy_job:self.message('轻量预览正在准备；右侧菜单可取消，普通编辑可以继续。');return False
        return self.use_original_preview() if self.proxy_active else self.prepare_proxy()

    def prepare_proxy(self):
        if not self.flush_edits():return False
        if self.proxy_job:self.message('轻量预览任务已经在运行。');return False
        if not self.project.media or not self.project.has_video or self.original_audio is None or self.analysis_job:self.message('请添加视频并等待波形就绪后准备轻量预览。');return False
        context=self.proxy_context()
        if context['audition']=='vocals' and not context['audition_stamp']:self.message('当前人声试听文件不可用，请先恢复或重新准备人声。');return False
        self._proxy_serial+=1;serial=self._proxy_serial;self.proxy_pending=None
        def valid():return not self.closing and serial==self._proxy_serial
        def work(cancel,report):
            base=proxy_video.prepare(context['source'],self.home/'preview-cache',cancel,report)
            display=proxy_video.prepare_mix(base,context['audition_path'],self.home/'preview-cache',cancel,report) if context['audition']=='vocals' else base
            return {'base':base,'display':display,'base_stamp':file_stamp(base['path']),'display_stamp':file_stamp(display['path'])}
        def failed(message):
            if not valid():return
            self.proxy_job=None;self.proxy_message='轻量预览未切换；'+str(message);self.busy_changed();self.refresh_proxy_tools();self.message(self.proxy_message)
        def done(result):
            if not valid():return
            cancelled=bool(self.proxy_job and self.proxy_job.cancel.is_set());self.proxy_job=None;self.busy_changed()
            if cancelled:self.proxy_message='已取消轻量预览；当前试听、原片和字幕保持。';self.refresh_proxy_tools();return
            if context!=self.proxy_context():self.proxy_message='工程或试听源已变化，旧代理未切换；结果保留在本机缓存。';self.refresh_proxy_tools();self.message(self.proxy_message);return
            self.proxy_pending=(context,result);self.apply_pending_proxy()
        def progress(value):
            if not valid():return
            if isinstance(value,str):self.proxy_message=value;self.refresh_proxy_tools()
            elif value.get('phase')=='encode':
                self.progress.setRange(0,100);self.progress.setValue(min(99,round(value['time_ms']*100/max(1,self.project.duration))))
            else:self.progress.setRange(0,0)
        self.proxy_message='正在本机准备轻量视频，原片与当前编辑保持…';self.proxy_job=jobs.run(work,done,failed,progress);self.busy_changed();self.refresh_proxy_tools();self.message(self.proxy_message);return True

    def proxy_temporary_changed(self,active):
        if not active and self.proxy_pending:self.proxy_apply_timer.start(0)

    def apply_pending_proxy(self):
        if not self.proxy_pending or self.closing:return
        context,result=self.proxy_pending
        if context!=self.proxy_context():self.proxy_pending=None;self.proxy_message='工程或试听源已变化，旧代理未采用。';self.refresh_proxy_tools();return
        if self.playback.temporary_owner is not None:
            self.proxy_message='轻量预览已就绪，当前细听保持；细听结束后自动采用。';self.refresh_proxy_tools();return
        display=result['display'];base=result['base']
        if file_stamp(base['source_path'])!=base['source_stamp'] or file_stamp(base['path'])!=result['base_stamp'] or file_stamp(display['path'])!=result['display_stamp']:self.proxy_pending=None;self.proxy_message='代理或原片已变化，请重新准备；当前试听保持。';self.refresh_proxy_tools();return
        self.proxy_pending=None;self.proxy_base=base;self._proxy_base_stamp=file_stamp(base['path']);self.proxy_active=True
        self.proxy_display_path=display['path'];self._proxy_display_stamp=file_stamp(display['path'])
        self.playback.replace_audition_source(display['path'],reference_size=(self.project.width,self.project.height))
        self.proxy_message='已启用轻量预览；播放位置与缩放保持，歌词、音轨选择和输出原片保持。';self.refresh_proxy_tools();self.message(self.proxy_message)

    def use_original_preview(self):
        if not self.flush_edits():return False
        displayed=bool(self.proxy_display_path)
        path=self._proxy_vocal_path if self.audition_role=='vocals' else self.project.media
        if displayed and not file_stamp(path):
            self.cancel_proxy_request(False);self.proxy_message='原片或当前人声文件不存在，未切换；当前轻量预览保留，请重新定位素材。';self.busy_changed();self.refresh_proxy_tools();self.message(self.proxy_message);return False
        self.cancel_proxy_request(False);self.proxy_active=False;self.proxy_display_path='';self._proxy_display_stamp={}
        if displayed and file_stamp(path):self.playback.replace_audition_source(path,reference_size=(self.project.width,self.project.height))
        self.proxy_message='预览已回到原片；当前原声／人声选择、时间轴和字幕保持。';self.busy_changed();self.refresh_proxy_tools();self.message(self.proxy_message);return True

    def proxy_audition_path(self,role,path):
        self.cancel_proxy_request(False);self.proxy_message='';self.proxy_display_path='';self._proxy_display_stamp={}
        if role=='vocals':self._proxy_vocal_path=str(path);self._proxy_vocal_stamp=file_stamp(path)
        if self.proxy_active and not self.proxy_base_bound():self.proxy_active=False;self.proxy_message='原片或代理缓存已变化，当前试听使用原片；可重新准备轻量预览。'
        if self.proxy_active and role=='original':
            self.proxy_display_path=self.proxy_base['path'];self._proxy_display_stamp=file_stamp(self.proxy_display_path);return self.proxy_display_path
        return path

    def proxy_after_audition(self):
        if self.proxy_active and self.audition_role=='vocals' and not self.prepare_proxy():self.proxy_active=False;self.proxy_message='当前人声使用原片预览，可在输入完成后重新准备轻量预览。'
        self.busy_changed();self.refresh_proxy_tools()

    def proxy_play_error(self,message):
        if not self.proxy_display_path or str(Path(self.playback.player.source().toLocalFile()))!=str(Path(self.proxy_display_path)):return False
        restored=self.use_original_preview();self.proxy_message=('轻量预览播放失败，已恢复当前原片试听；字幕与缓存保持。' if restored else '轻量预览播放失败且原试听文件不可用，请重新定位素材；字幕与工程保持。')+str(message);self.refresh_proxy_tools();self.message(self.proxy_message);return True
