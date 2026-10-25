"""Reviewable, local tail timing and pronunciation edits with real audition."""
import copy
from PySide6.QtCore import Qt,Slot,QSignalBlocker,QTimer,QBuffer,QByteArray,QIODevice,QUrl
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
    QPushButton,QCheckBox,QLineEdit,QDialogButtonBox,QDoubleSpinBox,QWidget,QScrollArea,QSizePolicy)
from .timeline import Timeline
from .native_slots import invoke_native_slot
from .audio_render import milliseconds_per_pixel
from .tail_model import tail_items,replace_mora,energy_info,consonant_clip
from .timing import set_time
from .widgets import TimeEdit,time_text


class TailDialog(QDialog):
    def __init__(self,line,playback,source_timeline,parent=None):
        super().__init__(parent);self.original=copy.deepcopy(line);self.preview=copy.deepcopy(line);self.result_line=None
        self.playback=playback;self.original_rate=playback.player.playbackRate();self.original_loop=playback.loop;self.closed=False;self.refreshing=False
        self.items=tail_items(line,20000);self.selected=len(self.items)-1
        self.filtered_player=QMediaPlayer(self);self.filtered_audio=QAudioOutput(self);self.filtered_player.setAudioOutput(self.filtered_audio);self.filtered_audio.setMuted(playback.audio.isMuted());self.filtered_buffers=[];self.filtered_start=0
        if hasattr(self.filtered_player,'setPitchCompensation'):self.filtered_player.setPitchCompensation(True)
        self.setWindowTitle('句尾细听 · 放大、慢放、微调');self.setMinimumSize(740,520);self.resize(900,640)
        layout=QVBoxLayout(self);title=QLabel(line.text);title.setTextFormat(Qt.TextFormat.PlainText);title.setWordWrap(True);layout.addWidget(title)
        hint=QLabel('先带前音听，再单独听尾音；拖边界或用 10ms 按钮微调。句末“す”的元音可能很弱，歌唱还会改变发音，需结合原声确认。');hint.setWordWrap(True);layout.addWidget(hint)
        if parent is not None and getattr(parent,'project',None) and parent.project.source_ass_active:
            hint.setText(hint.text()+' 修改读音并保存后使用声稿注音排版，原 ASS 保留，可一步撤销。')
        row=QHBoxLayout();self.combo=QComboBox();self.combo.setMinimumContentsLength(12);self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.combo.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        for i,j,a,b,text in self.items:self.combo.addItem(f'{text} · {time_text(a)} — {time_text(b)} · {line.units[i].text}')
        row.addWidget(self.combo,1)
        for text,fn in [('上一音',lambda:self.choose(self.selected-1)),('下一音',lambda:self.choose(self.selected+1)),('最后一音',lambda:self.choose(len(self.items)-1))]:
            button=QPushButton(text)
            if text=='上一音':button.clicked.connect(lambda:self.combo.setCurrentIndex(max(0,self.selected-1)))
            elif text=='下一音':button.clicked.connect(lambda:self.combo.setCurrentIndex(min(len(self.items)-1,self.selected+1)))
            else:button.clicked.connect(lambda:self.combo.setCurrentIndex(len(self.items)-1))
            row.addWidget(button)
        layout.addLayout(row)
        body=QHBoxLayout();self.timeline=Timeline();self.timeline.setMinimumSize(320,220);self.timeline.granularity='mora';self.timeline.quality=3;self.timeline.amplitude=2.;self.timeline.set_line(self.preview,False)
        if source_timeline.audio:
            audio=source_timeline.audio
            self.timeline.set_audio({'pcm':str(audio.samples.filename),'sample_rate':audio.rate,'duration':source_timeline.duration,'peaks':source_timeline.peaks,'keyframes':source_timeline.keyframes})
        body.addWidget(self.timeline,1);scroll=QScrollArea();self.controls_scroll=scroll;scroll.setWidgetResizable(True);scroll.setMinimumWidth(290);scroll.setMaximumWidth(330);controls_widget=QWidget();controls=QVBoxLayout(controls_widget);scroll.setWidget(controls_widget);body.addWidget(scroll);layout.addLayout(body,1)
        controls.addWidget(QLabel('① 放大看清弱音'))
        self.mode=QComboBox();self.mode.addItems(['频谱 · 看弱音细节','波形 · 看整体声强']);self.mode.currentIndexChanged.connect(self.change_mode);controls.addWidget(self.mode);row=QHBoxLayout()
        row.addWidget(QLabel('显示增益'));self.gain=QDoubleSpinBox();self.gain.setRange(.125,8);self.gain.setSingleStep(.25);self.gain.setValue(2);self.gain.setSuffix('×');self.gain.setToolTip('只放大频谱／波形，不改变试听音量');self.gain.valueChanged.connect(self.change_gain);row.addWidget(self.gain)
        controls.addLayout(row);button=QPushButton('放大当前音');button.clicked.connect(self.focus_part);controls.addWidget(button)
        row=QHBoxLayout();self.speed=QComboBox()
        for speed in [.5,.75,1.]:self.speed.addItem(f'{speed:g}× 保留音高',speed)
        controls.addWidget(QLabel('② 带前音慢放'));self.speed.setCurrentIndex(1);self.speed.currentIndexChanged.connect(self.set_speed);row.addWidget(self.speed)
        self.loop=QCheckBox('循环试听');self.loop.setChecked(True);self.loop.toggled.connect(lambda value:setattr(playback,'loop',value));row.addWidget(self.loop)
        controls.addLayout(row);self.enhance=QCheckBox('突出尾音辅音（减弱低频）');self.enhance.setToolTip('用于试听的频带增强；请关闭后对照原声确认，不改变素材、时间轴或导出。');self.enhance.toggled.connect(self.stop);controls.addWidget(self.enhance);row=QHBoxLayout()
        for text,fn in [('带前音试听',lambda:self.listen(True)),('仅听当前音',lambda:self.listen(False))]:
            button=QPushButton(text);button.clicked.connect(fn);row.addWidget(button)
        controls.addLayout(row);stop=QPushButton('停止试听');stop.clicked.connect(self.stop);controls.addWidget(stop)
        self.energy=QLabel();self.energy.setWordWrap(True);layout.addWidget(self.energy)
        controls.addWidget(QLabel('③ 调整这个音的起止'));row=QHBoxLayout();self.begin=TimeEdit();self.end=TimeEdit();row.addWidget(QLabel('开始'));row.addWidget(self.begin);controls.addLayout(row)
        row=QHBoxLayout();row.addWidget(QLabel('结束'));row.addWidget(self.end);controls.addLayout(row)
        button=QPushButton('应用这两个时间');button.clicked.connect(self.apply_times);controls.addWidget(button)
        for text,edge,delta in [('起点 −10ms',0,-10),('起点 +10ms',0,10),('终点 −10ms',1,-10),('终点 +10ms',1,10)]:
            if delta<0:row=QHBoxLayout()
            button=QPushButton(text);button.clicked.connect(lambda checked=False,e=edge,d=delta:self.nudge(e,d));row.addWidget(button)
            if delta>0:controls.addLayout(row)
        controls.addWidget(QLabel('④ 必要时修正假名'));self.reading=QLineEdit();self.reading.setPlaceholderText('例如 て、す、きょ');controls.addWidget(self.reading)
        button=QPushButton('应用这个读音');button.clicked.connect(self.apply_reading);controls.addWidget(button);controls.addStretch()
        self.status=QLabel('这里只先预览，保存后写回工程；取消保留原值。修改假名不改原歌词，原歌词有误可返回“编辑原歌词”。');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel);self.buttons.button(QDialogButtonBox.StandardButton.Apply).setText('保存本句修改');self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept_changes);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消修改')
        self.combo.currentIndexChanged.connect(self.change_selection);self.timeline.select.connect(self.select_from_plot);self.timeline.boundary.connect(self.boundary);self.timeline.action.connect(self.audio_action)
        playback.positionChanged.connect(self.timeline.follow_position);self.finished.connect(self.cleanup)
        queued=Qt.ConnectionType.QueuedConnection
        self.filtered_player.positionChanged.connect(self.filtered_position,queued)
        self.filtered_player.mediaStatusChanged.connect(self.filtered_status,queued)
        self.filtered_player.errorOccurred.connect(self.filtered_error,queued)
        playback.stop();playback.player.setPlaybackRate(.75);self.choose(self.selected);QTimer.singleShot(0,self.focus_part)

    def part(self):
        i,j,_,_,_=self.items[self.selected]
        return i,j,self.preview.units[i].highlights[j]

    def choose(self,index):
        index=max(0,min(len(self.items)-1,index));blocker=QSignalBlocker(self.combo);self.combo.setCurrentIndex(index);self.selected=index;self.refresh();self.focus_part()

    def change_selection(self,index):
        if self.refreshing:return
        old=self.selected
        if not self.apply_times() or not self.apply_reading():
            blocker=QSignalBlocker(self.combo);self.combo.setCurrentIndex(old);return
        self.choose(index)

    def select_from_plot(self,index,part):
        target=next((n for n,item in enumerate(self.items) if item[:2]==(index,part)),None)
        if target is not None:self.combo.setCurrentIndex(target)

    def refresh(self):
        self.refreshing=True
        try:
            i,j,part=self.part();self.timeline.set_line(self.preview,False);self.timeline.word,self.timeline.part=i,j;self.timeline.update()
            self.begin.setValue(part.start);self.end.setValue(part.end);self.reading.setText(part.kana)
            for n,(wi,pi,_,_,_) in enumerate(self.items):
                h=self.preview.units[wi].highlights[pi];self.combo.setItemText(n,f'{h.kana} · {time_text(h.start)} — {time_text(h.end)} · {self.preview.units[wi].text}')
            if self.timeline.audio:
                info=energy_info(self.timeline.audio.samples,self.timeline.audio.rate,part.start,part.end)
                detail='较前面 250ms 声强弱；可提高显示增益并带前音听。' if info['relative']<.45 else '可在频谱中对照前音与尾音的边界。'
                self.energy.setText(f'当前音 {part.kana} · {part.end-part.start}ms · 混合音轨约 {info["db"]:.1f}dBFS。{detail}\n声强包含伴奏，不用于自动判定发了哪个音。')
            else:self.energy.setText('音轨尚未分析完成，可先修改时间与假名；关闭后等待主时间轴就绪再细听。')
        finally:self.refreshing=False

    def focus_part(self):
        if self.closed:return
        _,_,part=self.part();wanted=max(500,part.end-part.start+400);t=self.timeline;physical=max(1,t.width()*t.devicePixelRatioF())
        t.zoom_level=min(range(-30,201),key=lambda n:abs(milliseconds_per_pixel(n)*physical-wanted));t.span=milliseconds_per_pixel(t.zoom_level)*physical;t.left=max(0,(part.start+part.end-t.span)/2);t.invalidate()

    def change_mode(self,index):self.timeline.show_spectrum=index==0;self.timeline.cache_key=None;self.timeline.update()
    def change_gain(self,value):self.timeline.amplitude=value;self.timeline.cache_key=None;self.timeline.update()

    def boundary(self,index,part,start,end):
        try:
            pending=self.reading.text();self.preview=set_time(self.preview,index,start,end,part);self.refresh();self.reading.setText(pending);self.status.setText('时间已在本窗口更新，保存后可在工程中一步撤销。');return True
        except ValueError as error:self.status.setText(str(error));return False

    def apply_times(self):
        i,j,part=self.part();a,b=self.begin.value(),self.end.value()
        if (a,b)==(part.start,part.end):return True
        pending_reading=self.reading.text();ok=self.boundary(i,j,a,b)
        if ok:self.reading.setText(pending_reading)
        return ok

    def apply_reading(self):
        i,j,part=self.part();value=self.reading.text()
        if value==part.kana:return True
        try:
            pending_times=self.begin.value(),self.end.value();self.preview=replace_mora(self.preview,i,j,value);self.refresh();self.begin.setValue(pending_times[0]);self.end.setValue(pending_times[1]);self.status.setText('假名已修改，其他音节与时间保持。请试听确认。');return True
        except ValueError as error:self.status.setText(str(error));return False

    def nudge(self,edge,delta):
        if not self.apply_times():return
        i,j,part=self.part();self.boundary(i,j,part.start+(delta if edge==0 else 0),part.end+(delta if edge==1 else 0))

    def listen(self,context):
        if not self.apply_times() or not self.apply_reading():return
        _,_,part=self.part();previous=self.items[max(0,self.selected-1)];previous_part=self.preview.units[previous[0]].highlights[previous[1]];start=max(0,min(previous_part.start,part.start)-100) if context else part.start;end=part.end+(100 if context else 0)
        if self.enhance.isChecked():
            if not self.timeline.audio:self.status.setText('音轨尚未就绪，请等主时间轴分析完成后再用增强试听。');return
            self.playback.stop();invoke_native_slot(self.filtered_player,'stop')
            maximum=262144*1000/self.timeline.audio.rate
            if end-part.start<=maximum:start=max(start,end-maximum)
            try:data,info=consonant_clip(self.timeline.audio.samples,self.timeline.audio.rate,start,end)
            except ValueError as error:self.status.setText(str(error));return
            buffer=QBuffer(self);buffer.setData(QByteArray(data));buffer.open(QIODevice.OpenModeFlag.ReadOnly);self.filtered_buffers.append(buffer);self.filtered_start=info['start']
            self.filtered_audio.setVolume(self.playback.audio.volume());self.filtered_player.setSourceDevice(buffer,QUrl('tail.wav'));self.filtered_player.setPlaybackRate(self.speed.currentData());invoke_native_slot(self.filtered_player,'play')
            self.status.setText(f'辅音增强试听 · 信号增益 {info["gain"]:.1f}×。关闭增强可对照原声；增强不判断唱了哪个音。')
        else:
            self.original_audition(start,end)

    def original_audition(self,start,end):
        invoke_native_slot(self.filtered_player,'stop');self.playback.player.setPlaybackRate(self.speed.currentData());self.playback.audition(start,end,self.loop.isChecked())

    def set_speed(self,*args):
        self.playback.player.setPlaybackRate(self.speed.currentData());self.filtered_player.setPlaybackRate(self.speed.currentData())

    def stop(self,*args):self.playback.stop();invoke_native_slot(self.filtered_player,'stop')

    @Slot('qint64')
    def filtered_position(self,value):
        if not self.closed:self.timeline.follow_position(self.filtered_start+int(value))

    @Slot(QMediaPlayer.Error,str)
    def filtered_error(self,code,message):
        if not self.closed:self.status.setText('增强试听失败：'+message)

    @Slot(QMediaPlayer.MediaStatus)
    def filtered_status(self,status):
        if not self.closed and status==QMediaPlayer.MediaStatus.EndOfMedia and self.loop.isChecked():self.filtered_player.setPosition(0);invoke_native_slot(self.filtered_player,'play')

    def audio_action(self,name):
        _,_,part=self.part();a,b=part.start,part.end
        if name=='stop':self.stop()
        elif name=='toggle' and any(p.playbackState()==QMediaPlayer.PlaybackState.PlayingState for p in [self.playback.player,self.filtered_player]):self.stop()
        elif name in ('selection','toggle'):self.listen(False)
        elif name=='line':self.original_audition(self.preview.start,self.preview.end)
        elif name in ('next','previous'):self.combo.setCurrentIndex(max(0,min(len(self.items)-1,self.selected+(1 if name=='next' else -1))));self.listen(False)
        elif name in ('confirm','confirm_default'):self.accept_changes()
        elif name.startswith('length_') and self.selected<len(self.items)-1:self.nudge(1,10 if 'plus' in name else -10)
        elif name.startswith('start_') and self.selected:self.nudge(0,10 if 'plus' in name else -10)
        elif name in ('before','after','begin','end','to_end'):
            ranges={'before':(max(0,a-500),a),'after':(b,b+500),'begin':(a,min(b,a+500)),'end':(max(a,b-500),b),'to_end':(a,self.playback.player.duration() or self.preview.end)}
            self.original_audition(*ranges[name])
        elif name.startswith('scroll_'):self.timeline.left+=128*self.timeline.pixel_ms/self.timeline.devicePixelRatioF()*(-1 if name=='scroll_left' else 1);self.timeline.invalidate()

    def accept_changes(self):
        if self.apply_times() and self.apply_reading():self.result_line=copy.deepcopy(self.preview);self.accept()

    def cleanup(self,*args):
        if self.closed:return
        self.closed=True;self.timeline.cancel_drag();self.stop();self.filtered_player.setSource(QUrl());self.playback.player.setPlaybackRate(self.original_rate);self.playback.loop=self.original_loop
        try:self.playback.positionChanged.disconnect(self.timeline.follow_position)
        except RuntimeError:pass
        if self.timeline.audio:self.timeline.audio.close();self.timeline.audio=None
