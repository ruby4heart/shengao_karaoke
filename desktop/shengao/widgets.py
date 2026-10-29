"""Small native Qt controls for a clear, compact production workspace."""
from decimal import Decimal,InvalidOperation
import re
from pathlib import Path
from PySide6.QtCore import Qt,QSize,QRectF,QPointF,Signal
from PySide6.QtGui import QPainter,QPen,QColor,QIcon,QPixmap,QFont,QValidator
from PySide6.QtWidgets import (QWidget,QPushButton,QToolButton,QVBoxLayout,QHBoxLayout,
    QLabel,QSpinBox,QSizePolicy,QFrame,QListWidget,QListWidgetItem,QStyledItemDelegate,QStyle)

def time_text(ms):
    ms=max(0,int(ms));seconds,rest=divmod(ms,1000);minutes,seconds=divmod(seconds,60);hours,minutes=divmod(minutes,60)
    return (f'{hours}:{minutes:02}:' if hours else f'{minutes:02}:')+f'{seconds:02}.{rest:03}'

def parse_time(text):
    value=text.strip().lower().replace('：',':').replace('，','.').replace(',','.')
    try:
        if value.endswith('ms'):return int(Decimal(value[:-2].strip()))
        pieces=value.split(':')
        if not 1<=len(pieces)<=3 or any(not p for p in pieces):raise ValueError('请输入分:秒.毫秒')
        seconds=Decimal(pieces[-1]);minutes=int(pieces[-2]) if len(pieces)>1 else 0;hours=int(pieces[-3]) if len(pieces)>2 else 0
        if seconds<0 or minutes<0 or hours<0 or (len(pieces)>1 and seconds>=60) or (len(pieces)>2 and minutes>=60):raise ValueError('时间格式无效')
        return int((seconds+minutes*60+hours*3600)*1000)
    except (InvalidOperation,OverflowError) as error:raise ValueError('时间格式无效') from error

class TimeEdit(QSpinBox):
    def __init__(self,parent=None):
        super().__init__(parent);self.setRange(0,2147480000);self.setSingleStep(10);self.setMinimumWidth(105)
        self.setToolTip('分:秒.毫秒，例如 01:23.450；也可输入 83.45 秒或 83450ms。上下键每次调整 10 毫秒。')
        self.setKeyboardTracking(False)
    def textFromValue(self,value):return time_text(value)
    def minimumSizeHint(self):return QSize(105,super().minimumSizeHint().height())
    def sizeHint(self):return QSize(128,super().sizeHint().height())
    def valueFromText(self,text):
        try:return parse_time(text)
        except ValueError:return self.value()
    def validate(self,text,pos):
        try:
            value=parse_time(text)
            state=QValidator.State.Acceptable if self.minimum()<=value<=self.maximum() else QValidator.State.Invalid
        except ValueError:state=QValidator.State.Intermediate if re.fullmatch(r'[0-9:.,：\s]*m?s?',text) else QValidator.State.Invalid
        return state,text,pos
    def fixup(self,text):return self.textFromValue(self.valueFromText(text))

