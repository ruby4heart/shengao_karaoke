"""Atomic background source switching; candidate failures leave playback alone."""
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction,QActionGroup
from PySide6.QtWidgets import QToolButton,QMenu,QFileDialog,QMessageBox
from . import jobs,media
from .project import file_stamp
from .media_versions import ROLES,apply_media_version,switch_warnings

class SourceSwitch:
    def build_source_switch(self):
        self.source_job=None;self._source_serial=0
        self.source_switch=QToolButton();self.source_switch.setObjectName('sourceSwitch');self.source_switch.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.source_switch.setToolTip('首次选择原唱版／伴奏版文件，以后一键切换。歌词、注音、样式及时间轴共用；预览、频谱和导出跟随当前源。右侧箭头可更换文件。')
        self.source_switch.setAccessibleName('切换原唱与伴奏视频源');self.source_switch.clicked.connect(self.toggle_media_source)
        menu=QMenu(self.source_switch);self.source_role_actions={};group=QActionGroup(menu);group.setExclusive(True)
        for role,title in ROLES.items():
            action=QAction(title,menu);action.setCheckable(True);group.addAction(action);action.triggered.connect(lambda checked=False,r=role:self.select_media_source(r));menu.addAction(action);self.source_role_actions[role]=action
        menu.addSeparator()
        for role,title in ROLES.items():menu.addAction(f'更换{title}文件…').triggered.connect(lambda checked=False,r=role:self.choose_media_source(r))
        menu.addSeparator();menu.addAction('重新载入当前源（保留字幕）').triggered.connect(self.reload_media_source)
        self.source_switch.setMenu(menu);self.refresh_media_source();return self.source_switch

    def refresh_media_source(self):
        if not hasattr(self,'source_switch'):return
        p=self.project;other='instrumental' if p.media_role=='original' else 'original'
        self.source_switch.setText(('切到' if other in p.media_versions else '添加')+ROLES[other]+('' if other in p.media_versions else '…') if p.media else '添加视频源…')
        self.source_switch.setEnabled(not (self.source_job or self.api.busy or self.local_job or self.analysis_job))
        for role,action in self.source_role_actions.items():
            action.setChecked(bool(p.media and role==p.media_role));entry=p.media_versions.get(role)
            action.setToolTip(entry.path if entry else '尚未选择文件')

    def toggle_media_source(self):
        self.select_media_source('instrumental' if self.project.media and self.project.media_role=='original' else 'original')

    def reload_media_source(self):
        if self.source_job or self.api.busy or self.local_job or self.analysis_job:self.message('请先完成或取消当前素材任务。');return False
        if not self.flush_edits():return False
        if not file_stamp(self.project.media):self.message('当前素材不存在，请重新定位文件。');return False
        self.load_media(self.project.media,edit=False,position=self.playback.canvas.position,zoom=self.playback.zoom,preview=True)
        self.message('正在重新载入当前源并核对内容；原文、注音和时间轴保持，试听回到原声。');return True

    def select_media_source(self,role):
        if role==self.project.media_role and self.project.media and file_stamp(self.project.media)==self.project.media_stamp:return
        entry=self.project.media_versions.get(role)
        if not entry or not Path(entry.path).is_file():self.choose_media_source(role)
        else:self.switch_media_source(role,entry.path)

    def choose_media_source(self,role):
        initial=self.project.media_versions.get(role)
        path,_=QFileDialog.getOpenFileName(self,'选择'+ROLES[role]+'素材',initial.path if initial else self.project.media,'音视频 (*.mp4 *.mkv *.mov *.webm *.avi *.wav *.mp3 *.flac *.m4a *.ogg);;所有文件 (*)')
        if path:self.switch_media_source(role,path)

    def confirm_media_source(self,warnings):
        return QMessageBox.question(self,'检查新视频源的同步','\n'.join(warnings)+'\n\n已有歌词和时间轴保持原值，不会自动拉伸。仍要使用新源吗？',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

    def switch_media_source(self,role,path):
        if role not in ROLES:self.message('视频版本类型无效');return False
        if not self.flush_edits():return False
        if self.source_job or self.api.busy or self.local_job or self.analysis_job:self.message('请先完成或取消当前任务，再更换视频源');return False
        path=str(Path(path).resolve());stamp=file_stamp(path)
        if not stamp:self.message('新源不存在；当前视频与字幕保留。请重新选择文件。');return False
        self._source_serial+=1;serial=self._source_serial;uid=self.project.uid;old_stamp=file_stamp(self.project.media);old_role=self.project.media_role
        def valid():return not self.closing and serial==self._source_serial
        def failed(message):
            if not valid():return
            self.source_job=None;self.busy_changed();self.message('未更换视频源，当前视频与字幕保留。'+str(message))
        def done(result):
            if not valid():return
            cancelled=self.source_job is not None and self.source_job.cancel.is_set();self.source_job=None;self.busy_changed()
            if cancelled:self.message('已取消换源，当前视频与字幕保留。');return
            if self.project.uid!=uid or self.project.media_role!=old_role or file_stamp(self.project.media)!=old_stamp:self.message('当前工程或源文件已变化，本次未切换。');return
            if file_stamp(path)!=stamp:self.message('读取期间新源发生变化，本次未切换，请重新选择。');return
            if not self.flush_edits():self.message('新源已读取，但当前输入无效，尚未换源；请先修正输入。');return
            warnings=switch_warnings(self.project,result);known=self.project.media_versions.get(role)
            if warnings and (not known or known.path!=path or known.stamp!=stamp or known.duration!=int(result['duration'])):
                if not self.confirm_media_source(warnings):self.message('已保留当前源，字幕时间未改动。');return
            # A modal confirmation can process events; recheck before commit.
            if not valid() or self.project.uid!=uid or self.project.media_role!=old_role or file_stamp(self.project.media)!=old_stamp or file_stamp(path)!=stamp:self.message('素材版本已变化，本次未切换。');return
            position=self.playback.canvas.position;zoom=self.playback.zoom
            if not self.edit('切换到'+ROLES[role],lambda p:apply_media_version(p,role,path,result,stamp)):return
            self.clear_media();self.playback.open(path,position,preview=True);self.timeline.set_audio(result);self.original_audio=result;self.playback.canvas.audio_only=not self.project.has_video;self.playback.set_reference_size(self.project.width,self.project.height);self.playback.set_zoom(zoom)
            target=min(position,max(0,self.project.duration-1));self.playback.seek(target)
            self.seek_slider.setMaximum(self.project.duration);self.refresh();self.save_recovery()
            self.message('已切到'+ROLES[role]+'：歌词、注音和时间轴保持；预览、频谱与导出使用此源。'+(' 请检查两版同步及片尾。' if warnings else ''))
        def progress(value):
            if valid():self.message('正在读取'+ROLES[role]+'；当前视频与字幕保留。'+(value if isinstance(value,str) else ''))
        self.source_job_kind='source';self.source_job=jobs.run(lambda cancel,report:media.analyze(path,self.home/'wave-cache',cancel,report),done,failed,progress)
        self.busy_changed();self.message('正在后台检查'+ROLES[role]+'，成功后再切换。');return True
