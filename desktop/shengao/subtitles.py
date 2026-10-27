"""One resolved ASS composition for live preview, sample and final encode."""
import base64
import json
from dataclasses import dataclass,replace
from pathlib import Path
from .fonts import resolve_font,metric_font,missing,family_name,traits,font_weight,AssMetrics
from studio_backend.model import literal
from studio_backend.export import ass_time
from .furigana import ruby_spans,unit_ruby_spans,reading_fragments,kanji
from .presentation import display_windows,WindowIndex


class CompositionCache:
    """Private line event reuse; completed output is still the full ASS."""
    def __init__(self):self.entries={};self.font_stamp=None

    def begin(self,paths,stamp=None):
        from .project import file_stamp
        if stamp is None:stamp=[file_stamp(path) for path in paths]
        if stamp!=self.font_stamp:self.entries={};self.font_stamp=stamp
        return {}

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

class _Measurements:
    """Bounded exact advances for this composition only, never across edits."""
    def __init__(self):self.fonts=set();self.widths={}


class _MeasuredFont:
    def __init__(self,metrics,measurements):self.metrics=metrics;self.measurements=measurements
    def getmetrics(self):return self.metrics.getmetrics()
    def getlength(self,text):
        font=self.metrics.font;cache=self.measurements
        if type(text) is not str or len(text)>512:return self.metrics.getlength(text)
        if font not in cache.fonts:
            if len(cache.fonts)>=48:return self.metrics.getlength(text)
            cache.fonts.add(font)
        key=(font,text)
        if key not in cache.widths:
            if len(cache.widths)>=4096:return self.metrics.getlength(text)
            cache.widths[key]=font.getlength(text)
        return cache.widths[key]*self.metrics.scale


def _measurement_font(metrics,measurements):
    if measurements is not None and type(metrics) is AssMetrics:
        from PIL import ImageFont
        if type(metrics.font) is ImageFont.FreeTypeFont:return _MeasuredFont(metrics,measurements)
    return metrics


def layout_line(line,style,font_paths=None,*,_measurements=None):
    main,ruby_path=font_paths or (resolve_font(style.font_file,style.font),resolve_font(style.ruby_font_file,style.ruby_font))
    size,ruby_size=style.size,style.ruby_size
    groups=pieces(line)
    for _ in range(12):
        mf=_measurement_font(metric_font(str(main),size,style.font),_measurements)
        rf=_measurement_font(metric_font(str(ruby_path),ruby_size,style.ruby_font),_measurements)
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

def lane_layout(project,window,windows,line_style=None,layouts=None,overlaps=None):
    """Size only against neighbouring displays, never a distant bad match.

    Dense, provisional overlaps remain in-frame and receive a layout warning.
    They cannot move an earlier, correctly timed phrase out of the video.
    """
    s=line_style or project.style
    if s.display_mode!='alternating':return s,1,0,1.
    if getattr(project,'layout_styles',{}):
        if layouts is None:
            from .line_layout import resolved_layouts
            layouts=resolved_layouts(project)
        neighbours=[(*layouts[i],windows[i]) for i in overlaps] if overlaps is not None else [(line,style,w) for (line,style),w in zip(layouts,windows) if w.start<window.end and window.start<w.end]
        count=max(2,max((w.slot+1 for line,style,w in neighbours),default=2))
        def line_band(line,style):
            result=(line.text.count('\n')+1)*(style.size+(style.ruby_size+24 if style.show_ruby else 16))+32
            if style.show_romaji and line.romaji:result+=style.romaji_size+20
            if style.show_translation and line.translation:result+=style.translation_size+20
            return result
        band=max((line_band(line,style) for line,style,w in neighbours),default=line_band(project.lines[0],s) if project.lines else 32)
    else:
        neighbours=[(project.lines[i],windows[i]) for i in overlaps] if overlaps is not None else [(line,w) for line,w in zip(project.lines,windows) if w.start<window.end and window.start<w.end]
        count=max(2,max((w.slot+1 for line,w in neighbours),default=2))
        row_count=max((line.text.count('\n')+1 for line,w in neighbours),default=1)
        band=row_count*(s.size+(s.ruby_size+24 if s.show_ruby else 16))+32
        if s.show_romaji and any(line.romaji for line,w in neighbours):band+=s.romaji_size+20
        if s.show_translation and any(line.translation for line,w in neighbours):band+=s.translation_size+20
    scale=min(1.,944/(count*band))
    effective=replace(s,**{name:getattr(s,name)*scale for name in ('size','ruby_size','romaji_size','translation_size','outline','shadow','glow')})
    return effective,count,band*scale,scale


