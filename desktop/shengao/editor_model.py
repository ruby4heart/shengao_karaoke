"""Inline boundary preview; only the changed words get new estimates."""
from dataclasses import dataclass
import copy
import unicodedata
from studio_backend.model import Highlight
from studio_backend.japanese import add_mora
from .timing import split_word,merge_words,manual
from .segmentation_dialog import regroup

@dataclass
class BoundaryPreview:
    line:object
    affected:tuple
    reestimated:bool
    kind:str='segmentation'
    skipped:int=0

def exact_morae(reading):
    """Keep the user's kana spelling, including katakana and halfwidth forms."""
    if any('\u3400'<=char<='\u9fff' or '\uf900'<=char<='\ufaff' for char in reading):return []
    normalized=unicodedata.normalize('NFKC',reading)
    if not any('\u3041'<=char<='\u30fa' for char in normalized):return []
    result=[];prefix=''
    for char in reading:
        normal=unicodedata.normalize('NFKC',char)
        if char.isspace() or unicodedata.category(char).startswith(('P','Z')):
            if result:result[-1]+=char
            else:prefix+=char
        elif result and (normal in 'ぁぃぅぇぉゃゅょゎゕゖァィゥェォャュョヮヵヶ' or any(unicodedata.combining(c) for c in normal)):result[-1]+=char
        else:result.append(prefix+char);prefix=''
    return result

def missing_mora_indices(line):
    result=[]
    if line and not line.locked:
        for i,unit in enumerate(line.units):
            parts=exact_morae(unit.kana)
            if not unit.locked and not unit.highlights and parts and unit.end-unit.start>=len(parts):result.append(i)
    return result

def missing_mora_preview(original):
    original.validate();indices=missing_mora_indices(original)
    if not indices:raise ValueError('没有可补音节的词组；先填写有效假名、调整过短范围或解除相应锁定')
    line=copy.deepcopy(original)
    for index in indices:
        unit=line.units[index];parts=exact_morae(unit.kana)
        unit.highlights=[Highlight(part,unit.start+round((unit.end-unit.start)*i/len(parts)),unit.start+round((unit.end-unit.start)*(i+1)/len(parts))) for i,part in enumerate(parts)]
        from studio_backend.provenance import derived
        for h in unit.highlights:h.timing_origin=derived('estimated',h.start,h.end,[unit],'mora_distribution',h.kana)
    manual(line);line.validate()
    skipped=sum(not unit.highlights for unit in original.units)-len(indices)
    return BoundaryPreview(line,tuple(original.units[i].text for i in indices),True,'mora',skipped)

def cuts_for(line):
    cursor=0;cuts=[]
    for unit in line.units[:-1]:cursor+=len(unit.text);cuts.append(cursor)
    return cuts

def boundary_preview(original,position):
    if type(position) is not int or not 0<position<len(original.text):raise ValueError('请选择原文内部的分界')
    if original.locked:raise ValueError('本句已锁定，请先解除锁定')
    cuts=cuts_for(original)
    if position in cuts:cuts.remove(position)
    else:cuts.append(position)
    return segmentation_preview(original,cuts)

def segmentation_preview(original,cuts):
    original.validate()
    if original.locked:raise ValueError('本句已锁定，请先解除锁定')
    cuts=list(cuts)
    if any(type(position) is not int or not 0<position<len(original.text) for position in cuts):raise ValueError('请选择原文内部的分界')
    cuts=sorted(set(cuts))
    bounds=[0,*sorted(cuts),len(original.text)]
    if any(not original.text[a:b].strip() for a,b in zip(bounds,bounds[1:])):raise ValueError('分词不能生成只有空格的词组；原歌词中的空格会保留在相邻词组中')
    if not original.units:
        result=regroup(original,cuts);affected=tuple(unit.text for unit in result.units);estimated=True
    else:
        result=copy.deepcopy(original);old_cuts=cuts_for(original)
        if cuts==old_cuts:return BoundaryPreview(result,(),False)
        for position in old_cuts:
            if position not in cuts:
                index=cuts_for(result).index(position);result=merge_words(result,index,index+1)
        for position in cuts:
            if position not in cuts_for(result):
                cursor=0
                for index,unit in enumerate(result.units):
                    if cursor<position<cursor+len(unit.text):break
                    cursor+=len(unit.text)
                else:raise ValueError('原文与词组范围不一致，请重新检查分词')
                result=split_word(result,index,position-cursor)
                for unit in result.units[index:index+2]:add_mora(unit)
        old={};cursor=0
        for unit in original.units:old[(cursor,cursor+len(unit.text))]=unit;cursor+=len(unit.text)
        affected=[];cursor=0
        for unit in result.units:
            if (cursor,cursor+len(unit.text)) not in old:affected.append(unit.text)
            cursor+=len(unit.text)
        affected=tuple(affected);estimated=bool(set(cuts)-set(old_cuts))
    result.kana=''.join(unit.kana for unit in result.units);result.romaji=' '.join(unit.romaji for unit in result.units if unit.romaji)
    result.validate();return BoundaryPreview(result,affected,estimated)
