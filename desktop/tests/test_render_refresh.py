from shengao import app as studio
from shengao.project import Project
from test_reading_candidates_workflow import reading_window


def test_navigation_and_identical_refresh_reuse_exact_full_composition(reading_window,monkeypatch,qapp):
    w=reading_window;w.render_subtitles();original=studio.compose;calls=[]
    def compose(*args,**kwargs):calls.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(studio,'compose',compose);before=w.project.to_dict();text=w.playback.canvas.renderer.text
    w.move_line(0);assert not w.render_timer.isActive();w.render_subtitles();qapp.processEvents()
    assert not calls and w.playback.canvas.renderer.text==text and w.project.to_dict()==before


def test_direct_data_changes_and_external_renderer_text_cannot_hide_behind_cache(reading_window,monkeypatch):
    w=reading_window;w.render_subtitles();original=studio.compose;calls=[]
    def compose(*args,**kwargs):calls.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(studio,'compose',compose)
    w.line.translation='新しい译文';w.render_subtitles()
    assert len(calls)==1 and w.playback.canvas.renderer.text==original(w.project)
    w.line.display_start=0;w.render_subtitles();assert len(calls)==2 and w.playback.canvas.renderer.text==original(w.project)
    w.playback.canvas.renderer.set_text(original(Project()));w.render_subtitles()
    assert len(calls)==3 and w.playback.canvas.renderer.text==original(w.project)


def test_invalid_changed_axis_is_still_rejected_instead_of_reusing_old_cache(reading_window):
    w=reading_window;w.render_subtitles();old=w.playback.canvas.renderer.text;w.line.units[-1].end=w.line.end+100
    w.render_subtitles()
    assert w.playback.canvas.renderer.text==old and '超出' in w.status.text()
