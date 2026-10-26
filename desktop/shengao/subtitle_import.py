"""ASS compatibility preserves original styles and override blocks by default."""
from pathlib import Path
import re
from studio_backend.model import LyricLine,Unit,plain_ass
from studio_backend.export import ass_time
from .project import Project

def milliseconds(text):
    h,m,s=text.strip().split(':');return round((int(h)*3600+int(m)*60+float(s))*1000)

def import_ass(text,path=None):
    project=Project(title=Path(path).stem if path else '导入字幕',source_ass=text,source_ass_active=True,source_path=str(path or ''))
    event_format=['Layer','Start','End','Style','Name','MarginL','MarginR','MarginV','Effect','Text']
    section=''
    for row_index,row in enumerate(text.splitlines()):
        if row.startswith('['):section=row.strip().lower()
        if section!='[events]':continue
        if row.startswith('Format:'):event_format=[x.strip() for x in row.split(':',1)[1].split(',')];continue
        if not row.startswith('Dialogue:'):continue
        values=row.split(':',1)[1].lstrip().split(',',len(event_format)-1)
        if len(values)!=len(event_format):continue
        fields=dict(zip(event_format,values));start=milliseconds(fields['Start']);end=max(start+10,milliseconds(fields['End']))
        from .song_info import own_event
        if own_event(fields):continue
        raw=fields['Text'];units=[];tags=[];cursor=start
        # A karaoke tag's following text can contain other overrides; keep them in raw ASS.
        matches=list(re.finditer(r'\\([kK](?:f|o)?)(\d+)',raw))
        for n,match in enumerate(matches):
            finish=cursor+int(match.group(2))*10
            fragment=raw[match.end():matches[n+1].start() if n+1<len(matches) else len(raw)]
            # Strip the close of the containing override block before extracting visible text.
            fragment=fragment.split('}',1)[1] if '}' in fragment else fragment
            visible=plain_ass(fragment).split('|',1)[0]
            reading=plain_ass(fragment).split('|',1)[1].lstrip('!') if '|' in plain_ass(fragment) else ''
            if visible and visible!='#':
                from studio_backend.provenance import create
                units.append(Unit(visible,cursor,finish,reading,source='imported',timing_origin=create('imported',cursor,finish,'ass','karaoke_tags')));tags.append(len(units)-1)
            else:tags.append(None)
            cursor=finish
        visible=''.join(u.text for u in units) if units else plain_ass(raw)
        if not visible.strip():continue
        line=LyricLine('ass-'+str(row_index),visible,start,max(end,cursor),units)
        try:line.validate()
        except ValueError:line=LyricLine(line.id,plain_ass(raw),start,end)
        from studio_backend.provenance import create
        line.timing_origin=create('imported',line.start,line.end,'ass','dialogue')
        project.lines.append(line)
        project.ass_rows.append({'row':row_index,'id':line.id,'fields':event_format,'original':line.to_dict(),'tags':tags})
    if not project.lines:raise ValueError('ASS 文件没有可编辑的 Dialogue 字幕')
    project.font_assets=source_fonts(text)
    project.validate();return project

def needed_fonts(text):
    result=set();names=[];section=''
    for row in text.splitlines():
        if row.startswith('['):section=row.strip().lower()
        if section=='[v4+ styles]':
            if row.startswith('Format:'):names=[x.strip() for x in row.split(':',1)[1].split(',')]
            elif row.startswith('Style:') and 'Fontname' in names:
                values=row.split(':',1)[1].strip().split(',')
                if len(values)>names.index('Fontname'):result.add(values[names.index('Fontname')].strip())
        if row.startswith(('Dialogue:','Comment:')):result.update(re.findall(r'\\fn([^\\}]+)',row))
    return result

def source_fonts(text):
    from .fonts import find_font
    return {family:str(found) for family in needed_fonts(text) if (found:=find_font(family))}

