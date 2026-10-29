"""Qt input/model around the original offscreen Aegisub timeline drawing."""
import math
import numpy as np
from PySide6.QtCore import Qt,Signal,QRectF,QTimer
from PySide6.QtGui import QPainter,QColor,QImage
from PySide6.QtWidgets import QWidget
from .audio_render import AudioRenderer,milliseconds_per_pixel
from .timeline_view import TimelineRenderer,Scene,cursor_label
from .widgets import time_text as time_label

def stamp(ms):
    seconds=max(0,ms)/1000
    return f'{int(seconds)//60:02}:{seconds%60:05.2f}'

class AudioScrollBar(QWidget):
    """Aegisub AudioDisplayScrollbar geometry, selection and palette."""
    valueChanged=Signal(int)
    def __init__(self,parent):
        super().__init__(parent);self.timeline=parent;self._value=0;self._maximum=0;self._page=1
    def setRange(self,minimum,maximum):self._maximum=max(0,maximum);self.update()
    def setPageStep(self,value):self._page=max(1,value);self.update()
    def setValue(self,value):
        value=max(0,min(self._maximum,int(value)));changed=value!=self._value;self._value=value
        if changed:self.valueChanged.emit(value)
        self.update()
    def thumb(self):
        dpr=self.devicePixelRatioF();width=round(self.width()*dpr)
        data=max(1,int(self.timeline.duration/(self.timeline.pixel_ms/dpr)))
        return int(width*self._value/data)/dpr,max(10,int(width*self._page/data))/dpr
    def paintEvent(self,event):
        # The parent's native scene already paints the original scrollbar.
        return
    def slide(self,event):
        self.timeline.setFocus();x,width=self.thumb();shaft=self.width()-width
        if shaft<=0:self.setValue(0);return
        left=event.position().x()-width/2;self.setValue(int(self._maximum*left/shaft))
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.slide(event)
    def mouseMoveEvent(self,event):
        if event.buttons()&Qt.MouseButton.LeftButton:self.slide(event)

