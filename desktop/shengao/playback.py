from PySide6.QtCore import Qt,Signal,Slot,QTimer,QElapsedTimer,QUrl,QEvent,QSize,QRectF
from PySide6.QtGui import QPainter,QColor,QImage,QLinearGradient
from PySide6.QtWidgets import QWidget,QScrollArea,QFrame
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput,QVideoSink,QVideoFrame
from .render import AssRenderer
from .native_slots import invoke_native_slot

class VideoCanvas(QWidget):
    zoomRequested=Signal(int)
    frameSizeChanged=Signal(int,int)
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumSize(1,1)
        self.frame=QImage();self.renderer=AssRenderer();self.position=0;self.aspect=16/9;self.show_subtitles=True;self.audio_only=False
        self.setObjectName('videoPreview');self._wheel=0
        self.setToolTip('滚轮按 12.5% 缩放视频；放大后可用滚动条移动画面。双击恢复适合窗口。')

    def video_frame(self,frame):
        image=frame.toImage()
        if not image.isNull():
            changed=self.frame.size()!=image.size();self.frame=image;self.aspect=image.width()/image.height()
            if changed:self.frameSizeChanged.emit(image.width(),image.height())
            self.update()

    def wheelEvent(self,event):
        self._wheel+=event.angleDelta().y();steps=int(self._wheel/120);self._wheel-=steps*120
        if steps:self.zoomRequested.emit(steps)
        event.accept()

    def mouseDoubleClickEvent(self,event):self.zoomRequested.emit(0);event.accept()

    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#0c1423'))
        w=self.width();h=round(w/self.aspect)
        if h>self.height():h=self.height();w=round(h*self.aspect)
        x=(self.width()-w)//2;y=(self.height()-h)//2
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.frame.isNull():p.drawImage(QRectF(x,y,w,h),self.frame)
        elif not self.audio_only:
            p.setPen(QColor('#93a4ba'));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'视频与字幕预览\n拖入视频开始制作；音频素材也可以使用')
        if self.show_subtitles and self.renderer.text and w>0 and h>0:
            # Bound the backing image at large zooms; Qt clips/scales the
            # composited image together with the video, rather than allocating
            # an 800 MB libass frame at 1000% zoom.
            factor=min(1.,4096/max(w,h));rw=max(1,round(w*factor));rh=max(1,round(h*factor))
            p.drawImage(QRectF(x,y,w,h),self.renderer.image(rw,rh,self.position))
        p.end()

