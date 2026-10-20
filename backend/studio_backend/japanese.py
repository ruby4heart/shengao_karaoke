"""Offline Japanese groups and sung morae. Source text is always authoritative."""
from dataclasses import dataclass
from functools import lru_cache
import copy
import unicodedata
from .model import Unit,Highlight


def hiragana(text):
    text=unicodedata.normalize('NFKC',text)
    return ''.join(chr(ord(c)-0x60) if 'ァ'<=c<='ヶ' else c for c in text)


def morae(reading):
    result=[]
    for c in hiragana(reading):
        if c.isspace() or unicodedata.category(c).startswith(('P','Z')):
            continue
        if result and (c in 'ぁぃぅぇぉゃゅょゎゕゖ' or unicodedata.combining(c)):
            result[-1]+=c
        else:
            result.append(c)
    return result


_ROMA=dict(zip('あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわゐゑをんがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽゔ',
    'a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to na ni nu ne no ha hi fu he ho ma mi mu me mo ya yu yo ra ri ru re ro wa i e o n ga gi gu ge go za ji zu ze zo da ji zu de do ba bi bu be bo pa pi pu pe po vu'.split()))
_PAIRS={}
for prefix,base in [('き','ky'),('ぎ','gy'),('し','sh'),('じ','j'),('ち','ch'),('ぢ','j'),('に','ny'),('ひ','hy'),('び','by'),('ぴ','py'),('み','my'),('り','ry')]:
    for tail,vowel in zip('ゃゅょ','auo'):_PAIRS[prefix+tail]=base+vowel
_PAIRS.update(dict(zip('ふぁ ふぃ ふぇ ふぉ てぃ でぃ とぅ どぅ うぃ うぇ うぉ しぇ じぇ ちぇ つぁ つぃ つぇ つぉ ゔぁ ゔぃ ゔぇ ゔぉ'.split(),
                      'fa fi fe fo ti di tu du wi we wo she je che tsa tsi tse tso va vi ve vo'.split())))


def romaji(reading):
    syllables=morae(reading);out=''
    for i,part in enumerate(syllables):
        following=syllables[i+1] if i+1<len(syllables) else ''
        next_roma=_PAIRS.get(following,_ROMA.get(following,following))
        if part=='っ':out+=('t' if next_roma.startswith('ch') else next_roma[:1]) if next_roma and next_roma[0] not in 'aeioun' else 'xtsu'
        elif part=='ー':out+=next((c for c in reversed(out) if c in 'aeiou'),'')
        elif part=='ん':out+="n'" if next_roma[:1] in 'aeiouy' and next_roma else 'n'
        else:out+=_PAIRS.get(part,_ROMA.get(part,part))
    return out


@dataclass(frozen=True)
class Group:
    text:str
    begin:int
    end:int
    kana:str=''
    romaji:str=''


@lru_cache(maxsize=1)
def tokenizer():
    from janome.tokenizer import Tokenizer
    return Tokenizer()


@lru_cache(maxsize=2048)
def word_groups(text):
    """Use original lyric boundaries, never ASR tokens or their inserted spaces."""
    result=[];cursor=0;pending=''
    for token in tokenizer().tokenize(text):
        position=text.find(token.surface,cursor)
        if position<0:raise ValueError('本地词典无法保持原歌词，请使用手动分词')
        gap=text[cursor:position]
        if gap and result:
            old=result.pop();result.append(Group(old.text+gap,old.begin,position,old.kana,old.romaji))
        else:pending+=gap
        surface=token.surface;finish=position+len(surface)
        if not any(unicodedata.category(c)[0] in 'LNM' for c in surface):
            if result:
                old=result.pop();result.append(Group(old.text+surface,old.begin,finish,old.kana,old.romaji))
            else:pending+=surface
        else:
            reading=hiragana(token.reading) if token.reading!='*' else (hiragana(surface) if all('ぁ'<=hiragana(c)<='ゖ' or c=='ー' for c in surface) else '')
            spoken=reading
            if token.part_of_speech.startswith('助詞') and surface in {'は','へ','を'}:spoken={'は':'わ','へ':'え','を':'お'}[surface]
            latin=romaji(spoken) if spoken else (surface if surface.isascii() else '')
            result.append(Group(pending+surface,position-len(pending),finish,reading,latin));pending=''
        cursor=finish
    tail=text[cursor:]
    if result:
        old=result.pop();result.append(Group(old.text+tail+pending,old.begin,len(text),old.kana,old.romaji))
    elif text:result=[Group(text,0,len(text))]
    if ''.join(g.text for g in result)!=text:raise ValueError('本地分词未完整保留原歌词')
    return tuple(result)


