"""One resolved ASS composition for live preview, sample and final encode."""
import base64
import json
from dataclasses import dataclass,replace
from pathlib import Path
from .fonts import resolve_font,metric_font,missing,family_name,traits,font_weight
from studio_backend.model import literal
from studio_backend.export import ass_time
from .furigana import ruby_spans,unit_ruby_spans,reading_fragments,kanji
from .presentation import display_windows

def color(value):
    return '&H00'+value[5:7]+value[3:5]+value[1:3]

def style_row(name,font,size,style,alignment=5,highlight=True,font_file=None):
    # Names from font metadata cannot inject ASS fields.
    font=font.replace(',',' ').replace('\n',' ')
    bold,italic=traits(str(font_file),font) if font_file else (False,False)
    return f'Style: {name},{font},{size},{color(style.highlight if highlight else style.color)},{color(style.color)},{color(style.outline_color)},&H80000000,{-1 if bold else 0},{-1 if italic else 0},0,0,100,100,0,0,1,{style.outline},{style.shadow},{alignment},50,50,50,1'

def dialogue(start,end,style,text,layer=0,comment=False):
    return f'{"Comment" if comment else "Dialogue"}: {layer},{ass_time(start)},{ass_time(max(start+10,end))},{style},,0,0,0,,{text}'

def ktag(start,end,line_start):
    gap=round(start/10)-round(line_start/10)
    return ('{\\k'+str(max(0,gap))+'}' if gap>0 else '')+'{\\kf'+str(max(0,round(end/10)-round(start/10)))+'}'

def text_width(font,text):return max((font.getlength(part) for part in text.split('\n')),default=0)

def pieces(line):
    result=[];row=0
    for unit in line.units:
        parts=unit.text.split('\n');count=sum(bool(text) for text in parts)
        for index,text in enumerate(parts):
            if index:row+=1
            if text:result.append((unit,text,row,count==1))
    return result

def layout_line(line,style):
    main=resolve_font(style.font_file,style.font);ruby_path=resolve_font(style.ruby_font_file,style.ruby_font)
    size,ruby_size=style.size,style.ruby_size
    groups=pieces(line)
    for _ in range(12):
        mf,rf=metric_font(str(main),size,style.font),metric_font(str(ruby_path),ruby_size,style.ruby_font)
        # Ruby must never insert spacing into the original lyric baseline.
        widths=[mf.getlength(text) for u,text,row,allow_ruby in groups]
        row_widths={}
        for (_,text,row,allow_ruby),w in zip(groups,widths):row_widths[row]=row_widths.get(row,0)+w
        width=max(row_widths.values(),default=0) if groups else text_width(mf,line.text)
        if width<=1792 or size<=14:break
        scale=min(.95,1792/width);size=max(14,int(size*scale));ruby_size=max(9,int(ruby_size*scale))
    return mf,rf,size,ruby_size,widths,width

@dataclass
class RubyPlacement:
    index:int
    reading_start:int
    reading_end:int
    center:float
    scale:float

def ruby_layout(groups,widths,font,main_font,row_lefts=None):
    """Fit annotations above the unchanged baseline, borrowing unannotated space.

    Adjacent annotation centres partition the available row. Only ruby is
    condensed when necessary; all of its timed fragments share the same scale.
    """
    rows={};result=[]
    for index,((unit,text,row,allowed),width) in enumerate(zip(groups,widths)):
        rows.setdefault(row,[]).append((index,unit,text,allowed,width))
    for row,items in rows.items():
        left=row_lefts[row] if row_lefts is not None else (1920-sum(item[4] for item in items))/2;annotations=[]
        for index,unit,text,allowed,width in items:
            if allowed and unit.kana and (unit.kana!=text or unit.reading_options.get('ruby',{}).get('mode') in {'whole','custom'}):
                for a,b,rs,re in unit_ruby_spans(unit,text):
                    center=left+(main_font.getlength(text[:a])+main_font.getlength(text[:b]))/2
                    annotations.append((index,center,font.getlength(unit.kana[rs:re]),rs,re))
            left+=width
        for n,(index,center,natural,rs,re) in enumerate(annotations):
            a=(annotations[n-1][1]+center)/2 if n else 64
            b=(center+annotations[n+1][1])/2 if n+1<len(annotations) else 1856
            width=min(natural,max(1,b-a-4));scale=width/natural if natural else 1
            center=max(a+2+width/2,min(b-2-width/2,center))
            result.append(RubyPlacement(index,rs,re,center,scale))
    return result

