"""Resolve state colours into ordinary ASS events for every output path."""
import math
import re
from .color_states import ass_ink,segments,validate_profile
from .subtitles import dialogue


def clean_tags(text):
    def block(match):
        value=re.sub(r'\\(?:[1234][ca]|alpha|c)&H[0-9a-fA-F]+&?','',match[0])
        value=re.sub(r'\\(?:kf|ko|kt|k|K)-?\d+','',value)
        return re.sub(r'\\(?:bord|shad|blur)-?(?:\d+(?:\.\d*)?|\.\d+)','',value)
    return re.sub(r'\{[^}]*\}',block,text)


def colour_tags(profile,role,phase,after=True,instant_started=False):
    layer=profile['layers'][role];state=layer[phase]
    fill=state['primary'] if phase!='singing' or after or instant_started else state['secondary']
    outline=layer['waiting']['outline'] if phase=='singing' and not after and profile['motion']['outline']=='sweep' else state['outline']
    shadow=layer['waiting']['shadow'] if phase=='singing' and not after and profile['motion']['shadow']=='sweep' else state['shadow']
    return ass_ink(fill,1)+ass_ink(fill,2)+ass_ink(outline,3)+ass_ink(shadow,4)


def component_events(profile,role,text,window,line_range,layer,outline,shadow,glow=0,timing=None,advance=None,validated=False):
    """Keep layout fixed; split only presentation time and complementary masks.

    Untimed text uses whole-line states. No reading or timing is inferred here.
    `advance` is the actual horizontal text extent from the existing layout.
    """
    if not validated:validate_profile(profile)
    if role not in profile['layers']:raise ValueError('未知文字层')
    text=clean_tags(text);result=[]
    for begin,end,phase in segments(window.start,window.end,*line_range):
        points=sorted({begin,end,*[v for v in timing if begin<v<end]}) if timing else [begin,end]
        for a,b in zip(points,points[1:]):
            if b<=a:continue
            running=bool(timing and timing[1]>timing[0] and a>=timing[0] and b<=timing[1] and phase=='singing')
            passed=not timing or a>=timing[1]
            before=bool(timing and b<=timing[0])
            instant=bool(running and profile['motion']['fill']=='instant')
            sweep=running and advance is not None and (profile['motion']['fill']=='sweep' or any(profile['motion'][key]=='sweep' for key in ('outline','shadow')))
            masks=[(not before,'')]
            if sweep:
                left,right=advance
                x0=left+(right-left)*(a-timing[0])/(timing[1]-timing[0]);x1=left+(right-left)*(b-timing[0])/(timing[1]-timing[0])
                duration=b-a
                masks=[(False,f'\\clip({x0:.3f},-4096,4096,4096)\\t(0,{duration},\\clip({x1:.3f},-4096,4096,4096))'),
                       (True,f'\\clip(-4096,-4096,{x0:.3f},4096)\\t(0,{duration},\\clip(-4096,-4096,{x1:.3f},4096))')]
            elif running:masks=[(True,'')]
            elif passed:masks=[(True,'')]
            for after,mask in masks:
                colors=colour_tags(profile,role,phase,after,instant)
                shape=f'\\bord{outline:.3f}\\shad{shadow:.3f}'
                style={'lyrics':'Lyrics','ruby':'Ruby','romaji':'Romaji','translation':'Translation'}[role]
                if glow:
                    halo=f'\\1a&HFF&\\2a&HFF&\\4a&HFF&\\bord{outline+glow:.3f}\\shad0\\blur{glow:.3f}'
                    result.append(dialogue(a,b,style,'{'+colors+halo+mask+'}'+text,0))
                result.append(dialogue(a,b,style,'{'+colors+shape+mask+'}'+text,layer))
    return result


def rounded_rectangle(width,height,radius):
    radius=min(radius,width/2,height/2)
    if radius<=0:return f'm 0 0 l {width:.3f} 0 {width:.3f} {height:.3f} 0 {height:.3f}'
    r=radius;k=.5522847498*r;w=width;h=height
    return (f'm {r:.3f} 0 l {w-r:.3f} 0 b {w-r+k:.3f} 0 {w:.3f} {r-k:.3f} {w:.3f} {r:.3f} '
            f'l {w:.3f} {h-r:.3f} b {w:.3f} {h-r+k:.3f} {w-r+k:.3f} {h:.3f} {w-r:.3f} {h:.3f} '
            f'l {r:.3f} {h:.3f} b {r-k:.3f} {h:.3f} 0 {h-r+k:.3f} 0 {h-r:.3f} '
            f'l 0 {r:.3f} b 0 {r-k:.3f} {r-k:.3f} 0 {r:.3f} 0')


def box_events(profile,window,line_range,bounds):
    validate_profile(profile);box=profile['box']
    if not box['enabled'] or bounds is None:return []
    if len(bounds)!=4 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in bounds):raise ValueError('背景底板范围无效')
    left,top,right,bottom=bounds
    if right<=left or bottom<=top:return []
    padding=box['padding'];left-=padding;top-=padding;right+=padding;bottom+=padding
    drawing=rounded_rectangle(right-left,bottom-top,box['radius']);rows=[]
    for a,b,phase in segments(window.start,window.end,*line_range):
        color=ass_ink(box['states'][phase],1)
        tags=f'{{\\an7\\pos({left:.3f},{top:.3f})\\bord0\\shad0\\blur0\\p1'+color+'}'
        rows.append(dialogue(a,b,'Lyrics',tags+drawing+'{\\p0}',-1))
    return rows
