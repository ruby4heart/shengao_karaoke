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

# What each export keeps and drops. Shown in the export dialog and help, so
# the promise in the interface is the one the writer actually implements.
FORMATS={
    'ass':dict(label='ASS 字幕',pattern='*.ass',keeps='逐音高亮、注音、翻译、样式、字幕出现时间和声稿工程信息',
               loses='无；其他字幕软件修改时间后，声稿重开时会列出改动并作为一步可撤销操作应用'),
    'lrc':dict(label='LRC 逐字歌词',pattern='*.lrc',keeps='每行开始时间、行间空白和逐音时间（增强 LRC 的 <mm:ss.xx> 标签）',
               loses='注音、翻译、样式和字幕出现时间；时间精度为 10 毫秒，一句内的换行会合并为空格'),
    'srt':dict(label='SRT 字幕',pattern='*.srt',keeps='每行开始、结束时间和原歌词换行',loses='逐音高亮、注音、翻译和样式'),
    'txt':dict(label='纯文本歌词',pattern='*.txt',keeps='原歌词文字',loses='全部时间、注音、翻译和样式'),
}

def format_filter():
    return ';;'.join(f"{v['label']} ({v['pattern']})" for v in FORMATS.values())

def format_kind(selected_filter,path=''):
    for kind,value in FORMATS.items():
        if selected_filter and selected_filter.startswith(value['label']):return kind
    suffix=Path(str(path)).suffix.lower()[1:]
    return suffix if suffix in FORMATS else 'ass'

def format_note(kind):
    value=FORMATS[kind];return f"{value['label']}保留：{value['keeps']}。不包含：{value['loses']}。"

_LRC_TAG=r'\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]'
_LRC_WORD=r'<(\d+):(\d{1,2})(?:[.:](\d{1,3}))?>|'+_LRC_TAG

def _lrc_ms(match,offset=0,base=1):
    minutes,seconds,fraction=match.group(base),match.group(base+1),match.group(base+2)
    return max(0,(int(minutes)*60+int(seconds))*1000+int((fraction or '0').ljust(3,'0')[:3])+offset)

def _lrc_words(lyric,start,offset):
    """Split enhanced LRC into (start, text) segments; None when untimed."""
    marks=[(m.start(),m.end(),_lrc_ms(m,offset,1) if m.group(1) is not None else _lrc_ms(m,offset,4)) for m in re.finditer(_LRC_WORD,lyric)]
    if not marks:return None
    segments=[(start,lyric[:marks[0][0]])] if marks[0][0] else []
    for index,(_,end,time) in enumerate(marks):
        segments.append((time,lyric[end:marks[index+1][0] if index+1<len(marks) else len(lyric)]))
    return segments

def _lrc_units(segments,delta,fallback_end):
    from studio_backend.model import Unit
    from studio_backend.provenance import create
    units=[]
    for index,(time,text) in enumerate(segments):
        if not text:continue
        start=time+delta;end=(segments[index+1][0]+delta) if index+1<len(segments) else fallback_end
        if end<start or (units and start<units[-1].end):return None,None
        units.append(Unit(text,start,end,source='imported',timing_origin=create('imported',start,end,'lrc','word_tags')))
    closed=bool(segments) and not segments[-1][1]
    return units,(segments[-1][0]+delta if closed else None)

