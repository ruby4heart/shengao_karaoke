import time
from PySide6.QtTest import QTest
from shengao.app import StudioWindow
from shengao.workbench_acceptance import exercise


def test_shared_workbench_acceptance(qapp,tmp_path):
    from shengao.theme import STYLE
    checks=[]
    def check(name,passed):
        checks.append(name);assert passed,name
    def wait(predicate,milliseconds):
        deadline=time.monotonic()+milliseconds/1000
        while time.monotonic()<deadline:
            qapp.processEvents()
            if predicate():return True
            QTest.qWait(20)
        return bool(predicate())
    old_style=qapp.style().objectName();old_sheet=qapp.styleSheet()
    try:
        qapp.setStyle('Fusion');qapp.setStyleSheet(STYLE)
        metrics=exercise(qapp,StudioWindow,tmp_path,check,wait)
        assert len(checks)>=25 and metrics['real_player_exercised'] and metrics['paid_api_calls']==0
    finally:qapp.setStyleSheet(old_sheet);qapp.setStyle(old_style)
