"""Format promises: LRC really exports, and external ASS edits are not lost."""
import re
from shengao.subtitle_files import FORMATS,export_subtitle,format_kind,format_note,import_timed,lrc_text
from shengao.project import History,load_project
from shengao import ass_roundtrip
from shengao.action_help import HELP


def _timing(project):
    return [(l.text,l.start,l.end,[(u.text,u.start,u.end) for u in l.units]) for l in project.lines]


def test_every_promised_export_format_is_written(project,tmp_path):
    for kind in FORMATS:
        path=tmp_path/('字幕.'+kind);export_subtitle(project,path,kind)
        assert path.read_text(encoding='utf-8-sig').strip()
        assert FORMATS[kind]['label'] in format_note(kind)
    assert format_kind('LRC 逐字歌词 (*.lrc)')=='lrc' and format_kind('','歌.SRT')=='srt' and format_kind('','x')=='ass'
    promised={kind for kind in FORMATS if kind.upper() in HELP['导出字幕文件…'] or (kind=='txt' and '文本' in HELP['导出字幕文件…'])}
    assert promised==set(FORMATS)


def test_enhanced_lrc_round_trip_keeps_units_and_gaps(project,tmp_path):
    path=tmp_path/'歌.lrc';export_subtitle(project,path,'lrc')
    text=path.read_text(encoding='utf-8')
    assert re.search(r'^\[00:01\.00\]<00:01\.00>今日<00:03\.00><00:03\.20>も',text,re.M)
    assert text.rstrip().endswith('[00:06.00]')  # blank tag closes the last line
    loaded=load_project(path)
    assert _timing(loaded)==_timing(project)
    assert loaded.lines[0].timing_origin['method']=='lrc_word_tags'


def test_lrc_blank_tag_ends_line_and_plain_lrc_still_imports():
    p=import_timed('[00:01.00]一\n[00:03.00]\n[00:08.00]二\n','.lrc')
    assert [(l.text,l.start,l.end) for l in p.lines]==[('一',1000,3000),('二',8000,13000)]
    p=import_timed('[00:01.00]今[00:01.50]日\n','.lrc')
    assert p.lines[0].text=='今日' and [(u.start,u.end) for u in p.lines[0].units]==[(1000,1500),(1500,6000)]


def test_lrc_flattens_line_breaks_without_touching_project(project):
    project.lines[0].units=[];project.lines[0].text='今日も\n歌う'
    assert '[00:01.00]今日も 歌う' in lrc_text(project)
    assert project.lines[0].text=='今日も\n歌う'


def _edit_source(text,line_id,new_text,start=None):
    rows=[]
    for row in text.splitlines():
        if f',shengao:{line_id},' in row:
            head,_=row.rsplit(',',1)
            if start:head=re.sub(r'^Comment: 0,[^,]+',f'Comment: 0,{start}',head)
            row=head+','+new_text
        rows.append(row)
    return '\n'.join(rows)+'\n'


def test_external_ass_timing_edit_is_detected_and_applied_as_one_step(project,tmp_path):
    path=tmp_path/'外部.ass';export_subtitle(project,path)
    text=path.read_text(encoding='utf-8-sig')
    edited=_edit_source(text,'demo',r'{\k150}今日{\k70}{\k80}も{\k20}{\k180}歌う')
    path.write_text(edited,encoding='utf-8-sig')
    loaded=load_project(path);report=ass_roundtrip.inspect(edited,loaded)
    assert report.marked and not report.display_changed and not report.conflicts
    assert report.changes=={'demo':(1000,6000,[(1000,2500),(3200,4000),(4200,6000)])}
    history=History(loaded)
    assert history.apply('应用外部 ASS 时间修改',lambda p:ass_roundtrip.apply(p,report))
    line=history.project.lines[0]
    assert [(u.start,u.end) for u in line.units]==[(1000,2500),(3200,4000),(4200,6000)]
    assert line.text==project.lines[0].text and line.units[0].source=='manual'
    assert 'manual_boundary' in line.units[0].timing_origin['operations']
    assert history.undo() and _timing(history.project)==_timing(project)


def test_external_ass_shift_moves_whole_line(project,tmp_path):
    path=tmp_path/'平移.ass';export_subtitle(project,path)
    text=path.read_text(encoding='utf-8-sig')
    source=next(r for r in text.splitlines() if ',shengao:demo,' in r).rsplit(',',1)[1]
    edited=_edit_source(text,'demo',source,start='0:00:02.00').replace(',0:00:06.00,Lyrics,shengao:demo',',0:00:07.00,Lyrics,shengao:demo')
    report=ass_roundtrip.inspect(edited,load_project(path))
    assert report.changes['demo']==(2000,7000,[(2000,4000),(4200,5000),(5200,7000)])


def test_external_text_edit_is_a_conflict_and_lyric_is_kept(project,tmp_path):
    path=tmp_path/'改字.ass';export_subtitle(project,path)
    text=path.read_text(encoding='utf-8-sig')
    edited=_edit_source(text,'demo',r'{\k200}明日{\k20}{\k80}も{\k20}{\k180}歌う')
    report=ass_roundtrip.inspect(edited,load_project(path))
    assert not report.changes and report.conflicts and '原歌词保留' in report.conflicts[0]
    assert '未应用' in report.summary()


def test_external_display_edit_needs_a_choice_and_number_reformatting_does_not(project,tmp_path):
    path=tmp_path/'样式.ass';export_subtitle(project,path)
    text=path.read_text(encoding='utf-8-sig')
    # Other editors re-serialize numbers and margins; that is not an edit.
    reformatted=re.sub(r'^(Dialogue: \d+,[^,]+,[^,]+,[^,]*,[^,]*),0,0,0,',r'\1,0000,0000,0000,',text,flags=re.M)
    assert reformatted!=text and not ass_roundtrip.inspect(reformatted,load_project(path)).any
    styled=re.sub(r'^(Style: Lyrics,[^,]+),(\d+)',lambda m:f'{m[1]},{int(m[2])+10}',text,count=1,flags=re.M)
    assert styled!=text
    report=ass_roundtrip.inspect(styled,load_project(path))
    assert report.display_changed and not report.changes and '样式' in report.summary()


def test_deleted_source_row_is_reported(project,tmp_path):
    path=tmp_path/'删除.ass';export_subtitle(project,path)
    text='\n'.join(r for r in path.read_text(encoding='utf-8-sig').splitlines() if ',shengao:' not in r)
    report=ass_roundtrip.inspect(text,load_project(path))
    assert report.conflicts==['第 1 句的声稿注释行被删除，保留原时间'] and not report.changes


def test_unmarked_or_external_ass_is_unaffected(project,tmp_path):
    from shengao.subtitles import compose
    assert not ass_roundtrip.inspect(compose(project,True),project).marked
    # Source rows are comments, so plain ASS import never turns them into lyrics.
    path=tmp_path/'无工程.ass';export_subtitle(project,path)
    text='\n'.join(r for r in path.read_text(encoding='utf-8-sig').splitlines() if not r.startswith('; Shengao'))
    from shengao.subtitle_import import import_ass
    imported=import_ass(text,path)
    assert all(not l.id.startswith('shengao') for l in imported.lines)
