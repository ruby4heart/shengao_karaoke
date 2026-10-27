from shengao.playback_acceptance import statistics, interval_lag
import pytest


def test_continuity_statistics_include_slow_final_interval():
    values = [40]*99+[701]
    result = statistics(values)
    assert result['count'] == 100 and result['p95_ms'] == 40 and result['max_ms'] == 701
    assert result['values_ms'] == values


def test_lag_uses_frame_interval_and_rejects_invalid_pts():
    assert interval_lag(120, 100000, 140000) == 0
    assert interval_lag(180, 100000, 140000) == 40
    assert interval_lag(80, 100000, 140000) == 20
    for start, end in ((None, 140000), (-1, 140000), (100000, -1), (100000, 100000)):
        with pytest.raises(ValueError):
            interval_lag(100, start, end)


def test_canvas_repaint_cannot_invent_a_new_frame_timestamp(qapp):
    from PySide6.QtCore import Qt, QSize
    from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat
    from shengao.playback import VideoCanvas
    canvas = VideoCanvas(); canvas.resize(320, 180); canvas.show()
    frame = QVideoFrame(QVideoFrameFormat(QSize(32, 18), QVideoFrameFormat.PixelFormat.Format_BGRA8888))
    frame.setStartTime(100000); frame.setEndTime(140000)
    canvas.video_frame(frame); qapp.processEvents()
    timestamp = canvas.new_frame_painted_at_s
    assert timestamp is not None and canvas.painted_sequence == 1
    for _ in range(5):
        canvas.position += 20; canvas.repaint(); qapp.processEvents()
        assert canvas.new_frame_painted_at_s == timestamp and canvas.painted_sequence == 1
    canvas.clear_frame(); assert canvas.new_frame_painted_at_s is None
    canvas.close(); canvas.renderer.close(); canvas.deleteLater()


def test_reopen_same_loaded_video_finishes_preview_at_requested_position(tmp_path, video):
    # Qt media decoder teardown is process-isolated from the suite's shared
    # QApplication, as it is for native GPU acceptance.
    import os, subprocess, sys
    from pathlib import Path
    script = tmp_path/'reopen.py'
    script.write_text(r'''import sys,time
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'desktop'),str(root/'backend')]
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from shengao.playback import Playback
app=QApplication([]);p=Playback();p.audio.setMuted(True);p.resize(640,360);p.show()
try:
    for position in (0,2000,0):
        previous=p.canvas.painted_sequence;p.open(Path(sys.argv[2]),position,preview=True)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            app.processEvents();QTest.qWait(5)
            if not p.preview_pending and p.canvas.painted_sequence>previous:break
        assert not p.preview_pending and p.canvas.painted_sequence>previous
        assert p.canvas.position==position and p.player.position()==position
        assert p.canvas.painted_frame_start_us<=position*1000<p.canvas.painted_frame_end_us,(position,p.canvas.painted_frame_start_us,p.canvas.painted_frame_end_us)
finally:
    p.clear();p.canvas.renderer.close();p.close();p.deleteLater();app.processEvents()
''',encoding='utf-8')
    env=os.environ.copy();env['QT_QPA_PLATFORM']='offscreen'
    result=subprocess.run([sys.executable,str(script),str(Path(__file__).resolve().parents[2]),str(video)],env=env,capture_output=True,timeout=45)
    assert result.returncode==0,result.stderr.decode(errors='replace')[-5000:]
