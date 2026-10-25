"""Independent song credits, composed into the same ASS used for every output."""
import math
import re
from pathlib import Path
from studio_backend.model import literal
from studio_backend.export import ass_time
from .fonts import resolve_font, metric_font, family_name, font_weight, traits, missing


MARKER = 'ShengaoSongInfo:v1'
PREFIX = '__ShengaoSongInfo_'
STYLE_FIELDS = 'Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding'.split(', ')
EVENT_FIELDS = 'Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text'.split(', ')
DEFAULTS = dict(version=1, enabled=False, title='', artist='', font='', font_file='',
                title_size=52, artist_size=34, title_color='#ffffff', artist_color='#ffffff',
                outline_color='#000000', shadow_color='#000000', opacity=100,
                outline=3., shadow=1.5, x=64, y=40, gap=8, period='all', start=0, end=10000)


def validate(value):
    if not isinstance(value, dict) or set(value)-set(DEFAULTS):
        raise ValueError('歌名／歌手设置格式无效')
    if not value:
        return
    s = {**DEFAULTS, **value}
    if type(s['version']) is not int or s['version'] != 1 or type(s['enabled']) is not bool:
        raise ValueError('歌名／歌手设置版本或开关无效')
    for key in ('title', 'artist', 'font', 'font_file'):
        text = s[key]
        if not isinstance(text, str) or '\x00' in text or any(ord(c)<32 and c not in '\n\t' for c in text):
            raise ValueError('歌名、歌手或字体内容无效')
        if key in ('title', 'artist') and (len(text)>500 or text.count('\n')>2):
            raise ValueError('歌名和歌手各最多 500 字、三行；请精简或手工换行')
        if key == 'font' and (len(text)>200 or any(c in text for c in ',\n\t{}\\')):
            raise ValueError('字体名称含有不支持的字符')
        if key == 'font_file' and (len(text)>4096 or '\n' in text or '\t' in text):
            raise ValueError('标识字体路径无效')
    if s['enabled'] and not (s['title'].strip() or s['artist'].strip()):
        raise ValueError('开启标识时请至少填写歌名或歌手')
    for key, lo, hi in [('title_size',8,180),('artist_size',8,180),('opacity',0,100),
                        ('x',0,1856),('y',0,1016),('gap',0,100),('start',0,360000000),('end',0,360000000)]:
        if type(s[key]) is not int or not lo<=s[key]<=hi:
            raise ValueError('歌名／歌手的字号、位置或显示时间超出范围')
    for key in ('outline', 'shadow'):
        v=s[key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=20:
            raise ValueError('标识描边和阴影须为 0–20 的有限数值')
    for key in ('title_color','artist_color','outline_color','shadow_color'):
        if not isinstance(s[key],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',s[key]):
            raise ValueError('标识颜色须为 #RRGGBB')
    if s['period'] not in ('all','range') or s['period']=='range' and s['end']-s['start']<10:
        raise ValueError('标识显示时段无效；结束须晚于开始')


def settings(project):
    validate(project.song_info)
    return {**DEFAULTS, **project.song_info}


def font_path(project):
    s=settings(project)
    return resolve_font(s['font_file'] or (project.style.font_file if not s['font'] else ''),
                        s['font'] or project.style.font)


def period(project):
    s=settings(project)
    if s['period']=='range':
        return s['start'],s['end']
    # Show through lyric leave-screen time as well when no media is attached.
    from .presentation import display_windows
    end=project.duration or max((v.end for v in display_windows(project)),default=10000)
    return 0,max(10,end)


def _rgba(rgb,opacity=100):
    return f'&H{round((100-opacity)*255/100):02X}'+rgb[5:7]+rgb[3:5]+rgb[1:3]


def _structure(text):
    rows=text.splitlines();section='';style_format=None;event_format=None;style_end=None;event_end=None
    width=height=None;style_names=set()
    for i,row in enumerate(rows):
        stripped=row.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if section=='[v4+ styles]':style_end=i
            if section=='[events]':event_end=i
            section=stripped.lower()
        if section=='[script info]':
            match=re.fullmatch(r'PlayRes([XY])\s*:\s*(\d+)\s*',stripped,re.I)
            if match:
                if match[1].lower()=='x':width=int(match[2])
                else:height=int(match[2])
        if section=='[v4+ styles]':
            style_end=i+1
            if stripped.lower().startswith('format:'):style_format=[x.strip() for x in stripped.split(':',1)[1].split(',')]
            if stripped.lower().startswith('style:') and style_format:
                values=stripped.split(':',1)[1].lstrip().split(',')
                fields=dict(zip((v.lower() for v in style_format),values));style_names.add(fields.get('name',''))
        if section=='[events]':
            event_end=i+1
            if stripped.lower().startswith('format:'):event_format=[x.strip() for x in stripped.split(':',1)[1].split(',')]
    if not width or not height or not 16<=width<=32768 or not 16<=height<=32768:
        raise ValueError('原 ASS 缺少有效 PlayResX／PlayResY；请先补全分辨率或选择声稿样式后添加标识')
    if not style_format or not event_format or style_end is None or event_end is None:
        raise ValueError('歌名标识需要标准 ASS 的 V4+ Styles 和 Events 格式；原字幕保持，请先转换或选择声稿样式')
    # Reordered valid fields are supported. Unknown columns are retained and blank
    # on our new rows; existing rows, styles and effect blocks are never rewritten.
    for names, required in ((style_format,STYLE_FIELDS),(event_format,EVENT_FIELDS)):
        lowered=[v.lower() for v in names]
        if len(lowered)!=len(set(lowered)) or any(v.lower() not in lowered for v in required):
            raise ValueError('原 ASS 的样式或事件字段不完整，无法安全添加歌名标识；原字幕保持')
    if event_format[-1].lower()!='text':
        raise ValueError('原 ASS 的 Text 须位于事件格式末尾，才能安全保留含逗号的文本')
    return rows,style_format,event_format,style_end,event_end,width,height,style_names


def own_event(fields):
    f={k.lower():v for k,v in fields.items()}
    return f.get('name')==MARKER and f.get('effect')==MARKER and f.get('style','').startswith(PREFIX)


def event_parts(text):
    section='';names=None
    for index,row in enumerate(text.splitlines()):
        stripped=row.strip()
        if stripped.startswith('['):section=stripped.lower()
        if section!='[events]':continue
        if stripped.lower().startswith('format:'):names=[v.strip() for v in stripped.split(':',1)[1].split(',')]
        elif stripped.lower().startswith('dialogue:') and names:
            values=stripped.split(':',1)[1].lstrip().split(',',len(names)-1)
            if len(values)==len(names):yield index,dict(zip(names,values))


def append_ass(text,project):
    s=settings(project)
    if not s['enabled']:return text
    rows,sf,ef,si,ei,width,height,used=_structure(text)
    # Replacing an imported known overlay never duplicates its old events.
    for index,fields in event_parts(text):
        if own_event(fields):rows[index]=''
    font=font_path(project);family=family_name(str(font),s['font'] or project.style.font)
    bold,italic=traits(str(font),family);weight=font_weight(str(font),family)
    family=family.replace(',',' ').replace('\n',' ')
    sx,sy=width/1920,height/1080;y=s['y']*sy;start,end=period(project);styles=[];events=[]
    for role in ('title','artist'):
        content=s[role]
        if not content.strip():continue
        name=PREFIX+role;serial=1
        while name in used:name=PREFIX+role+'_'+str(serial);serial+=1
        used.add(name);size=s[role+'_size']*sy
        values=[name,family,f'{size:.5f}',_rgba(s[role+'_color'],s['opacity']),_rgba(s[role+'_color'],s['opacity']),
                _rgba(s['outline_color'],s['opacity']),_rgba(s['shadow_color'],s['opacity']),str(-1 if bold else 0),str(-1 if italic else 0),
                '0','0','100','100','0','0','1',f'{s["outline"]*sy:.5f}',f'{s["shadow"]*sy:.5f}','7','0','0','0','1']
        fields=dict(zip((v.lower() for v in STYLE_FIELDS),values))
        styles.append('Style: '+','.join(fields.get(key.lower(),'') for key in sf))
        body=f'{{\\an7\\q2\\pos({s["x"]*sx:.5f},{y:.5f})\\b{weight}}}'+literal(content)
        values=['20',ass_time(start),ass_time(max(start+10,end)),name,MARKER,'0','0','0',MARKER,body]
        fields=dict(zip((v.lower() for v in EVENT_FIELDS),values))
        events.append('Dialogue: '+','.join(fields.get(key.lower(),'') for key in ef))
        mf=metric_font(str(font),size,family)
        y+=max(size,sum(mf.getmetrics()))*(content.count('\n')+1)+s['gap']*sy
    # Insert backwards, because source files may order their sections differently.
    for index, additions in sorted(((si,styles),(ei,events)),key=lambda v:v[0],reverse=True):rows[index:index]=additions
    return '\n'.join(rows)+'\n'


def issues(project,check_overlap=False):
    s=settings(project)
    if not s['enabled']:return []
    found=[];font=font_path(project);family=s['font'] or project.style.font;y=s['y']
    if s['font_file'] and not Path(s['font_file']).is_file():found.append((None,'歌名／歌手字体文件已丢失，目前使用备用字体；请重新添加'))
    for role,label in (('title','歌名'),('artist','歌手')):
        content=s[role]
        if not content.strip():continue
        absent=missing(font,literal(content).replace(r'\N',''),family)
        if absent:found.append((None,label+'字体缺少：'+absent[:24]))
        mf=metric_font(str(font),s[role+'_size'],family);width=max((mf.getlength(literal(v)) for v in content.split('\n')),default=0)
        height=max(s[role+'_size'],sum(mf.getmetrics()))*(content.count('\n')+1)
        margin=s['outline']+s['shadow']
        if s['x']-margin<32 or y-margin<32 or s['x']+width+margin>1888 or y+height+margin>1048:
            found.append((None,label+'超出建议安全区；请调整边距、字号或手工换行，内容未自动截断'))
        y+=height+s['gap']
    if project.duration and s['period']=='range' and s['end']>project.duration:found.append((None,'歌名／歌手显示结束超出媒体时长；请核对时段'))
    if check_overlap:found.extend(overlap_issues(project))
    return found


def overlap_issues(project):
    """Actual libass alpha intersection at the start/middle/end of each display.

    This is a bounded sampling check, not a proof about every animated frame.
    """
    from PIL import Image,ImageChops
    from .subtitles import compose
    from .render import AssRenderer
    from .fonts import project_font_files
    from .presentation import display_windows
    if not settings(project)['enabled']:return []
    text=compose(project);rows=text.splitlines();parts=dict(event_parts(text));start,end=period(project)
    logo='\n'.join(row for i,row in enumerate(rows) if i not in parts or own_event(parts[i]))+'\n'
    lyrics='\n'.join(row for i,row in enumerate(rows) if i not in parts or not own_event(parts[i]))+'\n'
    samples=[]
    for line,window in zip(project.lines,display_windows(project)):
        a,b=max(start,window.start),min(end,window.end)
        if b-a>=10:samples.append((line.id,(a+5,(a+b)//2,b-5)))
    result=[];renderer=AssRenderer()
    try:
        renderer.add_fonts(project_font_files(project));renderer.set_text(logo)
        mask=Image.frombytes('RGBA',(960,540),renderer.rgba(960,540,(start+end)//2)).getchannel('A').point(lambda v:255 if v>32 else 0)
        if mask.getbbox() is None:return [(None,'歌名／歌手未形成可检查的可见图像；请核对透明度、字体和位置')]
        renderer.set_text(lyrics)
        for uid,points in samples[:100]:
            for when in points:
                alpha=Image.frombytes('RGBA',(960,540),renderer.rgba(960,540,when)).getchannel('A').point(lambda v:255 if v>32 else 0)
                if ImageChops.multiply(mask,alpha).getbbox():
                    result.append((uid,'歌名／歌手区域与本句字幕重叠；请调整标识位置、字号或显示时段'));break
        if len(samples)>100:result.append((None,'歌名标识重叠检查已抽查前 100 个同时显示的句子；其余句子和动画请继续预览'))
    finally:renderer.close()
    return result
