"""Milliseconds are canonical; readings never substitute for source lyrics."""
from dataclasses import asdict, dataclass, field
import math
import re
import uuid


def identifier():
    return uuid.uuid4().hex


def ms(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('时间必须是有限数值')
    return round(value * 1000)


def plain_ass(text):
    return re.sub(r'\{[^}]*\}', '', text).replace(r'\N', '\n').replace(r'\n', '\n').replace(r'\h', ' ')


def literal(text):
    # User text cannot become ASS drawing or override commands.
    return text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\x00', '').replace('\r\n', '\n').replace('\r', '\n').replace('\n', r'\N')


@dataclass
class Highlight:
    kana: str
    start: int
    end: int
    source: str = 'estimated'
    timing_origin: dict = field(default_factory=dict)


@dataclass
class Unit:
    text: str
    start: int
    end: int
    kana: str = ''
    romaji: str = ''
    source: str = 'estimated'
    locked: bool = False
    highlights: list[Highlight] = field(default_factory=list)
    reading_source: str = ''
    timing_origin: dict = field(default_factory=dict)

    def __post_init__(self):
        self.highlights=[Highlight(**h) if isinstance(h,dict) else h for h in self.highlights]

    def validate(self):
        from .provenance import validate
        validate(self.timing_origin)
        if not isinstance(self.text, str) or len(self.text) > 20000:
            raise ValueError('音节文字无效')
        if type(self.start) is not int or type(self.end) is not int or self.start < 0 or self.end < self.start:
            raise ValueError('音节时间无效')
        previous=self.start
        for highlight in self.highlights:
            validate(highlight.timing_origin)
            if not isinstance(highlight.kana,str) or not highlight.kana:
                raise ValueError('演唱音节读音为空')
            if type(highlight.start) is not int or type(highlight.end) is not int or not previous<=highlight.start<=highlight.end<=self.end:
                raise ValueError('演唱音节时间超出词组范围或互相重叠')
            previous=highlight.end
        if self.highlights and ''.join(h.kana for h in self.highlights)!=self.kana:
            raise ValueError('演唱音节读音合并后必须与词组假名一致')


@dataclass
class LyricLine:
    id: str
    text: str
    start: int
    end: int
    units: list[Unit] = field(default_factory=list)
    kana: str = ''
    romaji: str = ''
    translation: str = ''
    locked: bool = False
    reviewed: bool = False
    match: dict = field(default_factory=dict)
    reading_review: dict = field(default_factory=dict)
    timing_evidence: dict = field(default_factory=dict)
    display_start: int | None = None
    display_end: int | None = None
    timing_origin: dict = field(default_factory=dict)

    def validate(self):
        from .provenance import validate
        validate(self.timing_origin)
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end:
            raise ValueError('歌词开始时间须小于结束时间')
        if not self.text or len(self.text) > 20000:
            raise ValueError('歌词内容为空或过长')
        if self.display_start is not None and (type(self.display_start) is not int or not 0 <= self.display_start <= self.start):
            raise ValueError('字幕出现时间须非负，且不能晚于演唱开始')
        if self.display_end is not None and (type(self.display_end) is not int or self.display_end < self.end):
            raise ValueError('字幕消失时间不能早于演唱结束')
        if len(self.units) > 20000:
            raise ValueError('音节过多')
        previous = self.start
        for unit in self.units:
            unit.validate()
            if unit.start < previous or unit.end > self.end:
                raise ValueError('音节超出歌词范围或互相重叠')
            previous = unit.end
        if self.units and ''.join(u.text for u in self.units) != self.text:
            raise ValueError('音节文字合并后必须与原歌词一致')
        if not isinstance(self.match,dict):
            raise ValueError('匹配资料无效')
        if not isinstance(self.reading_review,dict):
            raise ValueError('读音复核资料无效')
        if not isinstance(self.timing_evidence,dict):raise ValueError('歌声对齐资料无效')
        if self.timing_evidence:
            import json
            try:encoded=json.dumps(self.timing_evidence,ensure_ascii=False,allow_nan=False)
            except (TypeError,ValueError) as error:raise ValueError('歌声对齐资料包含无效数值') from error
            if len(encoded)>2000000:raise ValueError('歌声对齐资料过大')
        if self.match:
            if self.match.get('status') not in {'matched','uncertain','unmatched','protected','manual'}:
                raise ValueError('匹配状态无效')
            for name in ('score','coverage'):
                value=self.match.get(name,0)
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:
                    raise ValueError('匹配相似度无效')
            for name in ('recognized','reason'):
                if not isinstance(self.match.get(name,''),str) or len(self.match.get(name,''))>100000:
                    raise ValueError('匹配说明无效')

    @classmethod
    def from_dict(cls, value):
        fields = {k: v for k, v in value.items() if k in cls.__dataclass_fields__ and k != 'units'}
        fields['units'] = [Unit(**{k: v for k, v in u.items() if k in Unit.__dataclass_fields__}) for u in value.get('units', [])]
        line = cls(**fields)
        line.validate()
        return line

    def to_dict(self):
        value=asdict(self)
        # Older task signatures and immutable checkpoints predate this field.
        # Keep empty evidence out of legacy dictionaries. Real evidence is
        # always serialized and protected by project schema 7.
        if not self.timing_evidence:value.pop('timing_evidence')
        for item in [value,*value['units'],*(h for u in value['units'] for h in u['highlights'])]:
            if not item.get('timing_origin'):item.pop('timing_origin',None)
        return value

    def karaoke(self, tag='kf', furigana=False):
        self.validate()
        if tag not in {'k', 'kf', 'ko'}:
            raise ValueError('不支持的卡拉 OK 标签')
        if not self.units:
            return literal(self.text)
        output = []
        cursor = round(self.start / 10)
        for unit in self.units:
            if furigana and unit.highlights:
                for index,highlight in enumerate(unit.highlights):
                    begin=round(highlight.start/10);end=round(highlight.end/10)
                    if begin>cursor:
                        output.append('{\\k'+str(begin-cursor)+'}')
                    fragment=literal(unit.text) if index==0 else '#'
                    fragment+='|'+('!' if index==0 else '')+literal(highlight.kana)
                    output.append('{\\'+tag+str(max(0,end-max(cursor,begin)))+'}'+fragment)
                    cursor=max(cursor,end)
                continue
            begin = round(unit.start / 10)
            end = round(unit.end / 10)
            if begin > cursor:
                output.append('{\\k' + str(begin - cursor) + '}')
            fragment = literal(unit.text)
            if furigana and unit.kana and unit.kana != unit.text:
                # Automation 4 sequence break prevents adjacent words merging.
                fragment += '|!' + literal(unit.kana).replace('|', '｜')
            output.append('{\\' + tag + str(max(0, end - max(cursor, begin))) + '}' + fragment)
            cursor = max(cursor, end)
        return ''.join(output)


def estimated_units(text, start, end):
    """Editable fallback only; this is never presented as acoustic alignment."""
    if not text:
        return []
    # Small kana belong to the preceding mora; long vowels and ん remain separate.
    fragments = []
    for char in text:
        if fragments and char in 'ぁぃぅぇぉゃゅょァィゥェォャュョゎヮゕゖ':
            fragments[-1] += char
        else:
            fragments.append(char)
    n = len(fragments)
    from .provenance import create
    return [Unit(t,a,b,timing_origin=create('estimated',a,b,method='text_distribution')) for i,t in enumerate(fragments)
            for a,b in [(start+round((end-start)*i/n),start+round((end-start)*(i+1)/n))]]


def align_characters(text, characters, start_offset=0):
    """Require exact source coverage; omitted punctuation isn't silently guessed."""
    returned = ''.join(c.get('text', '') for c in characters)
    if returned != text:
        raise ValueError('API 对齐文字与歌词不一致，请检查歌词后重新对齐')
    units = []
    for char in characters:
        start, end = ms(char.get('start')), ms(char.get('end'))
        from .provenance import create
        a,b=start+start_offset,end+start_offset
        units.append(Unit(char['text'],a,b,source='alignment',timing_origin=create('character',a,b,'elevenlabs','text_alignment')))
    if not units:
        raise ValueError('API 没有返回可用的字符时间戳')
    return units
