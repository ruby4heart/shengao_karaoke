import copy
import pytest
from dataclasses import asdict,dataclass
from collections import namedtuple
from shengao.project import Project,History
from studio_backend.model import LyricLine,Unit,Highlight


def project():
    unit=Unit('明日',100,500,'あした',highlights=[Highlight('あ',100,200,fixed_edges=['start']),Highlight('し',200,300),Highlight('た',300,500)])
    return Project(lines=[LyricLine('line','明日',100,500,[unit],reading_review={'notes':{'values':['original']}})])


def test_project_reader_detaches_all_nested_line_and_highlight_data():
    data=project().to_dict();before=copy.deepcopy(data);restored=Project.from_dict(data)
    restored.lines[0].reading_review['notes']['values'].append('new')
    restored.lines[0].units[0].highlights[0].fixed_edges.append('end')
    assert data==before


def test_history_nested_edit_is_recorded_and_restored_by_one_undo_and_redo():
    history=History(project());original=history.project.to_dict()
    assert history.apply('修改本句复核备注',lambda p:p.lines[0].reading_review['notes']['values'].append('new'))
    changed=history.project.to_dict();assert changed!=original and history.undo_stack[-1][1]==original
    assert history.undo() and history.project.to_dict()==original
    assert history.redo() and history.project.to_dict()==changed


def test_standalone_line_reader_detaches_nested_inputs_in_both_directions():
    data=project().lines[0].to_dict();line=LyricLine.from_dict(data);before=line.to_dict()
    data['reading_review']['notes']['values'].append('new')
    data['units'][0]['highlights'][0]['fixed_edges'].append('end')
    assert line.to_dict()==before
    line.units[0].highlights[1].fixed_edges.append('start')
    assert data['units'][0]['highlights'][1].get('fixed_edges',[])==[]


def legacy_line_dictionary(line):
    # Exact pre-optimization serialization, independent of current to_dict.
    value=asdict(line)
    if not line.timing_evidence:value.pop('timing_evidence')
    for item in [value,*value['units'],*(h for u in value['units'] for h in u['highlights'])]:
        if not item.get('timing_origin'):item.pop('timing_origin',None)
        if 'fixed_edges' in item and not item['fixed_edges']:item.pop('fixed_edges')
        if 'reading_options' in item and not item['reading_options']:item.pop('reading_options')
    return value


def test_lyric_serializer_matches_legacy_deep_dataclass_and_container_semantics():
    @dataclass
    class Note:
        values:list
    Pair=namedtuple('Pair','name values');line=project().lines[0]
    line.reading_review['extra']=[Note([{'numbers':[1,2.5,True,None]}]),Pair('pair',[Note(['nested'])]),({'tuple':[1]},)]
    expected=legacy_line_dictionary(line);actual=line.to_dict();assert actual==expected
    actual['reading_review']['extra'][0]['values'][0]['numbers'].append('new')
    actual['units'][0]['highlights'][0]['fixed_edges'].clear()
    assert line.to_dict()==expected


@pytest.mark.parametrize('change',[
    lambda line:line.update(display_start=101),
    lambda line:line['units'][0].update(end=501),
    lambda line:line['units'][0]['highlights'][0].update(kana='wrong'),
    lambda line:line['units'][0]['highlights'][0].update(fixed_edges=['start','start']),
    lambda line:line.update(timing_origin={'bad':'record'}),
])
def test_document_and_standalone_readers_both_validate_all_nested_constraints(change):
    data=project().to_dict();change(data['lines'][0])
    with pytest.raises(ValueError):Project.from_dict(data)
    with pytest.raises(ValueError):LyricLine.from_dict(data['lines'][0])
