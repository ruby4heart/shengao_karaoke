"""Display-only formatting must not become a lyric or timing edit."""
import copy,hashlib,json,sys,types
from pathlib import Path
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.reading_options import set_ruby
from shengao.project import Project,History,SCHEMA,save_project,load_project
from shengao.line_layout import make_setting,break_status
from shengao.color_states import preset_profile,update_settings
from shengao.subtitles import compose,layout_issues
from shengao.subtitle_files import export_subtitle
from shengao.render import AssRenderer
from shengao.paths import ASSETS


def sample():
    line=LyricLine('layout','お星様と歌う',1001,4003,[Unit('お星様',1001,2502,'おほしさま',highlights=[Highlight('おほしさま',1001,2502,'manual')]),Unit('と歌う',2601,4003,'とうたう')],romaji='original',translation='原译',reviewed=True)
    line=set_ruby(line,0,{'mode':'custom','spans':[[1,2,1,3],[2,3,3,5]]})
    p=Project(lines=[line,LyricLine('next','次の歌',5001,8003)],duration=15000,checks={'layout':{'reading':True}})
    p.style.display_mode='alternating';p.color_styles=update_settings({},preset_profile(p.style,'blue'))
    p.layout_styles={'layout':make_setting(line,85,90,[3])};return p


def raster(p,when,filtered=False):
    renderer=AssRenderer()
    try:
        renderer.set_text(compose(p,preview_time=when) if filtered else compose(p));return renderer.rgba(640,360,when)
    finally:renderer.close()


def test_current_schema_and_all_prior_formats_have_an_explicit_default():
    assert SCHEMA==14
    for version in range(1,15):
        p=Project.from_dict({'version':version,'lines':[]})
        assert p.layout_styles=={} and p.to_dict()['version']==14
    p=sample();data=p.to_dict();data['version']=13
    with pytest.raises(ValueError,match='第 14 版'):Project.from_dict(data)
    for invalid in (True,15,'14'):
        with pytest.raises(ValueError):Project.from_dict({'version':invalid,'lines':[]})


def test_actual_released_029_reader_accepts_13_and_rejects_14():
    manifest=json.loads((ASSETS/'compatibility/project-v029-source.json').read_text())
    raw=(ASSETS/'compatibility/project-v029.py.txt').read_bytes()
    assert manifest['commit']=='34f4ef435705d71d4309e2091c5b7ff5dba102db'
    assert hashlib.sha256(raw).hexdigest()==manifest['sha256']=='2e0038535b2bbc9f96ae27d108e8086f4de97ddc55a88eed332741371cbb5939'
    module=types.ModuleType('shengao._compat_v029_project');module.__package__='shengao';sys.modules[module.__name__]=module
    try:
        exec(compile(raw,'actual-released-v029-project.py','exec'),module.__dict__)
        assert module.SCHEMA==13 and module.Project.from_dict({'version':13,'lines':[]}).to_dict()['version']==13
        with pytest.raises(ValueError,match='版本较新'):module.Project.from_dict(sample().to_dict())
    finally:sys.modules.pop(module.__name__,None)


@pytest.mark.parametrize('ext',['sgproj','ass'])
def test_save_and_own_ass_reopen_keep_axis_custom_ruby_colors_and_checks(tmp_path,ext):
    p=sample();before=p.to_dict();target=tmp_path/('本句外观.'+ext)
    if ext=='ass':export_subtitle(p,target)
    else:save_project(p,target)
    after=load_project(target)
    assert after.layout_styles==p.layout_styles and after.color_styles==p.color_styles
    assert [v.to_dict() for v in after.lines]==before['lines'] and after.checks==before['checks']
    assert compose(after)==compose(p) and p.to_dict()==before


def test_delete_replace_append_and_undo_prune_only_removed_line_overrides():
    p=sample();p.layout_styles['next']=make_setting(p.lines[1],90)
    p.color_styles=update_settings(p.color_styles,preset_profile(p.style,'blue'),['layout','next'])
    before=p.to_dict();h=History(p)
    h.apply('删除本句',lambda p:p.lines.pop(0))
    assert set(h.project.layout_styles)==set(h.project.color_styles['lines'])=={'next'}
    assert h.undo() and h.project.to_dict()==before
    h.apply('追加歌词',lambda p:p.replace_lyrics('追加歌词',append=True))
    assert h.project.layout_styles==before['layout_styles'] and h.undo()
    h.apply('替换歌词',lambda p:p.replace_lyrics('新歌词'))
    assert h.project.layout_styles=={} and h.project.color_styles['lines']=={}
    assert h.undo() and h.project.to_dict()==before