def _import_lrc(text):
    offset_match=re.search(r'\[offset:([+-]?\d+)\]',text,re.I);offset=int(offset_match[1]) if offset_match else 0
    entries=[]
    for row in text.splitlines():
        lead=re.match(r'(?:\s*'+_LRC_TAG+r')+',row)
        if not lead:continue
        tags=[_lrc_ms(m,offset) for m in re.finditer(_LRC_TAG,lead.group(0))]
        lyric=row[lead.end():]
        words=_lrc_words(lyric,tags[0],offset)
        plain=re.sub(_LRC_WORD,'',lyric) if words is not None else lyric
        for time in tags:
            # A tag with no lyric ends the previous line (instrumental gap).
            entries.append((time,plain if plain.strip() else None,words,time-tags[0]))
    entries.sort(key=lambda x:x[0])
    lines=[]
    for index,(start,lyric,words,delta) in enumerate(entries):
        if lyric is None:continue
        following=next((x[0] for x in entries[index+1:] if x[0]>start),None)
        end=following if following is not None else start+5000
        line=LyricLine(identifier(),lyric,start,end);origin=('estimated','lrc_end_estimate')
        if words is not None:
            units,closing=_lrc_units(words,delta,end)
            if units and ''.join(u.text for u in units)==lyric:
                line.start=min(start,units[0].start);line.end=max(closing or units[-1].end,units[-1].end,line.start+10)
                line.units=units;origin=('imported','lrc_word_tags') if closing is not None else ('estimated','lrc_end_estimate')
        if line.end<=line.start:line.end=line.start+10
        from studio_backend.provenance import create
        line.timing_origin=create(origin[0],line.start,line.end,'lrc',origin[1],parents=['imported'] if origin[0]=='estimated' else [])
        lines.append(line)
    return lines

def import_timed(text,kind,title='导入字幕'):
    lines=[]
    if kind=='.lrc':lines=_import_lrc(text)
    elif kind=='.srt':
        def stamp(value):
            h,m,s,f=re.split(r'[:,.]',value);return (int(h)*3600+int(m)*60+int(s))*1000+int(f.ljust(3,'0'))
        pattern=r'(\d+:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{1,3})[^\n]*\n(.+?)(?=\n\s*\n|\Z)'
        for match in re.finditer(pattern,text.replace('\r\n','\n'),re.S):
            lyric=match[3].rstrip('\n')
            if lyric.strip():lines.append(LyricLine(identifier(),lyric,stamp(match[1]),stamp(match[2])))
        from studio_backend.provenance import create
        for line in lines:line.timing_origin=create('imported',line.start,line.end,'srt','dialogue')
    else:raise ValueError('不支持的时间歌词格式')
    if not lines:raise ValueError('未找到有效的时间歌词或字幕')
    project=Project(title=title,lines=lines);project.validate();return project

def _lrc_time(value,brackets='[]'):
    centi=round(value/10);minutes,rest=divmod(centi,6000)
    return f'{brackets[0]}{minutes:02d}:{rest//100:02d}.{rest%100:02d}{brackets[1]}'

def _lrc_text(text):
    return re.sub(r'\s*\n\s*',' ',text.replace('\r\n','\n').replace('\r','\n'))

def lrc_text(project,words=True):
    """Standard LRC rows, with enhanced <mm:ss.xx> unit tags when timed."""
    rows=[]
    title=project.song_info.get('title','') or project.title;artist=project.song_info.get('artist','')
    if title:rows.append(f'[ti:{_lrc_text(title)}]')
    if artist:rows.append(f'[ar:{_lrc_text(artist)}]')
    rows.append('[re:声稿 Karaoke Studio]')
    ordered=sorted(project.lines,key=lambda x:(x.start,x.end))
    for index,line in enumerate(ordered):
        body=_lrc_text(line.text)
        if words and line.units:
            parts=[];cursor=None
            for unit in line.units:
                if cursor is not None and round(unit.start/10)>round(cursor/10):parts.append(_lrc_time(cursor,'<>'))
                parts.append(_lrc_time(unit.start,'<>')+_lrc_text(unit.text));cursor=unit.end
            parts.append(_lrc_time(cursor,'<>'));body=''.join(parts)
        rows.append(_lrc_time(line.start)+body)
        following=ordered[index+1].start if index+1<len(ordered) else None
        if following is None or round(following/10)>round(line.end/10):rows.append(_lrc_time(line.end))
    return '\n'.join(rows)+'\n'