class Timeline(QWidget):
    seek=Signal(int)
    select=Signal(int,int)
    boundary=Signal(int,int,int,int)
    audition=Signal(int,int)
    shifted=Signal(int,int,int,int)
    viewChanged=Signal()
    action=Signal(str)
    moved=Signal(int)
    notice=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName('karaokeTimeline');self.setMinimumHeight(222)
        self.setMouseTracking(True);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.line=None;self.word=-1;self.part=-1;self.left=0;self.span=8000;self.position=0
        self.peaks=None;self.spectrum=None;self.audio=None;self.duration=0;self.keyframes=[];self.neighbor_edges=[];self.previous_line=None;self.next_line=None;self.show_keyframes=True
        self.show_spectrum=True;self.waveform_averages=False;self.quality=1;self.curve=0;self.amplitude=1.;self.granularity='words';self.zoom_level=0;self.snap_enabled=False
        self.medusa_hotkeys=False
        self.drag=None;self.ghost=None;self.panning=None;self.hover=None;self.playing=False;self.cache_key=None;self.cache_image=None
        self.move_mode=False;self.moving=None;self.move_delta=0;self.drag_x=None;self.drag_modifiers=Qt.KeyboardModifier.NoModifier
        self.move_limits=None;self.move_error='';self.move_scope_label='本句';self.editing_enabled=True
        self.auto_scroll=QTimer(self);self.auto_scroll.setInterval(40);self.auto_scroll.timeout.connect(self.auto_pan)
        self.view_renderer=TimelineRenderer();self.cache_rgb=None
        self.scroll=AudioScrollBar(self);self.scroll.valueChanged.connect(self.scroll_to)
        self.scroll.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setToolTip('Aegisub 操作：左键选音节／拖边界，右键试听，中键定位视频；拖上方刻度平移；滚轮平移，Ctrl＋滚轮缩放，Shift 暂时关闭吸附')

    @property
    def pixel_ms(self):return self.span/max(1,self.width())
    @property
    def audio_top(self):return math.ceil(self.view_renderer.top(self.devicePixelRatioF())/self.devicePixelRatioF())
    @property
    def audio_bottom(self):return math.floor(self.height()-15/self.devicePixelRatioF())

    def segments(self,line=None):
        line=self.line if line is None else line
        if not line:return []
        if self.granularity=='line':return [(-1,-1,line.start,line.end,line.text)]
        values=[]
        for i,u in enumerate(line.units):
            if self.granularity=='mora' and u.highlights:
                values.extend((i,j,h.start,h.end,h.kana) for j,h in enumerate(u.highlights))
            else:values.append((i,-1,u.start,u.end,u.text))
        return values

    @staticmethod
    def reference_segments(line):
        if not line:return []
        values=[]
        for i,u in enumerate(line.units):
            if u.highlights:values.extend((i,j,h.start,h.end,h.kana) for j,h in enumerate(u.highlights))
            else:values.append((i,-1,u.start,u.end,u.text))
        return values or [(-1,-1,line.start,line.end,line.text)]

    def set_neighbors(self,previous=None,following=None):
        self.previous_line,self.next_line=previous,following
        self.neighbor_edges=[t for line in (previous,following) if line for t in (line.start,line.end)]
        self.cache_key=None;self.viewChanged.emit();self.update()

    def drag_bounds(self,value):
        i,j,edge,a,b,following=self.drag
        if edge==0:a=min(value,b-10)
        else:b=max(value,a+10)
        if self.line and i==-1 and self.line.units:
            if edge==0:a=min(a,self.line.units[0].end-10)
            else:b=max(b,self.line.units[-1].start+10)
        elif self.line and i>=0:
            segments=self.segments(self.line);position=next((n for n,s in enumerate(segments) if (s[0],s[1])==(i,j)),-1)
            if position>=0:
                if edge==0 and position>0:
                    prev=segments[position-1];old=segments[position][2]
                    a=max(a,prev[2]+10 if prev[3]==old else prev[3])
                if edge==1 and position+1<len(segments):
                    nxt=segments[position+1];old=segments[position][3]
                    b=min(b,nxt[3]-10 if nxt[2]==old else nxt[2])
        return a,b

    def preview_line(self):
        if self.line and self.moving is not None:
            from .tail_model import shift_line
            try:return shift_line(self.line,self.move_delta)
            except ValueError:return self.line
        if not self.line or not self.drag or self.ghost is None:return self.line
        from .timing import set_time,shift_following
        i,j,edge,a,b,following=self.drag
        try:
            if following and i>=0:
                old=a if edge==0 else b
                return shift_following(self.line,old,self.ghost-old)
            a,b=self.drag_bounds(self.ghost)
            return set_time(self.line,i,a,b,None if j<0 else j)
        except ValueError:return self.line

    def set_line(self,line,focus=True):
        changed=self.line is None or line is None or self.line.id!=line.id
        if changed:self.cancel_drag()
        self.line=line
        if changed:
            self.word=0 if line and line.units else -1
            self.part=0 if line and line.units and line.units[0].highlights and self.granularity=='mora' else -1
        if self.granularity=='line':self.word=self.part=-1
        elif line and line.units:
            if not 0<=self.word<len(line.units):self.word=0
            if self.granularity=='mora' and line.units[self.word].highlights:
                if not 0<=self.part<len(line.units[self.word].highlights):self.part=0
            else:self.part=-1
        else:self.word=self.part=-1
        self.cache_key=None
        if focus and line:self.focus_line()
        self.update_scroll();self.update()

    def focus_line(self):
        if self.line:
            start=self.line.start-700;end=self.line.end+700
            previous=self.previous_line
            if previous and previous.end>=self.line.start-2000:
                tail=self.reference_segments(previous)[-1]
                start=min(start,max(self.line.start-4000,tail[2]-250))
                end=max(end,min(previous.end+250,self.line.end+2000))
            requested=max(2400,end-max(0,start))
            candidates=range(-20,101)
            physical_width=max(1,self.width()*self.devicePixelRatioF())
            self.zoom_level=min(candidates,key=lambda n:abs(milliseconds_per_pixel(n)*physical_width-requested))
            self.span=milliseconds_per_pixel(self.zoom_level)*physical_width
            self.left=max(0,round(start/self.pixel_ms)*self.pixel_ms)
        self.invalidate()

    def focus_selection(self):
        selected=next((v for v in self.segments() if v[:2]==(self.word,self.part)),None)
        if not selected:self.focus_line();return
        a,b=selected[2:4];wanted=max(500,b-a+400);physical=max(1,self.width()*self.devicePixelRatioF())
        self.zoom_level=min(range(-30,201),key=lambda n:abs(milliseconds_per_pixel(n)*physical-wanted))
        self.span=milliseconds_per_pixel(self.zoom_level)*physical;self.left=max(0,(a+b-self.span)/2);self.invalidate()

    def focus_position(self):
        self.left=max(0,self.position-self.span/2);self.invalidate()

    def focus_range(self,start,end):
        wanted=max(500,end-start+400);physical=max(1,self.width()*self.devicePixelRatioF())
        self.zoom_level=min(range(-30,201),key=lambda n:abs(milliseconds_per_pixel(n)*physical-wanted))
        self.span=milliseconds_per_pixel(self.zoom_level)*physical;self.left=max(0,start-200);self.invalidate()

    def set_audio(self,value):
        if self.audio:self.audio.close()
        self.peaks=value['peaks'];self.spectrum=value.get('spectrum');self.duration=int(value['duration'])
        self.keyframes=value.get('keyframes',[])
        self.audio=AudioRenderer(value['pcm'],int(value['sample_rate']));self.invalidate()

    def invalidate(self):
        if self.duration:self.left=max(0,min(self.left,max(0,self.duration-self.span)))
        pp=self.pixel_ms/self.devicePixelRatioF();self.left=round(self.left/pp)*pp
        self.cache_key=None;self.update_scroll();self.viewChanged.emit();self.update()
    def tx(self,time):
        dpr=self.devicePixelRatioF();pp=self.pixel_ms/dpr
        return (int(time/pp)-round(self.left/pp))/dpr
    def time(self,x):return max(0,int(self.left+x*self.pixel_ms))
    def snap(self,time,modifiers=Qt.KeyboardModifier.NoModifier):
        if self.line and self.snap_enabled and not modifiers&Qt.KeyboardModifier.ShiftModifier:
            values=[self.line.start,self.line.end,self.position]+list(self.keyframes)+self.neighbor_edges
            nearest=min(values,key=lambda t:abs(t-time))
            if abs(nearest-time)<=8*self.pixel_ms:time=nearest
        return max(0,int((time+5)//10*10))

    def update_scroll(self):
        pp=self.pixel_ms/self.devicePixelRatioF();page=round(self.width()*self.devicePixelRatioF())
        blocker=self.scroll.blockSignals(True)
        self.scroll.setRange(0,max(0,int(self.duration/pp)-page));self.scroll.setPageStep(page);self.scroll.setValue(round(self.left/pp));self.scroll.blockSignals(blocker)
    def scroll_to(self,pixel):self.left=pixel*self.pixel_ms/self.devicePixelRatioF();self.cache_key=None;self.viewChanged.emit();self.update()
    def resizeEvent(self,event):
        old=event.oldSize().width();new=event.size().width()
        if old>0:self.span=self.span/old*new
        else:self.span=milliseconds_per_pixel(self.zoom_level)*new*self.devicePixelRatioF()
        bar=math.ceil(15/self.devicePixelRatioF());self.scroll.setGeometry(0,self.height()-bar,self.width(),bar);self.invalidate()
    def set_zoom(self,level,anchor=None):
        level=max(-30,min(200,int(level)));anchor=self.width()/2 if anchor is None else anchor
        time=self.left+anchor*self.pixel_ms;self.zoom_level=level;self.span=milliseconds_per_pixel(level)*self.width()*self.devicePixelRatioF()
        self.left=max(0,round((time-anchor*self.pixel_ms)/self.pixel_ms)*self.pixel_ms);self.invalidate()

    def targets(self):
        if not self.line:return []
        top,bottom=self.audio_top,self.audio_bottom
        values=[(-1,-1,self.line.start,self.line.end,top,bottom)]
        values.extend((i,j,a,b,top,bottom) for i,j,a,b,text in self.segments())
        return values

    def render_audio(self):
        if not self.audio:return None
        line=self.preview_line()
        dpr=self.devicePixelRatioF();width,height=round(self.width()*dpr),round(self.height()*dpr)-self.view_renderer.top(dpr)-15;pixel_ms=self.pixel_ms/dpr
        selected=next(((a,b) for i,j,a,b,text in self.segments(line) if (i,j)==(self.word,self.part)),None)
        key=(width,height,dpr,self.left,pixel_ms,self.show_spectrum,self.waveform_averages,self.quality,self.curve,self.amplitude,
             (line.start,line.end) if line else None,selected,(self.previous_line.start,self.previous_line.end) if self.previous_line else None)
        if key==self.cache_key:return self.cache_image
        start=max(0,round(self.left/pixel_ms));styles=np.zeros(width,np.uint8)
        def fill(a,b,style):
            # AudioDisplay::PaintAudio truncates each absolute time to pixels.
            left=max(0,min(width,int(a/pixel_ms)-start));right=max(0,min(width,int(b/pixel_ms)-start))
            styles[left:right]=style
        if self.previous_line:fill(self.previous_line.start,self.previous_line.end,1)
        if line:fill(line.start,line.end,2)
        if selected:fill(*selected,3)
        mode=1 if self.show_spectrum else 2 if self.waveform_averages else 0
        rgb=self.audio.rgb(start,width,height,pixel_ms,self.amplitude,mode,self.quality,self.curve,styles)
        self.cache_rgb=rgb
        self.cache_image=QImage(rgb.data,width,height,width*3,QImage.Format.Format_RGB888).copy();self.cache_image.setDevicePixelRatio(dpr);self.cache_key=key
        return self.cache_image

    def scene(self):
        dpr=self.devicePixelRatioF();pp=self.pixel_ms/dpr
        line=self.preview_line();segments=self.segments(line)
        selected=next(((a,b) for i,j,a,b,text in segments if (i,j)==(self.word,self.part)),None)
        cursor=self.ghost if self.ghost is not None else self.hover if self.hover is not None and not self.playing else self.position
        label=cursor_label(cursor).encode('utf-8') if self.ghost is not None or (self.hover is not None and not self.playing) else None
        scene=Scene(round(self.width()*dpr),round(self.height()*dpr),self.duration,round(self.left/pp),int(not self.show_spectrum),int(self.hasFocus()),*(selected or (-1,-1)),int(cursor/pp),pp,dpr,label)
        markers=[]
        def marker(time,color,width=1,dotted=False,feet=0):markers.append((int(time),0,*color,255,width,int(dotted),feet))
        if self.granularity=='line':
            for t in range(math.ceil(self.left/1000)*1000,int(self.left+self.span)+1,1000):marker(t,(0,100,255),dotted=True)
        if self.previous_line:
            previous=self.previous_line
            for t in sorted({t for i,j,a,b,text in self.reference_segments(previous) for t in (a,b)}-{previous.end}):
                if self.left<=t<=self.left+self.span:marker(t,(93,205,195),1,True)
            marker(previous.end,(93,205,195),2,feet=1)
        if self.next_line:marker(self.next_line.start,(170,180,198),2)
        if not self.previous_line and not self.next_line:
            for t in self.neighbor_edges:marker(t,(190,190,190),2)
        if line:
            if self.granularity!='line':
                for t in sorted({t for i,j,a,b,text in segments for t in (a,b)}-{line.start,line.end}):marker(t,(255,255,0),2,True)
            marker(line.start,(216,0,0),2,feet=2);marker(line.end,(0,0,216),2,feet=1)
        if self.show_keyframes:
            for t in self.keyframes:
                if self.left-6*pp<=t<=self.left+self.span+6*pp:marker(t,(255,0,255))
        # Avoid both needless native text work and off-screen clip rectangles.
        labels=[(a,b,text) for i,j,a,b,text in segments if self.granularity!='line' and b>self.left and a<self.left+self.span]
        return scene,markers,labels

    def paintEvent(self,event):
        self.render_audio();scene,markers,labels=self.scene()
        rgb=self.view_renderer.rgb(scene,self.cache_rgb if self.audio else None,markers,labels)
        image=QImage(rgb.data,scene.width,scene.height,scene.width*3,QImage.Format.Format_RGB888).copy();image.setDevicePixelRatio(self.devicePixelRatioF())
        p=QPainter(self);p.drawImage(0,0,image)
        if not self.audio:
            p.setPen(QColor(130,170,210));p.drawText(QRectF(8,self.audio_top,self.width()-16,self.audio_bottom-self.audio_top),Qt.AlignmentFlag.AlignCenter,'添加媒体后显示原版算法的频谱／波形')
        if self.moving is not None:
            text=f'{self.move_scope_label}：{time_label(self.line.start)} → {time_label(self.line.start+self.move_delta)} · '+('提前' if self.move_delta<0 else '延后')+f' {abs(self.move_delta)/1000:.3f} 秒 · 松开应用，Esc 取消'
            rect=QRectF(5,self.audio_bottom-29,self.width()-10,25);p.fillRect(rect,QColor(12,20,35,225));p.setPen(QColor('#ffffff'));p.drawText(rect.adjusted(5,0,-5,0),Qt.AlignmentFlag.AlignVCenter,text)
        p.end()

    def follow_position(self,value):
        self.position=value
        if self.playing and not self.drag:
            edge=40*self.pixel_ms
            if self.left>0 and value<self.left+edge:self.left=max(0,value-edge);self.invalidate()
            elif self.duration and value>self.left+self.span-edge and self.left+self.span<self.duration:
                self.left=value-self.span+edge;self.invalidate()
        self.update()

    def focusInEvent(self,event):super().focusInEvent(event);self.update()
    def focusOutEvent(self,event):super().focusOutEvent(event);self.update()

    def hit(self,pos):
        if not self.line or not self.audio_top<=pos.y()<=self.audio_bottom:return None
        candidates=[]
        for i,j,a,b,y1,y2 in self.targets():
            for edge,time in enumerate((a,b)):
                distance=abs(self.tx(time)-pos.x())
                if distance<=12:candidates.append((distance,0 if (i,j)==(self.word,self.part) else 1,0 if i>=0 else 1,i,j,edge,a,b))
        return min(candidates) if candidates else None
    def select_at(self,time):
        for i,j,a,b,text in self.segments():
            if time<=b:self.word,self.part=i,j;self.select.emit(i,j);self.cache_key=None;self.update();return a,b
        if self.line:return self.line.start,self.line.end

    def mousePressEvent(self,event):
        self.setFocus();pos=event.position()
        if pos.y()<self.audio_top and event.button()==Qt.MouseButton.LeftButton:self.panning=(pos.x(),self.left);return
        if event.button()==Qt.MouseButton.MiddleButton:self.seek.emit(self.time(pos.x()));return
        if not self.editing_enabled:
            if event.button()==Qt.MouseButton.LeftButton:self.select_at(self.time(pos.x()))
            elif event.button()==Qt.MouseButton.RightButton:
                selected=self.select_at(self.time(pos.x()))
                if selected:self.audition.emit(*selected)
            return
        if self.line and self.audio_top<=pos.y()<=self.audio_bottom and event.button()==Qt.MouseButton.LeftButton and (self.move_mode or event.modifiers()&Qt.KeyboardModifier.AltModifier):
            if self.move_error:self.notice.emit(self.move_error);return
            if self.line.locked or any(u.locked for u in self.line.units):self.notice.emit('本句或词组已锁定，请先解除锁定。');return
            if self.duration and self.line.end-self.line.start>self.duration:self.notice.emit('本句跨度超过素材时长，请先重新设置本句范围。');return
            value=self.time(pos.x());offset=value-self.line.start if self.line.start<=value<=self.line.end else 0
            self.moving=offset;self.drag_x=pos.x();self.drag_modifiers=event.modifiers();self.move_delta=self.move_value(pos.x());self.auto_scroll.start();self.viewChanged.emit();self.update();return
        if self.granularity=='line' and self.line and event.button() in (Qt.MouseButton.LeftButton,Qt.MouseButton.RightButton):
            a,b=self.line.start,self.line.end;value=self.snap(self.time(pos.x()),event.modifiers())
            if event.button()==Qt.MouseButton.LeftButton:a=min(value,(self.line.units[0].end if self.line.units else b)-10)
            else:b=max(value,(self.line.units[-1].start if self.line.units else a)+10)
            edge=0 if event.button()==Qt.MouseButton.LeftButton else 1
            self.drag=(-1,-1,edge,a,b,False);self.ghost=a if edge==0 else b;self.drag_x=pos.x();self.drag_modifiers=event.modifiers();self.auto_scroll.start();return
        if event.button()==Qt.MouseButton.RightButton:
            selected=self.select_at(self.time(pos.x()))
            if selected:self.audition.emit(*selected)
            return
        if event.button()!=Qt.MouseButton.LeftButton:return
        hit=self.hit(pos)
        if hit:
            _,_,_,i,j,edge,a,b=hit;self.drag=(i,j,edge,a,b,bool(event.modifiers()&Qt.KeyboardModifier.ControlModifier));self.word,self.part=i,j;self.drag_x=pos.x();self.drag_modifiers=event.modifiers();self.auto_scroll.start();self.select.emit(i,j);return
        self.select_at(self.time(pos.x()))
    def mouseMoveEvent(self,event):
        if event.buttons()&Qt.MouseButton.MiddleButton:self.seek.emit(self.time(event.position().x()));return
        if self.panning:
            x,left=self.panning;self.left=max(0,round((left-(event.position().x()-x)*self.pixel_ms)/self.pixel_ms)*self.pixel_ms);self.invalidate();return
        if self.moving is not None:
            self.drag_x=event.position().x();self.drag_modifiers=event.modifiers();self.move_delta=self.move_value(self.drag_x);self.viewChanged.emit();self.update();return
        if self.drag:self.drag_x=event.position().x();self.drag_modifiers=event.modifiers();self.ghost=self.snap(self.time(self.drag_x),event.modifiers());self.viewChanged.emit();self.update();return
        self.hover=self.time(event.position().x());self.setCursor(Qt.CursorShape.SizeAllCursor if self.move_mode and event.position().y()>=self.audio_top else Qt.CursorShape.SizeHorCursor if self.hit(event.position()) or event.position().y()<self.audio_top else Qt.CursorShape.ArrowCursor);self.update()
    def leaveEvent(self,event):self.hover=None;self.update()
    def mouseReleaseEvent(self,event):
        self.panning=None;self.auto_scroll.stop();self.drag_x=None
        if self.moving is not None:
            self.drag_modifiers=event.modifiers()
            delta=self.move_value(event.position().x());self.moving=None;self.move_delta=0
            if delta:self.moved.emit(delta)
            self.invalidate();return
        if self.drag:
            i,j,edge,a,b,following=self.drag;value=self.snap(self.time(event.position().x()),event.modifiers())
            final_a,final_b=self.drag_bounds(value);self.drag=None;self.ghost=None
            if following and i>=0:self.shifted.emit(i,j,a if edge==0 else b,value-(a if edge==0 else b))
            else:
                self.boundary.emit(i,j,final_a,final_b)
            self.invalidate()

    def move_value(self,x):
        if self.line is None or self.moving is None:return 0
        start=self.snap(max(0,self.time(x)-self.moving),self.drag_modifiers)
        if self.duration:
            limit=max(0,self.duration-(self.line.end-self.line.start));start=min(start,int(limit/10)*10)
        delta=int(start-self.line.start)
        if self.move_limits is not None:
            lower,upper=self.move_limits;delta=max(lower,delta)
            if upper is not None:delta=min(upper,delta)
        return delta

    def auto_pan(self):
        if self.drag_x is None or (not self.drag and self.moving is None):self.auto_scroll.stop();return
        direction=-1 if self.drag_x<24 else 1 if self.drag_x>self.width()-24 else 0
        if not direction:return
        old=self.left;self.left=max(0,self.left+direction*self.span*.025)
        if self.duration:self.left=min(self.left,max(0,self.duration-self.span))
        if self.left==old:return
        if self.moving is not None:self.move_delta=self.move_value(self.drag_x)
        else:self.ghost=self.snap(self.time(self.drag_x),self.drag_modifiers)
        self.invalidate()

    def cancel_drag(self):
        self.auto_scroll.stop();self.drag=None;self.ghost=None;self.panning=None;self.moving=None;self.move_delta=0;self.drag_x=None;self.cache_key=None;self.viewChanged.emit();self.update()

    def hideEvent(self,event):self.cancel_drag();super().hideEvent(event)
    def mouseDoubleClickEvent(self,event):
        selected=self.select_at(self.time(event.position().x()))
        if selected:self.audition.emit(*selected)
    def wheelEvent(self,event):
        step=1 if event.angleDelta().y()>0 else -1
        if event.modifiers()&Qt.KeyboardModifier.ControlModifier:self.set_zoom(self.zoom_level+step,event.position().x())
        else:self.left=max(0,self.left-step*self.span*.15);self.left=round(self.left/self.pixel_ms)*self.pixel_ms;self.invalidate()
        event.accept()

    def keyPressEvent(self,event):
        from .aeg_hotkeys import command
        handler=getattr(self,'audio_key_handler',None)
        name=handler(event,audio=True) if handler is not None else command(event,audio=True,medusa=self.medusa_hotkeys)
        if name:self.action.emit(name);event.accept()
        else:super().keyPressEvent(event)
