import json
import pytest
from shengao.preferences import Preferences


def test_related_settings_commit_together_and_preserve_other_preferences(tmp_path):
    prefs=Preferences(tmp_path);prefs.set('recent',[{'path':'song.sgproj','title':'作品'}])
    values={'audio_profile':{'keys':['R','Space']},'medusa_hotkeys':True}
    prefs.set_many(values)
    values['audio_profile']['keys'].append('F9')
    loaded=Preferences(tmp_path)
    assert loaded.data['audio_profile']['keys']==['R','Space']
    assert loaded.data['medusa_hotkeys'] is True and loaded.data['recent'][0]['title']=='作品'
    assert prefs.data==loaded.data


def test_failed_write_preserves_previous_live_and_persisted_configuration(tmp_path,monkeypatch):
    import shengao.preferences as module
    prefs=Preferences(tmp_path);prefs.set_many({'audio_profile':{'keys':['R']},'medusa_hotkeys':False})
    previous=prefs.path.read_bytes();live=prefs.data
    def fail(*args,**kwargs):raise OSError('disk full')
    monkeypatch.setattr(module,'atomic_json',fail)
    with pytest.raises(OSError,match='disk full'):
        prefs.set_many({'audio_profile':{'keys':['F9']},'medusa_hotkeys':True})
    assert prefs.data is live and prefs.path.read_bytes()==previous
    assert prefs.data['audio_profile']['keys']==['R'] and prefs.data['medusa_hotkeys'] is False


def test_invalid_json_value_does_not_replace_the_old_file_or_state(tmp_path):
    prefs=Preferences(tmp_path);prefs.set_many({'medusa_hotkeys':False})
    before=prefs.path.read_bytes()
    with pytest.raises(ValueError):prefs.set_many({'not_json':float('nan'),'medusa_hotkeys':True})
    assert prefs.path.read_bytes()==before and prefs.data=={'medusa_hotkeys':False}
    assert json.loads(before)['medusa_hotkeys'] is False


@pytest.mark.parametrize('changes',[[],{'audio_profile':{},1:'invalid key'}])
def test_invalid_update_is_not_silently_adopted(tmp_path,changes):
    prefs=Preferences(tmp_path)
    with pytest.raises(ValueError):prefs.set_many(changes)
    assert prefs.data=={} and not prefs.path.exists()
