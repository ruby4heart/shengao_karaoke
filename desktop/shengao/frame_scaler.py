"""Bounded GPU downscaling before readback; ordinary Qt remains the fallback.

The controlled sink owns precisely the supplied frame. It is independent of
the player's live sink, so a newer decoded frame cannot replace its pixels
while the associated timestamps are being recorded by VideoCanvas.
"""
from PySide6.QtCore import QSize,QUrl,QObject,Qt,QRect
from PySide6.QtGui import QGuiApplication,QImage,QColor
from PySide6.QtMultimedia import QVideoFrame
from .paths import ASSETS


def preview_size(frame,width,height,ratio=1.):
    factor=min(1.,max(64,width)*ratio/frame.width(),max(64,height)*ratio/frame.height())
    return QSize(max(16,round(frame.width()*factor)),max(16,round(frame.height()*factor)))


def eligible(frame,size):
    if QGuiApplication.platformName()!='windows' or not frame.isValid():return False
    if max(size.width(),size.height())>1920:return False
    if frame.width()*frame.height()<1920*1080 or size.width()*size.height()*2>=frame.width()*frame.height():return False
    surface=frame.surfaceFormat()
    # Keep unverified HDR, colour metadata and transformations on the original
    # path. The acceleration never changes which formats the app can display.
    return (frame.pixelFormat().name in ('Format_NV12','Format_YUV420P','Format_YV12')
        and surface.colorSpace().name=='ColorSpace_BT709'
        and surface.colorRange().name=='ColorRange_Video'
        and surface.colorTransfer().name=='ColorTransfer_BT709'
        and not surface.rotation().value and not surface.isMirrored()
        and surface.scanLineDirection().name=='TopToBottom'
        and surface.viewport()==QRect(0,0,frame.width(),frame.height())
        and not frame.rotation().value and not frame.mirrored())


class GpuFrameScaler:
    def __init__(self):
        self.view=None;self.sink=None;self.closed=False;self.backend='';self.frames=0;self.error=''

    def _initialize(self):
        from PySide6.QtQuickWidgets import QQuickWidget
        view=QQuickWidget();self.view=view
        view.setWindowFlags(Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint)
        view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen,True)
        view.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,True)
        view.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose,False)
        view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView);view.resize(64,64)
        view.setSource(QUrl.fromLocalFile(str(ASSETS/'preview-scale.qml')))
        if view.status()!=QQuickWidget.Status.Ready:raise ValueError('GPU preview component unavailable')
        self.sink=view.rootObject().findChild(QObject,'frameOutput').property('videoSink')
        view.show()
        # A real RGB probe rejects an unavailable/blank render backend before
        # any user frame is accepted. This window never appears on screen.
        probe=QImage(8,8,QImage.Format.Format_ARGB32);probe.fill(QColor(231,19,173))
        self.sink.setVideoFrame(QVideoFrame(probe));result=view.grabFramebuffer()
        self.backend=view.quickWindow().rendererInterface().graphicsApi().name
        if result.isNull() or self.backend in ('Software','Null','Unknown'):raise ValueError('GPU preview backend unavailable')
        if any(result.pixelColor(x,y).rgb()!=QColor(231,19,173).rgb() for x,y in ((2,2),(result.width()//2,result.height()//2),(result.width()-3,result.height()-3))):raise ValueError('GPU preview probe did not render')
        self.sink.setVideoFrame(QVideoFrame())

    def convert(self,frame,size):
        if self.closed or self.error or not eligible(frame,size):return None
        try:
            if self.view is None:self._initialize()
            ratio=self.view.devicePixelRatioF()
            self.view.resize(max(16,round(size.width()/ratio)),max(16,round(size.height()/ratio)))
            self.sink.setVideoFrame(frame)
            image=self.view.grabFramebuffer()
            if image.isNull() or max(image.width(),image.height())>1922:raise ValueError('GPU preview image unavailable or exceeds budget')
            image.setDevicePixelRatio(1.);self.frames+=1;return image
        except (ImportError,ValueError,RuntimeError,OSError,AttributeError) as error:
            self.error=str(error);self.close();return None

    def clear(self):
        if not self.closed and self.sink is not None:self.sink.setVideoFrame(QVideoFrame())

    def close(self,*_):
        if self.closed:return
        self.clear();self.closed=True
        if self.view is not None:
            self.view.close();self.view.deleteLater()
        self.sink=None;self.view=None

    def status(self):return {'backend':self.backend,'frames':self.frames,'error':self.error,'closed':self.closed}
