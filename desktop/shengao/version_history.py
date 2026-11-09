"""Project version history: checkpoints on disk, per-line comparison and restore.

Toolkit independent. A checkpoint is a detached project snapshot stored under
<home>/version-history/<project uid>/ with a small index for listing. The GUI
decides when to record one; writes may run on a worker thread because every
method works only on the data passed in and serialises disk access.

Single-line restore follows the 8.1 rules: the lyric text is never rewritten,
other lines, per-line styles and the current media relation stay as they are,
current fixed points are kept, and a confirmation only travels together with
the exact content it confirmed. The caller applies it as one undo step.
"""
from dataclasses import dataclass,field
from pathlib import Path
import copy
import hashlib
import json
import re
import threading
import time
import uuid

from studio_backend.settings import atomic_json
from .checkpoint_encoding import dumps as checkpoint_dumps

REASONS={'auto':'自动检查点','save':'保存','before_restore':'恢复前','opened':'打开时'}
KEEP={'save':20,'auto':40}
MEDIA_FIELDS=('media','media_stamp','media_versions','media_role','duration','has_video','width','height','fps','vocal_track')
_SAFE_UID=re.compile(r'[^A-Za-z0-9_-]')


def digest(snapshot):
    """Content digest of a project snapshot, independent of key order."""
    text=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False,default=repr)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _summary(snapshot):
    lines=snapshot.get('lines',[]);checks=snapshot.get('checks',{})
    return {'lines':len(lines),'timing':sum(bool(x.get('reviewed')) for x in lines),
            'readings':sum(bool(checks.get(x.get('id'),{}).get('reading')) for x in lines if isinstance(checks.get(x.get('id')),dict))}


class VersionHistory:
    """Checkpoints of one project. Thread safe for one process."""
    def __init__(self,root,uid):
        if not isinstance(uid,str) or not uid:raise ValueError('工程编号无效')
        self.folder=Path(root)/(_SAFE_UID.sub('_',uid)[:80] or 'project');self.uid=uid
        self._lock=threading.Lock()

    @property
    def index_path(self):return self.folder/'index.json'

    def _read_index(self):
        try:value=json.loads(self.index_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):return self._rebuild_index()
        entries=value.get('entries') if isinstance(value,dict) else None
        if not isinstance(entries,list) or any(not isinstance(x,dict) or not isinstance(x.get('id'),str) for x in entries):return self._rebuild_index()
        return [x for x in entries if (self.folder/(x['id']+'.json')).is_file()]

    def _rebuild_index(self):
        """A lost or damaged index never hides checkpoints that are still on disk."""
        entries=[]
        if not self.folder.is_dir():return entries
        for path in sorted(self.folder.glob('v-*.json')):
            try:value=json.loads(path.read_text(encoding='utf-8'));entries.append(value['meta'])
            except (OSError,ValueError,KeyError,TypeError):continue
        entries=[x for x in entries if isinstance(x,dict) and x.get('id')==Path(str(x.get('id'))).name]
        entries.sort(key=lambda x:(x.get('created_ms',0),x.get('id','')))
        return entries

    def entries(self):
        """Newest first; metadata only."""
        with self._lock:return list(reversed(self._read_index()))

    def latest_digest(self):
        entries=self.entries()
        return entries[0].get('digest') if entries else None

    def record(self,snapshot,reason='auto',label='',path='',now=None):
        """Store a checkpoint unless it equals the newest one. Returns its metadata or None."""
        if reason not in REASONS:raise ValueError('检查点类型无效')
        if not isinstance(snapshot,dict) or snapshot.get('uid')!=self.uid:raise ValueError('检查点与当前工程不一致')
        value=digest(snapshot);created=time.time() if now is None else now
        with self._lock:
            entries=self._read_index()
            if entries and entries[-1].get('digest')==value:return None
            ident='v-'+time.strftime('%Y%m%d-%H%M%S',time.localtime(created))+'-'+uuid.uuid4().hex[:8]
            meta={'id':ident,'created_ms':int(created*1000),'reason':reason,'label':str(label)[:120],'digest':value,
                  'path':str(path or ''),'title':str(snapshot.get('title',''))[:200],
                  'media_name':Path(snapshot.get('media') or '').name,'media_stamp':copy.deepcopy(snapshot.get('media_stamp') or {}),
                  **_summary(snapshot)}
            self.folder.mkdir(parents=True,exist_ok=True)
            atomic_json(self.folder/(ident+'.json'),{'meta':meta,'project':snapshot},compact=True,dumps=checkpoint_dumps)
            entries.append(meta);entries=self._prune(entries)
            atomic_json(self.index_path,{'uid':self.uid,'entries':entries},compact=True)
            return meta

    def _prune(self,entries):
        keep=set()
        for kind,count in KEEP.items():
            group=[x for x in entries if (x.get('reason')=='save')==(kind=='save')]
            keep.update(x['id'] for x in group[-count:])
        result=[]
        for item in entries:
            if item['id'] in keep:result.append(item)
            else:(self.folder/(item['id']+'.json')).unlink(missing_ok=True)
        return result

    def load(self,ident):
        if not isinstance(ident,str) or Path(ident).name!=ident or not ident.startswith('v-'):raise ValueError('检查点编号无效')
        with self._lock:
            try:value=json.loads((self.folder/(ident+'.json')).read_text(encoding='utf-8'))
            except OSError as error:raise ValueError('检查点已不存在') from error
        project=value.get('project') if isinstance(value,dict) else None
        if not isinstance(project,dict) or project.get('uid')!=self.uid:raise ValueError('检查点内容无效或不属于本工程')
        if value.get('meta',{}).get('digest') not in (None,digest(project)):raise ValueError('检查点内容已损坏')
        return project


