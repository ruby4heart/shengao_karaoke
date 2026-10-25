import copy
from pathlib import Path
import pytest
from studio_backend.model import LyricLine
from shengao.project import Project,History,save_project,load_project
from shengao.song_info import DEFAULTS,MARKER,settings,append_ass,event_parts,own_event,issues,overlap_issues
from shengao.subtitles import compose
from shengao.subtitle_files import export_subtitle
from shengao.subtitle_import import import_ass
from shengao.fonts import bundled_fonts
from shengao.render import AssRenderer


def sample(**overrides):
    return Project(duration=6000,lines=[LyricLine('line','明日へ',1000,4000)],
                   song_info={**DEFAULTS,'enabled':True,'title':'歌の名前','artist':'歌手の名前',**overrides})


def raster(project,when=2000):
    renderer=AssRenderer()
    try:
        from shengao.fonts import project_font_files
        renderer.add_fonts(project_font_files(project));renderer.set_text(compose(project));return renderer.rgba(640,360,when)
    finally:renderer.close()


def test_old_projects_and_disabled_settings_keep_actual_output_identical():
    p=sample();p.song_info={};base=compose(p);pixels=raster(p)
    p.song_info={**DEFAULTS,'title':'Stored title','artist':'Stored artist'}
    assert compose(p)==base and raster(p)==pixels
    old=p.to_dict();old['version']=12;old.pop('song_info')
    assert Project.from_dict(old).song_info=={}
    old['song_info']=p.song_info
    with pytest.raises(ValueError,match='13'):Project.from_dict(old)


def test_credits_are_separate_literal_events_without_touching_lyrics():
    p=sample(title=r'{\p1}song, name\Ntest',artist='歌手\n二行目');before=copy.deepcopy(p.to_dict());text=compose(p)
    rows=[v for _,v in event_parts(text) if own_event(v)]
    assert len(rows)==2 and all(v['Name']==MARKER and v['Effect']==MARKER for v in rows)
    assert r'{\p1}' not in rows[0]['Text'] and '｛＼p1｝song, name＼Ntest' in rows[0]['Text']
    assert r'歌手\N二行目' in rows[1]['Text'] and p.to_dict()==before
    p.song_info['title']='';assert len([v for _,v in event_parts(compose(p)) if own_event(v)])==1


@pytest.mark.parametrize('field,value',[('enabled',1),('version',True),('title_size',True),('x',-1),('y',1017),('opacity',101),('outline',float('nan')),('shadow',float('inf')),('title_color','#fff'),('artist_color','red'),('font','bad,field'),('title','x\x00'),('artist','a\nb\nc\nd'),('title','x'*501),('end',-1),('period','unknown')])
def test_invalid_settings_are_rejected_before_saving_or_rendering(field,value):
    p=sample(**{field:value})
    with pytest.raises(ValueError):p.validate()


def test_whole_media_or_explicit_period_reaches_real_raster():
    p=sample();p.lines=[]
    assert any(raster(p,0)[3::4]) and any(raster(p,5999)[3::4]) and not any(raster(p,6000)[3::4])
    p.song_info.update(period='range',start=1200,end=2400)
    assert not any(raster(p,1199)[3::4]) and any(raster(p,1200)[3::4]) and any(raster(p,2399)[3::4]) and not any(raster(p,2400)[3::4])
    p.song_info['opacity']=0;assert not any(raster(p,1800)[3::4])


def test_roundtrip_project_and_ass_carry_independent_font_and_state(tmp_path):
    font=bundled_fonts()[2];p=sample(font=font.family,font_file=font.path,title_color='#ff3355',period='range',start=500,end=5500)
    p.lines[0].reviewed=True;p.checks={'line':{'reading':True}};before=p.to_dict()
    for ext in ('sgproj','ass'):
        path=tmp_path/('歌手标识.'+ext)
        if ext=='ass':export_subtitle(p,path)
        else:save_project(p,path)
        loaded=load_project(path);assert loaded.lines[0].to_dict()==p.lines[0].to_dict() and loaded.checks==p.checks
        assert Path(loaded.song_info['font_file']).is_file() and Path(loaded.song_info['font_file']).parent.parent.name=='歌手标识.assets'
        assert raster(loaded)==raster(p) and compose(loaded)==compose(p)
        data=path.read_text(encoding='utf-8-sig');assert str(font.path) not in data
    assert p.to_dict()==before


