"""Second-pass readings use timed recognition as evidence, never as new lyrics."""
import copy
import unicodedata
from .provenance import change,legacy_manual_reading
from .japanese import hiragana,word_groups,romaji,add_mora,segment_line
from .model import LyricLine


def kana_only(text):
    value=''.join(c for c in hiragana(text) if not c.isspace() and not unicodedata.category(c).startswith(('P','Z')))
    return value if value and all('ぁ'<=c<='ゖ' or c=='ー' for c in value) else ''


def protected(line,reviewed=True):
    return line.locked or (reviewed and line.reviewed) or any(u.locked for u in line.units)


def smooth_gaps(line,maximum=120):
    if type(maximum) is not int or not 0<=maximum<=500:raise ValueError('短空隙阈值应为 0 到 500 毫秒')
    value=copy.deepcopy(line);count=0
    if protected(line):return value,count
    for left,right in zip(value.units,value.units[1:]):
        gap=right.start-left.end
        if not 0<gap<=maximum or left.source in {'manual','acoustic'} or right.source in {'manual','acoustic'}:continue
        if (left.highlights and left.highlights[-1].source in {'manual','acoustic'}) or (right.highlights and right.highlights[0].source in {'manual','acoustic'}):continue
        edge=max(left.end,min(right.start,((left.end+right.start+10)//20)*10))
        if left.highlights and left.highlights[-1].end==left.end:change(left.highlights[-1],left.highlights[-1].start,edge,'automatic_gap')
        if right.highlights and right.highlights[0].start==right.start:change(right.highlights[0],edge,right.highlights[0].end,'automatic_gap')
        change(left,left.start,edge,'automatic_gap');change(right,edge,right.end,'automatic_gap');count+=1
    value.validate();return value,count


def recognition_for(line,transcript):
    # Timed local context avoids using a different occurrence of a repeated
    # chorus. No dictionary-generated reading is labelled acoustic evidence.
    return [item for item in transcript if item.end>line.start-700 and item.start<line.end+700][:12]


def analyze_line(line,transcript,maximum=120,preserve_legacy=False,preserve_manual=True):
    line.validate()
    if protected(line,reviewed=False):return copy.deepcopy(line),True
    value=copy.deepcopy(line)
    if not line.units:
        value.reviewed=False;value,_=segment_line(value,'words')
    value.reviewed=line.reviewed
    if line.reviewed and line.units:
        from .provenance import preserve_before_confirmation
        preserve_before_confirmation(value)
        for unit in value.units:unit.source='manual'
    nearby=recognition_for(line,transcript);words=[]
    for unit in value.units:
        dictionary=''.join(g.kana for g in word_groups(unit.text))
        evidence=[]
        for row in nearby:
            for token in row.units or []:
                overlap=max(0,min(token.end,unit.end)-max(token.start,unit.start))
                if overlap>=max(10,(token.end-token.start)*.75):evidence.append(token)
            if not row.units and row.start>=unit.start-30 and row.end<=unit.end+30:evidence.append(row)
        recognized=''.join(token.text for token in evidence)
        heard=kana_only(recognized)
        coverage=sum(max(0,min(t.end,unit.end)-max(t.start,unit.start)) for t in evidence)/max(1,unit.end-unit.start)
        before=unit.kana;before_romaji=unit.romaji
        legacy=legacy_manual_reading(unit)
        manual=(preserve_manual and unit.reading_source=='manual') or (preserve_legacy and legacy) or unit.locked
        if unit.reading_source=='manual' and not preserve_manual:unit.reading_source='manual-review'
        if legacy and preserve_legacy:unit.reading_source='manual'
        if legacy and not preserve_legacy:unit.reading_source='legacy'
        candidate=heard if heard and coverage>=.6 and len(heard)<=max(12,len(unit.text)*5) else ''
        if candidate and not manual and candidate!=kana_only(before):
            unit.kana=candidate;unit.romaji=(' '.join(g.romaji for g in word_groups(unit.text) if g.romaji) if candidate==dictionary else romaji(candidate));unit.highlights=[];unit.reading_source='transcript';add_mora(unit)
        elif (not unit.kana or not kana_only(unit.kana)) and dictionary and not manual:
            unit.kana=dictionary;unit.romaji=' '.join(g.romaji for g in word_groups(unit.text) if g.romaji);unit.reading_source='dictionary'
            if unit.highlights:unit.highlights=[];add_mora(unit)
        if unit.kana and kana_only(unit.kana) and not unit.romaji and not manual:
            unit.romaji=' '.join(g.romaji for g in word_groups(unit.text) if g.romaji) if kana_only(unit.kana)==dictionary else romaji(unit.kana)
        words.append({'text':unit.text,'before':before,'dictionary':dictionary,'recognized':recognized,
                      'suggested':unit.kana,'basis':'manual' if manual else 'transcript' if candidate else 'dictionary',
                      'changed':before!=unit.kana or before_romaji!=unit.romaji,'legacy':legacy,
                      'before_romaji':before_romaji,'suggested_romaji':unit.romaji})
    value,count=smooth_gaps(value,maximum)
    value.kana=''.join(u.kana for u in value.units);value.romaji=' '.join(u.romaji for u in value.units if u.romaji)
    value.reading_review={'method':'local','recognized':' / '.join(x.text for x in nearby),
        'context_available':bool(nearby),'words':words,'closed_gaps':count,'requires_review':True,
        'notice':'转录是假名时才提出实际读音候选；同为汉字不能证明唱法，建议用 DeepSeek 结合上下文复核。'}
    if any(word['legacy'] for word in words):value.reading_review['notice']+=' 旧版未标记读音来源；未开启保留时仅提出候选，需人工选择。'
    if not preserve_manual:value.reading_review['notice']+=' 已允许重新复核手工读音；人工时间仍保留。'
    value.reviewed=line.reviewed and bool(line.units) and not count and not any(word['changed'] for word in words)
    value.validate();return value,False


def annotation_input(line,transcript,neighbors):
    nearby=recognition_for(line,transcript)
    return {'id':line.id,'text':line.text,
        'groups':[{'text':u.text,'kana':u.kana,'romaji':u.romaji,'reading_source':u.reading_source,
                   'dictionary':''.join(g.kana for g in word_groups(u.text))} for u in line.units],
        'recognition':[{'text':r.text[:1400],'start':r.start,'end':r.end} for r in nearby[:4]],
        'previous_lyric':neighbors[0][:1000],'next_lyric':neighbors[1][:1000],
        'instruction':'结合转录中的实际唱法修正汉字读音；仅为同一汉字时不可当作发音证据。保持分词原文及边界。'}


def aligned_words(value,original):
    from .japanese import Group,retime_groups
    groups=[];offset=0
    for word in original.units:
        groups.append(Group(word.text,offset,offset+len(word.text),word.kana,word.romaji));offset+=len(word.text)
    value.units=retime_groups(value,groups or word_groups(value.text),preserve_readings=False)
    for index,unit in enumerate(value.units):
        unit.source='alignment'
        if index<len(original.units):unit.reading_source=original.units[index].reading_source
        if unit.kana:add_mora(unit)
    value.kana=''.join(u.kana for u in value.units);value.romaji=' '.join(u.romaji for u in value.units if u.romaji)
    value.validate();return value
