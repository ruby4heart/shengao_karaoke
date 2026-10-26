"""Short, contextual audition in the main editor; enhancements never enter exports."""
import copy
from PySide6.QtCore import Qt,Slot,QTimer,QElapsedTimer,QBuffer,QByteArray,QIODevice,QUrl
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QCheckBox,QPushButton,QLabel
from .widgets import Collapsible,time_text
from .native_slots import invoke_native_slot
from .tail_model import consonant_clip


def selected_range(line,word,part,context=True):
    if line is None:raise ValueError('先选择一句歌词或演唱音节。')
    parts=[(i,j,h) for i,u in enumerate(line.units) for j,h in enumerate(u.highlights)]
    target=next((n for n,(i,j,h) in enumerate(parts) if (i,j)==(word,part)),None)
    if target is not None:
        h=parts[target][2];previous=parts[max(0,target-1)][2]
        return (max(0,min(previous.start,h.start)-100) if context else h.start,h.end+(100 if context else 0),h.start)
    if 0<=word<len(line.units):
        unit=line.units[word];previous=line.units[max(0,word-1)]
        return (max(0,min(previous.start,unit.start)-100) if context else unit.start,unit.end+(100 if context else 0),unit.start)
    return max(0,line.start-(150 if context else 0)),line.end+(150 if context else 0),line.start


