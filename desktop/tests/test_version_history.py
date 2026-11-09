import copy
import json
import os

import pytest

from shengao import version_history as vh
from shengao.project import History,Project,file_stamp


def shifted(line,uid,offset):
    value=line.to_dict();value['id']=uid
    for key in ('start','end'):value[key]+=offset
    for u in value['units']:
        u['start']+=offset;u['end']+=offset
        for h in u['highlights']:h['start']+=offset;h['end']+=offset
    from studio_backend.model import LyricLine
    return LyricLine.from_dict(value)


@pytest.fixture
def doc(project):
    first=project.lines[0]
    project.lines=[first,shifted(first,'second',6000),shifted(first,'third',12000)]
    project.checks={first.id:{'reading':True},'second':{'reading':True}}
    project.layout_styles={}
    project.validate()
    return project


def move_first_note(line,delta):
    h=line.units[0].highlights[0];h.start+=delta
    return line


def test_checkpoints_skip_duplicates_prune_and_rebuild_index(tmp_path,doc):
    store=vh.VersionHistory(tmp_path,doc.uid);snapshot=doc.to_dict()
    first=store.record(snapshot,'save',now=1000)
    assert first and store.record(snapshot,'auto',now=1001) is None
    for n in range(45):
        doc.lines[1].translation=f'译文 {n}';store.record(doc.to_dict(),'auto',now=1002+n)
    entries=store.entries()
    assert sum(e['reason']=='auto' for e in entries)==vh.KEEP['auto'] and any(e['id']==first['id'] for e in entries)
    assert len(list(store.folder.glob('v-*.json')))==len(entries)
    store.index_path.write_text('broken',encoding='utf-8')
    assert [e['id'] for e in store.entries()]==[e['id'] for e in entries]
    assert store.load(first['id'])==snapshot and first['lines']==3 and first['readings']==2


def test_damaged_or_foreign_checkpoint_is_refused(tmp_path,doc):
    store=vh.VersionHistory(tmp_path,doc.uid);meta=store.record(doc.to_dict(),'save')
    path=store.folder/(meta['id']+'.json');value=json.loads(path.read_text(encoding='utf-8'))
    value['project']['lines'][0]['translation']='被改过';path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    with pytest.raises(ValueError,match='损坏'):store.load(meta['id'])
    with pytest.raises(ValueError):store.load('../index')
    with pytest.raises(ValueError):vh.VersionHistory(tmp_path,'other').record(doc.to_dict())


def test_compare_lists_changed_removed_and_added_lines(doc):
    old=doc.to_dict()
    move_first_note(doc.lines[0],50);doc.lines[0].reviewed=True
    doc.checks.pop('second');doc.lines[2].translation='新的译文'
    removed=doc.lines.pop(1);del removed
    from studio_backend.model import LyricLine
    doc.lines.append(LyricLine('fourth','新しい',20000,22000))
    changes={c.line_id:c for c in vh.compare(old,doc.to_dict())}
    first=doc.lines[0].id
    assert changes[first].fields==['timing','timing_confirmed'] and changes[first].description=='时间、时间确认'
    assert changes['second'].status=='removed' and changes['third'].fields==['translation'] and changes['fourth'].status=='added'
    assert [c.line_id for c in vh.compare(old,doc.to_dict())]==[first,'second','third','fourth']


def test_single_line_restore_is_one_undo_and_keeps_everything_else(doc):
    old=doc.to_dict();history=History(doc)
    history.apply('改两句',lambda p:(move_first_note(p.lines[0],40),setattr(p.lines[1],'translation','后来的译文')))
    from shengao.line_layout import make_setting
    history.apply('单句排版',lambda p:p.layout_styles.update({p.lines[0].id:make_setting(p.lines[0],90)}))
    before=history.project.to_dict();notes=[]
    assert history.apply('恢复历史单句',lambda p:notes.extend(vh.restore_line(p,old,p.lines[0].id)))
    now=history.project
    assert now.lines[0].to_dict()==old['lines'][0]
    assert now.lines[1].translation=='后来的译文' and now.layout_styles==before['layout_styles']
    assert now.checks==before['checks'] and now.media==before['media']
    assert history.undo() and history.project.to_dict()==before


