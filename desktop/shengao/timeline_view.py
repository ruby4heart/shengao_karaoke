"""Original wx/GDI timeline drawing, in memory, inside the Qt application.

No wx windows or Aegisub documents/controllers are created. Qt owns all input.
"""
import ctypes as C
from functools import lru_cache
import numpy as np
from .paths import RUNTIME

class Marker(C.Structure):
    _fields_=[(n,C.c_int) for n in ['time','width','red','green','blue','alpha','thickness','dotted','feet']]

class Label(C.Structure):
    _fields_=[('start',C.c_int),('end',C.c_int),('text',C.c_char_p)]

class Scene(C.Structure):
    _fields_=[(n,C.c_int) for n in ['width','height','duration','start_pixel','scheme','focused','selection_start','selection_end','cursor_pixel']]+[('pixel_ms',C.c_double),('dpr',C.c_double),('cursor_label',C.c_char_p)]

class TimelineRenderer:
    def __init__(self,path=None):
        self.dll=C.CDLL(str(path or RUNTIME/'shengao-view.dll'))
        self.dll.sg_view_top.argtypes=[C.c_double];self.dll.sg_view_top.restype=C.c_int
        self.dll.sg_view_render.argtypes=[C.POINTER(Scene),C.c_void_p,C.c_int,C.POINTER(Marker),C.c_int,C.POINTER(Label),C.c_int,C.c_void_p];self.dll.sg_view_render.restype=C.c_int

    @lru_cache(maxsize=16)
    def top(self,dpr=1.):
        value=self.dll.sg_view_top(dpr)
        if value<1:raise ValueError('时间轴字体初始化失败')
        return value

    def rgb(self,scene,body,markers=(),labels=()):
        height=scene.height-self.top(scene.dpr)-15
        if body is not None:
            body=np.ascontiguousarray(body,dtype=np.uint8)
            if body.shape!=(height,scene.width,3):raise ValueError('时间轴底图尺寸不匹配')
        out=np.empty((scene.height,scene.width,3),np.uint8)
        # Hold UTF-8 buffers until the native call returns.
        texts=[text.encode('utf-8') for a,b,text in labels]
        native_labels=(Label*len(labels))(*[Label(a,b,text) for (a,b,_),text in zip(labels,texts)])
        native_markers=(Marker*len(markers))(*[Marker(*m) for m in markers])
        if not self.dll.sg_view_render(C.byref(scene),body.ctypes.data if body is not None else None,height,native_markers,len(markers),native_labels,len(labels),out.ctypes.data):raise ValueError('原版时间轴绘图失败')
        return out

def cursor_label(ms):
    # agi::Time::GetAssFormatted uses centiseconds.
    cs=(max(0,int(ms))+5)//10
    return f'{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'