def export_subtitle(project,path,kind='ass'):
    """Write the subtitle file; for ASS also carry every font it is drawn with.

    Returns ``{'path','fonts','missing'}``: the font files carried beside the
    ASS, and the fonts that could not be carried (their files are gone)."""
    path=Path(path);project.validate()
    if not project.lines:raise ValueError('工程没有歌词')
    carried=[];skipped=[]
    if kind=='ass':
        value=copy.deepcopy(project)
        resources=path.parent/(path.stem+'.assets')/'fonts';resources.mkdir(parents=True,exist_ok=True)
        for name,family in [('font_file','font'),('ruby_font_file','ruby_font'),('translation_font_file','translation_font')]:
            chosen=getattr(value.style,name)
            if chosen and not Path(chosen).is_file():skipped.append(Path(chosen).name)
            source=resolve_font(chosen,getattr(value.style,family));digest=hashlib.sha256(source.read_bytes()).hexdigest()[:12];destination=resources/(digest+source.suffix)
            if source.resolve()!=destination.resolve():shutil.copy2(source,destination)
            setattr(value.style,name,str(destination));carried.append(destination.name)
        # Embed relative resource paths so an exported ASS can reopen elsewhere.
        data=value.to_dict()
        if value.song_info.get('font') or value.song_info.get('font_file'):
            from .song_info import font_path
            source=font_path(value);destination=resources/(hashlib.sha256(source.read_bytes()).hexdigest()[:12]+source.suffix)
            if source.resolve()!=destination.resolve():shutil.copy2(source,destination)
            value.song_info['font_file']=str(destination);carried.append(destination.name)
            data['song_info']['font_file']=str(destination.relative_to(path.parent))
        for name in ('font_file','ruby_font_file','translation_font_file'):data['style'][name]=os.path.relpath(getattr(value.style,name),path.parent)
        for family,source_name in value.font_assets.items():
            source=Path(source_name)
            if not source.is_file():skipped.append(family);continue
            destination=resources/(hashlib.sha256(source.read_bytes()).hexdigest()[:12]+source.suffix)
            if source.resolve()!=destination.resolve():shutil.copy2(source,destination)
            data['font_assets'][family]=str(destination.relative_to(path.parent));carried.append(destination.name)
        if value.media:
            try:data['media']=os.path.relpath(value.media,path.parent)
            except ValueError:pass
        text=compose(value,True)
        import base64,json
        encoded=base64.b64encode(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()).decode()
        text='; ShengaoProject: '+encoded+'\n'+'\n'.join(row for row in text.splitlines() if not row.startswith('; ShengaoProject: '))+'\n'
        # Lets a reopen notice timing edits made in Aegisub and similar tools.
        from .ass_roundtrip import mark
        text=mark(text,value).rstrip('\n')+'\n'
        for license in (ASSETS/'fonts').glob('*LICENSE.txt'):shutil.copy2(license,resources.parent/license.name)
        (path.parent/(path.stem+'-字体说明.txt')).write_text('本 ASS 使用同名 .assets/fonts 中的字体。声稿重开时会自动读取。使用其他字幕播放器时请自行配置该字体目录，或安装所选字体；直接交付视频可使用内置压制。\n',encoding='utf-8-sig')
    elif kind=='srt':text='\n\n'.join(f'{i}\n{srt_time(line.start)} --> {srt_time(line.end)}\n{line.text}' for i,line in enumerate(project.lines,1))+'\n'
    elif kind=='lrc':text=lrc_text(project)
    elif kind=='txt':text='\n'.join(line.text for line in project.lines)+'\n'
    else:raise ValueError('不支持的字幕格式')
    fd,temporary=tempfile.mkstemp(prefix=path.stem+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8-sig' if kind=='ass' else 'utf-8',newline='\n') as stream:stream.write(text)
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)
    return {'path':str(path),'fonts':list(dict.fromkeys(carried)),'missing':list(dict.fromkeys(skipped))}