class _LaneLayoutIndex:
    """Fresh geometry summaries for one complete composition, never revisions."""
    def __init__(self,project,windows,layouts):
        self.project=project;self.windows=windows;self.local=bool(project.layout_styles);self.scaled={};self.index=None;self.common_features=None;self.signatures={}
        if project.style.display_mode=='alternating':
            if self.local:metrics=[(window.slot+1,self.band(line,style)) for (line,style),window in zip(layouts,windows)]
            else:
                metrics=[(window.slot+1,line.text.count('\n')+1,bool(line.romaji),bool(line.translation)) for line,window in zip(project.lines,windows)]
                if metrics and all(type(value) is str for line in project.lines for value in (line.text,line.romaji,line.translation)) and all(value[1:]==metrics[0][1:] for value in metrics):
                    self.common_features=metrics[0][1:];metrics=[(value[0],) for value in metrics]
            self.index=WindowIndex(windows,metrics)

    @staticmethod
    def band(line,style):
        value=(line.text.count('\n')+1)*(style.size+(style.ruby_size+24 if style.show_ruby else 16))+32
        if style.show_romaji and line.romaji:value+=style.romaji_size+20
        if style.show_translation and line.translation:value+=style.translation_size+20
        return value

    def get(self,window,style,*,_token=None):
        if style.display_mode!='alternating':return style,1,0,1.
        maxima=self.index.maximum(window)
        count=max(2,maxima[0] if maxima is not None else 2)
        if self.local:band=maxima[1] if maxima is not None else self.band(self.project.lines[0],style) if self.project.lines else 32
        else:
            features=(self.common_features if self.common_features is not None else maxima[1:]) if maxima is not None else (1,False,False)
            rows,has_romaji,has_translation=features
            band=rows*(style.size+(style.ruby_size+24 if style.show_ruby else 16))+32
            if style.show_romaji and has_romaji:band+=style.romaji_size+20
            if style.show_translation and has_translation:band+=style.translation_size+20
        if _token is None:
            values=tuple(getattr(style,name) for name in style.__dataclass_fields__)
            kinds=tuple(map(type,values));_token=(kinds,values) if all(kind in (str,int,float,bool,type(None)) for kind in kinds) else None
        key=(*_token,count,band) if _token is not None else None
        if key is not None and key in self.scaled:return self.scaled[key]
        scale=min(1.,944/(count*band))
        effective=replace(style,**{name:getattr(style,name)*scale for name in ('size','ruby_size','romaji_size','translation_size','outline','shadow','glow')})
        if key is not None:self.signatures[id(effective)]=(effective,tuple(getattr(effective,name) for name in effective.__dataclass_fields__))
        result=(effective,count,band*scale,scale)
        if key is not None:self.scaled[key]=result
        return result

    def signature(self,style):
        record=self.signatures.get(id(style))
        return record[1] if record is not None and record[0] is style else tuple(getattr(style,name) for name in style.__dataclass_fields__)

    def uniform(self,style,*,_token=None):
        """One geometry for known, nonempty windows in ordinary two lanes.

        Every window overlaps itself. With identical line features and no
        slot above one, every overlap maximum therefore has count two and
        the same band. Arbitrary queries still use get(), including gaps.
        This is derived afresh for this composition, never from a revision.
        """
        if (_token is None or self.common_features is None or self.index is None or
            self.index.scalar_metrics is None or self.index.scalar_metrics[1]>2 or
            not all(window.start<window.end for window in self.windows)):return None
        return self.get(self.windows[0],style,_token=_token)

def compose(project,embed=False,*,preview_time=None,preview_line_id=None,cache=None,_snapshot=None,_windows=None,_font_stamp=None):
    """Compose the whole export, or exact visible events for private thumbnails.

    Preview filtering retains full-project lane context. File exports and the
    main player use the default complete composition.
    """
    return _compose(project,embed,preview_time=preview_time,preview_line_id=preview_line_id,cache=cache,_snapshot=_snapshot,_windows=_windows,_font_stamp=_font_stamp)


