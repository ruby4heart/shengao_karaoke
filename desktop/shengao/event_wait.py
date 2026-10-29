"""Observe asynchronous completion while running the ordinary Qt dispatcher."""
from PySide6.QtCore import QEventLoop,QTimer,Qt


def wait_for_signal(signal,predicate,timeout_ms):
    """Return on matching completion, timeout, or application shutdown.

    No test-thread sleep delays native decoder/paint events. A notification
    alone is insufficient: the caller's full readiness predicate must pass.
    """
    loop=QEventLoop();timer=QTimer(loop);timer.setSingleShot(True)
    timer.setTimerType(Qt.TimerType.PreciseTimer);timer.timeout.connect(loop.quit)
    ready=False;failure=None
    def changed(*args):
        nonlocal ready,failure
        try:ready=bool(predicate())
        except BaseException as error:failure=error;loop.quit();return
        if ready:loop.quit()
    signal.connect(changed)
    try:
        if predicate():return True
        timer.start(timeout_ms);loop.exec()
        if failure is not None:raise failure
        return ready
    finally:
        timer.stop()
        try:signal.disconnect(changed)
        except RuntimeError:pass  # The sender may have been deleted while waiting.
