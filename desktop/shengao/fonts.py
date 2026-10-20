"""Font files, exact glyph coverage and metrics shared by export and UI."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os
import re
import unicodedata
from PIL import ImageFont
from fontTools.ttLib import TTFont, TTCollection
from .paths import ASSETS

@dataclass(frozen=True)
class FontInfo:
    family:str
    path:str
    kind:str='本机字体'
    index:int=0

def bundled_fonts():
    root=ASSETS/'fonts'
    return [FontInfo('Noto Sans CJK JP',str(root/'NotoSansCJKjp-Regular.otf'),'清晰黑体'),
            FontInfo('Noto Serif CJK JP',str(root/'NotoSerifCJKjp-Regular.otf'),'明朝风格'),
            FontInfo('BIZ UDPGothic',str(root/'BIZUDPGothic-Bold.ttf'),'高可读粗黑体'),
            FontInfo('Noto Serif CJK JP Black',str(root/'NotoSerifCJKjp-Black.otf'),'特粗明朝')]

@lru_cache(maxsize=192)
def font_weight(path,family=''):
    font=TTFont(path,fontNumber=face_index(str(path),family),lazy=True)
    try:return max(100,min(1000,int(font['OS/2'].usWeightClass))) if 'OS/2' in font else 400
    finally:font.close()

@lru_cache(maxsize=96)
def inspect_font(path,index=0):
    font=TTFont(path,fontNumber=index,lazy=True)
    def name(number):
        records=[n for n in font['name'].names if n.nameID==number]
        records.sort(key=lambda n:(n.platformID!=3,n.langID not in (0x409,0)))
        return next((x.toUnicode() for x in records),'')
    family=name(16) or name(1)
    coverage=frozenset(font.getBestCmap() or {})
    font.close();return family,coverage

def missing(path,text,family=''):
    _,coverage=inspect_font(str(path),face_index(str(path),family))
    return ''.join(dict.fromkeys(c for c in text if not c.isspace() and ord(c) not in coverage))

@lru_cache(maxsize=96)
def traits(path,family=''):
    font=TTFont(path,fontNumber=face_index(str(path),family),lazy=True)
    os2=font.get('OS/2');post=font.get('post')
    bold=bool(os2 and os2.usWeightClass>=600)
    italic=bool((os2 and os2.fsSelection&1) or (post and post.italicAngle))
    font.close();return bold,italic

@lru_cache(maxsize=48)
def metric_font(path,size,family=''):
    # ASS font sizes describe Win ascent + descent, not the em size Pillow uses.
    # Match libass 0.17.5 set_font_metrics / FT_SIZE_REQUEST_TYPE_REAL_DIM.
    # Pillow rounds CJK advances at small fractional sizes. Measure at a large
    # em and scale advances instead, avoiding accumulated gaps over long lines.
    font=ImageFont.truetype(str(path),1024,index=face_index(str(path),family))
    return AssMetrics(font,size*ass_em_scale(str(path),family)/1024)

@dataclass(frozen=True)
class AssMetrics:
    font:object
    scale:float
    def getlength(self,text):return self.font.getlength(text)*self.scale

@lru_cache(maxsize=96)
def ass_em_scale(path,family=''):
    font=TTFont(path,fontNumber=face_index(str(path),family),lazy=True)
    try:
        os2=font.get('OS/2');hhea=font.get('hhea');head=font['head']
        signed=lambda value:value-65536 if value>=32768 else value
        height=signed(os2.usWinAscent)+signed(os2.usWinDescent) if os2 else 0
        if not height:
            height=(os2.sTypoAscender-os2.sTypoDescender if os2 and os2.fsSelection&128 else hhea.ascent-hhea.descent if hhea else 0)
        if not height:height=(os2.sTypoAscender-os2.sTypoDescender if os2 else 0) or head.yMax-head.yMin
        return head.unitsPerEm/max(1,height)
    finally:font.close()

def resolve_font(path='',family=''):
    if path and Path(path).is_file():return Path(path)
    found=find_font(family)
    if found:return found
    default=Path(bundled_fonts()[0].path)
    if default.is_file():return default
    raise ValueError('默认字体资源缺失，请完整解压软件')

def key(name):return unicodedata.normalize('NFKC',name).strip().casefold()

@lru_cache(maxsize=1)
def system_fonts():
    result={}
    if os.name!='nt':return result
    import winreg
    system=Path(os.getenv('WINDIR','C:/Windows'))/'Fonts'
    for registry in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(registry,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as entry:
                for index in range(winreg.QueryInfoKey(entry)[1]):
                    name,value,_=winreg.EnumValue(entry,index)
                    if not isinstance(value,str):continue
                    path=Path(os.path.expandvars(value));path=path if path.is_absolute() else system/path
                    if not path.is_file():continue
                    name=re.sub(r'\s*\([^)]*\)\s*$','',name)
                    for family in name.split(' & '):result[key(family)]=path
        except OSError:continue
    return result

def find_font(family):
    for font in bundled_fonts():
        if key(family)==key(font.family) and Path(font.path).is_file():return Path(font.path)
    system=Path(os.getenv('WINDIR','C:/Windows'))/'Fonts'
    known={'Meiryo':'meiryo.ttc','Yu Gothic':'YuGothM.ttc','Microsoft YaHei':'msyh.ttc',
           'MS Gothic':'msgothic.ttc','MS PGothic':'msgothic.ttc','MS UI Gothic':'msgothic.ttc',
           'ＭＳ ゴシック':'msgothic.ttc','ＭＳ 明朝':'msmincho.ttc'}
    if family in known and (system/known[family]).is_file():return system/known[family]
    return system_fonts().get(key(family))

def families_in_file(path):
    with Path(path).open('rb') as stream:collection=stream.read(4)==b'ttcf'
    owner=TTCollection(path,lazy=True) if collection else TTFont(path,lazy=True);result=set()
    try:
        for font in owner.fonts if collection else [owner]:
            result.update(n.toUnicode() for n in font['name'].names if n.nameID in (1,4,16))
    finally:owner.close()
    return result

@lru_cache(maxsize=96)
def face_names(path):
    """Keep a collection's face identity through metrics, export and coverage."""
    with Path(path).open('rb') as stream:collection=stream.read(4)==b'ttcf'
    owner=TTCollection(path,lazy=True) if collection else TTFont(path,lazy=True)
    fonts=owner.fonts if collection else [owner]
    result=[]
    try:
        for index,font in enumerate(fonts):
            names=frozenset(key(n.toUnicode()) for n in font['name'].names if n.nameID in (1,4,16))
            result.append(names)
    finally:owner.close()
    return tuple(result)

