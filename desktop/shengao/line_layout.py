"""Per-line appearance and display-only word wrapping; source text stays put."""
import copy,unicodedata
from dataclasses import replace

FIELDS={'version','text','size_percent','ruby_percent','breaks'}


def glyph_boundary(text,position):
    if not 0<position<len(text):return False
    if text[position-1] in '\r\n\u200d' or text[position] in '\r\n\u200d\u309b\u309c\uff9e\uff9f':return False
    return unicodedata.category(text[position]) not in {'Mn','Mc','Me'}


def available_breaks(line):
    if not line.units:return tuple(i for i in range(1,len(line.text)) if glyph_boundary(line.text,i))
    result=[];position=0
    for unit in line.units:
        position+=len(unit.text)
        if glyph_boundary(line.text,position):result.append(position)
    return tuple(result)


def validate_entry(value):
    if not isinstance(value,dict) or set(value)!=FIELDS:raise ValueError('本句排版记录无效')
    if type(value['version']) is not int or value['version']!=1:raise ValueError('本句排版版本无效')
    if not isinstance(value['text'],str) or not 0<len(value['text'])<=20000:raise ValueError('本句换行原文依据无效')
    for name in ('size_percent','ruby_percent'):
        if type(value[name]) is not int or not 25<=value[name]<=200:raise ValueError('本句字号比例应在25%至200%之间')
    breaks=value['breaks']
    if not isinstance(breaks,list) or len(breaks)>8 or any(type(i) is not int or not glyph_boundary(value['text'],i) for i in breaks) or breaks!=sorted(set(breaks)):raise ValueError('本句换行位置无效，最多添加8处且不能拆开组合字符')


def validate_settings(settings,line_ids=None):
    if not isinstance(settings,dict) or len(settings)>100000:raise ValueError('指定歌词排版列表无效')
    for uid,value in settings.items():
        if not isinstance(uid,str) or not uid or line_ids is not None and uid not in line_ids:raise ValueError('本句排版没有对应歌词')
        validate_entry(value)


def make_setting(line,size_percent=100,ruby_percent=100,breaks=()):
    result={'version':1,'text':line.text,'size_percent':size_percent,'ruby_percent':ruby_percent,'breaks':list(breaks)}
    validate_entry(result)
    if any(i not in available_breaks(line) for i in breaks):raise ValueError('请在词组之间换行；需要在词内换行时先到分词处切开，原文和读音保留')
    return None if size_percent==ruby_percent==100 and not breaks else result


def break_status(line,setting):
    if not setting or not setting['breaks']:return (),()
    if setting['text']!=line.text:return (),tuple(setting['breaks'])
    safe=set(available_breaks(line));return tuple(i for i in setting['breaks'] if i in safe),tuple(i for i in setting['breaks'] if i not in safe)


def display_line(line,setting):
    active,_=break_status(line,setting)
    if not active:return line
    view=copy.copy(line);breaks=set(active)
    if line.units:
        view.units=list(line.units);position=0
        for i,unit in enumerate(line.units):
            position+=len(unit.text)
            if position in breaks:view.units[i]=copy.copy(unit);view.units[i].text=unit.text+'\n'
        view.text=''.join(u.text for u in view.units)
    else:view.text=''.join(c+('\n' if i+1 in breaks else '') for i,c in enumerate(line.text))
    return view


def effective_style(style,setting):
    if not setting:return style
    scale=setting['size_percent']/100;ruby=scale*setting['ruby_percent']/100
    values={n:max(8,round(getattr(style,n)*scale)) for n in ('size','romaji_size','translation_size')}
    values['ruby_size']=max(8,round(style.ruby_size*ruby))
    values.update({n:getattr(style,n)*scale for n in ('outline','shadow','glow')})
    return replace(style,**values)


def resolved_layouts(project):
    settings=getattr(project,'layout_styles',{})
    return [(display_line(line,settings.get(line.id)),effective_style(project.style,settings.get(line.id))) for line in project.lines]


def setting_issues(line,setting):
    if not setting:return []
    _,inactive=break_status(line,setting)
    return ['原文或分词已变化，原换行位置保留待复核；可重新选择词界或恢复全局排版'] if inactive else []
