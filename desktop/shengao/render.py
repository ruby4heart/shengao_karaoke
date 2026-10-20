"""Live ASS renderer, using exactly the libass dependency linked into FFmpeg."""
import ctypes
import hashlib
from pathlib import Path
from .paths import renderer,ASSETS

class AssRenderer:
    def __init__(self,fonts=None):
        self.dll=ctypes.CDLL(renderer());self.closed=False
        self.dll.sg_create.argtypes=[ctypes.c_char_p];self.dll.sg_create.restype=ctypes.c_void_p
        self.dll.sg_set.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int];self.dll.sg_set.restype=ctypes.c_int
        self.dll.sg_render.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int64,ctypes.c_void_p];self.dll.sg_render.restype=ctypes.c_int
        self.dll.sg_destroy.argtypes=[ctypes.c_void_p]
        self.dll.sg_add_font.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int]
        self.handle=self.dll.sg_create(str(fonts or ASSETS/'fonts').encode('utf-8'))
        if not self.handle:raise ValueError('无法初始化字幕渲染器')
        self.text='';self.buffer=None;self.size=None
        self.loaded_fonts=set();self.loaded_font_hashes=set()
        self.add_fonts(list((fonts or ASSETS/'fonts').glob('*.otf'))+list((fonts or ASSETS/'fonts').glob('*.ttf')))

    def add_fonts(self,paths):
        for path in paths:
            path=Path(path)
            if not path.is_file() or str(path.resolve()) in self.loaded_fonts:continue
            data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
            if digest not in self.loaded_font_hashes:
                self.dll.sg_add_font(self.handle,(digest[:12]+path.suffix).encode('utf-8'),data,len(data));self.loaded_font_hashes.add(digest)
            self.loaded_fonts.add(str(path.resolve()))

    def set_text(self,text):
        if self.closed:raise ValueError('字幕渲染器已关闭')
        if text==self.text:return
        data=text.encode('utf-8')
        if not self.dll.sg_set(self.handle,data,len(data)):raise ValueError('字幕格式无效，无法预览')
        self.text=text

    def rgba(self,width,height,time):
        if not self.handle:return bytes(width*height*4)
        if self.size!=(width,height):self.buffer=ctypes.create_string_buffer(width*height*4);self.size=(width,height)
        if not self.dll.sg_render(self.handle,width,height,int(time),self.buffer):raise ValueError('字幕渲染失败')
        return self.buffer.raw

    def image(self,width,height,time):
        from PySide6.QtGui import QImage
        data=self.rgba(width,height,time)
        return QImage(data,width,height,width*4,QImage.Format.Format_RGBA8888).copy()

    def close(self):
        if not self.closed:
            handle=self.handle;self.handle=None;self.closed=True;self.text='';self.buffer=None;self.size=None
            self.dll.sg_destroy(handle)

    def __del__(self):
        if hasattr(self,'handle'):self.close()
