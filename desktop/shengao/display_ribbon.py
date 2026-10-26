"""A separate display-window strip sharing the unmodified audio time scale."""
import copy
from PySide6.QtCore import Qt,Signal,QRectF,QLineF
from PySide6.QtGui import QPainter,QColor,QPen,QFontMetrics
from PySide6.QtWidgets import QWidget
from .presentation import display_windows,DisplayWindow
from .display_timing import edit_context,bounded_window
from .widgets import time_text


class DisplayTimingRibbon(QWidget):
    changed=Signal(int,int,int,str,object)
    selected=Signal(int)
    preview=Signal(int,str)
    notice=Signal(str)

    def __init__(self,timeline,parent=None):
        super().__init__(parent);self.timeline=timeline;self.project=None;self.current=-1;self.windows=[];self.rows=[];self.drag=None;self.edge='start'
        self.setObjectName('displayTimingRibbon');self.setMinimumHeight(68);self.setMaximumHeight(68);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.setMouseTracking(True)
        self.setToolTip('字幕留屏条：拖两端改出现／消失，拖中间平移留屏；演唱和音节不动。左右键微调10ms，Shift为100ms，Esc取消。双击查看出现或消失。滚轮沿用音频视野操作。')
        timeline.viewChanged.connect(self.update)

    def set_project(self,project,current,windows=None):
        if self.drag:
            try:unchanged=edit_context(project,self.drag['row'])==self.drag['context'] and current==self.current
            except ValueError:unchanged=False
            if not unchanged:self.cancel('内容已变化，本次留屏拖动已取消')
        self.project=project;self.current=current;self.windows=display_windows(project) if windows is None else windows
        self.rows=list(range(max(0,current-1),min(len(project.lines),current+2))) if 0<=current<len(project.lines) else []
        self.update()

    def x_at(self,ms):return (ms-self.timeline.left)*self.width()/max(1,self.timeline.span)
    def ms_at(self,x):return round(self.timeline.left+x*self.timeline.span/max(1,self.width()))
    def row_rect(self,row):
        index=self.rows.index(row);return QRectF(0,14+index*17,self.width(),16)
    def bar(self,row,window=None):
        w=window or self.windows[row];rect=self.row_rect(row)
        return QRectF(self.x_at(w.start),rect.top()+1,max(1,self.x_at(w.end)-self.x_at(w.start)),14)
    def hit(self,point):
        return next((row for row in self.rows if self.row_rect(row).contains(point)),None)
    def editable(self,row):return bool(self.project and not self.project.source_ass_active and not self.project.lines[row].locked)
    def side(self,row,x):
        w=self.windows[row];a,b=self.x_at(w.start),self.x_at(w.end)
        if min(abs(x-a),abs(x-b))<=8:return 'start' if abs(x-a)<=abs(x-b) else 'end'
        return 'move' if a<x<b else None

    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#f4f6fd'));p.setPen(QColor('#596c8a'))
        p.drawText(QRectF(4,0,self.width()-8,13),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,'字幕留屏 · 细线是演唱范围，拖动不改演唱轴')
        for row in self.rows:
            line=self.project.lines[row];w=self.windows[row]
            if self.drag and self.drag['row']==row:w=DisplayWindow(*self.drag['candidate'],w.slot)
            rect=self.bar(row,w);visible=rect.intersected(self.row_rect(row));active=row==self.current
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#aaaef6' if active else '#d1d9ec'));p.drawRoundedRect(rect,3,3)
            y=self.row_rect(row).bottom()-1;p.setPen(QPen(QColor('#174ca4'),2));p.drawLine(QLineF(self.x_at(line.start),y,self.x_at(line.end),y))
            p.setPen(QPen(QColor('#4249cb' if active else '#7f8eaa'),2))
            for x in (rect.left(),rect.right()):p.drawLine(QLineF(x,rect.top()+1,x,rect.bottom()-1))
            if visible.width()>24:
                p.setPen(QColor('#182d50'));text=f'{row+1} · {line.text.replace(chr(10)," ")}'
                text=QFontMetrics(p.font()).elidedText(text,Qt.TextElideMode.ElideRight,max(1,int(visible.width()-12)))
                p.drawText(visible.adjusted(6,0,-4,-1),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,text)
        p.end()

    def cancel(self,message='已取消留屏拖动，工程保持'):
        had=self.drag is not None;self.drag=None;self.unsetCursor();self.update()
        if had and message:self.notice.emit(message)

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return super().mousePressEvent(event)
        row=self.hit(event.position())
        if row is None:return
        self.setFocus()
        if row!=self.current:self.selected.emit(row);return
        part=self.side(row,event.position().x())
        if not part:return
        if not self.editable(row):self.notice.emit('本句已锁定或正在保留原 ASS；请先解除锁定或明确选择声稿样式');return
        self.edge=part if part!='move' else self.edge;w=self.windows[row]
        self.drag={'row':row,'part':part,'origin':self.ms_at(event.position().x()),'window':copy.copy(w),'context':edit_context(self.project,row),'candidate':(w.start,w.end)}
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mouseMoveEvent(self,event):
        if not self.drag:
            row=self.hit(event.position());part=self.side(row,event.position().x()) if row is not None else None
            self.setCursor(Qt.CursorShape.SizeHorCursor if row==self.current and part and self.editable(row) else Qt.CursorShape.ArrowCursor);return
        d=self.drag;value=self.ms_at(event.position().x());line=self.project.lines[d['row']]
        try:a,b=bounded_window(line,d['window'],self.project.duration,d['part'],value-d['origin'] if d['part']=='move' else value)
        except ValueError as error:self.cancel(str(error));return
        d['candidate']=(a,b);self.notice.emit(f'第 {d["row"]+1} 句留屏：{time_text(a)} — {time_text(b)}；松开采用，Esc取消；演唱轴保持')
        self.update()

    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or not self.drag:return super().mouseReleaseEvent(event)
        self.mouseMoveEvent(event)
        if not self.drag:return
        d=self.drag;self.drag=None;self.unsetCursor();self.update();a,b=d['candidate']
        if (a,b)!=(d['window'].start,d['window'].end):self.changed.emit(d['row'],a,b,d['part'],d['context'])

    def mouseDoubleClickEvent(self,event):
        row=self.hit(event.position())
        if row is not None:
            self.cancel('');w=self.windows[row];part='start' if abs(event.position().x()-self.x_at(w.start))<=abs(event.position().x()-self.x_at(w.end)) else 'end'
            self.preview.emit(row,part)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.cancel();event.accept();return
        if event.key() in (Qt.Key.Key_Home,Qt.Key.Key_End):
            self.edge='start' if event.key()==Qt.Key.Key_Home else 'end';self.notice.emit('已选择字幕出现边界' if self.edge=='start' else '已选择字幕消失边界');event.accept();return
        if event.key() not in (Qt.Key.Key_Left,Qt.Key.Key_Right):return super().keyPressEvent(event)
        if self.drag:self.cancel('先取消拖动，再用键盘微调');return
        row=self.current
        if row not in self.rows or not self.editable(row):return
        w=self.windows[row];delta=(100 if event.modifiers()&Qt.KeyboardModifier.ShiftModifier else 10)*(1 if event.key()==Qt.Key.Key_Right else -1)
        try:a,b=bounded_window(self.project.lines[row],w,self.project.duration,self.edge,(w.start if self.edge=='start' else w.end)+delta)
        except ValueError as error:self.notice.emit(str(error));return
        if (a,b)!=(w.start,w.end):self.changed.emit(row,a,b,self.edge,edit_context(self.project,row))
        event.accept()

    def wheelEvent(self,event):self.timeline.wheelEvent(event)
