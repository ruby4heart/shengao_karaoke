"""An adjacent lyric lane sharing the audio display's exact time coordinates."""
from PySide6.QtCore import Qt,QRectF,Signal
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QSizePolicy
from .widgets import time_text


class PreviousLane(QWidget):
    selected=Signal(int,int)
    audition=Signal(int,int)

    def __init__(self,timeline,parent=None,direction=-1):
        super().__init__(parent);self.timeline=timeline;self.direction=direction;self.setFixedHeight(27);self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def neighbour(self):return self.timeline.previous_line if self.direction<0 else self.timeline.next_line

    def visible_segments(self):
        t=self.timeline
        return [s for s in t.reference_segments(self.neighbour()) if s[3]>=t.left and s[2]<=t.left+t.span]

    def paintEvent(self,event):
        t=self.timeline;previous=self.neighbour()
        if not previous:return
        p=QPainter(self);p.fillRect(self.rect(),QColor('#edf6f5' if self.direction<0 else '#f1effa'));p.setFont(self.font())
        current=t.preview_line()
        for i,j,a,b,text in self.visible_segments():
            x1,x2=t.tx(a),t.tx(b);rect=QRectF(x1,1,max(1,x2-x1),self.height()-3)
            overlapping=current and max(a,current.start)<min(b,current.end)
            p.fillRect(rect,QColor('#fff0d8' if overlapping else '#e0f0ed' if self.direction<0 else '#e9e4f6'))
            p.setPen(QColor('#c88a25' if overlapping else '#39877f' if self.direction<0 else '#7863a8'));p.drawRect(rect)
            p.setClipRect(rect.adjusted(2,0,-2,0));p.drawText(rect.adjusted(3,0,-3,0),Qt.AlignmentFlag.AlignCenter,text.replace('\n',' '));p.setClipping(False)
        x=t.tx(previous.end if self.direction<0 else previous.start);p.setPen(QPen(QColor('#187c72' if self.direction<0 else '#7863a8'),2));p.drawLine(round(x),0,round(x),self.height())
        if not self.visible_segments():
            name='上句' if self.direction<0 else '下句'
            p.setPen(QColor('#657d7b'));p.drawText(self.rect().adjusted(6,0,-6,0),Qt.AlignmentFlag.AlignVCenter,name+'在视图外；可平移时间轴或点击修改')
        p.end()

    def segment_at(self,x):
        value=self.timeline.time(x)
        return next((s for s in self.visible_segments() if s[2]<=value<=s[3]),None)

    def mouseMoveEvent(self,event):
        s=self.segment_at(event.position().x())
        name='上句' if self.direction<0 else '下句'
        origin=''
        if s:
            from studio_backend.provenance import describe
            line=self.neighbour();word,part=s[0],s[1]
            item=line.units[word].highlights[part] if word>=0 and part>=0 else line.units[word] if word>=0 else line
            value=describe(item,line,word,part);origin=value['title']+'\n'+'\n'.join(value['issues'])+'\n'
        self.setToolTip((f'{name}音节：{s[4]}\n{time_text(s[2])} — {time_text(s[3])}\n'+origin+'单击修改这个音节，右键试听。' if s else '单击邻句音节进入校准，右键试听；滚轮平移，Ctrl＋滚轮缩放。'))

    def mousePressEvent(self,event):
        s=self.segment_at(event.position().x())
        if not s:return
        if event.button()==Qt.MouseButton.RightButton:self.audition.emit(s[2],s[3])
        elif event.button()==Qt.MouseButton.LeftButton:self.selected.emit(s[0],s[1])

    def wheelEvent(self,event):self.timeline.wheelEvent(event)


class PreviousContext(QWidget):
    selected=Signal(int,int)
    audition=Signal(int,int)

    def __init__(self,timeline,parent=None,direction=-1):
        super().__init__(parent);self.timeline=timeline;self.direction=direction
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(3)
        row=QHBoxLayout();row.setSpacing(5)
        self.caption=QLabel();self.caption.setTextFormat(Qt.TextFormat.PlainText);self.caption.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);row.addWidget(self.caption,1)
        self.listen=QPushButton('试听衔接');self.listen.setToolTip('试听相邻两句的衔接');self.listen.clicked.connect(self.listen_join);row.addWidget(self.listen)
        self.edit=QPushButton('改上句' if direction<0 else '改下句');self.edit.setToolTip('选择邻句靠近本句的音节进行校准');self.edit.clicked.connect(self.edit_tail);row.addWidget(self.edit)
        for button in (self.listen,self.edit):button.setStyleSheet('QPushButton { padding: 3px 7px; min-height: 18px; }')
        layout.addLayout(row);self.lane=PreviousLane(timeline,direction=direction);layout.addWidget(self.lane)
        self.lane.selected.connect(self.selected);self.lane.audition.connect(self.audition);timeline.viewChanged.connect(self.refresh)
        self.refresh()

    def set_compact(self,compact,hide_caption=False):
        self.caption.setVisible(not hide_caption);self.layout().setSpacing(0 if hide_caption else 3)
        self.listen.setVisible(not compact);self.edit.setVisible(not compact);self.lane.setFixedHeight(23 if compact else 27)
        # Its parent splitter asks for the minimum synchronously during resize.
        # Clear this inner layout's old 23px lane hint before that query.
        self.layout().invalidate();self.layout().activate();self.updateGeometry()

    def refresh(self):
        t=self.timeline;previous=self.lane.neighbour();current=t.preview_line();self.setVisible(bool(previous and current))
        if not previous or not current:return
        overlap=max(0,min(previous.end,current.end)-max(previous.start,current.start))
        gap=max(0,current.start-previous.end) if self.direction<0 else max(0,previous.start-current.end)
        state=f'重叠 {overlap} ms' if overlap else (f'间隔 {gap} ms' if gap else '首尾相接')
        text=f'上句结束 {time_text(previous.end)} · {state}' if self.direction<0 else f'下句开始 {time_text(previous.start)} · {state}'
        if self.direction<0 and getattr(self,'combined_caption',False) and t.next_line:
            text=f'上句尾 {time_text(previous.end)} · 下句头 {time_text(t.next_line.start)}'+(f' · 重叠 {overlap}ms' if overlap else '')
        colour='青色为上句' if self.direction<0 else '紫色为下句'
        self.caption.setText(text);self.caption.setToolTip(previous.text+'\n'+text+'\n'+colour+'音节边界，橙色表示演唱重叠，需试听判断。')
        self.caption.setStyleSheet('color: #9a5b00' if overlap else 'color: #28776f');self.lane.update()

    def edit_tail(self):
        values=self.timeline.reference_segments(self.lane.neighbour())
        if values:
            value=values[-1] if self.direction<0 else values[0];self.selected.emit(value[0],value[1])

    def listen_join(self):
        t=self.timeline;previous=self.lane.neighbour();current=t.line
        if not previous or not current:return
        if self.direction>0:
            tail=t.reference_segments(current)[-1];start=max(0,min(tail[2],previous.start)-250,previous.start-4000);end=min(max(previous.start+1000,current.end+250),previous.end+1000)
            if t.duration:end=min(end,t.duration)
            if end>start:self.audition.emit(start,end)
            return
        tail=t.reference_segments(previous)[-1]
        # A badly displaced previous endpoint must not start a minutes-long loop.
        start=max(0,min(tail[2],current.start)-250,current.start-4000)
        end=min(max(current.start+1000,previous.end+250),current.end+1000)
        if t.duration:end=min(end,t.duration)
        if end>start:self.audition.emit(start,end)
