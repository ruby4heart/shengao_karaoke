import json

from shengao import draft_recovery
from shengao.project import Project
from shengao.tap_timing import TapDraft


def tapped(project):
    line=project.lines[0];draft=TapDraft(line)
    for point in range(line.start,line.start+40*3,40)[:3]:draft.add(point)
    stamp={'path':'m','size':1,'modified_ns':2}
    return line,draft,stamp,draft_recovery.tap_record(project,line,draft,stamp,'original')


def test_unchanged_draft_can_be_restored_with_its_points(project):
    line,draft,stamp,record=tapped(project)
    record=json.loads(json.dumps(record))  # as stored in the recovery file
    assert draft_recovery.assess(record,project,stamp,'original')==('ready','')
    again=draft_recovery.rebuild(record,project.lines[0])
    assert again.points==draft.points and again.mode==draft.mode
    assert '已录 3/' in draft_recovery.describe(record)


def test_stale_drafts_are_reported_with_the_reason(project):
    line,draft,stamp,record=tapped(project)
    edited=Project.from_dict(project.to_dict());edited.lines[0].translation='后来改过'
    assert draft_recovery.assess(record,edited,stamp,'original')[0]=='stale'
    assert '修改' in draft_recovery.assess(record,edited,stamp,'original')[1]
    assert '素材' in draft_recovery.assess(record,project,{'path':'m','size':9,'modified_ns':2},'original')[1]
    assert '试听' in draft_recovery.assess(record,project,stamp,'vocals')[1]
    removed=Project.from_dict(project.to_dict());removed.lines=[]
    assert draft_recovery.assess(record,removed,stamp,'original')==('stale','这一句已删除')


def test_incomplete_records_are_invalid(project):
    assert draft_recovery.assess({'kind':'tap'},project,{},'original')[0]=='invalid'
    line,draft,stamp,record=tapped(project);record['points']=[record['points'][0],record['points'][0]-500]
    assert draft_recovery.assess(record,project,stamp,'original')[0]=='invalid'
