"""Notice edits other subtitle tools made to an ASS that Shengao exported.

An exported ASS carries the whole project, so reopening it used to restore the
project and silently drop anything changed in Aegisub or another editor. The
export now also writes, per lyric line, one commented karaoke source row
(Name ``shengao:<line id>``, Effect ``karaoke``, plain ``\\k`` timing) plus a
digest of the styles and display events. Reopening compares both:

* changed source rows become timing changes, applied as one undoable step;
  the original lyric text is never rewritten, so text or syllable-split edits
  are reported as conflicts instead;
* changed display rows or styles cannot be mapped back to lyric timing, so the
  person chooses between the Shengao project and importing the file as an
  external ASS (which keeps those styles and effects).
"""
from dataclasses import dataclass,field
import copy
import hashlib
import re
from studio_backend.export import ass_time
from studio_backend.model import literal,plain_ass

SOURCE_PREFIX='shengao:'
SOURCE_EFFECT='karaoke'
HEADER='; ShengaoEvents: v1 '
_EVENT_FORMAT=['Layer','Start','End','Style','Name','MarginL','MarginR','MarginV','Effect','Text']


def _centiseconds(text):
    h,m,s=text.strip().split(':');return round((int(h)*3600+int(m)*60+float(s))*100)


def _number(token):
    token=token.strip()
    try:return format(float(token),'g')
    except ValueError:return token


def _events(text):
    """Yield (kind, fields) for every Dialogue/Comment row in [Events]."""
    section='';names=_EVENT_FORMAT
    for row in text.splitlines():
        stripped=row.strip()
        if stripped.startswith('['):section=stripped.lower();continue
        if section!='[events]':continue
        if row.startswith('Format:'):names=[x.strip() for x in row.split(':',1)[1].split(',')];continue
        kind=row.split(':',1)[0]
        if kind not in ('Dialogue','Comment'):continue
        values=row.split(':',1)[1].lstrip().split(',',len(names)-1)
        if len(values)!=len(names):continue
        yield kind,dict(zip(names,values))


def _is_source(fields):
    return fields.get('Name','').strip().startswith(SOURCE_PREFIX) and fields.get('Effect','').strip()==SOURCE_EFFECT


def digest(text):
    """Hash of styles and display events, tolerant of number re-formatting."""
    parts=[];section=''
    for row in text.splitlines():
        stripped=row.strip()
        if stripped.startswith('['):section=stripped.lower();continue
        if section in ('[v4+ styles]','[v4 styles]') and row.startswith('Style:'):
            parts.append('S:'+','.join(_number(x) for x in row.split(':',1)[1].split(',')))
    for kind,fields in _events(text):
        if _is_source(fields):continue
        values=[]
        for name in _EVENT_FORMAT:
            value=fields.get(name,'')
            if name in ('Start','End'):
                try:value=str(_centiseconds(value))
                except ValueError:value=value.strip()
            elif name=='Text':value=value.rstrip()
            else:value=_number(value)
            values.append(value)
        parts.append(kind[0]+':'+','.join(values))
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def source_row(line):
    return f'Comment: 0,{ass_time(line.start)},{ass_time(line.end)},Lyrics,{SOURCE_PREFIX}{line.id},0,0,0,{SOURCE_EFFECT},{line.karaoke("k")}'


def mark(text,project):
    """Add source rows to [Events] and the display digest header."""
    rows=text.split('\n');section='';last=None
    for index,row in enumerate(rows):
        stripped=row.strip()
        if stripped.startswith('['):section=stripped.lower();continue
        if section=='[events]' and row.startswith(('Dialogue:','Comment:','Format:')):last=index
    if last is None:raise ValueError('ASS 内容缺少 [Events] 段落')
    rows[last+1:last+1]=[source_row(line) for line in project.lines]
    rows=[row for row in rows if not row.startswith(HEADER)]
    marked='\n'.join(rows)
    header=HEADER+digest(marked)
    at=1 if rows and rows[0].startswith('; ShengaoProject: ') else 0
    rows.insert(at,header)
    return '\n'.join(rows)


@dataclass
class ExternalEdits:
    marked:bool=False
    display_changed:bool=False
    changes:dict=field(default_factory=dict)  # line id -> (start, end, [(start, end)] or None)
    conflicts:list=field(default_factory=list)

    @property
    def any(self):return bool(self.display_changed or self.changes or self.conflicts)

    def summary(self):
        parts=[]
        if self.changes:parts.append(f'外部修改了 {len(self.changes)} 句的时间')
        if self.display_changed:parts.append('外部修改了样式或显示事件（无法换算回歌词时间）')
        if self.conflicts:parts.append(f'{len(self.conflicts)} 处修改未应用：'+'；'.join(self.conflicts[:5])+('……' if len(self.conflicts)>5 else ''))
        return '；'.join(parts)


