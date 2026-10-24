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
