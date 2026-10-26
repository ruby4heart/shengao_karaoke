import gc,weakref
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from shengao.gui_gc import GuiGcPolicy


def policy(qapp,collector=None):
    clock=[0.];held=[False];old=gc.get_threshold()
    p=GuiGcPolicy(qapp,clock=lambda:clock[0],collector=collector,counter=lambda:(0,0,old[2]+1),dragging=lambda:held[0])
    return p,clock,held,old


def test_policy_keeps_young_gc_enabled_and_restores_thresholds_and_callbacks(qapp):
    enabled=gc.isenabled();before=list(gc.callbacks);p,clock,held,old=policy(qapp,lambda generation:0)
    try:
        assert gc.isenabled()==enabled and gc.get_threshold()[:2]==old[:2] and p.collection_phase in gc.callbacks
        p.close();p.close()
        assert gc.get_threshold()==old and gc.isenabled()==enabled and gc.callbacks==before and not p.timer.isActive()
    finally:p.close()


def test_full_collection_waits_for_idle_and_collects_real_reference_cycles(qapp):
    p,clock,held,old=policy(qapp)
    class Node:pass
    node=Node();node.cycle=node;reference=weakref.ref(node);del node
    try:
        clock[0]=.8;p.maybe_collect();assert reference() is not None and not p.records
        clock[0]=1.1;p.maybe_collect();assert reference() is None and len(p.records)==1 and not p.records[0]['forced_after_60s']
    finally:p.close()


def test_continuous_activity_has_a_full_collection_deadline_but_mouse_drag_defers_it(qapp):
    calls=[];p,clock,held,old=policy(qapp,lambda generation:calls.append(generation) or 0)
    try:
        clock[0]=59;p.activity();p.maybe_collect();assert not calls
        clock[0]=61;p.activity();held[0]=True;p.maybe_collect();assert not calls
        held[0]=False;p.maybe_collect();assert calls==[2] and p.records[-1]['forced_after_60s']
        clock[0]=61.2;p.activity();p.maybe_collect();assert calls==[2]
    finally:p.close()


def test_real_keyboard_events_postpone_full_collection(qapp):
    from PySide6.QtWidgets import QLineEdit
    calls=[];p,clock,held,old=policy(qapp,lambda generation:calls.append(generation) or 0);editor=QLineEdit();editor.show()
    try:
        clock[0]=2;QTest.keyClick(editor,Qt.Key.Key_A);clock[0]=2.8;p.maybe_collect();assert not calls
        clock[0]=3.1;p.maybe_collect();assert calls==[2] and editor.text()=='a'
    finally:p.close();editor.close();editor.deleteLater();qapp.processEvents()


def test_external_gc_preferences_are_not_overwritten_on_close(qapp):
    p,clock,held,old=policy(qapp,lambda generation:0);external=(old[0]+1,old[1],old[2])
    try:
        gc.set_threshold(*external);p.close();assert gc.get_threshold()==external
    finally:p.close();gc.set_threshold(*old)
