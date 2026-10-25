"""Textual pronunciation choices; none of these proves what the singer sang."""
import copy
import unicodedata
from functools import lru_cache
from .analysis import kana_only,recognition_for
from .japanese import word_groups,tokenizer


def _surface(text):
    # Janome attaches lyric punctuation/spaces to a word. Keep source text intact;
    # remove only edge punctuation for this read-only dictionary lookup.
    start=0;end=len(text)
    while start<end and (text[start].isspace() or unicodedata.category(text[start]).startswith('P')):start+=1
    while end>start and (text[end-1].isspace() or unicodedata.category(text[end-1]).startswith('P')):end-=1
    return unicodedata.normalize('NFKC',text[start:end])


@lru_cache(maxsize=2048)
def dictionary_readings(text):
    """Actual exact-surface IPADIC entries, not readings invented from kanji."""
    core=_surface(text)
    if not core or len(core)>256:return ()
    try:
        tok=tokenizer();entries=[]
        for entry in tok.sys_dic.lookup(core.encode('utf-8'),tok.matcher):
            if entry[1]!=core:continue
            extra=tok.sys_dic.lookup_extra(entry[0]);kana=kana_only(extra[-2])
            if kana:entries.append((entry[4],kana,extra[0],extra[3]))
    except (Exception,SystemExit) as error:
        raise ValueError('本地日语词典读取失败，可先手改假名，再检查运行包是否完整。') from error
    seen=set();result=[]
    for cost,kana,pos,base in sorted(entries):
        if kana in seen:continue
        seen.add(kana);result.append((kana,pos,base))
        if len(result)==32:break
    return tuple(result)


def _transcript_word(unit,nearby):
    tokens=[];seen=set()
    for row in nearby:
        for token in row.units or [row]:
            overlap=max(0,min(token.end,unit.end)-max(token.start,unit.start))
            key=(token.start,token.end,token.text)
            if token.end>token.start and overlap>=max(10,(token.end-token.start)*.75) and key not in seen:
                tokens.append(token);seen.add(key)
    tokens.sort(key=lambda t:(t.start,t.end))
    ambiguous=any(a.end>b.start for a,b in zip(tokens,tokens[1:]))
    text=''.join(t.text for t in tokens)
    coverage=min(1.,sum(max(0,min(t.end,unit.end)-max(t.start,unit.start)) for t in tokens)/max(1,unit.end-unit.start))
    reading=kana_only(text) if not ambiguous and coverage>=.6 else ''
    if len(reading)>max(12,len(unit.text)*5):reading=''
    return {'text':text,'kana':reading,'coverage':coverage,'overlapping':ambiguous}


def review(line,index,transcript=(),verified=False,song_dictionary=None,personal_dictionary=None):
    """Return candidates + listening range, without changing lyrics or timing."""
    line.validate()
    if type(index) is not int or not 0<=index<len(line.units):raise ValueError('先选择一个词组，再查看读音候选。')
    unit=line.units[index];choices=[]
    def add(kana,source,reason):
        kana=kana_only(kana)
        if not kana:return
        value=next((v for v in choices if v['kana']==kana),None)
        if value is None:value={'kana':kana,'sources':[],'reasons':[]};choices.append(value)
        if source not in value['sources']:value['sources'].append(source)
        if reason not in value['reasons']:value['reasons'].append(reason[:600])
    add(unit.kana,'current','当前假名'+('（人工填写）' if unit.reading_source=='manual' else '（仍需试听确认）'))
    from .reading_dictionary import lookup
    for source,document,name in [('song_dictionary',song_dictionary or {},'本歌词典'),('personal_dictionary',personal_dictionary or {},'个人词典')]:
        for entry in lookup(document,unit.text):add(entry['kana'],source,name+'中手工保存的读音，仍需试听本句。'+(' 备注：'+entry['note'] if entry['note'] else ''))
    long_word=len(unit.text)>256
    try:default='' if long_word else ''.join(g.kana for g in word_groups(unit.text))
    except (Exception,SystemExit) as error:raise ValueError('本地日语词典读取失败，可先手改假名，再检查运行包是否完整。') from error
    add(default,'dictionary_context','本地词典的默认读法；文字分析，不是歌声识别。')
    for kana,pos,base in dictionary_readings(unit.text):
        kind='专名或地名' if '固有名詞' in pos else next((label for name,label in [('名詞','名词'),('動詞','动词'),('形容詞','形容词'),('副詞','副词'),('助詞','助词'),('助動詞','助动词'),('接頭詞','词头读法'),('連体詞','修饰词')] if pos.startswith(name)), '词典读法')
        add(kana,'dictionary_entry','词典中同一原文的读法（'+kind+'）；原词条：'+base+'。仍需结合上下文和原声，不证明本句唱法。')
    nearby=recognition_for(line,transcript);heard=_transcript_word(unit,nearby)
    if heard['kana']:
        add(heard['kana'],'transcript','对应时间段的转录假名；'+('已绑定当前素材版本' if verified else '旧记录未核对当前素材版本')+'，仍需按原声试听。')
    evidence=line.reading_review;words=evidence.get('words',[])
    saved=words[index] if isinstance(words,list) and index<len(words) and isinstance(words[index],dict) else {}
    if not evidence.get('stale') and str(evidence.get('method','')).startswith('deepseek') and saved.get('text')==unit.text:
        add(saved.get('deepseek_suggested',saved.get('suggested','')),'deepseek','已保存的 DeepSeek 文字建议：'+str(saved.get('reason','未提供理由。')))
    if heard['overlapping']:notice='对应转录存在重叠文字，未拼成读音候选；请试听确认。'
    elif heard['text'] and not heard['kana']:notice='对应转录仍含汉字或不足以覆盖本词，不能把它当作实际读音证据。'
    elif heard['kana']:notice='转录假名也是识别文字候选，不是已确认的声音事实。'
    else:notice='没有可对应的转录假名；词典和文字模型的候选仍需试听。'
    if long_word:notice='词组较长，先分词后再查看词典多读法。'+notice
    return {'word':index,'text':unit.text,'current':unit.kana,'choices':copy.deepcopy(choices),
            'recognized':heard,'transcript_verified':bool(verified),'notice':notice,
            'listen':[max(0,unit.start-180),unit.end+180],
            'context':[r.text for r in nearby],'original':line.to_dict()}
