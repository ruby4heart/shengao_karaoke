from shengao.furigana import unit_ruby_spans
from shengao.project import Project,save_project,load_project
from shengao.subtitles import compose,ruby_layout,pieces,layout_line
from shengao.subtitle_files import export_subtitle
from shengao.editor_model import segmentation_preview
from studio_backend.model import LyricLine,Unit
from studio_backend.reading_options import set_ruby
from studio_backend.convert import annotation_suggestion
import pytest


def sample():return LyricLine('ruby','お相手は',1000,3000,[Unit('お相手は',1000,3000,'おあいては')])


def test_user_mapping_reaches_real_ass_layout_and_roundtrip(tmp_path):
    line=set_ruby(sample(),0,{'mode':'custom','spans':[[1,2,1,2],[2,3,2,4]]});p=Project(lines=[line])
    assert unit_ruby_spans(line.units[0])==((1,2,1,2),(2,3,2,4))
    mf,rf,*values=layout_line(line,p.style);widths=values[2];positions=ruby_layout(pieces(line),widths,rf,mf)
    assert [(v.reading_start,v.reading_end) for v in positions]==[(1,2),(2,4)]
    path=tmp_path/'手工注音.ass';export_subtitle(p,path);restored=load_project(path)
    assert compose(restored)==compose(p) and restored.lines[0].units[0].reading_options==line.units[0].reading_options


def test_whole_and_off_control_actual_annotation_output():
    line=sample();whole=set_ruby(line,0,{'mode':'whole'});off=set_ruby(line,0,{'mode':'off'})
    assert unit_ruby_spans(whole.units[0])==((0,4,0,5),) and unit_ruby_spans(off.units[0])==()
    assert compose(Project(lines=[whole]))!=compose(Project(lines=[off]))


def test_annotation_suggestion_cannot_drop_manual_mapping_or_reading():
    line=set_ruby(sample(),0,{'mode':'custom','spans':[[1,3,1,4]]})
    suggestion=annotation_suggestion(line,{'groups':[{'text':line.text,'kana':'おてあいは','romaji':'oteaiha'}],'translation':'译文'})
    assert suggestion.units[0].kana=='おあいては' and suggestion.units[0].reading_options==line.units[0].reading_options


def test_explicit_resegmentation_does_not_silently_discard_manual_mapping():
    line=set_ruby(sample(),0,{'mode':'whole'})
    with pytest.raises(ValueError,match='手工注音对应'):segmentation_preview(line,[1])