# ---------------------------------------------------------------- comparison

def _timing_key(line):
    return (line.get('start'),line.get('end'),line.get('display_start'),line.get('display_end'),
            [(u.get('start'),u.get('end'),[(h.get('start'),h.get('end')) for h in u.get('highlights',[])]) for u in line.get('units',[])])

def _reading_key(line):
    return (line.get('kana',''),line.get('romaji',''),
            [(u.get('text'),u.get('kana',''),u.get('romaji',''),u.get('reading_options',{}),[h.get('kana') for h in u.get('highlights',[])]) for u in line.get('units',[])])

def _split_key(line):return [u.get('text') for u in line.get('units',[])]

def _fixed(line):
    return [(i,j,tuple(h.get('fixed_edges',[]))) for i,u in enumerate(line.get('units',[])) for j,h in enumerate(u.get('highlights',[])) if h.get('fixed_edges')]

def _locked(line):return bool(line.get('locked')) or any(u.get('locked') for u in line.get('units',[]))

CHANGE_TITLES={'text':'文字','split':'词组划分','timing':'时间','reading':'读音／音节','translation':'译文',
               'timing_confirmed':'时间确认','reading_confirmed':'读音确认','fixed':'固定点','locked':'锁定'}


@dataclass
class LineChange:
    line_id:str
    status:str            # unchanged, changed, removed (only in history), added (only now)
    old_index:int|None
    new_index:int|None
    text:str
    fields:list=field(default_factory=list)

    @property
    def description(self):
        if self.status=='removed':return '当前已删除'
        if self.status=='added':return '该版本中没有'
        if self.status=='unchanged':return '相同'
        return '、'.join(CHANGE_TITLES[x] for x in self.fields)


def compare(old_snapshot,current_snapshot):
    """Per-line differences between a checkpoint and the current document."""
    old={x['id']:(i,x) for i,x in enumerate(old_snapshot.get('lines',[]))}
    new={x['id']:(i,x) for i,x in enumerate(current_snapshot.get('lines',[]))}
    oc=old_snapshot.get('checks',{});nc=current_snapshot.get('checks',{})
    result=[]
    for uid,(index,line) in new.items():
        if uid not in old:result.append(LineChange(uid,'added',None,index,line['text']));continue
        old_index,before=old[uid];fields=[]
        if before['text']!=line['text']:fields.append('text')
        elif _split_key(before)!=_split_key(line):fields.append('split')
        if _timing_key(before)!=_timing_key(line):fields.append('timing')
        if _reading_key(before)!=_reading_key(line):fields.append('reading')
        if before.get('translation','')!=line.get('translation',''):fields.append('translation')
        if bool(before.get('reviewed'))!=bool(line.get('reviewed')):fields.append('timing_confirmed')
        if bool(oc.get(uid,{}).get('reading'))!=bool(nc.get(uid,{}).get('reading')):fields.append('reading_confirmed')
        if _fixed(before)!=_fixed(line):fields.append('fixed')
        if _locked(before)!=_locked(line):fields.append('locked')
        result.append(LineChange(uid,'changed' if fields else 'unchanged',old_index,index,line['text'],fields))
    for uid,(index,line) in old.items():
        if uid not in new:result.append(LineChange(uid,'removed',index,None,line['text']))
    order=lambda c:(c.new_index if c.new_index is not None else _insert_position(old_snapshot,current_snapshot,c.line_id)-.5,c.old_index or 0)
    result.sort(key=order)
    return result


def media_note(old_snapshot,current_snapshot):
    """Explain when a checkpoint was made against another media file."""
    old=old_snapshot.get('media_stamp') or {};new=current_snapshot.get('media_stamp') or {}
    if not old or not new:return ''
    if (old.get('size'),old.get('modified_ns'))==(new.get('size'),new.get('modified_ns')):return ''
    name=Path(old_snapshot.get('media') or '').name or '另一个文件'
    return f'该版本基于素材「{name}」，与当前素材不是同一文件；恢复的时间可能与当前素材对不上，请试听确认。'


