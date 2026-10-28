"""Real symbol glyphs and Unicode file names survive the UI fallback policy."""
from pathlib import Path
import hashlib,os,shutil,time
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextLayout,QFontDatabase,QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from shengao.fonts import register_qt_fonts
from shengao.theme import STYLE

NAME='Emerald ⧸ 楽園【OFFICIAL MUSIC VIDEO】'


@pytest.fixture(scope='module')
def offscreen_windows_symbol_font(qapp):
    # The offscreen plugin has no Windows system-font database. Load the real
    # OS font for these shaping tests; native acceptance must find it itself.
    added=None
    if QGuiApplication.platformName()=='offscreen' and 'Segoe UI Symbol' not in QFontDatabase.families():
        path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/seguisym.ttf'
        assert path.is_file()
        added=QFontDatabase.addApplicationFont(str(path));assert added>=0
    try:yield
    finally:
        if added is not None:assert QFontDatabase.removeApplicationFont(added)


@pytest.mark.parametrize('role',['projectName','muted'])
def test_filename_symbol_has_a_real_glyph_in_normal_and_header_text(qapp,role,offscreen_windows_symbol_font):
    register_qt_fonts()
    label=QLabel(NAME);label.setObjectName(role);label.setTextFormat(Qt.TextFormat.PlainText)
    label.setStyleSheet(STYLE);label.ensurePolished()
    try:
        layout=QTextLayout(NAME,label.font());layout.beginLayout()
        line=layout.createLine();line.setLineWidth(4000);layout.endLayout()
        runs=layout.glyphRuns()
        assert label.text()==NAME and runs
        assert all(glyph!=0 for run in runs for glyph in run.glyphIndexes())
        # Verify the actual chosen fallback has the missing separator glyph,
        # rather than accepting a tofu box or changing the displayed name.
        assert any(run.rawFont().familyName()=='Segoe UI Symbol' and
                   run.rawFont().glyphIndexesForString('⧸')[0]!=0 for run in runs)
    finally:label.close();label.deleteLater();qapp.processEvents()


def test_ui_font_fallback_does_not_change_subtitle_fonts_ass_or_pixels(qapp,project):
    from shengao.subtitles import compose
    from shengao.render import AssRenderer
    before=project.to_dict();text=compose(project);renderer=AssRenderer()
    previous=qapp.styleSheet()
    try:
        renderer.set_text(text);pixels=renderer.rgba(640,360,2000)
        qapp.setStyleSheet(STYLE)
        assert project.to_dict()==before and compose(project)==text
        assert renderer.rgba(640,360,2000)==pixels and any(pixels)
    finally:qapp.setStyleSheet(previous);renderer.close()


def test_unicode_source_name_import_is_exact_and_can_be_undone(qapp,tmp_path,video):
    from shengao.app import StudioWindow
    from shengao.project import Project,History
    from studio_backend.model import LyricLine,Unit
    target=tmp_path/(NAME+' .mp4');shutil.copy2(video,target)
    assert hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(video.read_bytes()).digest()
    w=StudioWindow(tmp_path/'home',test=True);w.setStyleSheet(STYLE);w.playback.audio.setMuted(True)
    lyrics=[LyricLine('manual','歌',100,700,[Unit('歌',100,700,'うた',source='manual')])]
    w.history=History(Project(lines=lyrics));w.current=0;w.refresh()
    before=w.project.to_dict()['lines'];w.load_media(target,preview=True)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline and (w.analysis_job is not None or w.playback.preview_pending):
        qapp.processEvents();QTest.qWait(5)
    assert w.analysis_job is None and not w.playback.preview_pending
    assert w.project.media==str(target.resolve()) and w.project.title==target.stem
    assert w.project_label.text()==target.stem and target.name in w.media_label.text()
    assert not w.playback.canvas.frame.isNull() and w.project.to_dict()['lines']==before
    assert len(w.history.undo_stack)==1
    w.undo();assert not w.project.media and w.project.to_dict()['lines']==before
