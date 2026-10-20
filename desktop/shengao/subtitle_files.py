"""Portable subtitle exports and common timed-lyrics imports."""
from pathlib import Path
import copy
import os
import re
import shutil
import tempfile
import hashlib
from studio_backend.model import LyricLine,identifier
from studio_backend.export import srt_time
from .project import Project
from .fonts import resolve_font
from .paths import ASSETS
from .subtitles import compose

def import_timed(text,kind,title='导入字幕'):
    lines=[]
    if kind=='.lrc':
        offset_match=re.search(r'\[offset:([+-]?\d+)\]',text,re.I);offset=int(offset_match[1]) if offset_match else 0
        values=[]
        for row in text.splitlines():
            tags=list(re.finditer(r'\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]',row))
            if not tags:continue
            lyric=row[tags[-1].end():]
            if not lyric.strip():continue
            for tag in tags:
                fraction=int((tag[3] or '0').ljust(3,'0'))
                values.append((max(0,(int(tag[1])*60+int(tag[2]))*1000+fraction+offset),lyric))
        values.sort(key=lambda x:x[0])
        for i,(start,lyric) in enumerate(values):
            end=values[i+1][0] if i+1<len(values) and values[i+1][0]>start else start+5000
            lines.append(LyricLine(identifier(),lyric,start,end))
    elif kind=='.srt':
        def stamp(value):
            h,m,s,f=re.split(r'[:,.]',value);return (int(h)*3600+int(m)*60+int(s))*1000+int(f.ljust(3,'0'))
        pattern=r'(\d+:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{1,3})[^\n]*\n(.+?)(?=\n\s*\n|\Z)'
        for match in re.finditer(pattern,text.replace('\r\n','\n'),re.S):
            lyric=match[3].rstrip('\n')
            if lyric.strip():lines.append(LyricLine(identifier(),lyric,stamp(match[1]),stamp(match[2])))
    else:raise ValueError('不支持的时间歌词格式')
    if not lines:raise ValueError('未找到有效的时间歌词或字幕')
    from studio_backend.provenance import create
    for line in lines:line.timing_origin=create('estimated' if kind=='.lrc' else 'imported',line.start,line.end,kind[1:],'lrc_end_estimate' if kind=='.lrc' else 'dialogue',parents=['imported'] if kind=='.lrc' else [])
    project=Project(title=title,lines=lines);project.validate();return project

def export_subtitle(project,path,kind='ass'):
    path=Path(path);project.validate()
    if not project.lines:raise ValueError('工程没有歌词')
    if kind=='ass':
        value=copy.deepcopy(project)
        resources=path.parent/(path.stem+'.assets')/'fonts';resources.mkdir(parents=True,exist_ok=True)
        for name,family in [('font_file','font'),('ruby_font_file','ruby_font'),('translation_font_file','translation_font')]:
            source=resolve_font(getattr(value.style,name),getattr(value.style,family));digest=hashlib.sha256(source.read_bytes()).hexdigest()[:12];destination=resources/(digest+source.suffix)
            if source.resolve()!=destination.resolve():shutil.copy2(source,destination)
            setattr(value.style,name,str(destination))
        # Embed relative resource paths so an exported ASS can reopen elsewhere.
        data=value.to_dict()
        for name in ('font_file','ruby_font_file','translation_font_file'):data['style'][name]=os.path.relpath(getattr(value.style,name),path.parent)
        for family,source_name in value.font_assets.items():
            source=Path(source_name)
            if not source.is_file():continue
            destination=resources/(hashlib.sha256(source.read_bytes()).hexdigest()[:12]+source.suffix)
            if source.resolve()!=destination.resolve():shutil.copy2(source,destination)
            data['font_assets'][family]=str(destination.relative_to(path.parent))
        if value.media:
            try:data['media']=os.path.relpath(value.media,path.parent)
            except ValueError:pass
        text=compose(value,True)
        import base64,json
        encoded=base64.b64encode(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()).decode()
        text='; ShengaoProject: '+encoded+'\n'+'\n'.join(row for row in text.splitlines() if not row.startswith('; ShengaoProject: '))+'\n'
        for license in (ASSETS/'fonts').glob('*LICENSE.txt'):shutil.copy2(license,resources/license.name)
        (path.parent/(path.stem+'-字体说明.txt')).write_text('本 ASS 使用同名 .assets/fonts 中的字体。声稿重开时会自动读取。使用其他字幕播放器时请自行配置该字体目录，或安装所选字体；直接交付视频可使用内置压制。\n',encoding='utf-8-sig')
    elif kind=='srt':text='\n\n'.join(f'{i}\n{srt_time(line.start)} --> {srt_time(line.end)}\n{line.text}' for i,line in enumerate(project.lines,1))+'\n'
    elif kind=='txt':text='\n'.join(line.text for line in project.lines)+'\n'
    else:raise ValueError('不支持的字幕格式')
    fd,temporary=tempfile.mkstemp(prefix=path.stem+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8-sig' if kind=='ass' else 'utf-8',newline='\n') as stream:stream.write(text)
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)