class FineListeningController(QWidget):
    def __init__(self,window):
        super().__init__();self.studio=window;self.playback=window.playback;self.mode=None;self.saved=None;self.closed=False;self.stopping=False;self.identity=None;self.buffers=[];self.current_buffer=None
        self.filtered_player=QMediaPlayer(self);self.filtered_audio=QAudioOutput(self);self.filtered_player.setAudioOutput(self.filtered_audio)
        self.playback.audio.volumeChanged.connect(self.filtered_audio.setVolume);self.playback.audio.mutedChanged.connect(self.filtered_audio.setMuted)
        if hasattr(self.filtered_player,'setPitchCompensation'):self.filtered_player.setPitchCompensation(True)
        self.anchor=0;self.clock=QElapsedTimer();self.clock.start();self.filtered_start=self.filtered_end=0
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.selection=QLabel();self.selection.setWordWrap(True);self.selection.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.selection)
        row=QHBoxLayout();self.context_button=QPushButton('带前音试听');self.only_button=QPushButton('只听所选');self.stop_button=QPushButton('停止细听')
        for control in (self.context_button,self.only_button,self.stop_button):row.addWidget(control)
        layout.addLayout(row);row=QHBoxLayout();self.speed=QComboBox()
        for value in (.5,.75,1.):self.speed.addItem(f'{value:g}× 细听',value)
        self.speed.setCurrentIndex(1);self.loop=QCheckBox('细听循环');self.loop.setChecked(True);row.addWidget(self.speed);row.addWidget(self.loop);layout.addLayout(row)
        self.enhance=QCheckBox('突出辅音（仅试听，须对照原声）');layout.addWidget(self.enhance)
        self.compare=QPushButton('关闭增强并听原声对照');layout.addWidget(self.compare)
        self.large=QPushButton('独立放大与微调窗口…');layout.addWidget(self.large)
        self.status=QLabel('停止或普通播放／定位／换源后恢复常规速度与循环。增强时视频保持定位静帧，播放点和字幕跟随试听声音。');self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.status)
        for control,tip in [(self.context_button,'按所选音节带上前音慢放；音节、词组或整句均可试听，不修改工程。'),
                            (self.only_button,'仅播放当前选择的演唱范围，使用细听速度与细听循环。'),
                            (self.stop_button,'停止临时细听并恢复常规播放速度与循环；当前位置保持。'),
                            (self.compare,'回到当前视频源的原声音轨，关闭辅音增强并按同一选择带前音试听；不改成片音轨。'),
                            (self.large,'打开原有独立尾音窗口，放大频谱／波形和按 10 毫秒微调；保存可撤销。')]:control.setToolTip(tip)
        self.speed.setToolTip('只用于这次细听；常规播放速度在停止、定位或换源后恢复。');self.loop.setToolTip('只用于当前细听范围；停止后恢复常规循环设置。');self.enhance.setToolTip('对当前试听音轨做有界高／低通增强，不判断发音，不修改源文件、转录或导出。')
        self.context_button.clicked.connect(lambda:self.listen(True));self.only_button.clicked.connect(lambda:self.listen(False));self.stop_button.clicked.connect(lambda:self.stop())
        self.compare.clicked.connect(self.original_compare);self.large.clicked.connect(window.inspect_tail);self.enhance.toggled.connect(lambda _:self.stop())
        self.speed.currentIndexChanged.connect(self.change_speed);self.loop.toggled.connect(self.change_loop)
        queued=Qt.ConnectionType.QueuedConnection
        self.filtered_player.positionChanged.connect(self.filtered_position,queued);self.filtered_player.mediaStatusChanged.connect(self.filtered_status,queued);self.filtered_player.errorOccurred.connect(self.filtered_error,queued)
        self.playback.player.playbackStateChanged.connect(self.normal_state,queued)
        self.timer=QTimer(self);self.timer.setInterval(25);self.timer.timeout.connect(self.tick);self.timer.start()
        self.prune_timer=QTimer(self);self.prune_timer.setSingleShot(True);self.prune_timer.timeout.connect(self.prune_buffers)

    def refresh(self):
        w=self.studio
        identity=(w.project.uid,w.project.media,w.line.to_dict() if w.line else None,w.timeline.word,w.timeline.part,id(w.timeline.audio))
        if identity!=self.identity:
            if self.mode:self.stop()
            self.identity=copy.deepcopy(identity)
        ready=bool(w.line and w.project.media and not self.playback.player.source().isEmpty() and not (w.source_job or w.analysis_job))
        for control in (self.context_button,self.only_button,self.compare):control.setEnabled(ready)
        self.large.setEnabled(bool(w.line and any(u.highlights for u in w.line.units)))
        try:
            a,b,_=selected_range(w.line,w.timeline.word,w.timeline.part,True)
            self.selection.setText(f'带前音范围：{time_text(a)} — {time_text(min(b,w.project.duration) if w.project.duration else b)} · '+('人声辅助' if w.audition_role=='vocals' else '原声'))
        except ValueError:self.selection.setText('先选歌词、词组或音节；没有匹配也可听整句。')

    def listen(self,context=True):
        w=self.studio
        if self.closed or not w.flush_edits():return False
        self.stop(quiet=True)
        try:
            start,end,target=selected_range(w.line,w.timeline.word,w.timeline.part,context)
            if w.project.duration:end=min(end,w.project.duration)
            if end<=start:raise ValueError('所选范围超出媒体，请先修正范围。')
            if self.enhance.isChecked():
                audio=w.timeline.audio
                if audio is None:raise ValueError('波形尚未就绪，请等待分析完成后再用增强；可先按原声试听。')
                maximum=262144*1000/audio.rate
                if end-target<=maximum:start=max(start,round(end-maximum))
                data,info=consonant_clip(audio.samples,audio.rate,start,end)
                self.playback.stop();self.saved=(self.playback.player.playbackRate(),self.playback.loop)
                self.mode='enhanced';self.last_clip=info;self.filtered_start=info['start'];self.filtered_end=info['end'];self.anchor=0;self.clock.restart()
                buffer=QBuffer(self);buffer.setData(QByteArray(data));buffer.open(QIODevice.OpenModeFlag.ReadOnly);self.buffers.append(buffer);self.current_buffer=buffer
                self.filtered_audio.setMuted(self.playback.audio.isMuted());self.filtered_audio.setVolume(self.playback.audio.volume())
                self.filtered_player.setSourceDevice(buffer,QUrl('fine-listening.wav'));self.filtered_player.setPlaybackRate(self.speed.currentData())
                self.playback.seek(self.filtered_start);self.playback.begin_temporary(self,self.stop,self.filtered_start);invoke_native_slot(self.filtered_player,'play')
                self.status.setText(f'辅音增强细听 · {self.speed.currentData():g}× · 实际范围 {time_text(info["start"])}–{time_text(info["end"])} · 增益 {info["gain"]:.1f}×；视频是定位静帧，播放点／字幕随声音。增强不证明实际发音，请对照原声。')
            else:
                if self.playback.player.source().isEmpty():raise ValueError('媒体尚未载入播放器；请重新载入素材或等待载入完成，再按原声试听。')
                self.saved=(self.playback.player.playbackRate(),self.playback.loop);self.playback.player.setPlaybackRate(self.speed.currentData())
                if not self.playback.audition(start,end,self.loop.isChecked()):
                    self.restore();return False
                self.mode='normal';self.playback.begin_temporary(self,self.stop)
                self.status.setText(f'按{("人声辅助" if w.audition_role=="vocals" else "原声")}细听 · {self.speed.currentData():g}×；停止后恢复常规速度与循环。')
            return True
        except (ValueError,OSError) as error:
            self.stop(quiet=True);self.status.setText(str(error));return False

    def restore(self):
        if self.saved is not None:
            rate,loop=self.saved;self.saved=None;self.playback.player.setPlaybackRate(rate);self.playback.loop=loop

    def stop(self,quiet=False):
        if self.stopping:return
        self.stopping=True
        try:
            mode=self.mode;self.mode=None;position=self.playback.canvas.position
            self.playback.end_temporary(self)
            if mode=='enhanced':
                invoke_native_slot(self.filtered_player,'stop');self.filtered_player.setSource(QUrl());self.current_buffer=None;self.playback.seek(position)
                self.prune_timer.start(0)
            elif mode=='normal':self.playback.stop()
            self.restore()
            if mode and not quiet:self.status.setText('细听已停止，常规速度与循环已恢复；工程和源音轨保持。')
        finally:self.stopping=False

    def prune_buffers(self):
        # A stopped source has released its QIODevice. Keep the current one
        # alive through every native callback; dispose retired buffers later.
        current=self.filtered_player.sourceDevice()
        for buffer in self.buffers[:]:
            if buffer is not current and buffer is not self.current_buffer:buffer.close();buffer.deleteLater();self.buffers.remove(buffer)

    def change_speed(self,*_):
        if self.mode=='normal':self.playback.player.setPlaybackRate(self.speed.currentData())
        elif self.mode=='enhanced':self.filtered_player.setPlaybackRate(self.speed.currentData());self.anchor=self.filtered_player.position();self.clock.restart()

    def change_loop(self,value):
        if self.mode=='normal':self.playback.loop=value

    def original_compare(self):
        self.stop(quiet=True)
        if self.studio.audition_role!='original' and not self.studio.select_vocal_audition('original'):return False
        self.enhance.setChecked(False);return self.listen(True)

    @Slot('qint64')
    def filtered_position(self,value):
        if self.mode=='enhanced':self.anchor=self.filtered_player.position();self.clock.restart();self.tick()

    def tick(self):
        if self.closed or self.mode!='enhanced':return
        playing=self.filtered_player.playbackState()==QMediaPlayer.PlaybackState.PlayingState
        relative=self.anchor+(round(self.clock.elapsed()*self.filtered_player.playbackRate()) if playing else 0)
        self.playback.update_temporary_position(self,min(self.filtered_end,self.filtered_start+max(0,relative)))

    @Slot(QMediaPlayer.MediaStatus)
    def filtered_status(self,status):
        if self.closed or status!=self.filtered_player.mediaStatus():return
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,QMediaPlayer.MediaStatus.BufferedMedia):self.prune_buffers()
        if self.mode=='enhanced' and status==QMediaPlayer.MediaStatus.EndOfMedia:
            if self.loop.isChecked():self.filtered_player.setPosition(0);self.anchor=0;self.clock.restart();invoke_native_slot(self.filtered_player,'play')
            else:self.stop()

    @Slot(QMediaPlayer.Error,str)
    def filtered_error(self,code,message):
        if self.mode=='enhanced':self.stop(quiet=True);self.status.setText('增强试听失败，原声与工程保持：'+message)

    @Slot(QMediaPlayer.PlaybackState)
    def normal_state(self,state):
        if not self.closed and self.mode=='normal' and self.playback.player.playbackState()==state and state!=QMediaPlayer.PlaybackState.PlayingState:
            if self.loop.isChecked() and self.playback.range and self.playback.player.mediaStatus()==QMediaPlayer.MediaStatus.EndOfMedia:
                self.playback.seek(self.playback.range[0],internal=True);invoke_native_slot(self.playback.player,'play')
            else:self.stop()

    def dispose(self):
        if self.closed:return
        self.stop(quiet=True);self.closed=True;self.timer.stop();self.prune_timer.stop();invoke_native_slot(self.filtered_player,'stop');self.filtered_player.setSource(QUrl());self.current_buffer=None;self.prune_buffers()


class FineListeningWorkflow:
    def build_fine_listening(self,layout):
        self.fine_listening=Collapsible('主界面细听：慢放、循环与辅音增强');self.fine_listener=FineListeningController(self);self.fine_listening.body.addWidget(self.fine_listener);layout.addWidget(self.fine_listening)

    def refresh_fine_listening(self):
        if hasattr(self,'fine_listener'):self.fine_listener.refresh()

    def open_inline_listening(self):
        if not self.flush_edits() or not self.line:return False
        self.set_stage(2)
        if self.timeline.part<0:
            target=next(((i,j) for i,u in reversed(list(enumerate(self.line.units))) for j,h in reversed(list(enumerate(u.highlights)))),None)
            if target:self.granularity.setCurrentIndex(self.granularity.findData('mora'));self.select_target(*target)
        self.fine_listening.toggle.setChecked(True);self.refresh_fine_listening();self.show_editor_widget(self.fine_listener.context_button);self.show_audio_axis();return True
