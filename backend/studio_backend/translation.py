"""Translation drafts and human edits never replace lyrics or sound timing."""
import copy


def _text(value):
    if not isinstance(value,str) or len(value)>20000:raise ValueError('译文须为文字，最多 20000 字。')
    return value.replace('\r\n','\n').replace('\r','\n')


def info(line):
    saved=line.reading_review.get('translation',{})
    if isinstance(saved,dict) and saved.get('source') in {'manual','deepseek','legacy'} and isinstance(saved.get('for_text'),str) and type(saved.get('confirmed')) is bool:return copy.deepcopy(saved)
    return {'source':'legacy' if line.translation else 'empty','for_text':'','confirmed':False}


def manual(original,text):
    if original.locked:raise ValueError('本句已锁定，译文保持。')
    value=copy.deepcopy(original);value.translation=_text(text);value.reading_review['translation']={'source':'manual','for_text':original.text,'confirmed':False};value.reading_review.pop('translation_original_changed',None);value.validate();return value


def record_suggestion(original,candidate,text):
    incoming=_text(text);previous=info(original)
    candidate.reading_review['translation_suggestion']={'text':incoming,'for_text':original.text,'provider':'deepseek'}
    if previous['source'] in {'manual','legacy'} or previous['confirmed']:
        candidate.translation=original.translation;candidate.reading_review['translation']=previous
        candidate.reading_review['translation_notice']='手工、已确认或来源未记录的译文保持；可在本句译文区比较已保存的新建议。'
    else:
        candidate.translation=incoming;candidate.reading_review['translation']={'source':'deepseek','for_text':original.text,'confirmed':False}
        candidate.reading_review['translation_notice']='DeepSeek 译文初稿，需要人工校对。'


def suggestion(line):
    value=line.reading_review.get('translation_suggestion',{})
    if not isinstance(value,dict) or value.get('provider')!='deepseek' or not isinstance(value.get('text'),str) or not isinstance(value.get('for_text'),str):return None
    _text(value['text']);return copy.deepcopy(value)


def accept_suggestion(original):
    if original.locked:raise ValueError('本句已锁定，译文保持。')
    proposed=suggestion(original)
    if proposed is None:raise ValueError('没有可采用的已保存译文建议。')
    if proposed['for_text']!=original.text:raise ValueError('原文已变化，旧译文建议未采用；请按当前原文重新复核。')
    value=copy.deepcopy(original);value.translation=proposed['text'];value.reading_review['translation']={'source':'deepseek','for_text':original.text,'confirmed':False};value.reading_review.pop('translation_original_changed',None);value.validate();return value


def confirm(original,checked):
    if original.locked:raise ValueError('本句已锁定，译文保持。')
    if type(checked) is not bool:raise ValueError('译文确认状态无效。')
    if checked and not original.translation:raise ValueError('译文为空；可保持为空，不必确认。')
    value=copy.deepcopy(original);current=info(original)
    if current['source']=='empty':current['source']='legacy'
    current['confirmed']=checked
    if checked:current['for_text']=original.text;value.reading_review.pop('translation_original_changed',None)
    value.reading_review['translation']=current;value.validate();return value


def carry_after_lyric_edit(original,candidate):
    if original.translation or original.reading_review.get('translation'):
        candidate.reading_review['translation']=info(original);candidate.reading_review['translation_original_changed']=True
    proposed=suggestion(original)
    if proposed is not None:candidate.reading_review['translation_suggestion']=proposed


def carry(original,candidate):
    """Nontranslation stages preserve the current text and its separate review."""
    candidate.translation=original.translation
    for key in ('translation','translation_suggestion','translation_original_changed','translation_notice'):
        if key in original.reading_review:candidate.reading_review[key]=copy.deepcopy(original.reading_review[key])
    if original.text!=candidate.text and (original.translation or 'translation' in original.reading_review):candidate.reading_review['translation_original_changed']=True
    return candidate
