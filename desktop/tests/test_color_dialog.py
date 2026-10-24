"""The real dialog edits a proposal and keeps bottom actions reachable."""
import copy
from PySide6.QtWidgets import QDialogButtonBox
from shengao.color_dialog import ColorDialog
from shengao.color_states import default_profile,update_settings,effective_profile
from shengao.project import Project
from studio_backend.model import LyricLine


def project():return Project(lines=[LyricLine('a','歌う',1000,3000),LyricLine('b','歌う',4000,6000)])


def test_dialog_cancel_never_changes_project_and_emits_independent_preview(qapp):
    p=project();before=p.to_dict();d=ColorDialog(p,0,['a','b']);previews=[];d.candidateChanged.connect(previews.append)
    d.scope.setCurrentIndex(d.scope.findData('current'));d.state.setCurrentIndex(d.state.findData('sung'))
    d.fields['outline'].hex.setText('#ff0000');d.fields['shadow'].opacity.setValue(25);d.box_enabled.setChecked(True)
    assert effective_profile(d.candidate,'a')['layers']['lyrics']['sung']['outline']['color']=='#ff0000'
    assert effective_profile(d.candidate,'b') is None and p.to_dict()==before
    previews[-1]['lines']['a']['layers']['lyrics']['sung']['outline']['color']='#000000'
    assert effective_profile(d.candidate,'a')['layers']['lyrics']['sung']['outline']['color']=='#ff0000'
    d.reject();assert d.result_settings is None and p.to_dict()==before;d.deleteLater()


def test_dialog_accepts_full_selected_scope_and_restores_inheritance(qapp):
    p=project();palette=default_profile(p.style);p.color_styles=update_settings({},palette)
    altered=copy.deepcopy(palette);altered['layers']['ruby']['waiting']['primary']['color']='#123456'
    p.color_styles=update_settings(p.color_styles,altered,['a']);before=p.to_dict();d=ColorDialog(p,0,['a','b'])
    d.scope.setCurrentIndex(d.scope.findData('selected'));assert '不同' in d.scope_hint.text()
    d.role.setCurrentIndex(d.role.findData('ruby'));d.fields['primary'].hex.setText('#abcdef');d.accept_changes()
    assert set(d.result_settings['lines'])=={'a','b'} and all(effective_profile(d.result_settings,uid)['layers']['ruby']['waiting']['primary']['color']=='#abcdef' for uid in ['a','b'])
    assert p.to_dict()==before;d.deleteLater()
    d=ColorDialog(p,0);d.scope.setCurrentIndex(d.scope.findData('current'));d.restore.click();d.accept_changes()
    assert d.result_settings=={'global':palette,'lines':{}} and p.to_dict()==before;d.deleteLater()


def test_invalid_hex_disables_adoption_until_correct_and_scope_reset_is_explicit(qapp):
    d=ColorDialog(project(),0);d.fields['primary'].hex.setText('#xx')
    assert not d.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    d.fields['primary'].hex.setText('#112233');assert d.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    d.scope.setCurrentIndex(d.scope.findData('current'));assert d.candidate=={}
    d.accept_changes();assert d.result_settings=={};d.deleteLater()


def test_small_dialog_footer_stays_visible(qapp):
    d=ColorDialog(project(),0);d.resize(720,560);d.show();qapp.processEvents()
    for button in [d.restore,d.reset,d.buttons.button(QDialogButtonBox.StandardButton.Ok),d.buttons.button(QDialogButtonBox.StandardButton.Cancel)]:
        assert button.isVisible() and d.rect().contains(button.mapTo(d,button.rect().center()))
    d.reject();d.deleteLater()


def test_state_selection_and_preview_buttons_stay_in_sync(qapp):
    from PySide6.QtWidgets import QPushButton
    d=ColorDialog(project(),0);requests=[];d.previewRequested.connect(requests.append)
    d.state.setCurrentIndex(d.state.findData('singing'));assert requests[-1]=='middle' and d.phase_buttons['middle'].isChecked()
    next(v for v in d.findChildren(QPushButton) if v.text()=='看待唱').click()
    assert d.state.currentData()=='waiting' and requests[-1]=='waiting' and d.candidate=={}
    d.reject();d.deleteLater()
