import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.reading_options import set_ruby
from shengao.project import Style
from shengao.line_layout import available_breaks,make_setting,validate_entry,validate_settings,display_line,break_status,effective_style,setting_issues
from shengao.furigana import unit_ruby_spans


def lyric():
    line=LyricLine('layout','お星様と歌う',1000,4000,[Unit('お星様',1000,2500,'おほしさま',highlights=[Highlight('おほしさま',1000,2500,'manual')]),Unit('と歌う',2600,4000,'とうたう')],romaji='original',translation='原译',reviewed=True)
    return set_ruby(line,0,{'mode':'custom','spans':[[1,2,1,3],[2,3,3,5]]})


def test_wrap_is_only_a_render_view_and_preserves_custom_ruby_and_manual_axis():
    line=lyric();before=line.to_dict();setting=make_setting(line,85,90,[3]);view=display_line(line,setting)
    assert view.text=='お星様\nと歌う' and line.to_dict()==before and view.id==line.id
    assert view.units[0] is not line.units[0] and view.units[1] is line.units[1]
    assert unit_ruby_spans(view.units[0],'お星様')==unit_ruby_spans(line.units[0],'お星様')
    assert [(u.start,u.end,u.kana,u.highlights) for u in view.units]==[(u.start,u.end,u.kana,u.highlights) for u in line.units]
    assert view.romaji==line.romaji and view.translation==line.translation and view.reviewed


def test_word_boundaries_are_explicit_and_do_not_cut_a_reading_group():
    line=lyric();assert available_breaks(line)==(3,)
    with pytest.raises(ValueError,match='词组'):make_setting(line,100,100,[1])
    assert make_setting(line) is None and display_line(line,None) is line


def test_unmatched_raw_lyric_can_wrap_without_inventing_words_or_timing():
    line=LyricLine('raw','明日へ歌う',1000,4000);view=display_line(line,make_setting(line,100,100,[3]))
    assert view.text=='明日へ\n歌う' and view.units==[] and (view.start,view.end)==(line.start,line.end) and line.text=='明日へ歌う'


def test_original_newlines_and_combining_dakuten_are_not_split_again():
    line=LyricLine('raw','か\u3099く\n歌う',0,1000)
    assert 1 not in available_breaks(line) and 3 not in available_breaks(line) and 4 not in available_breaks(line)
    for position in (1,3,4):
        with pytest.raises(ValueError):make_setting(line,100,100,[position])
    halfwidth=LyricLine('half','ｶﾞｸ',0,1000)
    assert available_breaks(halfwidth)==(2,)
    with pytest.raises(ValueError):make_setting(halfwidth,100,100,[1])


def test_old_breaks_survive_text_and_word_changes_as_inactive_reviewable_choices():
    line=lyric();setting=make_setting(line,85,90,[3]);old=copy.deepcopy(setting)
    changed=copy.deepcopy(line);changed.units=[Unit(changed.text,1000,4000,'おほしさまとうたう')]
    assert break_status(changed,setting)==((),(3,)) and display_line(changed,setting) is changed and setting_issues(changed,setting)
    assert setting==old
    changed.text='新しい原文';changed.units=[]
    assert break_status(changed,setting)==((),(3,)) and setting==old


def test_per_line_size_has_no_side_effect_on_global_colors_or_font_files():
    style=Style(size=100,ruby_size=40,romaji_size=30,translation_size=32);before=copy.deepcopy(style)
    s=effective_style(style,make_setting(lyric(),80,75,[3]))
    assert (s.size,s.ruby_size,s.romaji_size,s.translation_size)==(80,24,24,26)
    assert style==before and s.color==style.color and s.highlight==style.highlight and s.font_file==style.font_file


@pytest.mark.parametrize('field,value',[('version',True),('version',2),('text',''),('size_percent',True),('size_percent',float('nan')),('size_percent',201),('ruby_percent',0),('breaks',[True]),('breaks',[3,3]),('breaks',[99])])
def test_malformed_appearance_metadata_is_rejected(field,value):
    setting=make_setting(lyric(),90,100,[3]);setting[field]=value
    with pytest.raises(ValueError):validate_entry(setting)


def test_orphan_line_and_unknown_fields_are_rejected():
    setting=make_setting(lyric(),90,100,[3]);validate_settings({'layout':setting},{'layout'})
    with pytest.raises(ValueError):validate_settings({'missing':setting},{'layout'})
    setting['unexpected']=True
    with pytest.raises(ValueError):validate_entry(setting)
