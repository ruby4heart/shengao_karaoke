"""Validated runtime profiles and main-window text/IME focus protection."""
from PySide6.QtCore import Qt,QEvent
from PySide6.QtGui import QAction,QKeySequence
from PySide6.QtWidgets import (QApplication,QWidget,QLineEdit,QTextEdit,QPlainTextEdit,
    QAbstractSpinBox,QComboBox)
from .audio_shortcuts import Profile,normalise_key


def text_input(widget):
    while widget is not None:
        if isinstance(widget,(QLineEdit,QTextEdit,QPlainTextEdit,QAbstractSpinBox)):return True
        if isinstance(widget,QComboBox) and widget.isEditable():return True
        widget=widget.parentWidget()
    return False


class AudioShortcutWorkflow:
    def reserved_audio_shortcuts(self):
        labels={'Ctrl+S':'保存作品','F2':'保存作品','Ctrl+Shift+S':'另存作品','Ctrl+O':'打开作品','Ctrl+N':'新建作品',
                'Ctrl+Z':'撤销','Ctrl+Y':'重做','Ctrl+Return':'确认本句时间','Esc':'取消当前操作','Ctrl+P':'播放／暂停',
                'F6':'试听本句','Ctrl+1':'定位句首','Ctrl+2':'定位句尾','Ctrl+J':'下一待确认','Ctrl+Shift+P':'显示／隐藏字幕'}
        result={}
        for action in self.findChildren(QAction):
            for sequence in action.shortcuts():
                value=sequence.toString(QKeySequence.SequenceFormat.PortableText)
                if not value:continue
                try:key=normalise_key(value)
                except ValueError:continue
                result[key]=labels.get(key,action.text().replace('&','') or '作品操作')
        return result

    def init_audio_shortcuts(self):
        saved=self.preferences.data;self._shortcut_composing=None;self._shortcut_ime_finishing=False;self.audio_profile_warning=''
        legacy=saved.get('medusa_hotkeys',False) is True
        try:
            profile=Profile.from_data(saved['audio_profile']) if 'audio_profile' in saved else Profile.defaults(medusa=legacy,protect_text=not legacy)
            profile.require_ready(self.reserved_audio_shortcuts())
        except (ValueError,TypeError,KeyError) as error:
            profile=Profile.defaults();self.audio_profile_warning='键位配置未启用，已使用原版默认；原文件保留。'+str(error)
        self.audio_profile=profile;self.timeline.audio_key_handler=self.audio_key_command;self.timeline.medusa_hotkeys=profile.medusa

    def adopt_audio_profile(self,profile):
        if self.closing:raise ValueError('窗口正在关闭，未修改配置')
        candidate=Profile.from_data(profile.to_data());candidate.require_ready(self.reserved_audio_shortcuts())
        self.preferences.set_many({'audio_profile':candidate.to_data(),'medusa_hotkeys':candidate.medusa})
        self.audio_profile=candidate;self.timeline.medusa_hotkeys=candidate.medusa
        self.refresh_audio_shortcut_help()

    def set_medusa_mode(self,value):
        data=self.audio_profile.to_data();data['medusa']=bool(value)
        try:self.adopt_audio_profile(Profile.from_data(data))
        except (OSError,ValueError) as error:self.message('快捷键模式未更改：'+str(error));return False
        self.message('Medusa小键盘模式：'+('开启' if value else '关闭'));return True

    def audio_key_command(self,event,*,audio=False):
        profile=getattr(self,'audio_profile',None)
        if profile is None or QApplication.activeModalWidget() is not None or self._shortcut_composing is not None or self._shortcut_ime_finishing:return None
        return profile.command(event,audio=audio,medusa=self.timeline.medusa_hotkeys)

    def observe_audio_input(self,obj,event):
        if not isinstance(obj,QWidget) or obj.window() is not self:return
        if event.type()==QEvent.Type.InputMethod:
            previous=getattr(self,'_shortcut_composing',None)
            self._shortcut_composing=obj if event.preeditString() else None
            self._shortcut_ime_finishing=not event.preeditString() and (previous is obj or bool(event.commitString()))
        elif event.type()==QEvent.Type.KeyRelease:self._shortcut_ime_finishing=False
        elif event.type()==QEvent.Type.FocusOut or event.type()==QEvent.Type.FocusIn and obj is not getattr(self,'_shortcut_composing',None):
            self._shortcut_composing=None;self._shortcut_ime_finishing=False

    def filter_audio_shortcut(self,obj,event):
        if event.type() not in (QEvent.Type.KeyPress,QEvent.Type.ShortcutOverride):return False
        if not isinstance(obj,QWidget) or obj.window() is not self or not self.timeline.medusa_hotkeys:return False
        profile=getattr(self,'audio_profile',None)
        if profile is None or profile.protect_text and (text_input(obj) or text_input(QApplication.focusWidget())):return False
        name=self.audio_key_command(event)
        if not name:return False
        event.accept()
        if event.type()==QEvent.Type.KeyPress:self.audio_action(name)
        return True

    def refresh_audio_shortcut_help(self):
        from PySide6.QtWidgets import QPushButton
        from .audio_shortcut_dialog import display_key
        bindings={}
        for row in self.audio_profile.bindings:
            if row.context=='Audio':bindings.setdefault(row.command,[]).extend(row.keys)
        commands={'试听本句':('audio/play/line','；主窗口固定F6'),'试听所选':('audio/play/selection',''),'停止':('audio/stop','')}
        for button in self.findChildren(QPushButton):
            if button.text() in commands:
                command,extra=commands[button.text()];keys=bindings.get(command,[])
                button.setToolTip(button.text()+'；时间轴焦点：'+(' / '.join(map(display_key,keys)) or '未设置')+extra)

    def show_audio_shortcut_settings(self):
        from .audio_shortcut_dialog import AudioShortcutDialog
        dialog=AudioShortcutDialog(self.audio_profile,self.reserved_audio_shortcuts(),self.adopt_audio_profile,self)
        if dialog.exec()==dialog.DialogCode.Accepted:self.message('打轴键位已保存并启用；歌词、时间和确认保持。')
