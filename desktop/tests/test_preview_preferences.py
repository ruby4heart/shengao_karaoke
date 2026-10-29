import pytest
from PySide6.QtCore import QThreadPool,QPoint
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QVideoFrame
from shengao.app import StudioWindow
from shengao.preview_preferences import PreviewPreferencesDialog,validate


@pytest.fixture
def studio(qapp,tmp_path):
    pool=QThreadPool.globalInstance();old=pool.maxThreadCount();w=StudioWindow(tmp_path/'home',test=True)
    yield w
    w.close();qapp.processEvents();pool.setMaxThreadCount(old)


def test_optional_preview_settings_persist_without_mutating_project(studio,qapp):
    w=studio;before=w.project.to_dict();w.adopt_preview_preferences(False,1)
    assert not w.playback.canvas.gpu_enabled and QThreadPool.globalInstance().maxThreadCount()==1
    other=StudioWindow(w.home,test=True)
    assert not other.playback.canvas.gpu_enabled and other.local_worker_limit==1
    assert w.project.to_dict()==before
    other.close();qapp.processEvents()


def test_failed_save_keeps_active_gpu_and_worker_preferences(studio,monkeypatch):
    w=studio;original=w.preferences.data.copy();threads=QThreadPool.globalInstance().maxThreadCount()
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr(w.preferences,'set_many',fail)
    with pytest.raises(OSError):w.adopt_preview_preferences(False,1)
    assert w.playback.canvas.gpu_enabled and w.preferences.data==original and QThreadPool.globalInstance().maxThreadCount()==threads


@pytest.mark.parametrize('values',[(True,True),(1,2),(True,-1),(False,3)])
def test_invalid_resource_choices_do_not_change_runtime(values):
    with pytest.raises(ValueError):validate(*values)


def test_disabled_gpu_uses_regular_qt_frame_and_can_be_reenabled(studio,monkeypatch):
    import shengao.frame_scaler as module
    w=studio;canvas=w.playback.canvas;canvas.set_gpu_enabled(False)
    monkeypatch.setattr(module,'eligible',lambda *args:True)
    def unexpected(*args):pytest.fail('GPU converter used while disabled')
    monkeypatch.setattr(module,'GpuFrameScaler',unexpected)
    frame=QImage(40,20,QImage.Format.Format_ARGB32);frame.fill(0xff12ab34)
    canvas.video_frame(QVideoFrame(frame))
    assert not canvas.frame.isNull() and canvas.frame.pixelColor(10,10).rgb()==0xff12ab34 and canvas._gpu_scaler is None
    canvas.set_gpu_enabled(True);assert canvas.gpu_enabled


def test_small_dialog_has_reachable_save_and_cancel_is_private(studio,qapp):
    w=studio;dialog=PreviewPreferencesDialog(w);dialog.resize(400,340);dialog.show();qapp.processEvents()
    point=dialog.save_button.mapTo(dialog,QPoint(0,0))
    assert dialog.rect().contains(point+dialog.save_button.rect().bottomRight())
    dialog.gpu.setChecked(False);dialog.workers.setCurrentIndex(1);dialog.reject()
    assert w.playback.canvas.gpu_enabled and w.local_worker_limit==0


def test_disabling_existing_scaler_releases_it_and_retains_frame(studio):
    canvas=studio.playback.canvas
    class Scaler:
        closed=False
        def close(self,*args):self.closed=True
    old=Scaler();canvas._gpu_scaler=old;canvas.destroyed.connect(old.close)
    canvas.frame=QImage(10,10,QImage.Format.Format_ARGB32);canvas.frame.fill(0xff334455)
    canvas.set_gpu_enabled(False)
    assert old.closed and canvas._gpu_scaler is None and not canvas.frame.isNull()
