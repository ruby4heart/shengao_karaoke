"""Shared source/frozen check of stable geometry during ordinary timing edits."""
from PySide6.QtCore import QObject,QEvent
from PySide6.QtTest import QTest


def exercise_stable_timing(app,w,check,sizes=((1280,800),(960,680))):
    def settle():app.processEvents();QTest.qWait(60);app.processEvents()
    metrics=[]
    for size in sizes:
        w.resize(*size);w.set_stage(2);w.refresh();settle();w.render_subtitles();settle()
        check('timing_workbench_hidden_action_'+str(size[0]),w.next_button.isHidden())
        watched=(w.workflow_banner,w.workspace_scroll.viewport(),w.timeline)
        class Observer(QObject):
            def __init__(self):super().__init__();self.events=[]
            def eventFilter(self,obj,event):
                if event.type()==QEvent.Type.Resize:self.events.append(('resize',event.oldSize().width(),event.oldSize().height(),event.size().width(),event.size().height()))
                if obj is w.next_button and event.type() in (QEvent.Type.Show,QEvent.Type.Hide):self.events.append(('action',event.type().name))
                return False
        observer=Observer();controls=(*watched,w.next_button)
        for widget in controls:widget.installEventFilter(observer)
        initial=[widget.size() for widget in watched];before=w.project.to_dict();steps=len(w.history.undo_stack)
        try:
            for index in range(12):
                delta=10 if index%2==0 else -10
                w.change_boundary(-1,-1,w.line.start+delta,w.line.end+delta);settle()
            stable=not observer.events and [widget.size() for widget in watched]==initial and w.next_button.isHidden()
            check('timing_workbench_stable_'+str(size[0]),stable and len(w.history.undo_stack)==steps+12)
            metrics.append({'size':list(size),'dpr':w.devicePixelRatioF(),'events':list(observer.events),'stable':stable})
            for _ in range(12):w.undo();settle()
            check('timing_workbench_undo_'+str(size[0]),w.project.to_dict()==before and len(w.history.undo_stack)==steps)
            w.set_stage(3);settle();visible=not w.next_button.isHidden();w.set_stage(2);settle()
            check('timing_workbench_step_actions_'+str(size[0]),visible and w.next_button.isHidden())
        finally:
            for widget in controls:widget.removeEventFilter(observer)
    return metrics