def styled_dialogue(rows,window,style,text,layer,settings,highlight_start=None):
    shape=f'{{\\bord{settings.outline:.3f}\\shad{settings.shadow:.3f}}}'
    if settings.glow and highlight_start is not None:
        start=max(0,highlight_start-window.start)
        rgb=color(settings.highlight)[4:]
        halo=f'{{\\1a&HFF&\\2a&HFF&\\3a&HFF&\\bord{settings.outline+settings.glow}\\shad{settings.shadow:.3f}\\blur{settings.glow}\\3c&H{rgb}&\\t({start},{start+100},\\3a&H50&)}}'
        rows.append(dialogue(window.start,window.end,style,halo+text,0))
        text=f'{{\\t({start},{start+100},\\3c&HFFFFFF&)}}'+text
    rows.append(dialogue(window.start,window.end,style,shape+text,layer))

def lane_layout(project,window,windows):
    """Size only against neighbouring displays, never a distant bad match.

    Dense, provisional overlaps remain in-frame and receive a layout warning.
    They cannot move an earlier, correctly timed phrase out of the video.
    """
    s=project.style
    if s.display_mode!='alternating':return s,1,0,1.
    neighbours=[(line,w) for line,w in zip(project.lines,windows) if w.start<window.end and window.start<w.end]
    count=max(2,max((w.slot+1 for line,w in neighbours),default=2))
    row_count=max((line.text.count('\n')+1 for line,w in neighbours),default=1)
    band=row_count*(s.size+(s.ruby_size+24 if s.show_ruby else 16))+32
    if s.show_romaji and any(line.romaji for line,w in neighbours):band+=s.romaji_size+20
    if s.show_translation and any(line.translation for line,w in neighbours):band+=s.translation_size+20
    scale=min(1.,944/(count*band))
    effective=replace(s,**{name:getattr(s,name)*scale for name in ('size','ruby_size','romaji_size','translation_size','outline','shadow','glow')})
    return effective,count,band*scale,scale

