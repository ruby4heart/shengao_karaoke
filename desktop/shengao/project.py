"""Versioned source-of-truth document, independent of any editor toolkit."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
import base64
import copy
import json
import shutil
import uuid
import time
import math

from studio_backend.model import LyricLine, identifier
from studio_backend.settings import atomic_json

from .media_versions import MediaVersion,ROLES

SCHEMA=9

@dataclass
class Style:
    name:str='清晰通用'
    font:str='Noto Sans CJK JP'
    font_file:str=''
    ruby_font:str='Noto Sans CJK JP'
    ruby_font_file:str=''
    translation_font:str='Noto Sans CJK JP'
    translation_font_file:str=''
    size:int=62
    ruby_size:int=28
    romaji_size:int=30
    translation_size:int=32
    color:str='#ffffff'
    highlight:str='#73e8bb'
    outline_color:str='#15202d'
    outline:float=2.5
    shadow:float=1
    bottom:int=72
    show_ruby:bool=True
    show_romaji:bool=True
    show_translation:bool=True
    position:str='bottom'
    display_mode:str='single'
    preview_percent:int=50
    preview_lead_ms:int=3000
    previous_hold_ms:int=3000
    glow:float=0

    def validate(self):
        for name in ('name','font','font_file','ruby_font','ruby_font_file','translation_font','translation_font_file'):
            if not isinstance(getattr(self,name),str):raise ValueError('字体或样式名称格式无效')
        for name in ('size','ruby_size','romaji_size','translation_size'):
            if type(getattr(self,name)) is not int or not 8<=getattr(self,name)<=180: raise ValueError('字体大小应在 8 至 180 之间')
        for name in ('color','highlight','outline_color'):
            text=getattr(self,name)
            if not isinstance(text,str) or len(text)!=7 or text[0]!='#': raise ValueError('颜色格式无效')
            int(text[1:],16)
        if any(isinstance(getattr(self,n),bool) or not isinstance(getattr(self,n),(int,float)) or not math.isfinite(getattr(self,n)) for n in ('outline','shadow','bottom')):raise ValueError('样式边距或描边无效')
        if not 0<=self.outline<=12 or not 0<=self.shadow<=12 or not 0<=self.bottom<=400:
            raise ValueError('样式边距或描边超出范围')
        if self.position not in {'top','center','bottom'}:raise ValueError('字幕位置选项无效')
        if self.display_mode not in {'single','alternating'}:raise ValueError('字幕接唱方式无效')
        for name,minimum,maximum in [('preview_percent',10,90),('preview_lead_ms',0,15000),('previous_hold_ms',0,15000)]:
            value=getattr(self,name)
            if type(value) is not int or not minimum<=value<=maximum:raise ValueError('接唱显示时间超出范围')
        if isinstance(self.glow,bool) or not isinstance(self.glow,(int,float)) or not math.isfinite(self.glow) or not 0<=self.glow<=12:raise ValueError('光晕范围无效')

@dataclass
class Project:
    title:str='未命名作品'
    uid:str=field(default_factory=identifier)
    media:str=''
    media_stamp:dict=field(default_factory=dict)
    transcript_stamp:dict=field(default_factory=dict)
    media_versions:dict=field(default_factory=dict)
    media_role:str='original'
    duration:int=0
    has_video:bool|None=None
    width:int=1920
    height:int=1080
    fps:float=25
    lines:list=field(default_factory=list)
    style:Style=field(default_factory=Style)
    font_assets:dict=field(default_factory=dict)
    checks:dict=field(default_factory=dict)
    transcript:list=field(default_factory=list)
    transcript_fingerprint:str=''
    recognition_draft:dict=field(default_factory=dict)
    vocal_track:dict=field(default_factory=dict)
    source_ass:str=''
    source_ass_active:bool=False
    source_path:str=''
    ass_rows:list=field(default_factory=list)
    tasks:list=field(default_factory=list)
    note:str=''

    def validate(self):
        if any(not isinstance(getattr(self,name),str) for name in ('title','uid','media','source_ass','source_path','note')):raise ValueError('工程名称、素材路径或原字幕格式无效')
        if not isinstance(self.lines,list) or not isinstance(self.checks,dict) or not isinstance(self.transcript,list):raise ValueError('工程的歌词或审核资料无效')
        import re
        if not isinstance(self.transcript_fingerprint,str) or self.transcript_fingerprint and not re.fullmatch('[a-f0-9]{64}',self.transcript_fingerprint):raise ValueError('转录素材指纹无效')
        if not isinstance(self.recognition_draft,dict):raise ValueError('识别原文草稿无效')
        from .vocal_audio import valid_track
        valid_track(self.vocal_track)
        if self.recognition_draft:
            from studio_backend.recognition import validate
            validate(self.recognition_draft,self.transcript)
            if self.recognition_draft['media_stamp']!=self.transcript_stamp:raise ValueError('识别原文草稿和原始转录的素材记录不一致')
            if self.recognition_draft.get('media_fingerprint','')!=self.transcript_fingerprint:raise ValueError('识别原文草稿和原始转录的素材指纹不一致')
        if not isinstance(self.font_assets,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in self.font_assets.items()):raise ValueError('字体资源列表无效')
        if type(self.duration) is not int or self.duration<0:raise ValueError('媒体时长无效')
        if self.has_video is not None and type(self.has_video) is not bool:raise ValueError('媒体类型无效')
        if type(self.width) is not int or type(self.height) is not int:raise ValueError('视频尺寸无效')
        if isinstance(self.fps,bool) or not isinstance(self.fps,(int,float)) or not math.isfinite(self.fps):raise ValueError('视频帧率无效')
        if len(self.lines)>100000: raise ValueError('歌词行数过多')
        ids=set()
        for line in self.lines:
            line.validate()
            if not isinstance(line.id,str):raise ValueError('歌词编号须为文本')
            if line.id in ids: raise ValueError('歌词编号重复')
            ids.add(line.id)
        if not 16<=self.width<=8192 or not 16<=self.height<=8192: raise ValueError('视频尺寸超出范围')
        if not 1<=self.fps<=240: raise ValueError('视频帧率超出范围')
        if not isinstance(self.media_role,str) or self.media_role not in ROLES:raise ValueError('当前视频版本无效')
        if not isinstance(self.media_versions,dict) or any(key not in ROLES or not isinstance(value,MediaVersion) for key,value in self.media_versions.items()):raise ValueError('视频版本列表无效')
        for value in self.media_versions.values():value.validate()
        if self.media_versions:
            import os
            current=self.media_versions.get(self.media_role)
            if not current or os.path.normcase(os.path.abspath(current.path))!=os.path.normcase(os.path.abspath(self.media)):raise ValueError('当前源与视频版本不一致')
        self.style.validate()

    def to_dict(self):
        value=asdict(self)
        value['lines']=[line.to_dict() for line in self.lines]
        value['version']=SCHEMA;value['application']='Shengao Independent Studio'
        return value

    @classmethod
    def from_dict(cls,data,base=None):
        if not isinstance(data,dict): raise ValueError('工程格式无效')
        version=data.get('version',1)
        if version not in (1,2,3,4,5,6,7,8,9): raise ValueError('工程版本较新，请使用对应版本软件')
        fields={k:copy.deepcopy(v) for k,v in data.items() if k in cls.__dataclass_fields__}
        raw_lines=data.get('lines',[])
        if not isinstance(raw_lines,list) or any(not isinstance(x,dict) for x in raw_lines):raise ValueError('歌词列表格式无效')
        if version>=2 and any(not x.get('text') for x in raw_lines):raise ValueError('工程包含缺失或空白的歌词记录')
        fields['lines']=[LyricLine.from_dict({**x,'id':str(x['id'])} if version==1 and 'id' in x else x) for x in raw_lines if x.get('text')]
        fields['style']=Style(**{k:v for k,v in data.get('style',{}).items() if k in Style.__dataclass_fields__})
        fields['media']=data.get('video') or data.get('media','')
        raw_versions=data.get('media_versions',{})
        if not isinstance(raw_versions,dict) or any(not isinstance(value,dict) for value in raw_versions.values()):raise ValueError('视频版本列表无效')
        try:fields['media_versions']={key:MediaVersion(**value) for key,value in raw_versions.items()}
        except TypeError as error:raise ValueError('视频版本记录无效') from error
        project=cls(**fields)
        if base:
            for obj,name in [(project,'media'),(project.style,'font_file'),(project.style,'ruby_font_file'),(project.style,'translation_font_file')]:
                path=getattr(obj,name)
                if path and not Path(path).is_absolute(): setattr(obj,name,str((Path(base)/path).resolve()))
            for value in project.media_versions.values():
                if not Path(value.path).is_absolute():value.path=str((Path(base)/value.path).resolve())
            for name in ('path','source_path'):
                if project.vocal_track.get(name) and not Path(project.vocal_track[name]).is_absolute():project.vocal_track[name]=str((Path(base)/project.vocal_track[name]).resolve())
            project.font_assets={family:str((Path(base)/path).resolve()) if not Path(path).is_absolute() else path for family,path in project.font_assets.items()}
        project.validate()
        return project

    def replace_lyrics(self,text,append=False):
        fragments=[x.rstrip('\r') for x in text.split('\n') if x.strip()]
        if not fragments: raise ValueError('请粘贴歌词，每行一句')
        self.recognition_draft={}
        offset=self.lines[-1].end if append and self.lines else 0
        step=max(100,len(fragments) and (self.duration-offset)//len(fragments)) if self.duration>offset else 5000
        values=[LyricLine(identifier(),text,offset+i*step,offset+(i+1)*step) for i,text in enumerate(fragments)]
        from studio_backend.provenance import create
        for line in values:line.timing_origin=create('estimated',line.start,line.end,method='uniform_lines')
        if append: self.lines.extend(values)
        else: self.lines=values;self.checks={}
        self.source_ass_active=False

    def summary(self):
        return {'lines':len(self.lines),'timing':sum(x.reviewed for x in self.lines),
                'readings':sum(bool(self.checks.get(x.id,{}).get('reading')) for x in self.lines)}

    def issues(self):
        found=[]
        if not self.media or not Path(self.media).is_file(): found.append(('media',None,'请添加有效音视频；原素材移动后可重新定位'))
        if not self.lines: found.append(('lyrics',None,'请粘贴原歌词，每行一句'))
        for line in self.lines:
            if not line.reviewed: found.append(('timing',line.id,'时间尚未确认'))
            if not self.checks.get(line.id,{}).get('reading'): found.append(('reading',line.id,'读音尚未确认'))
            if self.duration and line.end>self.duration: found.append(('range',line.id,'歌词结束时间超出媒体'))
        return found

def load_project(path):
    try:return _load_project(path)
    except (TypeError,KeyError,AttributeError,OverflowError,RecursionError) as error:
        raise ValueError('工程内容不完整或数据类型无效，请检查文件格式') from error

def _load_project(path):
    path=Path(path)
    text=path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() in {'.lrc','.srt'}:
        from .subtitle_files import import_timed
        return import_timed(text,path.suffix.lower(),path.stem)
    if path.suffix.lower() in {'.ass','.ssa'}:
        for row in text.splitlines():
            if row.startswith('; ShengaoProject: '):
                data=json.loads(base64.b64decode(row.split(': ',1)[1],validate=True))
                project=Project.from_dict(data,path.parent)
                if data.get('version',1)<2:
                    from .subtitle_import import migrate_generated_style
                    project.source_ass=text;project.source_ass_active=True;project.source_path=str(path)
                    project.ass_rows=[{'generated':True,'originals':[x.to_dict() for x in project.lines]}]
                    migrate_generated_style(project,text)
                    from .subtitle_import import source_fonts
                    project.font_assets.update(source_fonts(text))
                return project
        from .subtitle_import import import_ass
        return import_ass(text,path)
    return Project.from_dict(json.loads(text),path.parent)

def save_project(project,path,portable_fonts=True):
    project.validate();path=Path(path);value=project.to_dict()
    if portable_fonts:
        for name in ('font_file','ruby_font_file','translation_font_file'):
            source=Path(value['style'][name]) if value['style'][name] else None
            if source and source.is_file():
                import hashlib
                digest=hashlib.sha256(source.read_bytes()).hexdigest()[:12]
                dest=path.parent/(path.stem+'.assets')/'fonts'/(digest+source.suffix)
                dest.parent.mkdir(parents=True,exist_ok=True)
                if source.resolve()!=dest.resolve() and (not dest.is_file() or hashlib.sha256(dest.read_bytes()).hexdigest()[:12]!=digest):shutil.copy2(source,dest)
                value['style'][name]=str(dest.relative_to(path.parent))
        for family,source_name in project.font_assets.items():
            source=Path(source_name)
            if not source.is_file():continue
            import hashlib
            digest=hashlib.sha256(source.read_bytes()).hexdigest()[:12];dest=path.parent/(path.stem+'.assets')/'fonts'/(digest+source.suffix)
            dest.parent.mkdir(parents=True,exist_ok=True)
            if source.resolve()!=dest.resolve() and (not dest.is_file() or hashlib.sha256(dest.read_bytes()).hexdigest()[:12]!=digest):shutil.copy2(source,dest)
            value['font_assets'][family]=str(dest.relative_to(path.parent))
    if project.media:
        import os
        try: value['media']=os.path.relpath(project.media,path.parent)
        except ValueError: pass
    for role,entry in value['media_versions'].items():
        import os
        try:entry['path']=os.path.relpath(project.media_versions[role].path,path.parent)
        except ValueError:pass
    if project.vocal_track:
        from .vocal_audio import digest
        source=Path(project.vocal_track['path'])
        if source.is_file():
            fingerprint=project.vocal_track['sha256']
            if digest(source)!=fingerprint:raise ValueError('人声缓存已变化，请重新生成后保存；工程未覆盖。')
            dest=path.parent/(path.stem+'.assets')/'audio'/(fingerprint+'.wav');dest.parent.mkdir(parents=True,exist_ok=True)
            if source.resolve()!=dest.resolve() and (not dest.is_file() or digest(dest)!=fingerprint):
                temp=dest.with_suffix('.copying');shutil.copy2(source,temp)
                if digest(temp)!=fingerprint:temp.unlink(missing_ok=True);raise ValueError('复制人声资源时发生变化，工程未覆盖。')
                temp.replace(dest)
            value['vocal_track']['path']=str(dest.relative_to(path.parent))
        import os
        try:value['vocal_track']['source_path']=os.path.relpath(project.vocal_track['source_path'],path.parent)
        except ValueError:pass
    atomic_json(path,value)

class History:
    """One user action is one undo step, including batch operations."""
    def __init__(self,project):
        self.project=project;self.undo_stack=[];self.redo_stack=[];self.saved=project.to_dict()
        self.merge_key=None;self.merge_time=0

    @property
    def dirty(self): return self.project.to_dict()!=self.saved

    def apply(self,label,edit,merge_key=None):
        before=self.project.to_dict();candidate=Project.from_dict(before)
        edit(candidate);candidate.validate()
        if candidate.to_dict()==before:return False
        now=time.monotonic()
        if merge_key is None or merge_key!=self.merge_key or now-self.merge_time>1:
            self.undo_stack.append((label,before));self.undo_stack=self.undo_stack[-150:]
        self.merge_key=merge_key;self.merge_time=now;self.redo_stack.clear()
        self.project=candidate;return True

    def undo(self):
        self.merge_key=None
        if not self.undo_stack:return False
        label,data=self.undo_stack.pop();self.redo_stack.append((label,self.project.to_dict()));self.project=Project.from_dict(data);return True

    def redo(self):
        self.merge_key=None
        if not self.redo_stack:return False
        label,data=self.redo_stack.pop();self.undo_stack.append((label,self.project.to_dict()));self.project=Project.from_dict(data);return True

    def mark_saved(self): self.saved=self.project.to_dict();self.merge_key=None

def file_stamp(path):
    if not path or not Path(path).is_file():return {}
    import os
    path=Path(path).resolve();stat=path.stat()
    return {'path':os.path.normcase(str(path)),'size':stat.st_size,'modified_ns':stat.st_mtime_ns}