def add_mora(unit):
    parts=morae(unit.kana)
    if not parts:return
    if unit.highlights and ''.join(h.kana for h in unit.highlights)==unit.kana:return
    unit.kana=''.join(parts)
    from .provenance import derived
    unit.highlights=[Highlight(part,a,b,timing_origin=derived('estimated',a,b,[unit],'mora_distribution',part))
                     for i,part in enumerate(parts) for a,b in [(unit.start+round((unit.end-unit.start)*i/len(parts)),unit.start+round((unit.end-unit.start)*(i+1)/len(parts)))]]


def retime_groups(line,groups,preserve_readings=True):
    """Preserve existing word edges and pauses; interpolate only newly cut edges."""
    groups=list(groups);positions=[];cursor=0
    for unit in line.units:
        positions.append((cursor,cursor+len(unit.text),unit));cursor+=len(unit.text)
    weights=[max(1,len(morae(g.kana)) or len(g.text.strip())) for g in groups];total=sum(weights);offset=0
    output=[]
    for group,weight in zip(groups,weights):
        old=next((u for a,b,u in positions if a==group.begin and b==group.end),None)
        def boundary(position,end=False):
            for a,b,u in (reversed(positions) if end else positions):
                if (a<position<=b if end else a<=position<b):
                    return round(u.start+(u.end-u.start)*(position-a)/max(1,b-a))
            return line.end if end else line.start
        if positions:
            start=boundary(group.begin);finish=boundary(group.end,True)
        else:
            start=line.start+round((line.end-line.start)*offset/total)
            finish=line.start+round((line.end-line.start)*(offset+weight)/total)
        reading=(old.kana if preserve_readings and old and old.kana else group.kana)
        latin=(old.romaji if preserve_readings and old and old.romaji else group.romaji)
        unit=Unit(group.text,start,max(start,finish),reading,latin,
                  old.source if old else 'estimated',old.locked if old else False,
                  copy.deepcopy(old.highlights) if old and old.kana==reading else [])
        unit.reading_source=old.reading_source if old and old.kana==reading else 'dictionary'
        from .provenance import group_basis,derived
        parents=[u for a,b,u in positions if a<group.end and b>group.begin]
        unit.timing_origin=copy.deepcopy(old.timing_origin) if old else group_basis(parents,unit.start,unit.end) if parents else derived('estimated',unit.start,unit.end,[line],'line_distribution')
        output.append(unit);offset+=weight
    return output


def segment_line(line,mode='words'):
    if mode not in {'words','mora'}:raise ValueError('不支持的分词方式')
    line.validate();value=copy.deepcopy(line)
    if line.locked or line.reviewed or any(u.locked for u in line.units):return value,True
    if mode=='words' or not line.units:
        value.units=retime_groups(line,word_groups(line.text))
    if mode=='mora':
        for unit in value.units:
            if not unit.kana:
                pieces=word_groups(unit.text);unit.kana=''.join(g.kana for g in pieces);unit.romaji=' '.join(g.romaji for g in pieces if g.romaji)
            add_mora(unit)
    value.kana=''.join(u.kana for u in value.units)
    value.romaji=' '.join(u.romaji for u in value.units if u.romaji)
    value.reviewed=False;value.validate()
    return value,False