@lru_cache(maxsize=192)
def face_index(path,family=''):
    wanted=key(family)
    return next((i for i,names in enumerate(face_names(path)) if wanted in names),0)

@lru_cache(maxsize=192)
def face_family(path,index=0):
    # libass' private FreeType font provider indexes the legacy family (name 1).
    # Black CJK faces may share typographic family 16 with Regular, while
    # exposing "... Black" as family 1. Export the actual face identity so
    # mixed libraries and FFmpeg choose the same font measured by Pillow.
    font=TTFont(path,fontNumber=index,lazy=True)
    try:
        records=[n for n in font['name'].names if n.nameID==1]
        records.sort(key=lambda n:(n.platformID!=3,n.langID not in (0x409,0)))
        return next((n.toUnicode() for n in records),inspect_font(str(path),index)[0])
    finally:font.close()

def family_name(path,family=''):return face_family(str(path),face_index(str(path),family))

def fonts_in_file(path):
    result=[];seen=set()
    for index,names in enumerate(face_names(str(path))):
        family=face_family(str(path),index)
        if key(family) not in seen:result.append(FontInfo(family,str(path),'本地字体',index));seen.add(key(family))
    return result

def recommend(text,extra=()):
    candidates=bundled_fonts()+list(extra)
    return sorted([(font,missing(font.path,text,font.family)) for font in candidates],key=lambda x:(bool(x[1]),len(x[1])))

_qt_fonts={}
def register_qt_fonts(extra=()):
    from PySide6.QtGui import QFontDatabase
    for font in bundled_fonts()+list(extra):
        path=Path(font.path)
        if path.is_file():
            stat=path.stat();identity=(str(path.resolve()),stat.st_size,stat.st_mtime_ns)
            registered=_qt_fonts.get(identity)
            if registered is not None and QFontDatabase.applicationFontFamilies(registered):continue
            value=QFontDatabase.addApplicationFont(str(path))
            if value>=0:_qt_fonts[identity]=value
