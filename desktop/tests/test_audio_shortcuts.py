from pathlib import Path
import json
import pytest
from PySide6.QtCore import Qt,QEvent
from PySide6.QtGui import QKeyEvent
from shengao.audio_shortcuts import Profile,normalise_key,import_preview


@pytest.mark.parametrize('key,mods,audio,medusa,expected',[
    (Qt.Key.Key_Return,Qt.KeyboardModifier.NoModifier,True,False,'confirm'),
    (Qt.Key.Key_Enter,Qt.KeyboardModifier.KeypadModifier,False,True,'confirm'),
    (Qt.Key.Key_Return,Qt.KeyboardModifier.KeypadModifier,False,True,'confirm'),
    (Qt.Key.Key_4,Qt.KeyboardModifier.NoModifier,False,True,None),
    (Qt.Key.Key_4,Qt.KeyboardModifier.KeypadModifier,False,True,'start_minus'),
    (Qt.Key.Key_G,Qt.KeyboardModifier.ShiftModifier,True,False,'confirm_default'),
    (Qt.Key.Key_R,Qt.KeyboardModifier.ControlModifier,True,False,None),
    (Qt.Key.Key_Asterisk,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.KeypadModifier,True,False,'medusa_toggle'),
    (Qt.Key.Key_Asterisk,Qt.KeyboardModifier.ControlModifier,True,False,None),
])
def test_default_contexts_and_physical_keypad_distinctions(key,mods,audio,medusa,expected):
    profile=Profile.defaults();profile.require_ready()
    assert profile.command(QKeyEvent(QEvent.Type.KeyPress,key,mods),audio=audio,medusa=medusa)==expected


def test_custom_key_replaces_default_and_owns_imported_and_exported_data():
    original=Profile.defaults();data=original.to_data();data['contexts']['Audio']['audio/play/line']=['F9']
    custom=Profile.from_data(data)
    data['contexts']['Audio']['audio/play/line'].append('F10')
    export=custom.to_data();export['contexts']['Audio']['audio/play/line'].append('F11')
    def command(key,profile=custom):return profile.command(QKeyEvent(QEvent.Type.KeyPress,key,Qt.KeyboardModifier.NoModifier),audio=True)
    assert command(Qt.Key.Key_F9)=='line' and command(Qt.Key.Key_R) is None
    assert command(Qt.Key.Key_F10) is None and command(Qt.Key.Key_F11) is None
    assert command(Qt.Key.Key_R,original)=='line'


def test_overlapping_audio_medusa_contexts_and_window_actions_conflict():
    data=Profile.defaults().to_data();data['contexts']['Always']['audio/play/selection']=['R']
    profile=Profile.from_data(data)
    assert profile.conflicts()[0].key=='R'
    with pytest.raises(ValueError,match='冲突'):profile.require_ready()
    data=Profile.defaults().to_data();data['contexts']['Audio']['audio/play/line']=['Ctrl+Return']
    profile=Profile.from_data(data)
    assert profile.conflicts({'Ctrl+Return':'确认本句时间'})[0].reserved=='确认本句时间'


@pytest.mark.parametrize('invalid',['junk','Ctrl+not-a-key','Ctrl+K, Ctrl+C','Meta+R'])
def test_invalid_qt_unknown_and_multi_chord_bindings_are_rejected(invalid):
    with pytest.raises(ValueError):normalise_key(invalid)


@pytest.mark.parametrize('version',[True,2,'1'])
def test_wrong_configuration_version_is_rejected(version):
    data=Profile.defaults().to_data();data['version']=version
    with pytest.raises(ValueError):Profile.from_data(data)


def test_original_aegisub_import_reports_unhandled_contexts_before_loading():
    source=Path(__file__).resolve().parents[1]/'assets/compatibility/aeg-3.5.0-default-hotkeys.json'
    data=json.loads(source.read_text(encoding='utf-8'));original=Profile.defaults()
    preview=import_preview(data,original)
    assert preview.profile.to_data()==original.to_data()
    assert preview.needs_acknowledgement and preview.ignored_contexts
    with pytest.raises(ValueError):preview.to_draft()
    assert preview.to_draft(acknowledge_unsupported=True).to_data()==original.to_data()


def test_unknown_aegisub_command_does_not_execute_an_unrelated_action():
    original=Profile.defaults();preview=import_preview({'Audio':{'unknown/remove':['R']}},original)
    assert preview.unsupported==('Audio/unknown/remove',)
    event=QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_R,Qt.KeyboardModifier.NoModifier)
    assert preview.profile.command(event,audio=True)=='line'
