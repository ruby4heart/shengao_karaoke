"""Windows Aegisub 3.5.0 Audio/Always contexts, with exact modifiers.

Bindings come from src/libresrc/default_hotkey.json. The Always context is
enabled by the Medusa option, exactly as in Aegisub's hotkey::check.
"""
from PySide6.QtCore import Qt

AUDIO={
    'Enter':'confirm','G':'confirm','Shift-G':'confirm_default',
    'R':'line','S':'selection','Space':'selection','W':'after','Q':'before',
    'E':'begin','D':'end','T':'to_end','B':'toggle','A':'scroll_left',
    'F':'scroll_right','H':'stop','C':'lead_in','V':'lead_out',
    'KP_Subtract':'length_minus','Shift-KP_Subtract':'length_minus_shift',
    'KP_Add':'length_plus','Shift-KP_Add':'length_plus_shift',
    'Right':'next','X':'next','Left':'previous','Z':'previous',
    'Ctrl-KP_Multiply':'medusa_toggle',
}
ALWAYS={
    'KP_Enter':'confirm','KP_5':'selection','KP_3':'after','KP_1':'before',
    'KP_8':'stop','KP_7':'length_minus','KP_9':'length_plus',
    'KP_2':'next','KP_0':'previous','KP_4':'start_minus','KP_6':'start_plus',
}

def key_name(event):
    key=event.key();mods=event.modifiers();keypad=bool(mods&Qt.KeyboardModifier.KeypadModifier)
    if key==Qt.Key.Key_Enter:name='KP_Enter'
    elif key==Qt.Key.Key_Return:name='KP_Enter' if keypad else 'Enter'
    elif keypad:
        name={Qt.Key.Key_Plus:'KP_Add',Qt.Key.Key_Minus:'KP_Subtract',Qt.Key.Key_Asterisk:'KP_Multiply'}.get(key)
        if name is None and Qt.Key.Key_0<=key<=Qt.Key.Key_9:name='KP_'+chr(key)
    else:
        name={Qt.Key.Key_Space:'Space',Qt.Key.Key_Right:'Right',Qt.Key.Key_Left:'Left'}.get(key)
        if name is None and Qt.Key.Key_A<=key<=Qt.Key.Key_Z:name=chr(key)
    if not name:return ''
    if mods&Qt.KeyboardModifier.MetaModifier:return ''
    prefix=''.join(text for flag,text in [(Qt.KeyboardModifier.ControlModifier,'Ctrl-'),(Qt.KeyboardModifier.AltModifier,'Alt-'),(Qt.KeyboardModifier.ShiftModifier,'Shift-')] if mods&flag)
    return prefix+name

def command(event,audio=False,medusa=False):
    name=key_name(event)
    if medusa and name in ALWAYS:return ALWAYS[name]
    return AUDIO.get(name) if audio else None
