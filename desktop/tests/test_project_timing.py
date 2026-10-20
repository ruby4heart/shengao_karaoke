import copy
import json
import pytest
from shengao.project import Project,History,save_project,load_project
from shengao.timing import set_time,pauses,merge_pauses,merge_words,split_word,edit_reading
from shengao.subtitles import compose

def test_source_spaces_preserved_with_undo(project):
    h=History(project);h.apply('lyrics',lambda p:p.replace_lyrics('  真夜中のネオンサインが君を抱きしめて  \n\n遠く隠してしまうよ'))
    assert h.project.lines[0].text=='  真夜中のネオンサインが君を抱きしめて  '
    assert h.dirty;h.undo();assert h.project.to_dict()==project.to_dict();assert not h.dirty
    h.redo();assert len(h.project.lines)==2

def test_bad_edit_does_not_mutate_or_add_undo(project):
    h=History(project)
    with pytest.raises(ValueError):h.apply('bad',lambda p:setattr(p.lines[0],'end',0))
    assert not h.undo_stack;assert h.project.lines[0].end==6000

@pytest.mark.parametrize('data',[{'version':2,'lines':None},{'version':2,'lines':[{}]},
    {'version':2,'fps':'unknown'},{'version':2,'style':{'size':None}},{'version':2,'checks':[]}])
def test_malformed_project_is_a_reviewable_error(tmp_path,data):
    path=tmp_path/'bad.sgproj';path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError):load_project(path)

def test_word_boundary_moves_shared_neighbor_and_mora(project):
    line=project.lines[0];line.units[1].start=line.units[0].end
    changed=set_time(line,0,1000,3100)
    assert changed.units[1].start==3100
    assert changed.units[0].highlights[-1].end==3100
    assert changed.text==line.text;changed.validate()

def test_mora_shared_boundary_keeps_whole_group(project):
    line=project.lines[0];h=line.units[0].highlights
    changed=set_time(line,0,h[0].start,h[0].end+50,0)
    assert changed.units[0].highlights[1].start==h[0].end+50
    assert changed.units[0].text=='今日';assert changed.units[0].start==line.units[0].start

def test_mora_cross_word_boundary_moves_word_envelopes_together(project):
    line=project.lines[0];line.units[1].start=line.units[0].end
    line.units[1].highlights[0].start=line.units[1].start
    index=len(line.units[0].highlights)-1;h=line.units[0].highlights[index]
    changed=set_time(line,0,h.start,h.end+100,index)
    assert changed.units[0].end==3100 and changed.units[1].start==3100
    assert changed.units[1].highlights[0].start==3100
    assert changed.text==line.text;changed.validate()

def test_lock_is_respected(project):
    line=project.lines[0];line.locked=True
    with pytest.raises(ValueError,match='锁定'):set_time(line,-1,1000,7000)
    with pytest.raises(ValueError,match='锁定'):merge_pauses(line,[0],'previous')

@pytest.mark.parametrize('policy',['previous','next'])
def test_pause_merge_changes_real_time_and_keeps_text(project,policy):
    line=project.lines[0];original=line.to_dict();gaps=pauses(line)
    changed=merge_pauses(line,[0],policy)
    assert changed.text==line.text and changed.kana==line.kana
    assert (changed.start,changed.end)==(line.start,line.end)
    assert len(pauses(changed))==len(gaps)-1
    assert changed.to_dict()!=original and line.to_dict()==original

def test_pause_keep_exactly_preserves(project):
    line=project.lines[0];assert merge_pauses(line,[0],'keep').to_dict()==line.to_dict()

def test_word_merge_and_split_preserve_original(project):
    line=project.lines[0];merged=merge_words(line,0,1)
    assert merged.text==line.text;assert merged.units[0].text=='今日も';assert merged.units[0].kana=='きょうも'
    split=split_word(merged,0,2);assert split.text==line.text;assert ''.join(u.text for u in split.units)==line.text

