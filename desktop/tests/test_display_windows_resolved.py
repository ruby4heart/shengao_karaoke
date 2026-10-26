import copy
from studio_backend.model import LyricLine
from shengao.project import Project
from shengao.presentation import display_windows


def project(ranges):
    p=Project(duration=max(b for a,b in ranges)+10000,lines=[LyricLine(str(i),'演唱',a,b,reviewed=True) for i,(a,b) in enumerate(ranges)])
    p.style.display_mode='alternating';return p


def no_lane_collisions(windows):
    for i,w in enumerate(windows):
        for other in windows[:i]:assert w.slot!=other.slot or not (w.start<other.end and other.start<w.end)


def test_manual_upcoming_appearance_updates_previous_automatic_hold():
    p=project([(1000,4000),(5000,8000)]);p.lines[1].display_start=3500;before=p.to_dict();w=display_windows(p)
    assert w[0].end==6500 and w[1].start==3500 and p.to_dict()==before
    p.lines[0].display_end=7500;w=display_windows(p);assert w[0].end==7500


def test_early_upcoming_never_erases_the_previous_singing():
    p=project([(1000,7000),(7500,9000)]);p.lines[1].display_start=500;before=p.to_dict();w=display_windows(p)
    assert w[0].end>=7000 and w[1].start==500 and p.to_dict()==before
    no_lane_collisions(w)


def test_explicit_long_hold_keeps_its_time_and_adds_a_lane_instead_of_cutting_it():
    from shengao.subtitles import layout_issues
    p=project([(1000,2000),(3000,4000),(5000,6000)]);p.lines[0].display_end=6500;before=p.to_dict();w=display_windows(p)
    assert w[0].end==6500 and any(v.slot>=2 for v in w) and p.to_dict()==before
    assert any('字幕同时显示' in message for _,message in layout_issues(p));no_lane_collisions(w)


def test_fallback_lane_then_next_preferred_lane_cannot_extend_back_into_each_other():
    p=project([(1000,3000),(2000,10000),(3500,4000),(8000,9000),(10000,11000)])
    before=p.to_dict();w=display_windows(p);no_lane_collisions(w)
    assert all(v.start<=line.start<line.end<=v.end for line,v in zip(p.lines,w)) and p.to_dict()==before


def test_nonmonotonic_manual_appearances_query_older_intervals_in_each_lane():
    p=project([(10000,11000),(12000,13000),(14000,15000),(16000,17000),(18000,19000)])
    p.lines[1].display_start=500;p.lines[3].display_start=1000;p.lines[4].display_start=600
    p.lines[0].display_end=16000;p.lines[2].display_end=19000;before=p.to_dict();w=display_windows(p)
    no_lane_collisions(w);assert p.to_dict()==before
    assert all(v.start<=line.start and v.end>=line.end for line,v in zip(p.lines,w))


def test_many_short_phrases_keep_two_rows_without_delaying_halfway_cues():
    p=project([(1000+i*900,1900+i*900) for i in range(500)]);before=copy.deepcopy(p.to_dict());w=display_windows(p)
    assert all(v.slot in (0,1) for v in w);no_lane_collisions(w)
    assert w[10].start==p.lines[9].start+450 and p.to_dict()==before
