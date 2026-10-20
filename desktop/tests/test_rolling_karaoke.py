import copy
import re
from pathlib import Path
import numpy as np
import pytest
from studio_backend.model import LyricLine,Unit
from studio_backend.japanese import add_mora
from shengao.project import Project,History,save_project,load_project
from shengao.presentation import display_windows
from shengao.furigana import ruby_spans,reading_fragments
from shengao.subtitles import compose,layout_line,ruby_layout,pieces
from shengao.render import AssRenderer
from shengao.app import StudioWindow


def song(duration=6000,gap=0):
    phrases=[('素敵な言葉に勘違い',[('素敵な','すてきな'),('言葉に','ことばに'),('勘違い','かんちがい')]),
             ('恋のお相手はお星様',[('恋の','こいの'),('お相手は','おあいては'),('お星様','おほしさま')]),
             ('今日も君と歌う',[('今日も','きょうも'),('君と','きみと'),('歌う','うたう')]),
             ('明日へ響く歌',[('明日へ','あしたへ'),('響く','ひびく'),('歌','うた')])]
    lines=[]
    for n,(text,groups) in enumerate(phrases):
        start=1000+n*(duration+gap);step=duration//len(groups)
        units=[Unit(t,start+i*step,start+(i+1)*step,kana=k) for i,(t,k) in enumerate(groups)]
        for unit in units:add_mora(unit)
        lines.append(LyricLine(str(n),text,start,start+duration,units=units))
    return Project(lines=lines)


@pytest.mark.parametrize('text,reading,expected',[
    ('素敵な','すてきな',[(0,2,0,3)]),('勘違い','かんちがい',[(0,2,0,4)]),
    ('お相手は','おあいては',[(1,3,1,4)]),('お星様','おほしさま',[(1,3,1,5)]),
    ('抱きしめて','だきしめて',[(0,1,0,1)]),('君と僕','きみとぼく',[(0,1,0,2),(2,3,3,5)]),
    ('大人','おとな',[(0,2,0,3)]),('ネオンサイン','ねおんさいん',[]),
    ('生き生き','いきいき',[(0,1,0,1),(2,3,2,3)]),
    ('今日','あす',[(0,2,0,2)]),
])
def test_ruby_is_over_corresponding_kanji_without_changing_the_approved_reading(text,reading,expected):
    assert list(ruby_spans(text,reading))==expected


def test_unknown_and_ambiguous_readings_stay_together_instead_of_guessing():
    assert ruby_spans('君と僕','きみはぼく')==((0,3,0,5),)
    assert ruby_spans('生き生','いききき')==((0,3,0,4),)
    # Long, merged text must not trigger unbounded recursive matching.
    assert ruby_spans('生き'*30,'あ'*200)==((0,60,0,200),)


def test_kanji_only_ruby_keeps_existing_mora_times_and_correct_horizontal_anchor():
    p=song();line=p.lines[1];unit=line.units[1];before=copy.deepcopy(unit)
    assert reading_fragments(unit,1,4)==[(h.kana,h.start,h.end) for h in unit.highlights[1:4]]
    mf,rf,size,rs,widths,width=layout_line(line,p.style);annotations=ruby_layout(pieces(line),widths,rf,mf)
    annotation=next(a for a in annotations if a.index==1)
    expected=(1920-width)/2+widths[0]+mf.getlength('お')+mf.getlength('相手')/2
    assert abs(annotation.center-expected)<.01 and unit==before
    text=compose(p);ruby_text=''.join(re.sub(r'\{[^}]*\}','',r.split(',,',1)[-1]) for r in text.splitlines() if ',Ruby,' in r)
    assert 'ネオンサイン' not in ruby_text


def test_halfway_preview_three_second_hold_and_two_fixed_slots_leave_singing_times_untouched():
    p=song();p.style.display_mode='alternating';before=p.to_dict();w=display_windows(p)
    assert [x.start for x in w]==[0,4000,10000,16000]
    assert [x.end for x in w]==[7000,13000,19000,28000]
    assert [x.slot for x in w]==[0,1,0,1]
    assert p.to_dict()==before
    # Current lyric is still singing when the upcoming lyric becomes visible.
    assert p.lines[0].start<w[1].start<p.lines[0].end
    assert w[1].start+3000==w[0].end


def test_short_phrases_do_not_stack_three_displays_or_erase_unfinished_singing():
    p=song(1200);p.style.display_mode='alternating';windows=display_windows(p)
    for line,w in zip(p.lines,windows):assert w.start<=line.start<line.end<=w.end
    for time in range(0,10000,50):assert sum(w.start<=time<w.end for w in windows)<=2
    assert all(w.slot in (0,1) for w in windows)


def test_interlude_clears_old_line_and_bounds_upcoming_lead():
    p=song(gap=20000);p.style.display_mode='alternating';windows=display_windows(p)
    assert windows[0].end==p.lines[0].end+3000
    assert windows[1].start==p.lines[1].start-3000
    assert windows[0].end<windows[1].start