def icon(name,color='#64748b',size=20):
    pix=QPixmap(size*2,size*2);pix.fill(Qt.GlobalColor.transparent);p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.scale(size/12,size/12)
    p.setPen(QPen(QColor(color),1.7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.setBrush(Qt.BrushStyle.NoBrush)
    def line(a,b,c,d):p.drawLine(QPointF(a,b),QPointF(c,d))
    if name=='folder':
        p.drawRoundedRect(QRectF(2,6,20,15),2,2);line(3,6,3,3);line(3,3,10,3);line(10,3,13,6)
    elif name=='save':
        p.drawRoundedRect(QRectF(3,3,18,18),2,2);p.drawRect(QRectF(7,3,9,6));p.drawRect(QRectF(7,14,10,7))
    elif name in ('undo','redo'):
        if name=='redo':p.translate(24,0);p.scale(-1,1)
        line(8,4,3,9);line(3,9,8,14);line(3,9,15,9);p.drawArc(QRectF(9,9,12,12),0,180*16)
    elif name=='play':line(8,4,20,12);line(20,12,8,20);line(8,20,8,4)
    elif name=='pause':line(8,5,8,19);line(16,5,16,19)
    elif name=='check':line(4,12,9,17);line(9,17,20,6)
    elif name=='plus':line(12,4,12,20);line(4,12,20,12)
    elif name=='settings':
        for y,x in [(6,8),(12,16),(18,10)]:line(3,y,21,y);p.drawEllipse(QPointF(x,y),2,2)
    elif name=='eye':p.drawEllipse(QRectF(2,6,20,12));p.drawEllipse(QPointF(12,12),3,3)
    elif name=='arrow':line(4,12,20,12);line(14,6,20,12);line(14,18,20,12)
    elif name=='music':line(9,18,9,5);line(9,5,20,3);line(20,3,20,16);p.drawEllipse(QRectF(3,16,6,5));p.drawEllipse(QRectF(14,14,6,5))
    else:
        for x,height in [(4,6),(8,14),(12,20),(16,12),(20,5)]:line(x,12-height/2,x,12+height/2)
    p.end();pix.setDevicePixelRatio(2);return QIcon(pix)

class StepButton(QPushButton):
    captions=['导入视频和歌词','离线生成或联网对齐','分词、假名和时间','选字体与接唱效果','先看样片，再导出']
    def __init__(self,index,title,parent=None):
        super().__init__(parent);self.setObjectName('workflowStep');self.index=index;self.title=title;self.complete=False;self.setCheckable(True);self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f'第 {index+1} 步 {title}');self.setToolTip(self.captions[index]);self.setMinimumHeight(62);self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
    def sizeHint(self):return QSize(145,62)
    def set_complete(self,value):self.complete=value;self.update()
    def set_status(self,state,caption):
        self.workflow_status=state;self.status_caption=caption;self.complete=state=='done'
        self.setToolTip(caption);self.setAccessibleDescription(caption);self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);active=self.isChecked();r=self.rect().adjusted(1,1,-1,-1)
        p.setBrush(QColor('#eef0ff' if active else '#ffffff'));p.setPen(QPen(QColor('#a7aff5' if active else '#e4e8f0'),1));p.drawRoundedRect(r,10,10)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#5263e8' if active else '#e5f4ee' if self.complete else '#f0f3f8'));p.drawEllipse(QRectF(12,18,26,26))
        p.setPen(QColor('#ffffff' if active else '#248264' if self.complete else '#64748b'));p.setFont(QFont('Microsoft YaHei UI',10,QFont.Weight.DemiBold));p.drawText(QRectF(12,18,26,26),Qt.AlignmentFlag.AlignCenter,'✓' if self.complete and not active else str(self.index+1))
        p.setPen(QColor('#3544b5' if active else '#25344b'));p.setFont(QFont('Microsoft YaHei UI',10,QFont.Weight.DemiBold));p.drawText(48,26,self.title)
        p.setPen(QColor('#77859a'));p.setFont(QFont('Microsoft YaHei UI',8));fm=p.fontMetrics();p.drawText(48,45,fm.elidedText(getattr(self,'status_caption',self.captions[self.index]),Qt.TextElideMode.ElideRight,max(1,self.width()-58)));p.end()

class Collapsible(QWidget):
    def __init__(self,title,parent=None):
        super().__init__(parent);layout=QVBoxLayout(self);layout.setContentsMargins(0,4,0,4);layout.setSpacing(8)
        self.toggle=QToolButton();self.toggle.setObjectName('disclosure');self.toggle.setText(title);self.toggle.setCheckable(True);self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon);self.toggle.setArrowType(Qt.ArrowType.RightArrow);self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed);layout.addWidget(self.toggle)
        self.content=QWidget();self.body=QVBoxLayout(self.content);self.body.setContentsMargins(0,0,0,0);self.body.setSpacing(8);layout.addWidget(self.content);self.content.hide();self.toggle.toggled.connect(self.expand)
    def expand(self,on):self.content.setVisible(on);self.toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

