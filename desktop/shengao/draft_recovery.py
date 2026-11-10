"""Unapplied manual drafts kept in the recovery file.

A draft records what it depends on: the exact original line, the media file
and the audition source. On reopen it is compared first; only a draft whose
line, media and audition source are all unchanged can be restored. A stale
draft can be viewed and discarded but never applied over later work.
"""
import copy
import time

KINDS={'tap':'跟唱打点'}


def tap_record(project,line,draft,media_stamp,audition_role,now=None):
    return {'kind':'tap','project_uid':project.uid,'line_id':line.id,'line_index':project.lines.index(line) if line in project.lines else -1,
            'text':line.text,'original':draft.original.to_dict(),'mode':draft.mode,'acknowledge_gaps':bool(draft.acknowledge_gaps),
            'points':list(draft.points),'required':draft.required,'media':project.media,'media_stamp':copy.deepcopy(media_stamp or {}),
            'media_role':project.media_role,'audition_role':audition_role,'created':int((time.time() if now is None else now)*1000)}


def valid(record):
    return (isinstance(record,dict) and record.get('kind') in KINDS and isinstance(record.get('line_id'),str) and
            isinstance(record.get('original'),dict) and isinstance(record.get('points'),list) and
            all(type(x) is int for x in record['points']) and isinstance(record.get('media_stamp'),dict))


def differences(record,project,media_stamp,audition_role=None):
    """What changed since a record was taken, in a fixed order, as (key, reason).

    The one version check shared by unapplied drafts and the remembered
    editing position: same project, the line by id and exact content, the
    media file stamp, the video version and (when given) the audition source.
    """
    if record.get('project_uid')!=project.uid:return [('project','草稿属于另一个工程')]
    found=[];line=next((x for x in project.lines if x.id==record.get('line_id')),None)
    if line is None:found.append(('line_missing','这一句已删除'))
    elif line.to_dict()!=record.get('original'):found.append(('line_changed','这一句后来被修改过，草稿基于旧内容'))
    if not same_media(record.get('media_stamp'),media_stamp):found.append(('media','素材文件已变化或尚未找到'))
    if record.get('media_role')!=project.media_role:found.append(('media_role','当前使用的视频版本不同'))
    if audition_role is not None and record.get('audition_role')!=audition_role:
        found.append(('audition','录制时使用'+('人声辅助' if record.get('audition_role')=='vocals' else '原声')+'试听，当前试听源不同'))
    return found


def assess(record,project,media_stamp,audition_role):
    """(state, reason). state is 'ready', 'stale' or 'invalid'."""
    if not valid(record):return 'invalid','草稿记录不完整'
    changed=differences(record,project,media_stamp,audition_role)
    if changed:return 'stale',changed[0][1]
    line=next(x for x in project.lines if x.id==record['line_id'])
    try:rebuild(record,line)
    except ValueError as error:return 'invalid',str(error)
    return 'ready',''


def same_media(recorded,current):
    """Same file content stamp; a file moved without change still counts."""
    recorded=recorded or {};current=current or {}
    if not recorded or not current:return recorded==current
    return (recorded.get('size'),recorded.get('modified_ns'))==(current.get('size'),current.get('modified_ns'))


def rebuild(record,line):
    """A TapDraft for the current (identical) line with the recorded points."""
    from .tap_timing import TapDraft
    return TapDraft(line,record.get('mode','paired'),bool(record.get('acknowledge_gaps')),list(record['points']))


def describe(record):
    points=len(record.get('points',[]));required=record.get('required') or points
    text=record.get('text','');text=text if len(text)<=24 else text[:23]+'…'
    return f'{KINDS.get(record.get("kind"),"草稿")} · 「{text}」 · 已录 {points}/{required} 点'