# ------------------------------------------------------------ single restore

def _insert_position(old_snapshot,current_snapshot,uid):
    """Current index for a deleted line: after the nearest earlier line that still exists."""
    old_ids=[x['id'] for x in old_snapshot.get('lines',[])];now=[x['id'] for x in current_snapshot.get('lines',[])]
    if uid not in old_ids:return len(now)
    for previous in reversed(old_ids[:old_ids.index(uid)]):
        if previous in now:return now.index(previous)+1
    return 0


def restore_line(project,old_snapshot,uid):
    """Restore one line from a checkpoint into the given (candidate) project.

    Returns a list of plain notes describing what was kept. Raises ValueError
    with the reason when the restore would break a protected decision.
    """
    from studio_backend.model import LyricLine
    old_lines={x['id']:x for x in old_snapshot.get('lines',[])}
    if uid not in old_lines:raise ValueError('该版本中没有这一句，不能恢复。')
    old=copy.deepcopy(old_lines[uid]);old_check=copy.deepcopy(old_snapshot.get('checks',{}).get(uid) or {})
    rows={line.id:i for i,line in enumerate(project.lines)};notes=[]
    if uid not in rows:
        # Deleted later: bring the historic line back where it was, with the
        # decisions recorded together with it. No other line is touched.
        position=_insert_position(old_snapshot,project.to_dict(),uid)
        line=LyricLine.from_dict(old);project.lines.insert(position,line)
        if old_check:project.checks[uid]=old_check
        else:project.checks.pop(uid,None)
        notes.append('已恢复删除的这一句，原来的时间和确认状态一起恢复；单句样式不恢复，使用当前样式。')
        return notes
    row=rows[uid];current=project.lines[row].to_dict()
    if _locked(current):raise ValueError('本句或其中词组已锁定；请先解除锁定再恢复。')
    if old['text']!=current['text']:
        raise ValueError('该版本中这一句的文字不同；单句恢复不会改写原歌词。如需找回旧文字，请先手动修改文字，或整份恢复该版本。')
    restored=copy.deepcopy(old);restored['id']=uid
    # Text matching and original-text confirmation belong to the unchanged text.
    restored['match']=copy.deepcopy(current.get('match',{}))
    if _reading_key(old)==_reading_key(current):
        for key in ('kana','romaji'):restored[key]=current.get(key,'')
        restored['reading_review']=copy.deepcopy(current.get('reading_review',{}))
        for target,source in zip(restored.get('units',[]),current.get('units',[])):
            for key in ('kana','romaji','reading_source','reading_options'):target[key]=copy.deepcopy(source.get(key,''if key!='reading_options' else {}))
        check=copy.deepcopy(project.checks.get(uid) or {})
    else:
        check=old_check
        if bool(check.get('reading'))!=bool(project.checks.get(uid,{}).get('reading')):
            notes.append('读音与当前不同，读音确认改为该版本当时的状态。' if check.get('reading') else '读音与当前不同，当前的读音确认不适用于旧读音，已改为未确认。')
    if _timing_key(old)==_timing_key(current):restored['reviewed']=current.get('reviewed',False)
    elif bool(old.get('reviewed'))!=bool(current.get('reviewed')):
        notes.append('时间确认改为该版本当时的状态。' if old.get('reviewed') else '时间与当前不同，当前的时间确认已改为未确认。')
    fixed=_fixed(current)
    if fixed:
        if [len(u.get('highlights',[])) for u in restored.get('units',[])]!=[len(u.get('highlights',[])) for u in current.get('units',[])] or _split_key(restored)!=_split_key(current):
            raise ValueError('本句有固定点，而该版本的词组或音节划分不同；恢复会丢失固定点，未恢复。')
        for i,j,edges in fixed:
            source=current['units'][i]['highlights'][j];target=restored['units'][i]['highlights'][j]
            for edge in edges:target[edge]=source[edge]
            target['fixed_edges']=list(edges)
        notes.append(f'保留当前 {len(fixed)} 个音节的固定点。')
    try:line=LyricLine.from_dict(restored)
    except (ValueError,TypeError) as error:raise ValueError('保留当前固定点后，该版本的时间与之冲突：'+str(error)) from error
    project.lines[row]=line
    if check:project.checks[uid]=check
    else:project.checks.pop(uid,None)
    return notes


def restore_document(project,old_snapshot):
    """Whole-version restore that keeps the project identity and current media relation."""
    from .project import Project
    value=copy.deepcopy(old_snapshot);current=project.to_dict()
    for name in MEDIA_FIELDS:value[name]=copy.deepcopy(current[name])
    value['uid']=current['uid']
    restored=Project.from_dict(value)
    for name in Project.__dataclass_fields__:setattr(project,name,getattr(restored,name))
    return ['素材和视频版本保持当前设置。']