def test_reading_edit_invalidates_timing_only_if_new_syllables(project):
    line=project.lines[0];line.reviewed=True
    changed=edit_reading(line,0,'こんにち')
    assert changed.units[0].reading_source=='manual';assert not changed.reviewed
    assert changed.units[0].text=='今日';assert ''.join(h.kana for h in changed.units[0].highlights)=='こんにち'

def test_project_carries_font_and_independent_confirmations(project,tmp_path):
    from shengao.fonts import bundled_fonts
    font=bundled_fonts()[1];project.style.font_file=font.path;project.style.font=font.family
    project.checks[project.lines[0].id]={'reading':True};project.lines[0].reviewed=False
    path=tmp_path/'作品.sgproj';save_project(project,path);raw=json.loads(path.read_text(encoding='utf-8'))
    assert not raw['style']['font_file'].startswith(('C:','E:'))
    loaded=load_project(path);assert loaded.lines[0].to_dict()==project.lines[0].to_dict()
    assert loaded.checks[loaded.lines[0].id]['reading'];assert not loaded.lines[0].reviewed
    assert loaded.style.font_file!=font.path

def test_ass_retains_styles_when_timing_changes(tmp_path):
    text='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Custom,Meiryo,70,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,20,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Custom,,0,0,0,,{\\pos(500,900)\\kf100}今日{\\blur2\\kf100}歌う
'''
    path=tmp_path/'legacy.ass';path.write_text(text,encoding='utf-8')
    p=load_project(path);p.lines[0]=set_time(p.lines[0],0,1000,2200)
    output=compose(p)
    assert 'Style: Custom,Meiryo,70' in output;assert r'\pos(500,900)' in output
    assert r'\blur2\kf80' in output;assert r'\kf120' in output

def test_embedded_ass_roundtrip(project,tmp_path):
    text=compose(project,True);path=tmp_path/'日本語.ass';path.write_text(text,encoding='utf-8-sig')
    assert load_project(path).lines[0].to_dict()==project.lines[0].to_dict()

def test_own_ass_remains_editable_after_reopen(project,tmp_path):
    path=tmp_path/'new.ass';path.write_text(compose(project,True),encoding='utf-8-sig');loaded=load_project(path)
    loaded.lines[0]=set_time(loaded.lines[0],-1,1100,6100)
    loaded.lines[0].translation='手动修正译文'
    rendered=compose(loaded)
    assert '0:00:01.10' in rendered and '手动修正译文' in rendered

def test_legacy_resolved_ass_preserves_custom_styles_and_applies_new_edits(project,tmp_path):
    from studio_backend.export import export_ass
    source=export_ass(project.lines).replace('Style: Lyrics,Meiryo,64,','Style: Lyrics,Meiryo,76,')
    path=tmp_path/'old.ass';path.write_text(source,encoding='utf-8-sig');loaded=load_project(path)
    assert loaded.source_ass_active and loaded.style.size==76
    assert compose(loaded).split('[Script Info]',1)[1]==source.split('[Script Info]',1)[1]
    loaded.lines[0].translation='保留旧样式，更新译文'
    rendered=compose(loaded)
    assert 'Style: Lyrics,Meiryo,76,' in rendered;assert '保留旧样式，更新译文' in rendered
    saved=tmp_path/'again.ass';saved.write_text(compose(loaded,True),encoding='utf-8-sig');assert load_project(saved).lines[0].translation==loaded.lines[0].translation

def test_legacy_resolved_parallel_lyrics_survive_edit(project,tmp_path):
    import copy
    from studio_backend.export import export_ass
    parallel=copy.deepcopy(project.lines[0]);parallel.id='parallel';parallel.text='今日も歌う';parallel.translation='同时演唱的另一行'
    project.lines.append(parallel)
    path=tmp_path/'parallel.ass';path.write_text(export_ass(project.lines),encoding='utf-8-sig')
    loaded=load_project(path);loaded.lines[0].translation='第一行人工校正'
    rendered=compose(loaded)
    assert '第一行人工校正' in rendered and '同时演唱的另一行' in rendered
    assert len(loaded.lines)==2