class Playback(QWidget):
    positionChanged=Signal(int)
    durationChanged=Signal(int)
    error=Signal(str)
    zoomChanged=Signal(float)
    temporaryChanged=Signal(bool)
    def __init__(self,parent=None):
        super().__init__(parent);self.canvas=VideoCanvas(self)
        from PySide6.QtWidgets import QVBoxLayout
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.viewport=QScrollArea();self.viewport.setFrameShape(QFrame.Shape.NoFrame);self.viewport.setAlignment(Qt.AlignmentFlag.AlignCenter);self.viewport.setMinimumSize(260,146);self.viewport.setWidget(self.canvas);layout.addWidget(self.viewport)
        self.source_size=QSize(1920,1080);self.zoom=None;self.reference_size=None
        self.viewport.viewport().installEventFilter(self);self.canvas.zoomRequested.connect(self.zoom_steps);self.canvas.frameSizeChanged.connect(self.set_frame_size)
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.sink=QVideoSink(self)
        self.temporary_owner=None;self.temporary_stop=None;self.temporary_position=None
        self.player.setAudioOutput(self.audio);self.player.setVideoSink(self.sink);self.audio.setVolume(.7)
        if hasattr(self.player,'setPitchCompensation'):self.player.setPitchCompensation(True)
        # Decode callbacks must not map a frame or pause the decoder inline.
        # Explicit receiver context also keeps QWidget work on the GUI thread.
        self.sink.videoFrameChanged.connect(self.receive_frame,Qt.ConnectionType.QueuedConnection)
        # All backend notifications unwind before Python queries or controls
        # the player again, including stop()/setSource() during disposal.
        queued=Qt.ConnectionType.QueuedConnection
        self.player.positionChanged.connect(self.receive_position,queued);self.player.durationChanged.connect(self.receive_duration,queued)
        self.player.errorOccurred.connect(self.play_error,queued)
        self.preview_pending=False;self.preview_started=False;self.preview_muted=False;self.preview_target=None
        self.resume_on_load=False;self.restore_range=None
        self.pending_seek=None;self.player.mediaStatusChanged.connect(self.loaded,queued)
        self.range=None;self.loop=False;self.anchor=0;self.clock=QElapsedTimer();self.clock.start()
        self.timer=QTimer(self);self.timer.setInterval(25);self.timer.timeout.connect(self.tick);self.timer.start()
        self.player.playbackStateChanged.connect(self.receive_state,queued)
        self.player.playbackRateChanged.connect(self.receive_rate,queued)

    def cancel_preview(self):
        if self.preview_started:self.audio.setMuted(self.preview_muted)
        self.preview_started=False;self.preview_pending=False;self.preview_target=None

    @Slot(QMediaPlayer.Error,str)
    def play_error(self,code,message):
        if self.player.source().isEmpty():return
        self.interrupt_temporary()
        self.cancel_preview();self.resume_on_load=False;self.error.emit('播放失败：'+message)

    @Slot('qint64')
    def receive_position(self,value):
        # A queued notification may describe the previous seek/source. Read
        # current state, and do not overwrite an explicit pending seek.
        if self.temporary_position is None and not self.player.source().isEmpty() and self.pending_seek is None and not self.preview_pending:self.on_position(self.player.position())

    @Slot('qint64')
    def receive_duration(self,value):
        if not self.player.source().isEmpty():self.durationChanged.emit(int(value))

    @Slot(QMediaPlayer.PlaybackState)
    def receive_state(self,state):
        if self.temporary_position is None and not self.player.source().isEmpty() and self.pending_seek is None and not self.preview_pending:self.on_position(self.player.position())

    @Slot(float)
    def receive_rate(self,rate):
        if self.temporary_position is None and not self.player.source().isEmpty() and self.pending_seek is None and not self.preview_pending:self.on_position(self.player.position())

    @Slot(QVideoFrame)
    def receive_frame(self,frame):
        if self.player.source().isEmpty():return
        self.canvas.video_frame(frame)
        if self.preview_started and frame.isValid():
            target=self.preview_target
            # A decoder can first deliver preroll before the requested seek.
            # Warm silently through it, then keep the exact audition position.
            if target is not None and frame.startTime()>=0:
                end=frame.endTime() if frame.endTime()>frame.startTime() else frame.startTime()+40000
                if end<target*1000:return
            invoke_native_slot(self.player,'pause');self.cancel_preview()
            if target is not None:self.seek(target,internal=True)
            if self.resume_on_load:self.resume_on_load=False;invoke_native_slot(self.player,'play')

    @Slot(QMediaPlayer.MediaStatus)
    def loaded(self,status):
        if self.player.source().isEmpty() or status!=self.player.mediaStatus():return
        if status==QMediaPlayer.MediaStatus.EndOfMedia:
            self.cancel_preview();self.resume_on_load=False;return
        if self.pending_seek is not None and status in (QMediaPlayer.MediaStatus.LoadedMedia,QMediaPlayer.MediaStatus.BufferingMedia,QMediaPlayer.MediaStatus.BufferedMedia):
            value=self.pending_seek;self.pending_seek=None;self.seek(value,internal=True)

        if status in (QMediaPlayer.MediaStatus.LoadedMedia,QMediaPlayer.MediaStatus.BufferedMedia):
            if self.restore_range is not None:self.range,self.loop=self.restore_range;self.restore_range=None
            if self.resume_on_load and not self.preview_pending:self.resume_on_load=False;invoke_native_slot(self.player,'play')
            elif self.preview_pending and not self.player.hasVideo():
                self.preview_pending=False
                if self.resume_on_load:self.resume_on_load=False;invoke_native_slot(self.player,'play')

        if self.preview_pending and not self.preview_started and self.player.hasVideo() and status in (QMediaPlayer.MediaStatus.LoadedMedia,QMediaPlayer.MediaStatus.BufferedMedia):
            self.preview_started=True;self.preview_muted=self.audio.isMuted();self.audio.setMuted(True);invoke_native_slot(self.player,'play')

    def open(self,path,position=0,preview=False,reference_size=None):
        self.interrupt_temporary()
        self.cancel_preview();self.resume_on_load=False;self.restore_range=None;invoke_native_slot(self.player,'stop');self.preview_pending=bool(preview);self.preview_target=max(0,int(position)) if preview else None;self.range=None;self.canvas.frame=QImage();self.canvas.update();self.canvas.aspect=16/9;self.canvas.audio_only=False;self.zoom=None;self.reference_size=reference_size;self.set_source_size(*(reference_size or (1920,1080)));self.pending_seek=max(0,int(position)) or None;self.player.setSource(QUrl.fromLocalFile(str(path)))

    def clear(self):
        self.interrupt_temporary()
        self.cancel_preview();self.pending_seek=None;self.resume_on_load=False;self.restore_range=None;self.range=None
        # Release displayed image resources before stopping the decoder.
        self.canvas.frame=QImage()
        self.canvas.update()
        self.reference_size=None
        invoke_native_slot(self.player,'stop')
        self.player.setSource(QUrl())
        self.on_position(0);self.durationChanged.emit(0)

    def replace_audition_source(self,path,reference_size=None):
        position=self.canvas.position;zoom=self.zoom;playing=self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState and not self.preview_started
        saved_range=self.range;loop=self.loop;size=self.source_size
        self.open(path,position,preview=True,reference_size=reference_size);self.resume_on_load=playing;self.restore_range=(saved_range,loop);self.set_source_size(*(reference_size or (size.width(),size.height())));self.set_zoom(zoom)
        self.seek(position)

    def set_frame_size(self,width,height):
        self.set_source_size(*(self.reference_size or (width,height)))

    def set_source_size(self,width,height):
        self.source_size=QSize(max(16,width),max(16,height));self.canvas.aspect=width/max(1,height);self.resize_canvas()

    def resize_canvas(self):
        if self.zoom is None:
            available=self.viewport.viewport().size();self.canvas.resize(self.source_size.scaled(available,Qt.AspectRatioMode.KeepAspectRatio))
        else:self.canvas.resize(round(self.source_size.width()*self.zoom),round(self.source_size.height()*self.zoom))
        self.zoomChanged.emit(0. if self.zoom is None else self.zoom)

    def set_zoom(self,value=None):
        self.zoom=None if value is None else max(.125,min(10.,float(value)));self.resize_canvas()

    def zoom_steps(self,steps):
        if not steps:self.set_zoom(None);return
        current=self.zoom if self.zoom is not None else self.canvas.width()/self.source_size.width()
        # Aegisub's SetWindowZoom: linear 1/8 steps, bounded at 12.5–1000%.
        self.set_zoom(round((current+steps*.125)*10000)/10000)

    def eventFilter(self,obj,event):
        if obj is self.viewport.viewport():
            if event.type()==QEvent.Type.Resize and self.zoom is None:QTimer.singleShot(0,self.resize_canvas)
            elif event.type()==QEvent.Type.Wheel:
                self.canvas.wheelEvent(event);return True
        return super().eventFilter(obj,event)

    def on_position(self,value):
        self.anchor=value;self.clock.restart();self.update_canvas_position(value);self.positionChanged.emit(value)

    def update_canvas_position(self,value):
        if value!=self.canvas.position:self.canvas.position=value;self.canvas.update()

    def tick(self):
        if self.temporary_position is not None:
            self.update_canvas_position(self.temporary_position);return
        target=self.pending_seek if self.pending_seek is not None else self.preview_target if self.preview_pending else None
        if target is not None:
            self.update_canvas_position(target);return
        playing=self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState
        position=self.anchor+round(self.clock.elapsed()*self.player.playbackRate()) if playing else (self.player.position() if self.player.duration()>0 else self.anchor)
        if self.range and playing and position>=self.range[1]:
            if self.loop:self.seek(self.range[0],internal=True)
            else:invoke_native_slot(self.player,'pause');self.seek(self.range[1],internal=True);self.range=None
            return
        self.update_canvas_position(max(0,min(position,self.player.duration() or position)))
        if playing:self.positionChanged.emit(self.canvas.position)

    def seek(self,value,internal=False):
        if not internal:self.interrupt_temporary()
        value=max(0,int(value));duration=self.player.duration()
        if duration>0:value=min(value,duration)
        if self.pending_seek is not None or self.player.mediaStatus() in (QMediaPlayer.MediaStatus.NoMedia,QMediaPlayer.MediaStatus.LoadingMedia):self.pending_seek=value
        if self.preview_pending:self.preview_target=value
        self.player.setPosition(value);self.on_position(value)

    def toggle(self):
        if self.temporary_owner is not None:self.interrupt_temporary();return
        warming=self.preview_started;self.cancel_preview()
        if not warming and self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:invoke_native_slot(self.player,'pause')
        else:self.range=None;invoke_native_slot(self.player,'play')

    def audition(self,start,end,loop=False):
        self.interrupt_temporary()
        self.cancel_preview()
        duration=self.player.duration();start=max(0,int(start));end=min(int(end),duration) if duration>0 else int(end)
        if start>=end:self.range=None;self.error.emit('所选时间超出了素材，请调整起止时间后试听。');return False
        self.range=(start,end);self.loop=loop;self.seek(self.range[0]);invoke_native_slot(self.player,'play');return True

    def stop(self):
        self.interrupt_temporary()
        self.cancel_preview();self.resume_on_load=False;self.restore_range=None;self.range=None;invoke_native_slot(self.player,'pause')
        self.on_position(self.player.position())

    def begin_temporary(self,owner,stop,position=None):
        self.interrupt_temporary();self.temporary_owner=owner;self.temporary_stop=stop
        self.temporary_position=None if position is None else max(0,int(position));self.temporaryChanged.emit(True)
        if position is not None:self.on_position(self.temporary_position)

    def update_temporary_position(self,owner,value):
        if self.temporary_owner is owner and self.temporary_position is not None:
            self.temporary_position=max(0,int(value));self.on_position(self.temporary_position)

    def end_temporary(self,owner):
        if self.temporary_owner is owner:
            self.temporary_owner=None;self.temporary_stop=None;self.temporary_position=None;self.temporaryChanged.emit(False)

    def interrupt_temporary(self):
        if self.temporary_owner is not None:
            stop=self.temporary_stop;self.temporary_owner=None;self.temporary_stop=None;self.temporary_position=None
            # Release ownership before invoking a controller that may pause/seek.
            if stop is not None:stop()
            self.temporaryChanged.emit(False)

    def set_rate(self,value):
        self.interrupt_temporary();self.player.setPlaybackRate(value)
