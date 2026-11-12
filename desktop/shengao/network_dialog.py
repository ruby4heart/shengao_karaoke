"""Asked before a background task goes online: which service, audio or text, and what stays here.

Every task the window starts passes through ``confirm``. Tasks that stay on
this computer return True at once. Online tasks show the explanation from
``network_notice`` unless the person already chose not to be asked again for
every kind of sending in the request; that choice is kept per kind (for
example ElevenLabs transcription, DeepSeek text) in the workspace settings
and is cleared from the API settings dialog.
"""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPlainTextEdit,QDialogButtonBox,QCheckBox
from . import network_notice

PREFERENCE='network_confirmed'


class NetworkDialog(QDialog):
    def __init__(self,parent,text):
        super().__init__(parent);self.setWindowTitle('联网前确认');self.resize(660,540)
        layout=QVBoxLayout(self)
        label=QLabel('请确认下面的内容可以发送。取消不会发送任何内容，也不会产生费用。');label.setWordWrap(True);layout.addWidget(label)
        view=QPlainTextEdit(text);view.setReadOnly(True);layout.addWidget(view)
        self.remember=QCheckBox('以后同类发送不再询问（可在“API 设置”中恢复询问）');layout.addWidget(self.remember)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('确认发送')
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消，不发送')
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setFocus()


def services(home):
    """Public service settings (no keys), or nothing when they cannot be read."""
    from studio_backend.settings import Settings
    try:return Settings(home).public()
    except (OSError,ValueError):return {}


def confirm(window,request,dialog=None):
    """True when the request may be sent. ``dialog`` replaces the window class in tests."""
    found=services(window.home)
    if not network_notice.describe(request,found):return True
    saved=window.preferences.data.get(PREFERENCE)
    waiting=network_notice.pending(request,saved,found)
    if not waiting:return True
    duration=getattr(getattr(window,'project',None),'duration',0)
    box=(dialog or NetworkDialog)(window,network_notice.text(request,window.home,found,duration))
    if box.exec()!=QDialog.DialogCode.Accepted:return False
    if box.remember.isChecked():window.preferences.set(PREFERENCE,sorted(network_notice.remembered(saved)|set(waiting)))
    return True


def remembered_count(preferences):
    return len(network_notice.remembered(preferences.data.get(PREFERENCE)))
