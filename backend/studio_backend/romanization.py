"""Selectable display spelling, separate from kana and acoustic evidence."""
import copy,unicodedata
from functools import lru_cache
from .japanese import morae,hiragana,tokenizer,_ROMA,_PAIRS
from .analysis import kana_only

DEFAULT={'system':'hepburn','long_vowels':'literal','particles':True}
MACRONS=dict(zip('aeiou','āēīōū'))


def validate_rules(rules):
    if not isinstance(rules,dict) or set(rules)!=set(DEFAULT) or rules.get('system') not in {'hepburn','kunrei'} or rules.get('long_vowels') not in {'literal','macron'} or type(rules.get('particles')) is not bool:raise ValueError('罗马音规则无效。')


def validate_manual(value):
    if not isinstance(value,str) or len(value)>20000:raise ValueError('手写罗马音须为文字，最多 20000 字。')
    for char in value:
        category=unicodedata.category(char)
        if char.isspace() or category.startswith(('P','N','M')):continue
        if ord(char)<128 and char.isprintable() or unicodedata.name(char,'').startswith('LATIN'):continue
        raise ValueError('罗马音请使用拉丁字母、数字或标点；日语假名保留在假名栏。')


def validate_setting(setting,kana,latin):
    if not isinstance(setting,dict) or setting.get('mode') not in {'auto','manual'}:raise ValueError('罗马音来源无效。')
    expected={'mode',*DEFAULT}|({'basis'} if setting['mode']=='manual' else set())
    if set(setting)!=expected:raise ValueError('罗马音来源记录格式无效。')
    validate_rules({key:setting[key] for key in DEFAULT})
    if setting['mode']=='manual':
        if not isinstance(setting.get('basis'),str) or len(setting['basis'])>20000:raise ValueError('手写罗马音的原假名记录无效。')
        validate_manual(latin)


def romanize(reading,rules=None):
    rules=copy.deepcopy(DEFAULT if rules is None else rules);validate_rules(rules)
    parts=morae(reading);base=dict(_ROMA);pairs=dict(_PAIRS)
    if rules['system']=='kunrei':
        base.update({'し':'si','ち':'ti','つ':'tu','ふ':'hu','じ':'zi','ぢ':'zi'})
        for source,prefix in [('し','sy'),('ち','ty'),('じ','zy'),('ぢ','zy')]:
            for tail,vowel in zip('ゃゅょ','auo'):pairs[source+tail]=prefix+vowel
    def syllable(part):return pairs.get(part,base.get(part,part))
    out=''
    for i,part in enumerate(parts):
        following=syllable(parts[i+1]) if i+1<len(parts) else ''
        if part=='っ':out+=('t' if rules['system']=='hepburn' and following.startswith('ch') else following[:1]) if following and following[0] not in 'aeioun' else 'xtsu'
        elif part=='ん':out+="n'" if following[:1] in 'aeiouy' and following else 'n'
        elif part=='ー':
            position=next((n for n in range(len(out)-1,-1,-1) if out[n] in 'aeiouāēīōū'),None)
            if position is not None:
                vowel=out[position];plain=next((a for a,b in MACRONS.items() if b==vowel),vowel)
                if rules['long_vowels']=='macron':out=out[:position]+MACRONS[plain]+out[position+1:]
                else:out+=plain
        else:out+=syllable(part)
    return out


@lru_cache(maxsize=4096)
def _spoken(text,reading,long_mode,particles):
    normalized=kana_only(reading)
    try:
        values=[]
        for token in tokenizer().tokenize(text):
            base=kana_only(token.reading) if token.reading!='*' else kana_only(token.surface)
            if not base:
                if any(unicodedata.category(c)[0] in 'LNM' for c in token.surface):return reading
                continue
            phonetic=kana_only(token.phonetic) if token.phonetic!='*' else base
            if token.part_of_speech.startswith('助詞') and token.surface in {'は','へ','を'}:
                spoken={'は':'わ','へ':'え','を':'お'}[token.surface] if particles else base
            else:spoken=phonetic if long_mode=='macron' else base
            values.append((base,spoken))
        return ''.join(value for _,value in values) if ''.join(base for base,_ in values)==normalized else reading
    except (Exception,SystemExit):return reading


def automatic(unit,rules=None):
    rules=copy.deepcopy(DEFAULT if rules is None else rules);validate_rules(rules)
    if not kana_only(unit.kana):return unit.text if unit.text.isascii() else ''
    return romanize(_spoken(unit.text,unit.kana,rules['long_vowels'],rules['particles']),rules)


def state(unit,defaults=None):
    rules=copy.deepcopy(DEFAULT if defaults is None else defaults);validate_rules(rules)
    saved=unit.reading_options.get('romaji')
    if saved:return copy.deepcopy(saved)
    mode='auto' if not unit.romaji or unit.reading_source in {'dictionary','llm','transcript'} or unit.reading_source!='manual' and unit.romaji==automatic(unit,rules) else 'legacy'
    return {'mode':mode,**rules,'basis':unit.kana} if mode=='legacy' else {'mode':mode,**rules}


def after_reading_change(before,after,defaults=None):
    source=state(before,defaults);rules={key:source[key] for key in DEFAULT}
    if source['mode'] in {'manual','legacy'}:
        after.romaji=before.romaji;after.reading_options['romaji']={'mode':'manual',**rules,'basis':source.get('basis',before.kana)};return True
    after.romaji=automatic(after,rules);after.reading_options['romaji']={'mode':'auto',**rules};return False


def set_manual(original,index,value,defaults=None):
    original.validate();validate_manual(value)
    if type(index) is not int or not 0<=index<len(original.units):raise ValueError('先选择一个词组。')
    if original.locked or original.units[index].locked:raise ValueError('已锁定内容不能修改罗马音。')
    line=copy.deepcopy(original);unit=line.units[index];source=state(unit,defaults);rules={key:source[key] for key in DEFAULT}
    unit.romaji=value;unit.reading_options['romaji']={'mode':'manual',**rules,'basis':unit.kana};line.romaji=' '.join(u.romaji for u in line.units if u.romaji);line.validate();return line


def apply_rules(original,indices,rules,replace_manual=False):
    original.validate();validate_rules(rules)
    if type(replace_manual) is not bool:raise ValueError('手写罗马音覆盖选项无效。')
    indices=list(indices)
    if any(type(i) is not int or not 0<=i<len(original.units) for i in indices) or len(indices)!=len(set(indices)):raise ValueError('罗马音修改范围无效。')
    line=copy.deepcopy(original);changed=[];kept=[]
    for index in indices:
        unit=line.units[index];before=copy.deepcopy(unit);old=state(unit,rules)
        if original.locked or unit.locked:kept.append({'word':index,'reason':'已锁定'});continue
        if old['mode'] in {'manual','legacy'} and not replace_manual:kept.append({'word':index,'reason':'手写或来源未记录，保持'});continue
        unit.romaji=automatic(unit,rules);unit.reading_options['romaji']={'mode':'auto',**copy.deepcopy(rules)}
        if unit!=before:changed.append(index)
        else:kept.append({'word':index,'reason':'已使用当前规则'})
    line.romaji=' '.join(u.romaji for u in line.units if u.romaji);line.validate()
    return {'line':line,'changed':changed,'kept':kept}