def compose(project,embed=False):
    project.validate()
    if project.source_ass_active and project.source_ass:
        from .subtitle_import import preserve_ass
        text=preserve_ass(project)
        if embed:
            data=base64.b64encode(json.dumps(project.to_dict(),ensure_ascii=False,separators=(',',':')).encode()).decode()
            text='; ShengaoProject: '+data+'\n'+text
        return text
    style=project.style
    main=resolve_font(style.font_file,style.font);ruby=resolve_font(style.ruby_font_file,style.ruby_font)
    translated=resolve_font(style.translation_font_file,style.translation_font)
    main_family=family_name(str(main),style.font);ruby_family=family_name(str(ruby),style.ruby_font);trans_family=family_name(str(translated),style.translation_font)
    main_weight=font_weight(str(main),style.font);ruby_weight=font_weight(str(ruby),style.ruby_font);trans_weight=font_weight(str(translated),style.translation_font)
    rows=['[Script Info]','Title: Shengao Independent Studio','ScriptType: v4.00+',
          'PlayResX: 1920','PlayResY: 1080','WrapStyle: 0','ScaledBorderAndShadow: yes','',
          '[V4+ Styles]',
          'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
          style_row('Lyrics',main_family,style.size,style,font_file=main),style_row('Ruby',ruby_family,style.ruby_size,style,font_file=ruby),
          style_row('Romaji',main_family,style.romaji_size,style,highlight=False,font_file=main),style_row('Translation',trans_family,style.translation_size,style,highlight=False,font_file=translated),'',
          '[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    windows=display_windows(project)
    for line,window in zip(project.lines,windows):
        effective,slot_count,band_height,scale=lane_layout(project,window,windows)
        mf,rf,size,ruby_size,widths,width=layout_line(line,effective)
        from .color_states import effective_profile
        palette=effective_profile(project.color_styles,line.id,validated=True);color_bounds=[]
        def colored(role,text,layer,font,cx,cy,text_width,font_size,timing=None,advance=None,lines=1):
            if palette is None:return False
            from .color_ass import component_events
            height=max(font_size,sum(font.getmetrics()))*lines
            margin=effective.outline+effective.shadow+effective.glow
            color_bounds.append((cx-text_width/2-margin,cy-height/2-margin,cx+text_width/2+margin,cy+height/2+margin))
            rows.extend(component_events(palette,role,text,window,(line.start,line.end),layer,effective.outline,effective.shadow,effective.glow,timing,advance,validated=True))
            return True
        base=1080-style.bottom
        trans_y=base-effective.translation_size/2
        latin_y=trans_y-(effective.translation_size+20*scale if style.show_translation and line.translation else 0)
        main_y=latin_y-(effective.romaji_size+size/2+16*scale if style.show_romaji and line.romaji else size/2+8*scale)
        segments=pieces(line);row_count=max((row+1 for u,text,row,ruby in segments),default=max(1,len(line.text.split('\n'))))
        row_height=size+(ruby_size+24*scale if style.show_ruby else 16*scale)
        if style.position=='top':
            delta=style.bottom+100-main_y+(row_count-1)*row_height
            main_y+=delta;latin_y+=delta;trans_y+=delta
        elif style.position=='center':
            delta=540-main_y+(row_count-1)*row_height/2;main_y+=delta;latin_y+=delta;trans_y+=delta
        if style.display_mode=='alternating':
            offset=(window.slot if style.position=='top' else window.slot-(slot_count-1)/2 if style.position=='center' else window.slot-slot_count+1)*band_height
            main_y+=offset;latin_y+=offset;trans_y+=offset
            # Large fonts/margins and multi-line drafts must never disappear.
            top=main_y-(row_count-1)*row_height-size/2-(ruby_size+8*scale if style.show_ruby else 0)-effective.outline-effective.glow
            bottom=max(main_y+size/2,latin_y+effective.romaji_size/2 if style.show_romaji and line.romaji else 0,trans_y+effective.translation_size/2 if style.show_translation and line.translation else 0)+effective.outline+effective.glow
            correction=max(0,64-top)-max(0,bottom-1016)
            main_y+=correction;latin_y+=correction;trans_y+=correction
        shape=f'\\bord{effective.outline:.3f}\\shad{effective.shadow:.3f}'
        def row_left(w):
            return (64 if window.slot%2==0 else 1856-w) if style.display_mode=='alternating' else (1920-w)/2
        if not line.units:
            # Keep the unsegmented draft visible before singing, without
            # pretending that it already has syllable timing.
            if style.display_mode!='alternating':
                x=row_left(width)+width/2;y=main_y-(row_count-1)*size/2
                body=f'{{\\an5\\q2\\pos({x:.2f},{y:.2f})\\fs{size}\\b{main_weight}{shape}\\1c{color(style.color)}}}'+literal(line.text)
                if not colored('lyrics',body,1,mf,x,y,width,size,lines=row_count):rows.append(dialogue(window.start,window.end,'Lyrics',body,1))
            else:
                for n,part in enumerate(line.text.split('\n')):
                    w=mf.getlength(part);x=row_left(w)+w/2;y=main_y-(row_count-1-n)*row_height
                    body=f'{{\\an5\\q2\\pos({x:.2f},{y:.2f})\\fs{size}\\b{main_weight}{shape}\\1c{color(style.color)}}}'+literal(part)
                    if not colored('lyrics',body,1,mf,x,y,w,size):rows.append(dialogue(window.start,window.end,'Lyrics',body,1))
        row_widths={}
        for (_,text,row,ruby),w in zip(segments,widths):row_widths[row]=row_widths.get(row,0)+w
        positions={row:row_left(w) for row,w in row_widths.items()}
        annotations=ruby_layout(segments,widths,rf,mf,positions)
        for index,((unit,text,row,can_ruby),w) in enumerate(zip(segments,widths)):
            center=positions[row]+w/2;y_main=main_y-(row_count-1-row)*row_height
            tags=f'{{\\an5\\q2\\pos({center:.2f},{y_main:.2f})\\fs{size}\\b{main_weight}}}'
            body=tags+ktag(unit.start,unit.end,window.start)+literal(text)
            if not colored('lyrics',body,1,mf,center,y_main,w,size,(unit.start,unit.end),(positions[row],positions[row]+w)):
                styled_dialogue(rows,window,'Lyrics',body,1,effective,unit.start)
            if style.show_ruby:
                y=y_main-size/2-ruby_size/2-8*scale
                for annotation in (a for a in annotations if a.index==index):
                    annotation_scale=annotation.scale;reading=unit.kana[annotation.reading_start:annotation.reading_end]
                    left=annotation.center-rf.getlength(reading)*annotation_scale/2
                    for kana,start,end in reading_fragments(unit,annotation.reading_start,annotation.reading_end):
                        part_width=rf.getlength(kana)*annotation_scale;cx=left+part_width/2
                        tags=f'{{\\an5\\q2\\pos({cx:.2f},{y:.2f})\\fs{ruby_size}\\b{ruby_weight}\\fscx{annotation_scale*100:.2f}}}'
                        body=tags+ktag(start,end,window.start)+literal(kana)
                        if not colored('ruby',body,2,rf,cx,y,part_width,ruby_size,(start,end),(left,left+part_width)):
                            styled_dialogue(rows,window,'Ruby',body,2,effective,start)
                        left+=part_width
            positions[row]+=w
        if style.show_romaji and line.romaji:
            w=text_width(metric_font(str(main),effective.romaji_size,style.font),line.romaji);x=row_left(w)+w/2
            body=f'{{\\an5\\q2\\pos({x:.2f},{latin_y:.2f})\\fs{effective.romaji_size}\\b{main_weight}{shape}}}'+literal(line.romaji)
            font=metric_font(str(main),effective.romaji_size,style.font)
            if not colored('romaji',body,3,font,x,latin_y,w,effective.romaji_size,lines=line.romaji.count('\n')+1):rows.append(dialogue(window.start,window.end,'Romaji',body,3))
        if style.show_translation and line.translation:
            w=text_width(metric_font(str(translated),effective.translation_size,style.translation_font),line.translation);x=row_left(w)+w/2
            body=f'{{\\an5\\q2\\pos({x:.2f},{trans_y:.2f})\\fs{effective.translation_size}\\b{trans_weight}{shape}}}'+literal(line.translation)
            font=metric_font(str(translated),effective.translation_size,style.translation_font)
            if not colored('translation',body,3,font,x,trans_y,w,effective.translation_size,lines=line.translation.count('\n')+1):rows.append(dialogue(window.start,window.end,'Translation',body,3))
        if palette is not None and color_bounds:
            from .color_ass import box_events
            bounds=(min(v[0] for v in color_bounds),min(v[1] for v in color_bounds),max(v[2] for v in color_bounds),max(v[3] for v in color_bounds))
            rows.extend(box_events(palette,window,(line.start,line.end),bounds))
    text='\n'.join(rows)+'\n'
    if embed:
        data=base64.b64encode(json.dumps(project.to_dict(),ensure_ascii=False,separators=(',',':')).encode()).decode()
        text='; ShengaoProject: '+data+'\n'+text
    return text

def layout_issues(project):
    result=[];s=project.style
    if project.source_ass_active:
        from .subtitle_import import needed_fonts
        from .fonts import find_font
        for family in needed_fonts(project.source_ass):
            if not (project.font_assets.get(family) and Path(project.font_assets[family]).is_file()) and not find_font(family):result.append((None,'原 ASS 字体文件无法定位：'+family+'；可添加本地字体'))
        return result
    main=resolve_font(s.font_file,s.font);ruby=resolve_font(s.ruby_font_file,s.ruby_font);trans=resolve_font(s.translation_font_file,s.translation_font)
    for value,label in [(s.font_file,'原文'),(s.ruby_font_file,'假名'),(s.translation_font_file,'译文')]:
        if value and not Path(value).is_file():result.append((None,f'{label}字体文件已丢失，目前使用备用字体；请重新添加字体'))
    for line in project.lines:
        for path,text,label,family in [(main,line.text,'原文',s.font),(ruby,''.join(u.kana for u in line.units),'假名',s.ruby_font),(main,line.romaji,'罗马音',s.font),(trans,line.translation,'译文',s.translation_font)]:
            absent=missing(path,text,family)
            if absent:result.append((line.id,f'{label}字体缺少：{absent[:24]}'))
        mf,rf,size,ruby_size,widths,width=layout_line(line,s)
        if size<s.size:result.append((line.id,f'本行较长，原文已缩小为 {size}；可拆行或降低字号'))
        if width>1792:result.append((line.id,'原文仍超出安全区域，请拆成两行'))
        if s.show_ruby and any(a.scale<.6 for a in ruby_layout(pieces(line),widths,rf,mf)):result.append((line.id,'相邻假名较密，已仅压缩假名宽度；可降低假名字号以改善阅读'))
        if s.show_ruby:
            for unit in line.units:
                spans=unit_ruby_spans(unit)
                if unit.reading_options.get('ruby',{}).get('mode','auto')=='auto' and spans==((0,len(unit.text),0,len(unit.kana)),) and any('\u3040'<=c<='\u30ff' and not kanji(c) for c in unit.text):
                    result.append((line.id,'有假名无法与汉字唯一对应，暂用整词注音；请核对读音或拆分该词组'));break
        if any('\n' in u.text.strip('\n') and u.kana for u in line.units):result.append((line.id,'有词组跨越多行，请拆分该词组后分别核对假名'))
        if s.show_romaji and text_width(metric_font(str(main),s.romaji_size,s.font),line.romaji)>1792:result.append((line.id,'罗马音较长，请缩小字号或拆行'))
        if s.show_translation and text_width(metric_font(str(trans),s.translation_size,s.translation_font),line.translation)>1792:result.append((line.id,'译文较长，请缩小字号或拆行'))
    if s.display_mode=='alternating':
        for i,(line,window) in enumerate(zip(project.lines,display_windows(project))):
            if window.slot>=2:result.append((line.id,'有三句以上同时演唱，已增加临时字幕行；请检查是否误匹配了重复歌词'))
            if i and line.start<project.lines[i-1].start:result.append((line.id,'本句演唱早于上一句，请检查重复歌词的匹配顺序'))
    return result
