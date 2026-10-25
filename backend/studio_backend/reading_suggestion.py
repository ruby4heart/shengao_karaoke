"""Text suggestions reuse editor boundary rules; text models never supply time."""
import copy
from .reading_change import preview
from .japanese import hiragana,Group,retime_groups,add_mora
from .provenance import inferred
from .romanization import state


def propose_unit(line,index,kana,source='llm',rules=None):
    if source not in {'llm','dictionary','transcript'}:raise ValueError('读音建议来源无效。')
    try:
        result=preview(line,index,kana,rules);unit=result['line'].units[index]
        unit.reading_source=source
        return unit,''
    except ValueError as error:return copy.deepcopy(line.units[index]),str(error)


def _shape(unit):
    return (unit.start,unit.end,[(hiragana(h.kana),h.start,h.end,h.source,tuple(h.fixed_edges)) for h in unit.highlights])


def _groups(line):
    result=[];offset=0
    for unit in line.units:result.append(Group(unit.text,offset,offset+len(unit.text),unit.kana,unit.romaji));offset+=len(unit.text)
    return result


def validate_text_result(old,candidate):
    old.validate();candidate.validate()
    if old.locked and old!=candidate:raise ValueError('本句已锁定，文字建议不能改变内容。')
    if (old.id,old.text,old.start,old.end,old.display_start,old.display_end)!=(candidate.id,candidate.text,candidate.start,candidate.end,candidate.display_start,candidate.display_end):raise ValueError('文字读音建议不能更改原文、整句或字幕显示时间。')
    if candidate.timing_evidence!=old.timing_evidence or candidate.timing_origin!=old.timing_origin:raise ValueError('文字模型不能生成新的声音时间依据。')
    legacy=candidate.reading_review.get('text_suggestion_version')!=1
    same_groups=[u.text for u in old.units]==[u.text for u in candidate.units]
    if not same_groups:
        if old.units and not legacy:raise ValueError('文字读音建议须保留本句已有分词。')
        sensitive=any(u.locked or u.source in {'manual','acoustic'} or u.reading_source=='manual' or u.reading_options or any(h.source in {'manual','acoustic'} or h.fixed_edges or inferred(h)['kind'] in {'manual','acoustic'} for h in u.highlights) for u in old.units)
        if sensitive:raise ValueError('旧分词含人工内容，文字建议不能重新分词后丢掉它们。')
        expected_units=retime_groups(old,_groups(candidate),preserve_readings=False)
        for unit in expected_units:add_mora(unit)
    else:
        expected_units=[]
        for index,(before,after) in enumerate(zip(old.units,candidate.units)):
            if hiragana(before.kana)==hiragana(after.kana):
                expected=copy.deepcopy(before)
                if not expected.highlights and after.highlights:add_mora(expected)
            else:
                expected,problem=propose_unit(old,index,after.kana)
                if problem or hiragana(expected.kana)!=hiragana(after.kana):raise ValueError('读音变化会丢掉人工边界，旧时间保持。')
            expected_units.append(expected)
    for index,(expected,actual) in enumerate(zip(expected_units,candidate.units)):
        shape_ok=_shape(expected)==_shape(actual)
        if not shape_ok and legacy and same_groups:
            before=old.units[index]
            soft=not before.reading_options and all(h.source not in {'manual','acoustic'} and not h.fixed_edges and inferred(h)['kind'] not in {'manual','acoustic'} for h in before.highlights)
            if soft:
                uniform=copy.deepcopy(before);uniform.kana=actual.kana;uniform.highlights=[];add_mora(uniform);shape_ok=_shape(uniform)==_shape(actual)
        if not shape_ok:raise ValueError('读音建议的时间不是由本词原范围生成，或改动了人工固定边界。')
        if not legacy and expected.timing_origin!=actual.timing_origin:raise ValueError('文字建议改变了词组的时间依据，未采用。')
        for reference,proposed in zip(expected.highlights,actual.highlights):
            if proposed.timing_origin and inferred(reference)!=inferred(proposed):raise ValueError('读音建议改变了原时间来源，未采用。')
            if not legacy and reference.timing_origin and not proposed.timing_origin:raise ValueError('读音建议缺少应保留的时间来源，未采用。')
        if same_groups:
            before=old.units[index]
            if before.reading_options.get('ruby')!=actual.reading_options.get('ruby'):raise ValueError('文字建议不能改动人工注音对应。')
            original_roman=state(before)
            if original_roman['mode'] in {'manual','legacy'}:
                if actual.romaji!=before.romaji or state(actual)['mode']=='auto':raise ValueError('手写或来源未记录的罗马音不能被文字建议覆盖。')
            if before.locked and before!=actual:raise ValueError('读音建议改变了锁定词组。')