def test_single_line_restore_never_rewrites_text_or_locked_lines(doc):
    old=doc.to_dict()
    candidate=Project.from_dict(old);line=candidate.lines[0]
    line.text='今日も歌おう';line.units[-1].text='歌おう'
    with pytest.raises(ValueError,match='不会改写原歌词'):vh.restore_line(Project.from_dict(candidate.to_dict()),doc.to_dict(),line.id)
    locked=Project.from_dict(old);move_first_note(locked.lines[0],30);locked.lines[0].locked=True
    with pytest.raises(ValueError,match='锁定'):vh.restore_line(locked,old,locked.lines[0].id)


def test_current_fixed_points_survive_restore(doc):
    old=doc.to_dict();current=Project.from_dict(old)
    h=current.lines[0].units[0].highlights[0];h.start+=60;h.fixed_edges=['start']
    current.lines[0].units[0].highlights[-1].end-=30
    notes=vh.restore_line(current,old,current.lines[0].id)
    restored=current.lines[0].units[0]
    assert restored.highlights[0].start==old['lines'][0]['units'][0]['highlights'][0]['start']+60
    assert restored.highlights[0].fixed_edges==['start'] and restored.highlights[-1].end==old['lines'][0]['units'][0]['highlights'][-1]['end']
    assert any('固定点' in n for n in notes)


def test_fixed_points_block_restore_of_another_split(doc):
    old=doc.to_dict();current=Project.from_dict(old)
    unit=current.lines[0].units[0];unit.highlights=unit.highlights[:1]
    unit.highlights[0].end=unit.end;unit.highlights[0].kana=unit.kana;unit.highlights[0].fixed_edges=['end']
    current.validate()
    with pytest.raises(ValueError,match='固定点'):vh.restore_line(current,old,current.lines[0].id)


def test_reading_confirmation_travels_only_with_its_reading(doc):
    old=doc.to_dict();uid=doc.lines[0].id
    current=Project.from_dict(old);move_first_note(current.lines[0],20)
    vh.restore_line(current,old,uid);assert current.checks[uid]=={'reading':True}
    current=Project.from_dict(old)
    u=current.lines[0].units[1];u.romaji='mo2'
    current.checks[uid]={'reading':True}
    old_unconfirmed=copy.deepcopy(old);old_unconfirmed['checks'].pop(uid)
    current.lines[0].units[1].romaji='mo';current.lines[0].units[1].kana=u.kana
    # Same reading as the checkpoint: the current confirmation is kept.
    vh.restore_line(current,old_unconfirmed,uid);assert current.checks[uid]=={'reading':True}
    current=Project.from_dict(old);current.lines[0].units[1].romaji='mo-'
    notes=vh.restore_line(current,old_unconfirmed,uid)
    assert uid not in current.checks and any('未确认' in n for n in notes)


def test_deleted_line_returns_in_place_with_its_decisions(doc):
    old=doc.to_dict();current=Project.from_dict(old);current.lines.pop(1);current.checks.pop('second')
    vh.restore_line(current,old,'second')
    assert [x.id for x in current.lines]==[x['id'] for x in old['lines']] and current.checks['second']=={'reading':True}


def test_whole_version_restore_keeps_media(tmp_path,doc):
    old=doc.to_dict();media=tmp_path/'new.wav';media.write_bytes(b'0'*10)
    current=Project.from_dict(old);current.media=str(media);current.media_stamp=file_stamp(media);current.lines.pop()
    vh.restore_document(current,old)
    assert len(current.lines)==3 and current.media==str(media) and current.media_stamp==file_stamp(media)


def test_media_note_flags_another_file(doc):
    old=doc.to_dict();old['media_stamp']={'path':'a','size':1,'modified_ns':1};old['media']='/x/a.mp4'
    now=doc.to_dict();now['media_stamp']={'path':'a','size':2,'modified_ns':1}
    assert '「a.mp4」' in vh.media_note(old,now) and vh.media_note(old,old)==''
