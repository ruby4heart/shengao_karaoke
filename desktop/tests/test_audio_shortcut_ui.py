import json
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QEvent
from PySide6.QtGui import QKeyEvent,QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog,QApplication,QLineEdit
from shengao.app import StudioWindow
from shengao.project import History
from shengao.preferences import Preferences
from shengao.audio_shortcuts import Profile
from shengao.audio_shortcut_dialog import AudioShortcutDialog,KeyCapture,ImportReview


@pytest.fixture
def workbench(qapp,tmp_path,project):
    w=StudioWindow(tmp_path/'home',test=True);w.history=History(project);w.current=0;w.show();w.refresh();w.set_stage(2);qapp.processEvents()
    yield w
    w.close();qapp.processEvents()


def spy_actions(window,monkeypatch):
    actions=[];window.timeline.action.disconnect(window.audio_action)
    monkeypatch.setattr(window,'audio_action',actions.append);window.timeline.action.connect(actions.append)
    return actions


def custom_profile(window,*,medusa=False,protect_text=True):
    data=window.audio_profile.to_data();data['contexts']['Audio']['audio/play/line']=['F9']
    data.update(medusa=medusa,protect_text=protect_text);return Profile.from_data(data)


def test_custom_binding_dispatches_and_is_preserved_after_restart(workbench,qapp,monkeypatch):
    w=workbench;before=w.project.to_dict();w.adopt_audio_profile(custom_profile(w));actions=spy_actions(w,monkeypatch)
    w.timeline.setFocus();QTest.keyClick(w.timeline,Qt.Key.Key_F9);QTest.keyClick(w.timeline,Qt.Key.Key_R)
    assert actions==['line'] and w.project.to_dict()==before
    other=StudioWindow(w.home,test=True)
    assert other.audio_profile.to_data()==w.audio_profile.to_data()
    assert Preferences(w.home).data['audio_profile']==w.audio_profile.to_data()
    other.close();qapp.processEvents()


def test_failed_profile_save_does_not_replace_runtime_profile(workbench,monkeypatch):
    w=workbench;old=w.audio_profile;old_data=dict(w.preferences.data)
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr(w.preferences,'set_many',fail)
    with pytest.raises(OSError):w.adopt_audio_profile(custom_profile(w,medusa=True))
    assert w.audio_profile is old and not w.timeline.medusa_hotkeys and w.preferences.data==old_data


def test_global_window_shortcut_cannot_be_overridden(workbench):
    w=workbench;data=w.audio_profile.to_data();data['contexts']['Audio']['audio/play/line']=['Ctrl+S']
    with pytest.raises(ValueError,match='保存作品'):w.adopt_audio_profile(Profile.from_data(data))


@pytest.mark.parametrize('target',['translation','time','table','editable_combo'])
def test_medusa_input_protection_preserves_editing(workbench,qapp,monkeypatch,target):
    w=workbench;w.adopt_audio_profile(custom_profile(w,medusa=True));actions=spy_actions(w,monkeypatch)
    w.calibration_tabs.setCurrentIndex(1)
    if target=='translation':editor=w.translation
    elif target=='time':editor=w.begin.lineEdit()
    elif target=='table':
        w.units.editItem(w.units.item(0,1));qapp.processEvents();editor=w.units.findChild(QLineEdit)
    else:
        from PySide6.QtWidgets import QComboBox
        combo=QComboBox(w);combo.setEditable(True);combo.addItem('');combo.show();editor=combo.lineEdit()
    assert editor is not None
    editor.setFocus();editor.selectAll();QTest.keyClick(editor,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier)
    assert not actions


def test_explicit_original_always_mode_and_ime_guard(workbench,qapp,monkeypatch):
    w=workbench;w.adopt_audio_profile(custom_profile(w,medusa=True,protect_text=False));actions=spy_actions(w,monkeypatch)
    editor=w.translation;editor.setFocus();qapp.processEvents()
    QTest.keyClick(editor,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier);assert actions==['selection'];actions.clear()
    QApplication.sendEvent(editor,QInputMethodEvent('かな',[]))
    QTest.keyClick(editor,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier);assert not actions
    commit=QInputMethodEvent();commit.setCommitString('かな');QApplication.sendEvent(editor,commit)
    QApplication.sendEvent(editor,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Enter,Qt.KeyboardModifier.KeypadModifier))
    assert not actions
    QApplication.sendEvent(editor,QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_Enter,Qt.KeyboardModifier.KeypadModifier))
    QTest.keyClick(editor,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier);assert actions==['selection']


def test_legacy_medusa_preference_keeps_original_behavior(qapp,tmp_path):
    prefs=Preferences(tmp_path);prefs.set('medusa_hotkeys',True)
    w=StudioWindow(tmp_path,test=True)
    assert w.audio_profile.medusa and not w.audio_profile.protect_text and w.timeline.medusa_hotkeys
    w.close();qapp.processEvents()


def test_modal_dialog_does_not_dispatch_main_window_audio(workbench,qapp,monkeypatch):
    w=workbench;w.adopt_audio_profile(custom_profile(w,medusa=True,protect_text=False));actions=spy_actions(w,monkeypatch)
    dialog=QDialog(w);dialog.setModal(True);editor=QLineEdit(dialog);dialog.show();editor.setFocus();qapp.processEvents()
    QTest.keyClick(editor,Qt.Key.Key_5,Qt.KeyboardModifier.KeypadModifier)
    assert QApplication.activeModalWidget() is dialog and not actions
    assert w.audio_key_command(QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_F9,Qt.KeyboardModifier.NoModifier),audio=True) is None
    dialog.close();qapp.processEvents()