class WelcomePane(QWidget):
    openProject=Signal(str)
    def __init__(self,add_media,paste_lyrics,open_project,demo,parent=None):
        super().__init__(parent);self.setObjectName('welcome');l=QVBoxLayout(self);l.setContentsMargins(36,28,36,28);l.setSpacing(14)
        l.addStretch(1);eyebrow=QLabel('从一首歌开始');eyebrow.setObjectName('eyebrow');l.addWidget(eyebrow)
        title=QLabel('让每个字，跟上歌声');title.setObjectName('welcomeTitle');l.addWidget(title)
        subtitle=QLabel('拖入视频或音频，有原歌词就粘贴；没有也能先识别并核对。\n生成初稿后，边听边校准，最后导出字幕或视频。');subtitle.setObjectName('welcomeSubtitle');subtitle.setWordWrap(True);l.addWidget(subtitle)
        row=QHBoxLayout()
        for text,kind,fn,primary in [('添加视频或音频','plus',add_media,True),('打开已有作品','folder',open_project,False)]:
            b=QPushButton(text);b.setIcon(icon(kind,'#ffffff' if primary else '#64748b'));b.setMinimumHeight(38);b.clicked.connect(fn);b.setObjectName('primary' if primary else 'secondary');row.addWidget(b)
        row.addStretch();l.addLayout(row)
        row=QHBoxLayout()
        for text,fn in [('先粘贴歌词',paste_lyrics),('用示例练习一下',demo)]:b=QPushButton(text);b.setObjectName('textButton');b.clicked.connect(fn);row.addWidget(b)
        row.addStretch();l.addLayout(row);l.addStretch(1)
        heading=QLabel('最近打开');heading.setObjectName('sectionTitle');l.addWidget(heading)
        self.recent=QListWidget();self.recent.setObjectName('recentList');self.recent.setMaximumHeight(180);self.recent.setMinimumHeight(70);self.recent.itemActivated.connect(lambda item:self.openProject.emit(item.data(Qt.ItemDataRole.UserRole)) if item.data(Qt.ItemDataRole.UserRole) else None);self.recent.itemClicked.connect(lambda item:self.openProject.emit(item.data(Qt.ItemDataRole.UserRole)) if item.data(Qt.ItemDataRole.UserRole) else None);l.addWidget(self.recent)
        note=QLabel('本地编辑、预览和视频导出无需联网；调用云端服务前由你决定。');note.setObjectName('muted');note.setWordWrap(True);l.addWidget(note);l.addStretch(1)
    def set_recent(self,values):
        self.recent.clear()
        for value in values[:4]:
            path=Path(value['path']);item=QListWidgetItem(value['title']+'\n'+str(path));item.setData(Qt.ItemDataRole.UserRole,str(path));item.setToolTip(str(path));item.setSizeHint(QSize(200,48));self.recent.addItem(item)
        if not values:
            item=QListWidgetItem('还没有最近作品。保存第一份作品后，它会出现在这里。');item.setFlags(Qt.ItemFlag.NoItemFlags);self.recent.addItem(item)

class LyricDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):return QSize(180,72)
    def paint(self,painter,option,index):
        painter.save();painter.setRenderHint(QPainter.RenderHint.Antialiasing);selected=bool(option.state&QStyle.StateFlag.State_Selected);r=QRectF(option.rect.adjusted(3,3,-3,-3));painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor('#eef0ff' if selected else '#ffffff'));painter.drawRoundedRect(r,8,8)
        if selected:painter.setBrush(QColor('#5966e8'));painter.drawRoundedRect(QRectF(r.left(),r.top()+10,3,r.height()-20),1.5,1.5)
        text=index.data(Qt.ItemDataRole.DisplayRole) or '';first,_,lyric=text.partition('\n');painter.setFont(QFont('Microsoft YaHei UI',8));painter.setPen(QColor('#6c7c93'));painter.drawText(QRectF(r.left()+12,r.top()+8,r.width()-24,20),Qt.AlignmentFlag.AlignLeft,first)
        painter.setFont(QFont('Microsoft YaHei UI',10,QFont.Weight.DemiBold if selected else QFont.Weight.Normal));painter.setPen(QColor('#27364e'));fm=painter.fontMetrics();painter.drawText(QRectF(r.left()+12,r.top()+31,r.width()-24,24),Qt.AlignmentFlag.AlignLeft,fm.elidedText(lyric.replace('\n',' '),Qt.TextElideMode.ElideRight,int(r.width()-24)));painter.restore()
