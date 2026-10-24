"""State boundaries, inheritance and colour alpha must survive actual edits."""
import copy
from types import SimpleNamespace
import pytest
from shengao.color_states import (default_profile,validate_profile,validate_settings,
    update_settings,effective_profile,segments,phase_at,ass_ink)


def profile():return default_profile(SimpleNamespace(color='#ffffff',highlight='#00ff00',outline_color='#101020'))


def test_state_windows_cover_exactly_singing_and_visual_hold():
    assert segments(1000,8000,3000,5000)==[(1000,3000,'waiting'),(3000,5000,'singing'),(5000,8000,'sung')]
    assert [phase_at(t,3000,5000) for t in [2999,3000,4999,5000]]==['waiting','singing','singing','sung']
    assert segments(3000,5000,3000,5000)==[(3000,5000,'singing')]
    assert segments(3500,4500,3000,5000)==[(3500,4500,'singing')]


def test_local_overrides_restore_inheritance_and_are_not_shared():
    original=profile();settings=update_settings({},original)
    red=copy.deepcopy(original);red['layers']['lyrics']['sung']['outline']['color']='#ff0000'
    local=update_settings(settings,red,['chorus2']);validate_settings(local,{'chorus1','chorus2'})
    global_new=copy.deepcopy(original);global_new['layers']['lyrics']['sung']['outline']['color']='#0000ff'
    changed=update_settings(local,global_new)
    assert effective_profile(changed,'chorus2')['layers']['lyrics']['sung']['outline']['color']=='#ff0000'
    assert effective_profile(changed,'chorus1')['layers']['lyrics']['sung']['outline']['color']=='#0000ff'
    restored=update_settings(changed,None,['chorus2'])
    assert effective_profile(restored,'chorus2')==global_new
    effective_profile(restored,'chorus1')['layers']['lyrics']['sung']['outline']['color']='#123456'
    assert effective_profile(restored,'chorus1')==global_new
    assert settings=={'global':original,'lines':{}}
    assert update_settings(settings,None)=={}


@pytest.mark.parametrize('opacity,alpha',[(0,'FF'),(50,'80'),(100,'00')])
def test_ass_bgr_and_inverse_alpha(opacity,alpha):
    assert ass_ink({'color':'#123456','opacity':opacity},3)==f'\\3c&H563412&\\3a&H{alpha}&'


@pytest.mark.parametrize('field,value',[('color','red'),('color','#ffffff}\\pos(0,0)'),('opacity',True),('opacity',-1),('opacity',101)])
def test_untrusted_or_invalid_colour_is_rejected(field,value):
    p=profile();p['layers']['ruby']['waiting']['primary'][field]=value
    with pytest.raises(ValueError):validate_profile(p)


def test_unknown_structure_and_orphan_line_fail_before_use():
    p=profile();p['unexpected']=True
    with pytest.raises(ValueError):validate_profile(p)
    with pytest.raises(ValueError):validate_settings({'global':profile(),'lines':{'removed':profile()}},{'current'})
    with pytest.raises(ValueError):update_settings({},profile(),['same','same'])


def test_project_save_and_one_undo_preserve_axis_and_locked_readings(tmp_path):
    from shengao.project import Project,History,save_project,load_project
    from studio_backend.model import LyricLine,Unit
    line=LyricLine('lyric','歌う',1000,2000,[Unit('歌う',1000,2000,kana='うたう',source='manual',locked=True)],kana='うたう',locked=True,reviewed=True)
    p=Project(lines=[line],checks={'lyric':{'reading':True}});before=p.to_dict();history=History(p)
    palette=profile();palette['box']['enabled']=True
    history.apply('修改指定歌词颜色',lambda current:setattr(current,'color_styles',update_settings(current.color_styles,palette,['lyric'])))
    assert history.project.lines[0].to_dict()==before['lines'][0] and history.project.checks==before['checks']
    path=tmp_path/'颜色 工程.sgproj';save_project(history.project,path);again=load_project(path)
    assert again.to_dict()==history.project.to_dict() and again.to_dict()['version']==10
    assert history.undo() and history.project.to_dict()==before
    assert history.redo() and history.project.to_dict()==again.to_dict()
    frozen=history.project.to_dict()
    with pytest.raises(ValueError,match='没有对应歌词'):
        history.apply('迟到的指定行',lambda current:setattr(current,'color_styles',update_settings(current.color_styles,palette,['removed'])))
    assert history.project.to_dict()==frozen


def test_lyric_removal_prunes_only_removed_override_and_undo_restores():
    from shengao.project import Project,History
    from studio_backend.model import LyricLine
    p=Project(lines=[LyricLine('a','今日',0,1000),LyricLine('b','明日',1000,2000)])
    p.color_styles=update_settings({},profile(),['a','b']);before=p.to_dict();history=History(p)
    history.apply('删除一句',lambda current:current.lines.pop(0))
    assert set(history.project.color_styles['lines'])=={'b'}
    assert history.undo() and history.project.to_dict()==before


def test_legacy_project_has_no_automatic_color_rewrite():
    from shengao.project import Project
    raw=Project().to_dict();raw['version']=9;raw.pop('color_styles')
    p=Project.from_dict(raw)
    assert p.color_styles=={} and effective_profile(p.color_styles,'any') is None
    raw['color_styles']=update_settings({},profile())
    with pytest.raises(ValueError,match='第 10 版'):Project.from_dict(raw)
    raw['version']=11
    with pytest.raises(ValueError,match='版本较新'):Project.from_dict(raw)
