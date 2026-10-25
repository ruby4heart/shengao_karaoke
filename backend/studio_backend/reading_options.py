"""Validated visual reading correspondence, independent of singing time."""
import copy,unicodedata
from .analysis import kana_only
from .japanese import hiragana,morae


def _plain_kana(text):
    return ''.join(c for c in hiragana(text) if not c.isspace() and not unicodedata.category(c).startswith(('P','Z')))


def validate_ruby(setting,text,kana):
    if not isinstance(setting,dict) or setting.get('mode') not in {'auto','whole','custom','off'}:raise ValueError('注音对应方式无效。')
    mode=setting['mode']
    if set(setting)!=({'mode','spans'} if mode=='custom' else {'mode'}):raise ValueError('注音对应记录格式无效。')
    if mode in {'auto','off'}:return
    if not isinstance(kana,str) or not kana_only(kana):raise ValueError('先填写实际日语假名，再设置注音对应。')
    if mode=='whole':return
    if len(hiragana(kana))!=len(kana):raise ValueError('先使用完整的全角假名，或选择整词注音，避免拆开组合字符。')
    spans=setting['spans']
    if not isinstance(spans,list) or not spans or len(spans)>256:raise ValueError('请指定 1 至 256 段原文与假名范围。')
    boundaries={0};offset=0
    for part in morae(kana):offset+=len(part);boundaries.add(offset)
    ta=ra=0
    for span in spans:
        if not isinstance(span,list) or len(span)!=4 or any(type(n) is not int for n in span):raise ValueError('注音对应范围须为四个整数字符位置。')
        a,b,c,d=span
        if not ta<=a<b<=len(text) or not ra<=c<d<=len(kana):raise ValueError('注音范围越界、重叠或顺序错误。')
        if c not in boundaries or d not in boundaries:raise ValueError('假名范围不能拆开拗音或组合字符。')
        if any(i<len(text) and (unicodedata.category(text[i]).startswith('M') or text[i] in '\ufe0e\ufe0f') for i in (a,b)):raise ValueError('原文范围不能拆开组合字符。')
        if _plain_kana(text[ta:a])!=_plain_kana(kana[ra:c]):raise ValueError('未标注部分的送假名与读音不对应；熟字训可选择整词注音。')
        ta,ra=b,d
    if _plain_kana(text[ta:])!=_plain_kana(kana[ra:]):raise ValueError('注音范围尚未覆盖相应读音；请核对送假名或选择整词注音。')


def validate(options,text,kana,latin=''):
    if not isinstance(options,dict) or set(options)-{'ruby','romaji'}:raise ValueError('读音显示设置无效。')
    if 'ruby' in options:validate_ruby(options['ruby'],text,kana)
    if 'romaji' in options:
        from .romanization import validate_setting
        validate_setting(options['romaji'],kana,latin)


def set_ruby(original,index,setting):
    original.validate()
    if type(index) is not int or not 0<=index<len(original.units):raise ValueError('先选择一个词组。')
    unit=original.units[index]
    if original.locked or unit.locked:raise ValueError('已锁定词组不能改变注音对应。')
    validate_ruby(setting,unit.text,unit.kana);value=copy.deepcopy(original);target=value.units[index]
    if setting['mode']=='auto':target.reading_options.pop('ruby',None)
    else:target.reading_options['ruby']=copy.deepcopy(setting);target.reading_source='manual'
    value.validate();return value
