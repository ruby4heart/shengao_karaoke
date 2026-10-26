import copy
import pytest
from shengao.project import Project,History
from shengao.timing import set_time
from studio_backend.model import LyricLine
from test_project_snapshot_isolation import project


def sample():
    p=project();p.lines.append(LyricLine('neighbor','次',600,1000,reading_review={'notes':['neighbor']}));p.tasks=[{'notes':['task']}];return p


@pytest.mark.parametrize('a,b',[(110,510),(90,490),(100,600),(100,450)])
def test_single_line_history_matches_general_transaction_and_undo_redo(a,b):
    p=sample();before=p.to_dict();general=History(Project.from_dict(before));local=History(Project.from_dict(before))
    assert general.apply('调整',lambda q:q.lines.__setitem__(0,set_time(q.lines[0],-1,a,b)))
    assert local.apply_line('调整',0,lambda line:set_time(line,-1,a,b))
    after=general.project.to_dict();assert local.project.to_dict()==after and local.undo_stack==general.undo_stack
    assert local.undo() and local.project.to_dict()==before
    assert local.redo() and local.project.to_dict()==after


def test_line_transaction_detaches_other_rows_global_data_and_undo_records():
    p=sample();before=p.to_dict();history=History(p)
    def edit(line):line.reading_review['notes']['values'].append('new');return line
    assert history.apply_line('本句备注',0,edit);after=history.project.to_dict()
    p.lines[1].reading_review['notes'].append('old reference');p.tasks[0]['notes'].append('old task')
    assert history.project.to_dict()==after and history.undo_stack[-1][1]==before
    history.project.lines[1].reading_review['notes'].append('new reference')
    assert p.lines[1].reading_review['notes']==['neighbor','old reference'] and history.undo_stack[-1][1]==before


@pytest.mark.parametrize('invalid',[
    lambda p:setattr(p.lines[0],'end',0),
    lambda p:setattr(p.lines[1],'end',0),
    lambda p:setattr(p.style,'size',0),
    lambda p:p.lines[1].reading_review.update(mora_edits={'bad':'record'}),
])
def test_invalid_before_line_neighbor_and_global_records_cannot_be_published(invalid):
    p=sample();invalid(p);history=History(p);before=p.to_dict()
    with pytest.raises(ValueError):history.apply_line('调整',0,lambda line:set_time(line,-1,110,510))
    assert history.project is p and p.to_dict()==before and not history.undo_stack


def test_line_transaction_rejects_invalid_after_and_keeps_all_history_on_exception():
    history=History(sample());before=history.project.to_dict()
    def invalid(line):line.units[0].highlights[0].fixed_edges=['start','start'];return line
    with pytest.raises(ValueError):history.apply_line('错误',0,invalid)
    def failed(line):line.reading_review['notes']['values'].append('discarded');raise ValueError('controlled')
    with pytest.raises(ValueError):history.apply_line('失败',0,failed)
    assert history.project.to_dict()==before and not history.undo_stack and not history.redo_stack


def test_noop_and_merged_line_transactions_keep_one_undo_step():
    history=History(sample());before=history.project.to_dict()
    assert not history.apply_line('没有修改',0,lambda line:line) and not history.undo_stack
    for start in (110,120):assert history.apply_line('微调',0,lambda line:set_time(line,-1,start,start+400),merge_key='same-line')
    assert len(history.undo_stack)==1 and history.undo() and history.project.to_dict()==before
