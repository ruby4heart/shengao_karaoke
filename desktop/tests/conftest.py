from pathlib import Path
import os
import sys
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'desktop'),str(ROOT/'backend')]
import pytest

@pytest.fixture
def project():
    from shengao.project import load_project
    from studio_backend.japanese import add_mora
    p=load_project(ROOT/'demo'/'tutorial.json')
    for u in p.lines[0].units:add_mora(u)
    return p

@pytest.fixture(scope='session')
def video(tmp_path_factory):
    import subprocess
    from shengao.paths import ffmpeg
    root=tmp_path_factory.mktemp('desktop-video-日语');path=root/'素材.mp4'
    result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y',
        '-f','lavfi','-i','color=c=0x142238:s=640x360:r=25:d=8','-f','lavfi','-i','sine=frequency=440:duration=8',
        '-c:v','h264_mf','-hw_encoding','0','-b:v','2M','-pix_fmt','nv12','-c:a','aac','-shortest',str(path)],
        capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    return path

@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    return app

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item,call):
    outcome=yield
    report=outcome.get_result()
    if report.failed:item._desktop_failed=True

@pytest.fixture(autouse=True)
def release_test_windows(request):
    yield
    # Closed windows also retain Qt style caches and signal cycles. Release
    # them after every test so later stylesheet changes don't repolish every
    # window created earlier in the suite.
    from PySide6.QtCore import QCoreApplication,QEvent
    from PySide6.QtWidgets import QApplication
    from shengao.app import StudioWindow
    app=QApplication.instance()
    if app:
        windows=[widget for widget in app.topLevelWidgets() if isinstance(widget,StudioWindow)]
        for widget in windows:
            if not widget.closing:widget.test=True;widget.close()
        app.processEvents()
        for widget in windows:widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