def test_original_ass_styles_and_effects_survive_overlay_and_own_roundtrip(tmp_path):
    original=Project(lines=[LyricLine('raw','原字幕',1000,4000)]);text=compose(original).replace('PlayResX: 1920','PlayResX: 1280').replace('PlayResY: 1080','PlayResY: 720')
    text=text.replace(r'{\bord2.500\shad1.000}',r'{\blur2\t(0,600,\frz5)\bord2.500\shad1.000}')
    p=import_ass(text);p.song_info=sample().song_info;before=copy.deepcopy(p.to_dict());result=compose(p)
    assert all(row in result.splitlines() for row in text.splitlines())
    own=[v for _,v in event_parts(result) if own_event(v)]
    assert len(own)==2 and r'\pos(42.66667,26.66667)' in own[0]['Text'] and p.to_dict()==before and p.source_ass_active
    assert result.count('YCbCr Matrix: None')==text.count('YCbCr Matrix: None')
    path=tmp_path/'原效果和标识.ass';export_subtitle(p,path);loaded=load_project(path)
    assert loaded.source_ass_active and loaded.source_ass==text and raster(loaded)==raster(p)
    stripped='\n'.join(v for v in result.splitlines() if not v.startswith('; ShengaoProject: '))
    external=import_ass(stripped);assert len(external.lines)==len(p.lines)
    external.song_info=p.song_info
    assert len([v for _,v in event_parts(compose(external)) if own_event(v)])==2


def test_reordered_valid_ass_columns_remain_valid():
    p=sample();p.song_info={};text=compose(p);rows=text.splitlines();section=''
    for i,row in enumerate(rows):
        if row.startswith('['):section=row
        if row.startswith('Format:') and section=='[V4+ Styles]':
            names=[v.strip() for v in row.split(':',1)[1].split(',')];names[1],names[2]=names[2],names[1];rows[i]='Format: '+', '.join(names)
        elif row.startswith('Style:'):
            values=row.split(':',1)[1].lstrip().split(',');values[1],values[2]=values[2],values[1];rows[i]='Style: '+','.join(values)
        elif row.startswith('Format:') and section=='[Events]':
            names=[v.strip() for v in row.split(':',1)[1].split(',')];names[1],names[2]=names[2],names[1];rows[i]='Format: '+', '.join(names)
        elif row.startswith('Dialogue:'):
            values=row.split(':',1)[1].lstrip().split(',',9);values[1],values[2]=values[2],values[1];rows[i]='Dialogue: '+','.join(values)
    p.source_ass='\n'.join(rows)+'\n';p.source_ass_active=True;p.song_info=sample().song_info
    text=compose(p);credits=[v for _,v in event_parts(text) if own_event(v)]
    assert len(credits)==2 and credits[0]['Start']=='0:00:00.00' and credits[0]['End']=='0:00:06.00'
    assert any(raster(p)[3::4])


def test_incomplete_foreign_ass_errors_without_mutating_it():
    p=sample();p.source_ass=compose(Project()).replace('PlayResX: 1920\n','');p.source_ass_active=True;before=p.to_dict()
    with pytest.raises(ValueError,match='PlayRes'):compose(p)
    assert p.to_dict()==before;p.song_info={};assert compose(p)==p.source_ass


def test_safe_area_missing_font_and_media_range_have_actionable_warnings():
    p=sample(title='長'*80,x=1850,y=0,font_file='missing.otf',period='range',start=0,end=7000)
    messages=[text for _,text in issues(p)]
    assert any('安全区' in v for v in messages) and any('丢失' in v for v in messages) and any('超出媒体' in v for v in messages)


def test_actual_lyric_pixels_detect_overlap_and_nonoverlapping_period():
    p=sample(title='明日へ',artist='',title_size=62,x=885,y=910);p.style.show_romaji=False;p.style.show_translation=False
    assert any(uid=='line' and '重叠' in text for uid,text in overlap_issues(p))
    p.song_info['y']=40;assert not overlap_issues(p)
    p.song_info.update(y=910,period='range',start=0,end=500);assert not overlap_issues(p)


def test_metadata_is_one_history_step_and_preserves_line_locks():
    p=sample();p.lines[0].locked=True;p.lines[0].reviewed=True;p.checks={'line':{'reading':True}};history=History(p);before=p.to_dict()
    assert history.apply('改标识',lambda p:p.song_info.update(title='另一个歌名'))
    assert history.project.lines[0].to_dict()==p.lines[0].to_dict() and history.project.checks==p.checks
    assert history.undo() and history.project.to_dict()==before