def test_three_simultaneous_singing_lines_receive_extra_row_and_warning():
    from shengao.subtitles import layout_issues
    p=song();p.style.display_mode='alternating'
    for n,line in enumerate(p.lines):
        delta=-n*5000;line.start+=delta;line.end+=delta
        for u in line.units:
            u.start+=delta;u.end+=delta
            for h in u.highlights:h.start+=delta;h.end+=delta
    w=display_windows(p)
    assert any(x.slot>=2 for x in w)
    assert any('三句' in message for uid,message in layout_issues(p))
    for line,x in zip(p.lines,w):assert x.start<=line.start and x.end>=line.end


def test_actual_render_has_preview_unhighlighted_then_sweeps_and_clears_each_slot(tmp_path):
    from PIL import Image
    p=song();p.style.display_mode='alternating';p.style.show_romaji=p.style.show_translation=False
    p.style.size=108;p.style.ruby_size=46;p.style.highlight='#58abf4';p.style.glow=5
    before=p.to_dict();text=compose(p);renderer=AssRenderer();renderer.set_text(text)
    try:
        frames={t:np.frombuffer(renderer.rgba(1920,1080,t),np.uint8).reshape(1080,1920,4).copy() for t in [3500,5000,7500,9000,11000]}
        # First lane upper-left, upcoming second lane lower-right; while merely
        # previewing the second line its visible pixels are neutral white.
        assert frames[3500][900:,:,3].max()==0
        assert frames[5000][900:,:,3].max()>0
        lower=frames[5000][900:];mask=lower[:,:,3]>100
        assert np.abs(lower[:,:,:3][mask].astype(int).max(axis=1)-lower[:,:,:3][mask].astype(int).min(axis=1)).mean()<10
        assert frames[7500][900:,:,3].max()>0
        assert not frames[7500][580:800,:,3].any()
        assert not np.array_equal(frames[7500],frames[9000])
        assert frames[11000][580:800,:,3].any()
        Image.fromarray(frames[5000]).save(tmp_path/'dual-row-preview.png')
        Image.fromarray(frames[9000]).save(tmp_path/'dual-row-singing.png')
    finally:renderer.close()
    assert p.to_dict()==before


def test_two_rows_glow_and_kanji_ruby_have_same_positions_in_ffmpeg_and_live(tmp_path):
    import shutil,subprocess
    from shengao.paths import ffmpeg
    from shengao.fonts import bundled_fonts
    p=song();p.style.display_mode='alternating';p.style.size=108;p.style.ruby_size=46;p.style.glow=5
    text=compose(p);(tmp_path/'lyrics.ass').write_text(text,encoding='utf-8-sig');(tmp_path/'fonts').mkdir()
    for font in bundled_fonts():shutil.copy2(font.path,tmp_path/'fonts'/Path(font.path).name)
    result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=black:s=640x360:r=25:d=6','-vf','ass=lyrics.ass:fontsdir=fonts','-ss','5','-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'],cwd=tmp_path,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    actual=np.frombuffer(result.stdout,np.uint8).reshape(360,640,4)[:,:,:3].astype(float)
    renderer=AssRenderer()
    try:
        renderer.set_text(text);rgba=np.frombuffer(renderer.rgba(640,360,5000),np.uint8).reshape(360,640,4)
        expected=rgba[:,:,:3].astype(float)*rgba[:,:,3:4]/255
        mask=np.max(expected,axis=2)>20;assert mask.sum()>500
        assert np.mean(np.abs(expected[mask]-actual[mask]))<18
        # Chroma subsampling alters the threshold of low-opacity blue halos.
        # It must not move glyphs/halos beyond their neighbouring pixel.
        actual_mask=np.max(actual,axis=2)>20
        def expanded(m):
            padded=np.pad(m,1)
            return np.logical_or.reduce([padded[y:y+m.shape[0],x:x+m.shape[1]] for y in range(3) for x in range(3)])
        assert (actual_mask&~expanded(mask)).sum()<10
        assert (mask&~expanded(actual_mask)).sum()<10
    finally:renderer.close()


def test_rolling_preset_and_settings_save_round_trip_without_retiming(qapp,tmp_path):
    w=StudioWindow(home=tmp_path/'home',test=True);w.history=History(song());w.current=1;w.show();w.refresh();before=[x.to_dict() for x in w.project.lines]
    w.apply_preset(2);assert w.project.style.display_mode=='alternating' and not w.project.style.show_romaji
    w.presentation_spins['previous_hold_ms'][0].setValue(2.5)
    assert w.project.style.previous_hold_ms==2500 and [x.to_dict() for x in w.project.lines]==before
    path=tmp_path/'接唱.sgproj';save_project(w.project,path);assert compose(load_project(path))==compose(w.project)
    ass=tmp_path/'接唱.ass';ass.write_text(compose(w.project,True),encoding='utf-8-sig');loaded=load_project(ass)
    assert loaded.style.display_mode=='alternating' and [x.to_dict() for x in loaded.lines]==before
    w.close()