def _segments(raw):
    """[(centiseconds, visible text)] for each \\k tag; None when untagged."""
    matches=list(re.finditer(r'\\[kK](?:f|o)?(\d+)',raw))
    if not matches:return None
    lead=plain_ass(raw[:matches[0].start()].rsplit('{',1)[0])
    if lead:return False
    result=[]
    for n,match in enumerate(matches):
        fragment=raw[match.end():matches[n+1].start() if n+1<len(matches) else len(raw)]
        fragment=fragment.split('}',1)[1] if '}' in fragment else fragment
        fragment=fragment.rsplit('{',1)[0] if n+1<len(matches) else fragment
        result.append((int(match.group(1)),plain_ass(fragment)))
    return result


def _keep(original,centiseconds):
    """Keep millisecond precision for boundaries the other tool did not move."""
    return original if round(original/10)==centiseconds else centiseconds*10


def inspect(text,project):
    """Compare an exported ASS with the project embedded in it."""
    report=ExternalEdits()
    header=next((row for row in text.splitlines() if row.startswith(HEADER)),None)
    if header is None:return report
    report.marked=True
    report.display_changed=header[len(HEADER):].strip()!=digest(text)
    by_id={line.id:(index,line) for index,line in enumerate(project.lines)}
    seen=set()
    for _,fields in _events(text):
        if not _is_source(fields):continue
        line_id=fields['Name'].strip()[len(SOURCE_PREFIX):]
        if line_id not in by_id:report.conflicts.append('有一条声稿注释行对应不到原歌词');continue
        if line_id in seen:report.conflicts.append(f'第 {by_id[line_id][0]+1} 句的声稿注释行重复');continue
        seen.add(line_id);index,line=by_id[line_id];label=f'第 {index+1} 句'
        try:start,end=_centiseconds(fields['Start']),_centiseconds(fields['End'])
        except ValueError:report.conflicts.append(label+'的时间格式无法读取');continue
        raw=fields['Text'].rstrip()
        expected=source_row(line).split(',',9)
        if (start,end,raw)==(_centiseconds(expected[1]),_centiseconds(expected[2]),expected[9]):continue
        if line.units:
            segments=_segments(raw)
            if not segments:report.conflicts.append(label+'的逐音标签被删除或改动，保留原时间');continue
            units=[];cursor=start
            for duration,visible in segments:
                if visible:units.append((cursor,cursor+duration,visible))
                cursor+=duration
            if [v for _,_,v in units]!=[literal(u.text) for u in line.units]:
                report.conflicts.append(label+'的文字或音节划分在外部被修改；原歌词保留，未应用');continue
            timed=[(_keep(u.start,a),_keep(u.end,b)) for u,(a,b,_) in zip(line.units,units)]
            new_start=min(_keep(line.start,start),timed[0][0]);new_end=max(_keep(line.end,end),timed[-1][1])
        else:
            if plain_ass(raw)!=plain_ass(expected[9]):
                report.conflicts.append(label+'的文字在外部被修改；原歌词保留，未应用');continue
            timed=None;new_start,new_end=_keep(line.start,start),_keep(line.end,end)
        if line.locked:report.conflicts.append(label+'已锁定，外部时间修改未应用');continue
        if (new_start,new_end)==(line.start,line.end) and (timed is None or timed==[(u.start,u.end) for u in line.units]):continue
        report.changes[line_id]=(new_start,new_end,timed)
    for line_id,(index,_) in by_id.items():
        if line_id not in seen:report.conflicts.append(f'第 {index+1} 句的声稿注释行被删除，保留原时间')
    return report


def apply(project,report):
    """Apply timing changes in place; returns messages for lines left as-is."""
    from studio_backend import provenance
    from .timing import manual,retime_unit
    skipped=[]
    for index,line in enumerate(project.lines):
        change=report.changes.get(line.id)
        if change is None:continue
        start,end,timed=change;before=copy.deepcopy(line)
        try:
            line.start,line.end=start,end
            for unit,(a,b) in zip(line.units,timed or ()):
                if (a,b)!=(unit.start,unit.end):retime_unit(unit,a,b)
            provenance.record(before,line,'shift' if end-start==before.end-before.start else 'manual_boundary')
            manual(line);line.validate()
        except ValueError as error:
            project.lines[index]=before;skipped.append(f'第 {index+1} 句：{error}')
    return skipped
