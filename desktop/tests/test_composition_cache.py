import copy,random
import pytest
from studio_backend.model import LyricLine
from shengao.presentation import WindowIndex,DisplayWindow,display_windows
from shengao.subtitles import compose,CompositionCache,lane_layout
from shengao.render import AssRenderer
from shengao.color_states import update_settings,preset_profile
from shengao.line_layout import make_setting
from test_line_layout_project import sample


@pytest.mark.parametrize('count',[0,1,2,35,350])
def test_overlap_index_matches_strict_brute_force_for_unordered_and_equal_edges(count):
    rng=random.Random(5481);windows=[]
    for _ in range(count):
        start=rng.randrange(0,100)*10;windows.append(DisplayWindow(start,start+rng.randrange(0,80)*10))
    index=WindowIndex(windows)
    for query in [*windows,DisplayWindow(0,0),DisplayWindow(500,500),DisplayWindow(0,2000)]:
        assert index.overlapping(query)==[i for i,w in enumerate(windows) if w.start<query.end and query.start<w.end]


def test_indexed_lane_layout_matches_original_scan_including_local_layout_and_manual_times():
    p=sample();p.lines.extend([LyricLine('earlier','早い表示',9001,10001,display_start=0,display_end=14000),LyricLine('later','次',11001,12001)])
    windows=display_windows(p);index=WindowIndex(windows)
    from shengao.line_layout import resolved_layouts
    layouts=resolved_layouts(p)
    for (_,style),window in zip(layouts,windows):
        assert lane_layout(p,window,windows,style,layouts,index.overlapping(window))==lane_layout(p,window,windows,style,layouts)


def compare(p,cache):
    before=p.to_dict();full=compose(p);actual=compose(p,cache=cache)
    assert actual==full and p.to_dict()==before
    assert compose(p,cache=cache,_snapshot=before)==full and p.to_dict()==before
    assert compose(p,cache=cache,_snapshot=before,_windows=display_windows(p))==full
    renderer=AssRenderer()
    try:
        for when in (0,1000,1001,2000,4003,5001,8003,11001,14000):
            renderer.set_text(full);expected=renderer.rgba(320,180,when)
            renderer.set_text(actual);assert renderer.rgba(320,180,when)==expected
    finally:renderer.close()
    return actual


def test_cached_full_ass_stays_exact_after_direct_edits_layout_colors_neighbors_and_deletion():
    p=sample();cache=CompositionCache();compare(p,cache);compare(p,cache)
    p.lines[0].units[1].end+=10;p.lines[0].end+=10;compare(p,cache)
    p.lines[0].units[1].kana='とうとう';compare(p,cache)
    p.lines[0].display_start=0;p.lines[1].display_end=14500;compare(p,cache)
    p.layout_styles['layout']=make_setting(p.lines[0],100,110,[3]);compare(p,cache)
    p.color_styles=update_settings(p.color_styles,preset_profile(p.style,'gold'),['next']);compare(p,cache)
    p.style.position='top';p.style.size=80;p.style.ruby_size=40;compare(p,cache)
    p.lines.insert(0,LyricLine('intro','前',100,800));compare(p,cache)
    del p.lines[1];p.prune_line_overrides();compare(p,cache)
    assert set(cache.entries)=={line.id for line in p.lines}


def test_filtered_and_embedded_composition_never_reuses_an_incompatible_event_subset():
    p=sample();cache=CompositionCache();full=compare(p,cache)
    for when in (0,1001,4000,5001,8003):
        assert compose(p,preview_time=when,cache=cache)==compose(p,preview_time=when)
        assert compose(p,cache=cache)==full
    assert compose(p,embed=True,cache=cache)==compose(p,embed=True)


def test_cached_render_still_validates_direct_invalid_mutations():
    p=sample();cache=CompositionCache();compose(p,cache=cache);p.lines[0].end=0
    with pytest.raises(ValueError):compose(p,cache=cache)
