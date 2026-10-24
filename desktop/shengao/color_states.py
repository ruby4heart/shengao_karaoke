"""Validated colour profiles shared by the editor, ASS and saved projects.

An empty configuration means legacy rendering. A per-line profile is explicit
and remains independent of later global edits until the user restores inheritance.
"""
import copy
import re

STATES=('waiting','singing','sung')
ROLES=('lyrics','ruby','romaji','translation')
CHANNELS=('primary','secondary','outline','shadow')
PRESETS=(('blue','白字／蓝色扫亮'),('gold','高对比黄字'),('ruby','日式蓝字／白色描边'))


def ink(color,opacity=100):return {'color':color,'opacity':opacity}


def default_profile(style):
    layers={}
    for role in ROLES:
        active=style.highlight if role in {'lyrics','ruby'} else style.color
        layers[role]={}
        for state in STATES:
            primary=active if state!='waiting' else style.color
            secondary=style.color if state!='sung' else active
            layers[role][state]={'primary':ink(primary),'secondary':ink(secondary),
                'outline':ink(style.outline_color),'shadow':ink('#000000',50)}
    return {'version':1,'layers':layers,'motion':{'fill':'sweep','outline':'line','shadow':'line'},
        'box':{'enabled':False,'padding':12,'radius':0,'states':{state:ink('#000000',50) for state in STATES}}}


def preset_profile(style,name):
    if name not in {key for key,label in PRESETS}:raise ValueError('未知颜色预设')
    result=default_profile(style)
    highlight={'blue':'#58abf4','gold':'#ffd54f','ruby':'#58abf4'}[name]
    for role in ROLES:
        for phase in STATES:
            state=result['layers'][role][phase]
            state.update(primary=ink(highlight if phase=='singing' and role in {'lyrics','ruby'} else '#ffffff'),secondary=ink('#ffffff'),outline=ink('#10151d'),shadow=ink('#000000',50))
            if name=='ruby' and phase=='singing':state['outline']=ink('#ffffff')
    if name=='ruby':result['motion'].update(outline='sweep',shadow='sweep')
    if name=='gold':result['box'].update(enabled=True,padding=14,radius=8)
    return result


def keys(value,expected,message):
    if not isinstance(value,dict) or set(value)!=set(expected):raise ValueError(message)


def validate_ink(value):
    keys(value,('color','opacity'),'颜色与不透明度记录无效')
    if not isinstance(value['color'],str) or not re.fullmatch('#[0-9a-fA-F]{6}',value['color']):raise ValueError('颜色应为 #RRGGBB')
    if type(value['opacity']) is not int or not 0<=value['opacity']<=100:raise ValueError('不透明度应为 0 至 100')


def validate_profile(value):
    keys(value,('version','layers','motion','box'),'颜色方案结构无效')
    if type(value['version']) is not int or value['version']!=1:raise ValueError('颜色方案版本无效')
    keys(value['layers'],ROLES,'文字层颜色方案不完整')
    for layer in value['layers'].values():
        keys(layer,STATES,'待唱、演唱中、唱完的配色不完整')
        for state in layer.values():
            keys(state,CHANNELS,'文字、次色、描边与阴影配色不完整')
            for channel in state.values():validate_ink(channel)
    motion=value['motion'];keys(motion,('fill','outline','shadow'),'颜色扫描选项无效')
    if motion['fill'] not in {'sweep','instant'} or any(motion[k] not in {'line','sweep'} for k in ('outline','shadow')):raise ValueError('颜色扫描方式无效')
    box=value['box'];keys(box,('enabled','padding','radius','states'),'背景底板选项无效')
    if type(box['enabled']) is not bool:raise ValueError('背景底板开关无效')
    for field,limit in [('padding',100),('radius',100)]:
        if type(box[field]) is not int or not 0<=box[field]<=limit:raise ValueError('背景底板边距或圆角超出范围')
    keys(box['states'],STATES,'背景底板状态配色不完整')
    for channel in box['states'].values():validate_ink(channel)


def validate_settings(value,line_ids=None):
    if value=={}:return
    keys(value,('global','lines'),'工程颜色设置无效')
    if value['global'] is not None:validate_profile(value['global'])
    if not isinstance(value['lines'],dict) or len(value['lines'])>100000:raise ValueError('指定歌词配色列表无效')
    for uid,profile in value['lines'].items():
        if not isinstance(uid,str) or not uid or line_ids is not None and uid not in line_ids:raise ValueError('指定歌词配色没有对应歌词')
        validate_profile(profile)


def effective_profile(settings,line_id,validated=False):
    if not settings:return None
    if not validated:validate_settings(settings)
    return copy.deepcopy(settings['lines'].get(line_id,settings['global']))


def update_settings(settings,profile,line_ids=None):
    """Return one atomic candidate; never mutate the project or lyric timings."""
    validate_settings(settings)
    if profile is not None:validate_profile(profile)
    result=copy.deepcopy(settings) if settings else {'global':None,'lines':{}}
    if line_ids is None:result['global']=copy.deepcopy(profile)
    else:
        ids=list(line_ids)
        if not ids or any(not isinstance(uid,str) or not uid for uid in ids) or len(ids)!=len(set(ids)):raise ValueError('请明确选择不重复的目标歌词')
        for uid in ids:
            if profile is None:result['lines'].pop(uid,None)
            else:result['lines'][uid]=copy.deepcopy(profile)
    return result if result['global'] is not None or result['lines'] else {}


def phase_at(position,start,end):
    return 'waiting' if position<start else 'singing' if position<end else 'sung'


def segments(window_start,window_end,singing_start,singing_end):
    """Half-open presentation segments, independent of the singing axis."""
    points=sorted({window_start,window_end,*[v for v in (singing_start,singing_end) if window_start<v<window_end]})
    return [(a,b,phase_at(a,singing_start,singing_end)) for a,b in zip(points,points[1:]) if b>a]


def ass_ink(value,channel):
    validate_ink(value)
    if type(channel) is not int or channel not in (1,2,3,4):raise ValueError('ASS 颜色通道无效')
    rgb=value['color'];bgr=rgb[5:7]+rgb[3:5]+rgb[1:3]
    alpha=round((100-value['opacity'])*255/100)
    return f'\\{channel}c&H{bgr}&\\{channel}a&H{alpha:02X}&'