def _compose_after_edit(project,*,cache,_snapshot,_windows,_font_stamp):
    """Only for a successful synchronous History transaction, before UI binding.

    History has fully validated this detached candidate. No event processing or
    live-widget binding may occur between that transaction and this call.
    Independent previews and exports must continue to use compose().
    """
    return _compose(project,cache=cache,_snapshot=_snapshot,_windows=_windows,_font_stamp=_font_stamp,_validated=True)


def _compose(project,embed=False,*,preview_time=None,preview_line_id=None,cache=None,_snapshot=None,_windows=None,_font_stamp=None,_validated=False):
    if preview_time is not None and (type(preview_time) is not int or preview_time<0):raise ValueError('预览时间无效')
    if preview_line_id is not None and (preview_time is None or not isinstance(preview_line_id,str) or not any(line.id==preview_line_id for line in project.lines)):raise ValueError('本句预览需要有效的歌词和时间')
    if not _validated:project.validate()
    if project.source_ass_active and project.source_ass:
        if preview_line_id is not None:raise ValueError('保留原 ASS 时不能筛出单句；请先明确选择声稿样式')
        from .subtitle_import import preserve_ass
        text=preserve_ass(project)
        from .song_info import append_ass
        text=append_ass(text,project)
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
          'PlayResX: 1920','PlayResY: 1080','YCbCr Matrix: None','WrapStyle: 0','ScaledBorderAndShadow: yes','',
          '[V4+ Styles]',
          'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
          style_row('Lyrics',main_family,style.size,style,font_file=main),style_row('Ruby',ruby_family,style.ruby_size,style,font_file=ruby),
          style_row('Romaji',main_family,style.romaji_size,style,highlight=False,font_file=main),style_row('Translation',trans_family,style.translation_size,style,highlight=False,font_file=translated),'',
          '[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    from .line_layout import resolved_layouts
    windows=display_windows(project) if _windows is None else _windows;layouts=resolved_layouts(project);lane_index=_LaneLayoutIndex(project,windows,layouts)
    next_entries=cache.begin((main,ruby,translated),_font_stamp) if cache is not None else None
    line_snapshots={line['id']:line for line in _snapshot['lines']} if cache is not None and _snapshot is not None else {}
    layout_snapshots=_snapshot['layout_styles'] if _snapshot is not None else None
    style_key=tuple(getattr(style,name) for name in style.__dataclass_fields__)
    from .project import Style
    kinds=tuple(map(type,style_key));style_token=(kinds,style_key) if type(style) is Style and all(kind in (str,int,float,bool,type(None)) for kind in kinds) else None
    uniform_geometry=lane_index.uniform(style,_token=style_token)
    measurements=_Measurements()
    for original,(line,line_style),window in zip(project.lines,layouts,windows):
        if preview_line_id is not None and line.id!=preview_line_id:continue
        # ASS rounds times to centiseconds, and short colour phases last at
        # least 10 ms. Keep a conservative boundary margin; libass decides
        # visibility, exactly as it does for the complete composition.
        if preview_time is not None and not window.start-10<=preview_time<window.end+20:continue
        effective,slot_count,band_height,scale=uniform_geometry if uniform_geometry is not None else lane_index.get(window,line_style,_token=style_token if line_style is style else None)
        from .color_states import effective_profile
        palette=effective_profile(project.color_styles,line.id,validated=True);color_bounds=[]
        if cache is not None:
            import copy
            source=line_snapshots[original.id] if line_snapshots else original.to_dict()
            setting=layout_snapshots.get(line.id) if layout_snapshots is not None else copy.deepcopy(project.layout_styles.get(line.id))
            key=(source,setting,style_key,style_key if effective is style else lane_index.signature(effective),window.start,window.end,window.slot,slot_count,band_height,scale,palette)
            previous=cache.entries.get(line.id)
            if previous is not None and previous[0]==key:rows.extend(previous[1]);next_entries[line.id]=previous;continue
            row_begin=len(rows)
        mf,rf,size,ruby_size,widths,width=layout_line(line,effective,(main,ruby),_measurements=measurements)
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
        for (_,text,row,allow_ruby),w in zip(segments,widths):row_widths[row]=row_widths.get(row,0)+w
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
        if cache is not None:next_entries[line.id]=(key,tuple(rows[row_begin:]))
    if cache is not None:cache.entries=next_entries
    text='\n'.join(rows)+'\n'
    from .song_info import append_ass
    if preview_line_id is None:text=append_ass(text,project)
    if embed:
        data=base64.b64encode(json.dumps(project.to_dict(),ensure_ascii=False,separators=(',',':')).encode()).decode()
        text='; ShengaoProject: '+data+'\n'+text
    return text

