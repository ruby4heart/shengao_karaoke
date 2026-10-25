"""Align approved readings to kanji runs using written kana as fixed anchors."""
import unicodedata
from functools import lru_cache
from studio_backend.japanese import hiragana


def kanji(c):
    return c in '々〆' or '\u3400'<=c<='\u9fff' or '\uf900'<=c<='\ufaff' or '\U00020000'<=c<='\U000323af'


@lru_cache(maxsize=4096)
def ruby_spans(text,reading):
    """(text start/end, reading start/end), without guessing individual kanji.

    Ambiguous anchors fall back to one word annotation; the reading itself is
    always the user's current reading, never a fresh dictionary inference.
    """
    if not reading or not any(kanji(c) for c in text):return ()
    tokens=[]
    for i,c in enumerate(text):
        is_kanji=kanji(c)
        if tokens and tokens[-1][2]==is_kanji:tokens[-1]=(tokens[-1][0],i+1,is_kanji)
        else:tokens.append((i,i+1,is_kanji))
    normalized=hiragana(reading)
    # NFKC may merge half-width dakuten. Preserve offsets into the approved
    # reading by falling back rather than splitting a grapheme incorrectly.
    if len(normalized)!=len(reading):return ((0,len(text),0,len(reading)),)
    @lru_cache(maxsize=None)
    def solve(n,offset):
        if n==len(tokens):
            return ((),) if offset==len(normalized) else ()
        a,b,is_kanji=tokens[n]
        if is_kanji:
            results=[]
            for end in range(offset+1,len(normalized)+1):
                for suffix in solve(n+1,end):
                    results.append(((a,b,offset,end),)+suffix)
                    if len(results)==2:return tuple(results)
            return tuple(results)
        else:
            anchor=''.join(c for c in hiragana(text[a:b]) if not c.isspace() and not unicodedata.category(c).startswith('P'))
            return solve(n+1,offset+len(anchor)) if normalized.startswith(anchor,offset) else ()
    # Unusually long merged units should remain responsive and reviewable.
    solutions=solve(0,0) if len(tokens)<=24 and len(normalized)<=256 else ()
    return solutions[0] if len(solutions)==1 else ((0,len(text),0,len(reading)),)


def reading_fragments(unit,start,end):
    if not unit.highlights:return [(unit.kana[start:end],unit.start,unit.end)]
    result=[];offset=0
    for h in unit.highlights:
        finish=offset+len(h.kana);a,b=max(start,offset),min(end,finish)
        if a<b:result.append((h.kana[a-offset:b-offset],h.start,h.end))
        offset=finish
    return result


def unit_ruby_spans(unit,text=None):
    """Resolve the one mapping used by preview, ASS and final video output."""
    setting=unit.reading_options.get('ruby',{'mode':'auto'});mode=setting['mode'];visible=unit.text if text is None else text
    if mode=='auto':return ruby_spans(visible,unit.kana)
    from studio_backend.reading_options import validate_ruby
    validate_ruby(setting,unit.text,unit.kana)
    if mode=='off':return ()
    if mode=='whole':return ((0,len(visible),0,len(unit.kana)),)
    offset=0 if visible==unit.text else unit.text.find(visible)
    if offset<0:raise ValueError('当前显示文字与手工注音对应不一致。')
    spans=[]
    for a,b,c,d in setting['spans']:
        start,end=max(0,a-offset),min(len(visible),b-offset)
        if start<end:spans.append((start,end,c,d))
    return tuple(spans)
