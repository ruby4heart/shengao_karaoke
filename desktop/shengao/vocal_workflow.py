"""Human vocal audition stays independent of the subtitle and delivery source."""
from pathlib import Path
from PySide6.QtGui import QAction,QActionGroup
from PySide6.QtWidgets import QToolButton,QMenu
from . import jobs,vocal_audio
from .project import file_stamp

class VocalWorkflow:
    def build_vocal_tools(self):
        self.audition_role='original';self.original_audio=None;self.source_job_kind='source';self._playing_vocal_hash=''
        self.vocal_tools=QToolButton();self.vocal_tools.setObjectName('vocalAudition');self.vocal_tools.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.vocal_tools.setAccessibleName('原声与人声辅助试听');self.vocal_tools.setToolTip('切换原声／人声，试听与频谱同步；不改变歌词、时间轴、转录上传源或成片音轨。首次使用在本机分离，无需密钥。')
        self.vocal_tools.clicked.connect(self.toggle_vocal_audition)
        self.playback.error.connect(self.vocal_play_error)
        menu=QMenu(self.vocal_tools);group=QActionGroup(menu);self.audition_actions={}
        for role,title in [('original','原声 · 当前视频源'),('vocals','人声辅助 · 试听与频谱')]:
            action=QAction(title,menu);action.setCheckable(True);group.addAction(action);menu.addAction(action);self.audition_actions[role]=action
            action.triggered.connect(lambda checked=False,r=role:self.select_vocal_audition(r))
        menu.addSeparator();self.generate_vocal_action=menu.addAction('为当前源生成人声辅助…');self.generate_vocal_action.triggered.connect(self.generate_vocals)
        self.vocal_tools.setMenu(menu);return self.vocal_tools

    def refresh_vocal_tools(self):
        if not hasattr(self,'vocal_tools'):return
        if self.audition_role=='vocals' and (not vocal_audio.bound(self.project.vocal_track,self.project.media) or self.project.vocal_track.get('sha256')!=self._playing_vocal_hash):
            if self.original_audio is not None:self.apply_audition('original',self.project.media,self.original_audio)
            else:self.audition_role='original'
        self.vocal_tools.setText('试听：人声' if self.audition_role=='vocals' else '试听：原声')
        self.vocal_tools.setEnabled(bool(self.project.media and self.original_audio is not None and not (self.source_job or self.analysis_job or self.local_job)))
        for role,action in self.audition_actions.items():action.setChecked(role==self.audition_role)
        ready=vocal_audio.bound(self.project.vocal_track,self.project.media)
        self.generate_vocal_action.setText('复用／重新检查本机人声缓存' if ready else '为当前源生成人声辅助…')
        self.audition_actions['vocals'].setText('人声辅助 · 试听与频谱' if ready else '人声辅助 · 先在本机生成')

    def toggle_vocal_audition(self):self.select_vocal_audition('original' if self.audition_role=='vocals' else 'vocals')

    def select_vocal_audition(self,role):
        if role not in {'original','vocals'}:return False
        if self.source_job or self.analysis_job or self.local_job:self.message('请等待或取消当前素材任务，再切换试听音轨。');return False
        if role==self.audition_role:return True
        if role=='vocals':return self.generate_vocals()
        if not self.original_audio:return False
        self.apply_audition('original',self.project.media,self.original_audio)
        self.message('试听和频谱已回到当前视频原声；成片音轨未改变。');return True

    def apply_audition(self,role,path,audio):
        # One media player contains both video and the chosen audio. Separate
        # asynchronous players cannot drift during slow playback or looping.
        left=self.timeline.left;position=self.playback.canvas.position
        self.playback.replace_audition_source(path);self.playback.canvas.audio_only=not self.project.has_video
        self.timeline.set_audio(audio);self.timeline.left=left;self.timeline.position=position;self.timeline.update_scroll();self.timeline.update()
        self.audition_role=role;self._playing_vocal_hash=self.project.vocal_track.get('sha256','') if role=='vocals' else '';self.refresh_vocal_tools();self.render_subtitles()

    def vocal_play_error(self,message):
        if self.audition_role=='vocals' and self.original_audio is not None:
            self.apply_audition('original',self.project.media,self.original_audio);self.message('人声预览播放失败，已恢复当前视频原声；人声缓存和字幕保留。'+message)

    def generate_vocals(self,after_ready=None):
        if not self.project.media or self.original_audio is None:self.message('请先添加素材，等波形就绪后再生成人声。');return False
        if self.source_job or self.analysis_job or self.local_job:self.message('请等待或取消当前素材任务。');return False
        if not self.flush_edits():return False
        source=self.project.media;stamp=file_stamp(source);uid=self.project.uid;self._source_serial+=1;serial=self._source_serial;old_track=self.project.vocal_track.copy();original_audio=self.original_audio
        self.source_job_kind='vocals'
        def valid():return not self.closing and serial==self._source_serial
        def work(cancel,report):
            track=old_track
            if not vocal_audio.bound(track,source):track=vocal_audio.generate(source,self.home,cancel,report)
            else:
                try:result=vocal_audio.prepare(track,source,self.home,cancel,report,original_audio);return {'track':track,**result}
                except ValueError:
                    vocal_audio.cancelled(cancel);track=vocal_audio.generate(source,self.home,cancel,report)
            return {'track':track,**vocal_audio.prepare(track,source,self.home,cancel,report,original_audio)}
        def failed(message):
            if not valid():return
            self.source_job=None;self.busy_changed();self.message('人声辅助未切换；当前试听、原素材和字幕保留。'+str(message))
        def done(result):
            if not valid():return
            was_cancelled=self.source_job is not None and self.source_job.cancel.is_set();self.source_job=None;self.busy_changed()
            if was_cancelled:self.message('已取消人声任务，原素材和字幕保留。');return
            if self.project.uid!=uid or self.project.media!=source or file_stamp(source)!=stamp or self.project.vocal_track!=old_track:self.message('当前工程或素材记录已变化，人声结果留在本机缓存，未切换。');return
            if not self.flush_edits():self.message('人声已生成，请先修正当前输入，再切换试听。');return
            if self.project.vocal_track!=result['track'] and not self.edit('添加人声辅助音轨',lambda p:setattr(p,'vocal_track',result['track'])):return
            self.apply_audition('vocals',result['path'],result['audio']);self.save_recovery()
            self.message('已切到人声辅助试听与频谱。分离可能残留伴奏或损伤弱音，请对照原声；转录与成片仍使用当前视频源。')
            if callable(after_ready):after_ready()
        def progress(value):
            if valid():self.message(str(value) if isinstance(value,str) else '正在准备人声频谱…')
        self.source_job=jobs.run(work,done,failed,progress);self.busy_changed();self.message('正在本机准备人声辅助；可以继续校对，取消后保留原素材。');return True