def layout_issues(project,line_ids=None,*,include_song=True):
    from .song_info import issues as song_issues
    result=song_issues(project,check_overlap=True) if include_song else [];s=project.style
    if project.source_ass_active:
        from .subtitle_import import needed_fonts
        from .fonts import find_font
        for family in needed_fonts(project.source_ass):
            if not (project.font_assets.get(family) and Path(project.font_assets[family]).is_file()) and not find_font(family):result.append((None,'原 ASS 字体文件无法定位：'+family+'；可添加本地字体'))
        return result
    main=resolve_font(s.font_file,s.font);ruby=resolve_font(s.ruby_font_file,s.ruby_font);trans=resolve_font(s.translation_font_file,s.translation_font)
    for value,label in [(s.font_file,'原文'),(s.ruby_font_file,'假名'),(s.translation_font_file,'译文')]:
        if value and not Path(value).is_file():result.append((None,f'{label}字体文件已丢失，目前使用备用字体；请重新添加字体'))
    from .line_layout import resolved_layouts,setting_issues
    for original,(line,local_style) in zip(project.lines,resolved_layouts(project)):
        if line_ids is not None and line.id not in line_ids:continue
        result.extend((line.id,message) for message in setting_issues(original,project.layout_styles.get(line.id)))
        for path,text,label,family in [(main,line.text,'原文',s.font),(ruby,''.join(u.kana for u in line.units),'假名',s.ruby_font),(main,line.romaji,'罗马音',s.font),(trans,line.translation,'译文',s.translation_font)]:
            absent=missing(path,text,family)
            if absent:result.append((line.id,f'{label}字体缺少：{absent[:24]}'))
        mf,rf,size,ruby_size,widths,width=layout_line(line,local_style,(main,ruby))
        if size<local_style.size:result.append((line.id,f'本行较长，原文已缩小为 {size}；可拆行或降低字号'))
        if width>1792:result.append((line.id,'原文仍超出安全区域，请拆成两行'))
        if s.show_ruby and any(a.scale<.6 for a in ruby_layout(pieces(line),widths,rf,mf)):result.append((line.id,'相邻假名较密，已仅压缩假名宽度；可降低假名字号以改善阅读'))
        if s.show_ruby:
            for unit in line.units:
                spans=unit_ruby_spans(unit)
                if unit.reading_options.get('ruby',{}).get('mode','auto')=='auto' and spans==((0,len(unit.text),0,len(unit.kana)),) and any('\u3040'<=c<='\u30ff' and not kanji(c) for c in unit.text):
                    result.append((line.id,'有假名无法与汉字唯一对应，暂用整词注音；请核对读音或拆分该词组'));break
        if any('\n' in u.text.strip('\n') and u.kana for u in line.units):result.append((line.id,'有词组跨越多行，请拆分该词组后分别核对假名'))
        if s.show_romaji and text_width(metric_font(str(main),local_style.romaji_size,s.font),line.romaji)>1792:result.append((line.id,'罗马音较长，请缩小字号或拆行'))
        if s.show_translation and text_width(metric_font(str(trans),local_style.translation_size,s.translation_font),line.translation)>1792:result.append((line.id,'译文较长，请缩小字号或拆行'))
    if s.display_mode=='alternating':
        for i,(line,window) in enumerate(zip(project.lines,display_windows(project))):
            if line_ids is not None and line.id not in line_ids:continue
            if window.slot>=2:result.append((line.id,'有三句以上字幕同时显示，已增加临时字幕行；请检查留屏时间或重复歌词匹配'))
            if i and line.start<project.lines[i-1].start:result.append((line.id,'本句演唱早于上一句，请检查重复歌词的匹配顺序'))
    return result
