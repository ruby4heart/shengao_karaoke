from pathlib import Path
from shengao.subtitle_files import import_timed,export_subtitle
from shengao.project import load_project

def test_lrc_multiple_timestamps_offsets_and_spaces():
    p=import_timed('[ti:歌]\n[offset:20]\n[00:01.50][00:10.123] 今日も歌う  \n[00:20.00]明日へ','.lrc')
    assert [x.start for x in p.lines]==[1520,10143,20020]
    assert p.lines[0].text==' 今日も歌う  '

def test_srt_and_txt_export_without_losing_source(project,tmp_path):
    path=tmp_path/'字幕.srt';export_subtitle(project,path,'srt');p=load_project(path)
    assert p.lines[0].text==project.lines[0].text;assert p.lines[0].start==1000
    export_subtitle(project,tmp_path/'歌詞.txt','txt');assert (tmp_path/'歌詞.txt').read_text(encoding='utf-8').strip()==project.lines[0].text

def test_ass_portable_fonts_and_editable_metadata(project,tmp_path):
    path=tmp_path/'日本語.ass';export_subtitle(project,path);loaded=load_project(path)
    assert loaded.lines[0].to_dict()==project.lines[0].to_dict()
    assert Path(loaded.style.font_file).is_file() and str(tmp_path) in loaded.style.font_file
    assert Path(loaded.style.ruby_font_file).is_file()
    assert (tmp_path/'日本語-字体说明.txt').exists()

def test_multiline_srt_keeps_linebreak_when_adding_karaoke(tmp_path):
    import re
    from studio_backend.japanese import segment_line
    from shengao.subtitles import compose
    p=import_timed('1\n00:00:01,000 --> 00:00:06,000\n今日も歌う\n明日へ歩こう\n','.srt')
    original=p.lines[0].text;assert '\\N' in compose(p)
    p.lines[0],_=segment_line(p.lines[0],'mora');assert p.lines[0].text==original
    rendered=compose(p)
    # ASS tags can precede positioning (outline, wrapping, weight). Inspect
    # actual lyric events rather than binding the check to tag order.
    lyrics=[row.split(',',9)[9] for row in rendered.splitlines() if row.startswith('Dialogue:') and row.split(',',9)[3]=='Lyrics']
    ys={match.group(1) for text in lyrics if (match:=re.search(r'\\pos\([\d.]+,([\d.]+)\)',text))}
    assert len(ys)==2
    path=tmp_path/'multiple.ass';export_subtitle(p,path);assert load_project(path).lines[0].text==original

def test_long_original_lyric_shrinks_without_changing_text(project):
    from shengao.subtitles import compose,layout_issues
    from studio_backend.japanese import segment_line
    # Exceed the actual ASS advance width, rather than the old em-size estimate.
    project.replace_lyrics('真夜中のネオンサインが君を抱きしめてもう一度だけここで歌っていたい' * 2)
    project.lines[0],_=segment_line(project.lines[0],'mora')
    original=project.lines[0].text;rendered=compose(project)
    assert 'Dialogue:' in rendered and project.lines[0].text==original
    assert any('缩小' in issue[1] for issue in layout_issues(project))