def test_stale_wrap_is_loadable_visible_and_retained_until_explicit_resolution():
    p=sample();stored=copy.deepcopy(p.layout_styles)
    p.lines[0].units=[Unit(p.lines[0].text,1001,4003,'おほしさまとうたう')]
    after=Project.from_dict(p.to_dict());assert after.layout_styles==stored
    assert break_status(after.lines[0],after.layout_styles['layout'])==((),(3,))
    assert any(uid=='layout' and '原换行位置保留' in message for uid,message in layout_issues(after))
    assert any(raster(after,2000)[3::4]) and after.layout_styles==stored


def test_malformed_or_orphan_layout_does_not_partially_mutate_history():
    p=sample();h=History(p);before=p.to_dict()
    with pytest.raises(ValueError):h.apply('过期外观',lambda p:p.layout_styles.update({'missing':make_setting(p.lines[0],85)}))
    assert h.project.to_dict()==before and not h.undo_stack


@pytest.mark.parametrize('when',[0,990,1000,1001,2501,4000,4003,6500,8000,8003,11000,11003,11020,14999])
def test_private_preview_filter_has_identical_native_pixels_even_at_ass_rounding_edges(when):
    p=sample();before=p.to_dict()
    assert raster(p,when,True)==raster(p,when) and p.to_dict()==before


def test_unwrapped_default_and_inherited_settings_keep_ass_identical():
    p=sample();p.layout_styles={};before=compose(p)
    # The explicit 100% record is accepted on disk, while the editor emits
    # absence for inheritance. It must produce the same actual appearance.
    p.layout_styles={'layout':{'version':1,'text':p.lines[0].text,'size_percent':100,'ruby_percent':100,'breaks':[]}}
    assert compose(p)==before


def test_line_sizes_and_view_breaks_change_output_without_touching_raw_content():
    p=sample();before=p.to_dict();wrapped=compose(p);pixels=raster(p,2000)
    p.layout_styles={};plain=compose(p)
    assert wrapped!=plain and pixels!=raster(p,2000)
    assert [v.to_dict() for v in p.lines]==before['lines'] and p.checks==before['checks'] and p.color_styles==before['color_styles']
    assert '\\N' not in p.lines[0].text and p.lines[0].units[0].reading_options['ruby']['mode']=='custom'


def test_original_ass_effects_stay_exact_with_dormant_layout_settings():
    p=sample();p.source_ass=compose(p).replace('WrapStyle: 0','WrapStyle: 2');p.source_ass_active=True
    before=p.to_dict();assert compose(p)==p.source_ass and compose(p,preview_time=2000)==p.source_ass and p.to_dict()==before


def test_close_up_keeps_exact_full_context_positions_and_excludes_other_text():
    import numpy as np
    from shengao.song_info import DEFAULTS
    p=sample();p.song_info={**DEFAULTS,'enabled':True,'title':'歌名'};before=p.to_dict();renderer=AssRenderer()
    try:
        renderer.set_text(compose(p));full=np.frombuffer(renderer.rgba(640,360,3000),np.uint8).reshape(360,640,4).copy()
        renderer.set_text(compose(p,preview_time=3000,preview_line_id='layout'));focus=np.frombuffer(renderer.rgba(640,360,3000),np.uint8).reshape(360,640,4)
        mask=focus[:,:,3]>0
        assert mask.any() and np.array_equal(focus[mask],full[mask]) and (full[:,:,3]>0).sum()>mask.sum()
        assert p.to_dict()==before
    finally:renderer.close()
    with pytest.raises(ValueError):compose(p,preview_line_id='layout')
    with pytest.raises(ValueError):compose(p,preview_time=3000,preview_line_id='missing')


def test_regenerating_one_legacy_line_prunes_other_line_overrides_only_in_temporary_copy():
    p=sample();p.layout_styles['next']=make_setting(p.lines[1],90)
    p.color_styles=update_settings(p.color_styles,preset_profile(p.style,'blue'),['next'])
    p.source_ass=compose(p);p.source_ass_active=True;p.ass_rows=[{'generated':True,'originals':[v.to_dict() for v in p.lines]}]
    p.lines[0].translation='改过的译文';before=p.to_dict();result=compose(p)
    assert '改过的译文' in result and '次の歌' in result and p.to_dict()==before


def test_layout_decision_is_reopened_when_only_per_line_appearance_changes():
    from shengao.review_issues import collect,record_decision,state
    p=sample();p.lines[0].units=[Unit(p.lines[0].text,1001,4003,'おほしさまとうたう')]
    old=next(v for v in collect(p) if v.kind=='layout' and '原换行位置保留' in v.why)
    records=record_decision({},old,'keep');p.layout_styles['layout']['ruby_percent']=95
    current=next(v for v in collect(p) if v.id==old.id)
    assert current.why==old.why and state(current,records)=='changed'