def test_capture_distinguishes_keypad_enter_and_never_accepts_the_dialog(qapp):
    dialog=QDialog();capture=KeyCapture(dialog);dialog.show();capture.show();capture.setFocus();qapp.processEvents()
    QTest.keyClick(capture,Qt.Key.Key_Return);assert capture.value=='Return'
    QTest.keyClick(capture,Qt.Key.Key_Enter,Qt.KeyboardModifier.KeypadModifier);assert capture.value=='Num+Return'
    assert dialog.isVisible() and dialog.result()!=QDialog.DialogCode.Accepted
    QTest.keyClick(capture,Qt.Key.Key_Escape);assert capture.value is None
    dialog.close();qapp.processEvents()


def test_dialog_changes_are_drafts_and_conflicts_disable_apply(workbench,qapp):
    w=workbench;old=w.audio_profile.to_data();dialog=AudioShortcutDialog(w.audio_profile,w.reserved_audio_shortcuts(),w.adopt_audio_profile,w)
    dialog.set_binding('Audio','audio/play/line',['F9']);assert w.audio_profile.to_data()==old
    dialog.set_binding('Audio','audio/play/selection',['F9']);assert not dialog.save_button.isEnabled()
    dialog.reject();assert w.audio_profile.to_data()==old
    dialog=AudioShortcutDialog(w.audio_profile,w.reserved_audio_shortcuts(),w.adopt_audio_profile,w)
    dialog.set_binding('Audio','audio/play/line',['F9']);dialog.apply()
    assert dialog.accepted_profile and w.audio_profile.to_data()['contexts']['Audio']['audio/play/line']==['F9']
    dialog.close();qapp.processEvents()


def test_import_review_cancel_bad_json_and_export_scope(workbench,tmp_path,monkeypatch):
    w=workbench;dialog=AudioShortcutDialog(w.audio_profile,w.reserved_audio_shortcuts(),w.adopt_audio_profile,w)
    original=dialog.candidate().to_data()
    aeg=Path(__file__).resolve().parents[1]/'assets/compatibility/aeg-3.5.0-default-hotkeys.json'
    monkeypatch.setattr(dialog,'review_import',lambda preview:False)
    assert not dialog.import_file(aeg) and dialog.candidate().to_data()==original
    bad=tmp_path/'invalid.json';bad.write_text('{invalid',encoding='utf-8')
    with pytest.raises(ValueError):dialog.import_file(bad)
    assert dialog.candidate().to_data()==original
    path=tmp_path/'keys.json';dialog.export_file(path);data=json.loads(path.read_text(encoding='utf-8'))
    assert set(data)=={'application','version','medusa','protect_text','contexts'} and data==original
    assert w.audio_profile.to_data()==original
    dialog.close()


@pytest.mark.parametrize('size',[(820,720),(560,480)])
def test_settings_footer_stays_reachable_in_small_windows(workbench,qapp,size):
    w=workbench;dialog=AudioShortcutDialog(w.audio_profile,w.reserved_audio_shortcuts(),w.adopt_audio_profile,w)
    dialog.resize(*size);dialog.show();qapp.processEvents()
    from PySide6.QtCore import QPoint
    corner=dialog.save_button.mapTo(dialog,QPoint(0,0))
    assert dialog.save_button.isVisible() and dialog.rect().contains(corner)
    assert dialog.rect().contains(corner+dialog.save_button.rect().bottomRight())
    dialog.scroll.verticalScrollBar().setValue(dialog.scroll.verticalScrollBar().maximum());qapp.processEvents()
    assert dialog.save_button.isVisible() and dialog.table.minimumHeight()>=180
    dialog.reject();qapp.processEvents()


def test_import_loads_only_a_draft_and_failed_save_keeps_dialog_open(workbench,tmp_path,monkeypatch,qapp):
    w=workbench;old=w.audio_profile.to_data();dialog=AudioShortcutDialog(w.audio_profile,w.reserved_audio_shortcuts(),w.adopt_audio_profile,w)
    path=tmp_path/'custom.json';path.write_text(json.dumps(custom_profile(w).to_data()),encoding='utf-8')
    monkeypatch.setattr(dialog,'review_import',lambda preview:True)
    assert dialog.import_file(path) and dialog.candidate().to_data()!=old and w.audio_profile.to_data()==old
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr(w.preferences,'set_many',fail);dialog.show();qapp.processEvents();dialog.apply()
    assert dialog.isVisible() and dialog.accepted_profile is None and w.audio_profile.to_data()==old
    assert '原配置保留' in dialog.status.text()
    dialog.reject();qapp.processEvents()


def test_original_aeg_import_requires_explicit_review(qapp):
    from shengao.audio_shortcuts import import_preview
    from PySide6.QtWidgets import QDialogButtonBox
    path=Path(__file__).resolve().parents[1]/'assets/compatibility/aeg-3.5.0-default-hotkeys.json'
    preview=import_preview(json.loads(path.read_text(encoding='utf-8')),Profile.defaults())
    assert preview.needs_acknowledgement
    dialog=ImportReview(preview);controls=dialog.findChild(QDialogButtonBox)
    assert not controls.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.acknowledge.setChecked(True)
    assert controls.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.close();qapp.processEvents()