def preserve_ass(project):
    rows=project.source_ass.splitlines();by_id={line.id:line for line in project.lines}
    if project.ass_rows and project.ass_rows[0].get('generated'):
        return preserve_generated(project)
    if not project.ass_rows:
        # Embedded older Shengao ASS remains byte-for-byte until a template is chosen.
        # Do not silently destroy its resolved ruby events or third-party effects.
        return '\n'.join(row for row in rows if not row.startswith('; ShengaoProject: '))+'\n'
    for mapping in project.ass_rows:
        index=mapping['row'];line=by_id.get(mapping['id'])
        if line is None:rows[index]='';continue
        original={'display_start':None,'display_end':None,**mapping['original']}
        if line.to_dict()==original:continue
        names=mapping['fields'];values=rows[index].split(':',1)[1].lstrip().split(',',len(names)-1)
        values[names.index('Start')]=ass_time(line.start);values[names.index('End')]=ass_time(line.end)
        raw=values[names.index('Text')]
        if line.text!=original['text']:
            raise ValueError('此 ASS 含原始样式；改写歌词前请选择声稿样式模板，原 ASS 会保留在工程中')
        if line.units and len(line.units)==len(original.get('units',[])):
            tags=mapping.get('tags',[]);counter=0;cursor=line.start
            def replace(match):
                nonlocal counter,cursor
                unit_index=tags[counter] if counter<len(tags) else None;counter+=1
                if unit_index is None:
                    upcoming=next((x for x in tags[counter:] if x is not None),None)
                    end=line.units[upcoming].start if upcoming is not None else line.end
                else:end=line.units[unit_index].end
                duration=max(0,round(end/10)-round(cursor/10));cursor=end
                return '\\'+match.group(1)+str(duration)
            raw=re.sub(r'\\([kK](?:f|o)?)(\d+)',replace,raw)
        values[names.index('Text')]=raw;rows[index]='Dialogue: '+','.join(values)
    return '\n'.join(row for row in rows if not row.startswith('; ShengaoProject: '))+'\n'

def migrate_generated_style(project,text):
    """Read actual legacy styles, rather than replacing them with defaults."""
    names=[];styles={};section=''
    for row in text.splitlines():
        if row.startswith('['):section=row.strip().lower()
        if section!='[v4+ styles]':continue
        if row.startswith('Format:'):names=[x.strip() for x in row.split(':',1)[1].split(',')]
        elif row.startswith('Style:') and names:
            fields=dict(zip(names,row.split(':',1)[1].strip().split(',')))
            styles[fields.get('Name')]=fields
    def from_color(value):
        value=value.upper().removeprefix('&H').rstrip('&').zfill(8)
        return '#'+value[-2:]+value[-4:-2]+value[-6:-4]
    s=project.style
    for name,family,size in [('Lyrics','font','size'),('Ruby','ruby_font','ruby_size'),('Romaji','font','romaji_size'),('Translation','translation_font','translation_size')]:
        fields=styles.get(name,{})
        if fields.get('Fontname'):setattr(s,family,fields['Fontname'])
        if fields.get('Fontsize'):setattr(s,size,max(8,min(180,round(float(fields['Fontsize'])))))
    fields=styles.get('Lyrics',{})
    for name,key in [('highlight','PrimaryColour'),('color','SecondaryColour'),('outline_color','OutlineColour')]:
        if key in fields:setattr(s,name,from_color(fields[key]))
    for name,key in [('outline','Outline'),('shadow','Shadow')]:
        if key in fields:setattr(s,name,max(0,min(12,float(fields[key]))))

def preserve_generated(project):
    """Keep untouched resolved legacy events exactly; regenerate edited lines only."""
    import copy
    from .subtitles import compose
    originals={x['id']:{'display_start':None,'display_end':None,**x} for x in project.ass_rows[0]['originals']}
    current={x.id:x for x in project.lines}
    changed={uid for uid,value in originals.items() if uid not in current or current[uid].to_dict()!=value}
    changed.update(uid for uid in current if uid not in originals)
    if not changed:return '\n'.join(row for row in project.source_ass.splitlines() if not row.startswith('; ShengaoProject: '))+'\n'
    ranges={(value['start'],value['end']) for uid,value in originals.items() if uid in changed}
    # Legacy resolved ASS has many events per lyric and no per-event line ID.
    # Removing one time range also removes simultaneous lyrics; regenerate all
    # lyrics in those affected ranges so an untouched parallel line survives.
    changed.update(uid for uid,value in originals.items() if (value['start'],value['end']) in ranges)
    kept=[]
    for row in project.source_ass.splitlines():
        if row.startswith('; ShengaoProject: '):continue
        if row.startswith(('Dialogue:','Comment:')):
            fields=row.split(':',1)[1].strip().split(',',9)
            if len(fields)==10 and (milliseconds(fields[1]),milliseconds(fields[2])) in ranges:continue
        kept.append(row)
    p=copy.deepcopy(project);p.source_ass_active=False;p.lines=[line for line in p.lines if line.id in changed];p.song_info={};p.prune_line_overrides()
    kept.extend(row for row in compose(p).splitlines() if row.startswith('Dialogue:'))
    return '\n'.join(kept)+'\n'
