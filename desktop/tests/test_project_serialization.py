import copy,sys,types
from dataclasses import dataclass
from shengao.paths import ASSETS
from test_line_layout_project import sample


def test_current_serializer_matches_actual_released_serializer_for_all_prior_fields():
    p=sample();p.layout_styles={};p.tasks=[{'status':'pending','nested':{'rows':[1,2,3]}}];current=p.to_dict()
    module=types.ModuleType('shengao._serialization_v029');module.__package__='shengao';sys.modules[module.__name__]=module
    try:
        raw=(ASSETS/'compatibility/project-v029.py.txt').read_bytes();exec(compile(raw,'actual-v029-project.py','exec'),module.__dict__)
        prior=copy.deepcopy(current);prior['version']=13;prior.pop('layout_styles')
        expected=module.Project.from_dict(prior).to_dict();expected['version']=14;expected['layout_styles']={}
        assert current==expected
    finally:sys.modules.pop(module.__name__,None)


def test_serialization_stays_a_deep_snapshot_including_nested_dataclasses():
    @dataclass
    class Note:
        values:list
    p=sample();p.tasks=[{'annotation':Note(['original'])}];before=copy.deepcopy(p)
    data=p.to_dict();data['lines'][0]['units'][0]['highlights'][0]['kana']='changed';data['tasks'][0]['annotation']['values'].append('changed');data['layout_styles']['layout']['breaks'].clear()
    assert p==before and p.tasks[0]['annotation'].values==['original'] and p.layout_styles['layout']['breaks']==[3]
