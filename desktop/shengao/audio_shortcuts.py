"""Single-key audio profiles, Aegisub import and context-aware conflicts.

The application adopts a profile only after validation and an atomic preference save.
"""
from dataclasses import dataclass
from PySide6.QtCore import Qt,QKeyCombination
from PySide6.QtGui import QKeySequence
from shengao.aeg_hotkeys import AUDIO,ALWAYS

APPLICATION='Shengao Audio Shortcuts'
COMMANDS={
    'audio/commit':('confirm','提交时间'),
    'audio/commit/default':('confirm_default','按默认方式提交'),
    'audio/play/line':('line','试听整句'),
    'audio/play/selection':('selection','试听所选'),
    'audio/play/selection/after':('after','试听所选后500ms'),
    'audio/play/selection/before':('before','试听所选前500ms'),
    'audio/play/selection/begin':('begin','试听所选开头500ms'),
    'audio/play/selection/end':('end','试听所选结尾500ms'),
    'audio/play/to_end':('to_end','从所选开始播到末尾'),
    'audio/play/toggle':('toggle','试听所选／停止'),
    'audio/scroll/left':('scroll_left','时间轴向左滚动'),
    'audio/scroll/right':('scroll_right','时间轴向右滚动'),
    'audio/stop':('stop','停止试听'),
    'time/lead/in':('lead_in','整句增加引入'),
    'time/lead/out':('lead_out','整句增加引出'),
    'time/length/decrease':('length_minus','缩短所选'),
    'time/length/decrease/shift':('length_minus_shift','缩短并移动后续内部边界'),
    'time/length/increase':('length_plus','延长所选'),
    'time/length/increase/shift':('length_plus_shift','延长并移动后续内部边界'),
    'time/next':('next','下一词组／音节／句子'),
    'time/prev':('previous','上一词组／音节／句子'),
    'time/start/decrease':('start_minus','起点前移'),
    'time/start/increase':('start_plus','起点后移'),
    'app/toggle/global_hotkeys':('medusa_toggle','开关Medusa小键盘模式'),
}
CONTEXTS=('Audio','Always')
_MODIFIERS=(Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.AltModifier|
            Qt.KeyboardModifier.ShiftModifier|Qt.KeyboardModifier.KeypadModifier)
_MODIFIER_KEYS={Qt.Key.Key_Control,Qt.Key.Key_Shift,Qt.Key.Key_Alt,Qt.Key.Key_Meta,
                Qt.Key.Key_AltGr,Qt.Key.Key_unknown,0}


def _combination(key,modifiers):
    key=int(key)
    if key in _MODIFIER_KEYS or modifiers.value & ~_MODIFIERS.value:
        raise ValueError('请选择完整按键组合，不支持系统Win键或输入法组合键')
    if key==Qt.Key.Key_Enter:
        key=Qt.Key.Key_Return;modifiers|=Qt.KeyboardModifier.KeypadModifier
    if key==Qt.Key.Key_Backtab:
        key=Qt.Key.Key_Tab;modifiers|=Qt.KeyboardModifier.ShiftModifier
    value=QKeySequence(QKeyCombination(modifiers,Qt.Key(key))).toString(QKeySequence.SequenceFormat.PortableText)
    if not value:raise ValueError('不能识别此按键')
    return value


def normalise_key(text):
    if not isinstance(text,str) or not text.strip() or len(text)>80:
        raise ValueError('快捷键必须是有效的单组按键')
    sequence=QKeySequence.fromString(text.strip(),QKeySequence.SequenceFormat.PortableText)
    # Qt returns non-empty Key_unknown for invalid text; isEmpty alone is unsafe.
    if sequence.count()!=1 or sequence[0].key()==Qt.Key.Key_unknown:
        raise ValueError('只支持单组按键；多个备选请分别添加')
    value=sequence[0]
    return _combination(value.key(),value.keyboardModifiers())


def event_key(event):
    try:return _combination(event.key(),event.modifiers())
    except (ValueError,TypeError):return None


def aeg_key(text):
    if not isinstance(text,str) or not text or len(text)>80:raise ValueError('Aegisub按键无效')
    modifiers=[];remaining=text
    while True:
        found=next((value for value in ('Ctrl','Alt','Shift','Meta') if remaining.lower().startswith(value.lower()+'-')),None)
        if found is None:break
        if found in modifiers:raise ValueError('快捷键修饰键重复')
        modifiers.append(found);remaining=remaining[len(found)+1:]
    names={'Enter':'Return','Escape':'Esc','BackSpace':'Backspace','PageUp':'PgUp','PageDown':'PgDown',
           'KP_Add':'Num++','KP_Subtract':'Num+-','KP_Multiply':'Num+*','KP_Divide':'Num+/',
           'KP_Enter':'Num+Return','KP_Decimal':'Num+.'}
    if remaining.startswith('KP_') and len(remaining)==4 and remaining[-1] in '0123456789':
        remaining='Num+'+remaining[-1]
    else:remaining=names.get(remaining,remaining)
    return normalise_key('+'.join([*modifiers,remaining]))


@dataclass(frozen=True)
class Binding:
    context:str
    command:str
    keys:tuple[str,...]


@dataclass(frozen=True)
class Conflict:
    key:str
    commands:tuple[str,...]
    contexts:tuple[str,...]
    reserved:str=''


