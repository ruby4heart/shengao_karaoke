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


def test_immediate_boundary_composes_detached_validated_candidate_before_binding(reading_window,monkeypatch):
    w=reading_window;w.set_stage(2);w.render_subtitles();before=w.project.to_dict();previous=w.timeline.line
    validate=Project.validate;compose_after_edit=studio._compose_after_edit;checked=[];rendered=[]
    def record_validation(project):
        result=validate(project);checked.append(project);return result
    def record_render(project,**kwargs):
        assert checked==[project] and w.timeline.line is previous and project.lines[0] is not previous
        assert kwargs['_snapshot']==project.to_dict()
        rendered.append(project);return compose_after_edit(project,**kwargs)
    monkeypatch.setattr(Project,'validate',record_validation);monkeypatch.setattr(studio,'_compose_after_edit',record_render)
    w.change_boundary(0,0,1000,1120)
    assert rendered==[w.project] and checked==[w.project] and not w.render_timer.isActive()
    assert w.timeline.line is w.line and len(w.history.undo_stack)==1
    after=w.project.to_dict();assert after!=before and w.playback.canvas.renderer.text==studio.compose(w.project)
    w.undo();assert w.project.to_dict()==before
    w.redo();w.render_subtitles();assert w.project.to_dict()==after and w.playback.canvas.renderer.text==studio.compose(w.project)
    # A later mutation must receive normal full validation, even though this
    # object was validated during the earlier synchronous transaction.
    text=w.playback.canvas.renderer.text;w.line.units[-1].end=w.line.end+100;w.render_subtitles()
    assert w.playback.canvas.renderer.text==text and '超出' in w.status.text()


def test_immediate_render_failure_survives_refresh_without_losing_edit(reading_window,monkeypatch):
    w=reading_window;w.render_subtitles();before=w.project.to_dict();text=w.playback.canvas.renderer.text
    def fail(*args,**kwargs):raise OSError('测试渲染资源不可读')
    monkeypatch.setattr(studio,'_compose_after_edit',fail)
    w.change_boundary(0,0,1000,1120)
    assert w.project.to_dict()!=before and len(w.history.undo_stack)==1
    assert w.playback.canvas.renderer.text==text and w.status.text()=='测试渲染资源不可读'
    w.undo();assert w.project.to_dict()==before
