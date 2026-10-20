"""Export standards-compliant ASS with resolved ruby positions, plus project data."""
import base64
import json
import os
from pathlib import Path
import tempfile

from PIL import ImageFont

from .model import literal


def ass_time(milliseconds):
    value=max(0,round(milliseconds/10))
    hours,value=divmod(value,360000)
    minutes,value=divmod(value,6000)
    seconds,cs=divmod(value,100)
    return f'{hours}:{minutes:02}:{seconds:02}.{cs:02}'


def srt_time(milliseconds):
    hours,value=divmod(milliseconds,3600000)
    minutes,value=divmod(value,60000)
    seconds,millis=divmod(value,1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{millis:03}'


def ass_header():
    return '''[Script Info]
Title: Shengao Karaoke Studio
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lyrics,Meiryo,64,&H0075E8B3,&H00FFFFFF,&H00181818,&H80000000,0,0,0,0,100,100,0,0,1,2,0,5,80,80,80,1
Style: Ruby,Meiryo,30,&H0075E8B3,&H00FFFFFF,&H00181818,&H80000000,0,0,0,0,100,100,0,0,1,1,0,5,80,80,80,1
Style: Romaji,Meiryo,34,&H00FFFFFF,&H00FFFFFF,&H00181818,&H80000000,0,0,0,0,100,100,0,0,1,1.5,0,5,80,80,80,1
Style: Translation,Microsoft YaHei,36,&H00FFFFFF,&H00FFFFFF,&H00181818,&H80000000,0,0,0,0,100,100,0,0,1,1.5,0,2,80,80,45,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''


def font_path():
    fonts=Path(os.getenv('WINDIR','C:/Windows'))/'Fonts'
    for name in ('meiryo.ttc','YuGothM.ttc','msgothic.ttc','msyh.ttc'):
        if (fonts/name).exists():
            return str(fonts/name)
    raise ValueError('未找到支持日文的系统字体，请安装 Meiryo 或 Yu Gothic 后导出注音成品')


def event(start,end,style,text,layer=0,comment=False,effect=''):
    return f'{"Comment" if comment else "Dialogue"}: {layer},{ass_time(start)},{ass_time(max(start+10,end))},{style},,0,0,0,{effect},{text}'


def export_ass(lines, resolved=True, show_ruby=True, show_romaji=True, show_translation=True):
    rows=[ass_header().rstrip()]
    metadata=base64.b64encode(json.dumps({'version':1,'lines':[line.to_dict() for line in lines]},
                                       ensure_ascii=False,separators=(',',':')).encode()).decode('ascii')
    rows.insert(0,'; ShengaoProject: '+metadata)
    for line in lines:
        line.validate()
        if not resolved:
            rows.append(event(line.start,line.end,'Lyrics',line.karaoke(furigana=show_ruby),effect='karaoke'))
            continue
        # Keep the editable original as a comment; the resolved events play everywhere.
        rows.append(event(line.start,line.end,'Lyrics',line.karaoke(furigana=True),comment=True,effect='karaoke'))
        if line.units:
            path=font_path()
            main_size,ruby_size=64,30
            for _ in range(5):
                main_font=ImageFont.truetype(path,main_size)
                ruby_font=ImageFont.truetype(path,ruby_size)
                widths=[max(main_font.getlength(u.text),ruby_font.getlength(u.kana) if show_ruby else 0)+6 for u in line.units]
                if sum(widths)<=1760:
                    break
                scale=1760/sum(widths)
                main_size=max(16,int(main_size*scale));ruby_size=max(10,int(ruby_size*scale))
            x=(1920-sum(widths))/2
            for unit,width in zip(line.units,widths):
                center=x+width/2
                gap=max(0,round(unit.start/10)-round(line.start/10))
                duration=max(0,round(unit.end/10)-round(unit.start/10))
                tags=r'{\an5\pos(' + f'{center:.2f},850)' + r'\fs'+str(main_size)+'}'
                timing=('{\\k'+str(gap)+'}' if gap else '')+'{\\kf'+str(duration)+'}'
                rows.append(event(line.start,line.end,'Lyrics',tags+timing+literal(unit.text),1))
                if show_ruby and unit.kana and unit.kana!=unit.text:
                    ruby_y=850-main_size/2-ruby_size/2-8
                    if unit.highlights:
                        ruby_left=center-ruby_font.getlength(unit.kana)/2
                        for highlight in unit.highlights:
                            part_width=ruby_font.getlength(highlight.kana)
                            part_center=ruby_left+part_width/2
                            part_gap=max(0,round(highlight.start/10)-round(line.start/10))
                            part_duration=max(0,round(highlight.end/10)-round(highlight.start/10))
                            part_timing=('{\\k'+str(part_gap)+'}' if part_gap else '')+'{\\kf'+str(part_duration)+'}'
                            tags=r'{\an5\pos('+f'{part_center:.2f},{ruby_y:.2f})'+r'\fs'+str(ruby_size)+'}'
                            rows.append(event(line.start,line.end,'Ruby',tags+part_timing+literal(highlight.kana),2))
                            ruby_left+=part_width
                    else:
                        tags=r'{\an5\pos(' + f'{center:.2f},{ruby_y:.2f})' + r'\fs'+str(ruby_size)+'}'
                        rows.append(event(line.start,line.end,'Ruby',tags+timing+literal(unit.kana),2))
                x+=width
        else:
            rows.append(event(line.start,line.end,'Lyrics',r'{\an5\pos(960,850)}'+literal(line.text)))
        if show_romaji and line.romaji:
            rows.append(event(line.start,line.end,'Romaji',r'{\an5\pos(960,930)}'+literal(line.romaji),3))
        if show_translation and line.translation:
            rows.append(event(line.start,line.end,'Translation',literal(line.translation),3))
    return '\n'.join(rows)+'\n'


def read_embedded_project(text):
    for line in text.splitlines():
        if line.startswith('; ShengaoProject: '):
            return json.loads(base64.b64decode(line.split(': ',1)[1],validate=True))
    raise ValueError('ASS 中没有声稿工程数据')


def export_file(lines,request):
    kind=request.get('format','ass')
    if kind=='ass':
        text=export_ass(lines,resolved=request.get('resolved',True),show_ruby=request.get('show_ruby',True),
                        show_romaji=request.get('show_romaji',True),show_translation=request.get('show_translation',True))
    elif kind=='srt':
        text='\n\n'.join(f'{i}\n{srt_time(line.start)} --> {srt_time(line.end)}\n{line.text}' for i,line in enumerate(lines,1))+'\n'
    elif kind=='txt':
        text='\n'.join(line.text for line in lines)+'\n'
    elif kind=='json':
        text=json.dumps({'version':1,'media':request.get('media',''),'video':request.get('video',''),
                         'api_history':request.get('api_history',[]),'lines':[line.to_dict() for line in lines]},ensure_ascii=False,indent=2)
    else:
        raise ValueError('不支持的导出格式')
    path=Path(request['output'])
    if not path.parent.is_dir():
        raise ValueError('导出目录不存在')
    fd,temp=tempfile.mkstemp(prefix=path.stem+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8-sig' if kind=='ass' else 'utf-8',newline='\n') as stream:
            stream.write(text)
        os.replace(temp,path)
    finally:
        Path(temp).unlink(missing_ok=True)
    return {'output':str(path),'line_count':len(lines)}