class Profile:
    def __init__(self,bindings,*,protect_text=True,medusa=False):
        if type(protect_text) is not bool or type(medusa) is not bool:raise ValueError('键位模式必须为开关值')
        rows=[];seen=set()
        for row in bindings:
            if row.context not in CONTEXTS or row.command not in COMMANDS:raise ValueError('包含不支持的上下文或命令')
            if (row.context,row.command) in seen:raise ValueError('同一命令只能出现一次')
            seen.add((row.context,row.command))
            if not isinstance(row.keys,(tuple,list)) or len(row.keys)>16:raise ValueError('每个命令最多16个备选键')
            keys=tuple(normalise_key(key) for key in row.keys)
            if len(set(keys))!=len(keys):raise ValueError('同一命令的备选键重复')
            rows.append(Binding(row.context,row.command,keys))
        self.bindings=tuple(rows);self.protect_text=protect_text;self.medusa=medusa
        self._index={context:{} for context in CONTEXTS}
        for row in self.bindings:
            for key in row.keys:self._index[row.context].setdefault(key,[]).append(row.command)

    @classmethod
    def defaults(cls,*,protect_text=True,medusa=False):
        command_ids={value[0]:key for key,value in COMMANDS.items()};rows=[]
        for context,original in (('Audio',AUDIO),('Always',ALWAYS)):
            by_command={}
            for key,action in original.items():by_command.setdefault(command_ids[action],[]).append(aeg_key(key))
            rows.extend(Binding(context,command,tuple(keys)) for command,keys in by_command.items())
        return cls(rows,protect_text=protect_text,medusa=medusa)

    def to_data(self):
        return {'application':APPLICATION,'version':1,'protect_text':self.protect_text,'medusa':self.medusa,
                'contexts':{context:{row.command:list(row.keys) for row in self.bindings if row.context==context} for context in CONTEXTS}}

    @classmethod
    def from_data(cls,data):
        if type(data) is not dict or data.get('application')!=APPLICATION or type(data.get('version')) is not int or data['version']!=1:
            raise ValueError('不是支持的声稿键位配置，或配置版本较新')
        if set(data)-{'application','version','protect_text','medusa','contexts'}:raise ValueError('配置包含未知字段')
        contexts=data.get('contexts')
        if type(contexts) is not dict or set(contexts)!=set(CONTEXTS):raise ValueError('缺少Audio／Always上下文')
        rows=[]
        for context,commands in contexts.items():
            if type(commands) is not dict:raise ValueError('上下文须为命令表')
            for command,keys in commands.items():
                if type(keys) is not list:raise ValueError('命令按键须为列表')
                rows.append(Binding(context,command,tuple(keys)))
        return cls(rows,protect_text=data.get('protect_text',True),medusa=data.get('medusa',False))

    def conflicts(self,reserved=None):
        uses={};result=[]
        for row in self.bindings:
            for key in row.keys:uses.setdefault(key,[]).append(row)
        reserved={normalise_key(key):label for key,label in (reserved or {}).items()}
        for key,rows in uses.items():
            commands=tuple(dict.fromkeys(row.command for row in rows));contexts=tuple(dict.fromkeys(row.context for row in rows))
            if len(commands)>1 or key in reserved:
                result.append(Conflict(key,commands,contexts,reserved.get(key,'')))
        return tuple(result)

    def require_ready(self,reserved=None):
        errors=self.conflicts(reserved)
        if errors:
            first=errors[0];names='、'.join(COMMANDS[c][1] for c in first.commands)
            raise ValueError(f'{first.key}存在冲突：{names}'+('／'+first.reserved if first.reserved else ''))

    def command(self,event,*,audio=False,medusa=None):
        key=event_key(event)
        if key is None:return None
        active=self.medusa if medusa is None else medusa
        for context in (('Always','Audio') if active and audio else ('Always',) if active else ('Audio',) if audio else ()):
            values=self._index[context].get(key,())
            if len(values)==1:return COMMANDS[values[0]][0]
            if values:return None
        return None


@dataclass(frozen=True)
class ImportPreview:
    profile:Profile
    ignored_contexts:tuple[str,...]
    unsupported:tuple[str,...]

    @property
    def needs_acknowledgement(self):return bool(self.ignored_contexts or self.unsupported)

    def to_draft(self,*,acknowledge_unsupported=False):
        if self.needs_acknowledgement and acknowledge_unsupported is not True:
            raise ValueError('先确认忽略列表中的未支持命令和其他窗口上下文')
        # Loading an editor draft never activates it. Activation must separately
        # call require_ready with the current application's reserved shortcuts.
        return Profile.from_data(self.profile.to_data())


def import_preview(data,current):
    if type(data) is not dict:raise ValueError('配置须为JSON对象')
    if data.get('application')==APPLICATION:return ImportPreview(Profile.from_data(data),(),())
    if not set(CONTEXTS)&set(data):raise ValueError('未找到支持的声稿配置或Aegisub音频上下文')
    merged=current.to_data();ignored=[];unsupported=[]
    for context,commands in data.items():
        if context not in CONTEXTS:ignored.append(str(context));continue
        if type(commands) is not dict:raise ValueError('Aegisub上下文须为命令表')
        for command,keys in commands.items():
            if command not in COMMANDS:unsupported.append(context+'/'+str(command));continue
            if type(keys) is not list or len(keys)>16:raise ValueError('Aegisub命令按键须为列表，最多16项')
            try:normalised=[aeg_key(key) for key in keys]
            except (ValueError,TypeError):unsupported.append(context+'/'+command+'（存在不支持的按键）');continue
            merged['contexts'][context][command]=normalised
    return ImportPreview(Profile.from_data(merged),tuple(ignored),tuple(unsupported))
