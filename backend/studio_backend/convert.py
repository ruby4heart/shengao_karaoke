import copy
from .model import LyricLine, Unit, identifier, ms, estimated_units
from .japanese import Group,retime_groups,add_mora
from .provenance import create,group_basis,change,legacy_manual_reading


def eleven_lines(result):
    lines=[]
    current=[]
    for word in result.get('words',[]):
        if word.get('type')=='audio_event':
            continue
        if word.get('type')=='spacing':
            if current:
                current[-1].text += word.get('text','')
            continue
        if not word.get('text'):
            continue
        start,end=ms(word.get('start')),ms(word.get('end'))
        if start<0 or end<start:
            raise ValueError('API 返回无效时间戳')
        if current and (start-current[-1].end>1200 or end-current[0].start>7000 or len(''.join(u.text for u in current))>65):
            lines.append(pack(current)); current=[]
        characters=word.get('characters') or []
        if characters and ''.join(c.get('text','') for c in characters)==word['text']:
            for char in characters:
                a,b=ms(char['start']),ms(char['end'])
                current.append(Unit(char['text'],a,b,source='recognition',timing_origin=create('character',a,b,'elevenlabs','transcription')))
        else:
            current.append(Unit(word['text'],start,end,source='word',timing_origin=create('word',start,end,'elevenlabs','transcription')))
        if word['text'].rstrip().endswith(('。','！','？','!','?')):
            lines.append(pack(current)); current=[]
    if current:
        lines.append(pack(current))
    if not lines and result.get('text','').strip():
        raise ValueError('API 返回文字但没有有效时间戳')
    return lines


def pack(units):
    start=min(u.start for u in units)
    end=max(max(u.end for u in units),start+10)
    # API token overlap is normalized while keeping the original JSON for review.
    previous=start
    for unit in units:
        a=max(previous,unit.start);b=max(a,unit.end)
        if (a,b)!=(unit.start,unit.end):change(unit,a,b,'clamp')
        previous=unit.end
    line=LyricLine(identifier(),''.join(u.text for u in units),start,max(end,previous),units)
    line.timing_origin=group_basis(units,line.start,line.end,'transcript_envelope')
    line.validate()
    return line


def mai_lines(result):
    lines=[]
    for phrase in result.get('phrases',[]):
        text=phrase.get('text','')
        if not text.strip():
            continue
        start=ms(phrase['offsetMilliseconds']/1000)
        end=start+ms(phrase['durationMilliseconds']/1000)
        words=phrase.get('words') or []
        units=[]; cursor=0
        for word in words:
            token=word.get('text','')
            position=text.find(token,cursor) if token else -1
            if position<0:
                units=[];break
            if position>cursor and units:
                units[-1].text+=text[cursor:position]
            elif position>cursor:
                token=text[cursor:position]+token
            word_start=round(word['offsetMilliseconds'])
            word_end=word_start+round(word['durationMilliseconds'])
            units.append(Unit(token,word_start,word_end,source='word',timing_origin=create('word',word_start,word_end,'microsoft','transcription')))
            cursor=position+len(word['text'])
        if units:
            units[-1].text+=text[cursor:]
            lines.append(pack(units))
        else:
            line=LyricLine(identifier(),text,start,end,estimated_units(text,start,end))
            line.timing_origin=create('reference',start,end,'microsoft','phrase_transcription')
            for unit in line.units:unit.timing_origin=create('estimated',unit.start,unit.end,'microsoft','phrase_distribution',parents=['reference'])
            line.validate();lines.append(line)
    if not lines and any(p.get('text','').strip() for p in result.get('combinedPhrases',[])):
        raise ValueError('MAI 返回全文但没有时间戳')
    return lines


def annotation_suggestion(line, annotation, romanization_rules=None):
    """Preserve existing acoustic boundaries where a reading group's edges match."""
    groups=[];position=0
    for group in annotation['groups']:
        next_position=position+len(group['text'])
        groups.append(Group(group['text'],position,next_position,group['kana'],group['romaji']))
        position=next_position
    units=retime_groups(line,groups,preserve_readings=False)
    starts={0};ends={len(line.text)};offset=0
    for old in line.units:starts.add(offset);offset+=len(old.text);ends.add(offset)
    for group,unit in zip(groups,units):
        if group.begin in starts and group.end in ends and not any(old.text==unit.text and old.start==unit.start and old.end==unit.end for old in line.units):unit.source='mapped'
    word_reviews=[]
    for index,unit in enumerate(units):
        protection_notice=''
        old=next((old for old in line.units if old.text==unit.text and old.start==unit.start and old.end==unit.end),None)
        if old and (old.reading_source=='manual' or legacy_manual_reading(old) or old.locked or old.reading_options.get('ruby',{}).get('mode','auto')!='auto'):
            unit.kana=old.kana;unit.romaji=old.romaji;unit.highlights=copy.deepcopy(old.highlights);unit.reading_source=old.reading_source;unit.reading_options=copy.deepcopy(old.reading_options)
        else:
            if old and old.kana!=unit.kana:
                from .reading_suggestion import propose_unit
                old_index=line.units.index(old);unit,protection_notice=propose_unit(line,old_index,unit.kana,'llm',romanization_rules);units[index]=unit
            unit.reading_source='llm' if not protection_notice else old.reading_source
            from .romanization import after_reading_change,automatic,DEFAULT
            if old:after_reading_change(old,unit,romanization_rules)
            else:
                rules=DEFAULT if romanization_rules is None else romanization_rules
                unit.romaji=automatic(unit,rules);unit.reading_options['romaji']={'mode':'auto',**rules}
        if old is None or old.kana!=unit.kana:add_mora(unit)
        previous=line.reading_review.get('words',[]);review=copy.deepcopy(previous[index]) if isinstance(previous,list) and index<len(previous) and isinstance(previous[index],dict) and previous[index].get('text')==unit.text else {}
        review.update(text=unit.text,before=review.get('before',old.kana if old else ''),suggested=unit.kana,deepseek_suggested=annotation['groups'][index]['kana'],reason=annotation['groups'][index].get('reason',''),protection_notice=protection_notice,suggested_romaji=unit.romaji)
        word_reviews.append(review)
    suggestion=LyricLine(line.id,line.text,line.start,line.end,units,
                         ''.join(u.kana for u in units),' '.join(u.romaji for u in units if u.romaji),annotation['translation'],
                         match=copy.deepcopy(line.match),reading_review=copy.deepcopy(line.reading_review))
    suggestion.display_start=line.display_start;suggestion.display_end=line.display_end;suggestion.locked=line.locked
    suggestion.reading_review.update(method='deepseek',words=word_reviews,stale=False,text_suggestion_version=1)
    from .translation import record_suggestion
    record_suggestion(line,suggestion,annotation['translation'])
    suggestion.timing_origin=copy.deepcopy(line.timing_origin);suggestion.timing_evidence=copy.deepcopy(line.timing_evidence)
    def timing(words):return [(u.text,u.start,u.end,[(h.kana,h.start,h.end) for h in u.highlights]) for u in words]
    suggestion.reviewed=line.reviewed and timing(units)==timing(line.units)
    suggestion.validate()
    return suggestion
