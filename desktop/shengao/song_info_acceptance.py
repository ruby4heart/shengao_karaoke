"""Actual song-credit UI, resources and rendering in dev and frozen runtimes."""
import copy,hashlib,json,subprocess,sys,types
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from studio_backend.model import LyricLine,Unit,Highlight
from .project import Project,History,SCHEMA,save_project,load_project
from .paths import ASSETS,ffmpeg
from .song_info import own_event,event_parts,overlap_issues
from .song_info_dialog import SongInfoDialog
from .fonts import bundled_fonts
from .subtitles import compose
from .subtitle_files import export_subtitle
from .subtitle_import import import_ass
from .encode import encode,EncodeOptions


def exercise(app,StudioWindow,out,check,wait):
    import numpy as np
    out=Path(out);seen={};metrics={};w=StudioWindow(out/'song-info-home',test=True);w.playback.audio.setMuted(True);w.show()
    line=LyricLine('song-info-line','明日へ',1000,5000,[Unit('明日へ',1000,5000,'あしたへ',highlights=[Highlight(k,1000+i*1000,2000+i*1000,'manual') for i,k in enumerate('あしたへ')])],reviewed=True)
    def schedule(fn):
        def invoke():
            d=QApplication.activeModalWidget()
            try:fn(d)
            except Exception as error:
                seen['error']=repr(error)
                if d is not None:d.reject()
        QTimer.singleShot(25,invoke)
    try:
        w.history=History(Project(title='合成练习：歌名与歌手',lines=[line],checks={line.id:{'reading':True}}));w.current=0;w.refresh();w.load_media(ASSETS/'demo/tutorial.mp4',preview=True)
        check('song_info_actual_synthetic_media_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None and not w.playback.canvas.frame.isNull() and not w.playback.preview_pending,25000));w.set_stage(3)
        before=w.project.to_dict();position=w.playback.canvas.position;undo_count=len(w.history.undo_stack)
        def choose(d):
            assert isinstance(d,SongInfoDialog);d.resize(620,520);d.fields['title'].setPlainText('夜色の練習曲');d.fields['artist'].setPlainText('声稿 デモ')
            d.fields['title_size'].setValue(72);d.fields['artist_size'].setValue(46);d.fields['title_color'].setText('#ff3355');d.fields['artist_color'].setText('#73e8bb')
            font=bundled_fonts()[2];d.font.setCurrentIndex(next(i for i in range(d.font.count()) if tuple(d.font.itemData(i))==(font.family,font.path)))
            d.period.setCurrentIndex(d.period.findData('range'));d.fields['start'].setValue(500);d.fields['end'].setValue(6500);d.enabled.setChecked(True);d.preview_time.setValue(2000);d.render_preview();app.processEvents()
            seen['readonly']=w.project.to_dict()==before and w.playback.canvas.position==position
            seen['preview']=d.picture.pixmap() is not None and not d.picture.pixmap().isNull() and d.detail.pixmap() is not None and not d.detail.pixmap().isNull()
            seen['footer']=d.rect().contains(d.buttons.geometry()) and d.scroll.horizontalScrollBar().maximum()==0
            d.scroll.verticalScrollBar().setValue(0);d.grab().save(str(out/'song-info-settings.png'));d.apply.click()
        schedule(choose);applied=w.edit_song_info()
        check('song_info_private_preview_and_footer',seen.get('readonly') and seen.get('preview') and seen.get('footer') and not seen.get('error'))
        check('song_info_actual_controls_adopt_one_edit',applied and w.project.song_info['title']=='夜色の練習曲' and w.project.song_info['artist']=='声稿 デモ' and len(w.history.undo_stack)==undo_count+1)
        check('song_info_lyrics_axis_locks_checks_unchanged',[v.to_dict() for v in w.project.lines]==before['lines'] and w.project.checks==before['checks'])
        events=[v for _,v in event_parts(compose(w.project)) if own_event(v)]
        check('song_info_one_title_one_artist_with_exact_period',len(events)==2 and all(v['Start']=='0:00:00.50' and v['End']=='0:00:06.50' for v in events))
        p=copy.deepcopy(w.project);p.lines=[]
        from .render import AssRenderer
        from .fonts import project_font_files
        renderer=AssRenderer();renderer.add_fonts(project_font_files(p));renderer.set_text(compose(p))
        try:
            before_start=renderer.rgba(640,360,499);visible=renderer.rgba(640,360,500);after_end=renderer.rgba(640,360,6500)
            check('song_info_real_visibility_and_disappearance',not any(before_start[3::4]) and any(visible[3::4]) and not any(after_end[3::4]))
        finally:renderer.close()
        saved=out/'歌名与歌手.sgproj';ass=out/'歌名与歌手.ass';save_project(w.project,saved);export_subtitle(w.project,ass)
        a=load_project(saved);b=load_project(ass)
        check('song_info_project_ass_and_portable_font',SCHEMA==13 and compose(a)==compose(w.project)==compose(b) and Path(a.song_info['font_file']).is_file() and Path(b.song_info['font_file']).is_file())
        output=out/'song-info-sample.mp4';encode(w.project,EncodeOptions(str(output),start=2000,duration=800))
        result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-i',str(output),'-frames:v','1','-f','rawvideo','-pix_fmt','rgba','-'],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        renderer=w.playback.canvas.renderer;renderer.set_text(compose(w.project));rgba=np.frombuffer(renderer.rgba(w.project.width,w.project.height,2000),np.uint8).reshape(w.project.height,w.project.width,4)
        check('song_info_actual_sample_encoded',result.returncode==0 and len(result.stdout)==w.project.width*w.project.height*4)
        actual=np.frombuffer(result.stdout,np.uint8).reshape(w.project.height,w.project.width,4)[:,:,:3].astype(float);mask=rgba[:,:,3]>250;mask[round(w.project.height*.4):]=False
        metrics['core_pixels']=int(mask.sum());metrics['sample_core_rgb_mean_error']=float(np.abs(actual[mask]-rgba[:,:,:3][mask]).mean()) if mask.any() else 999.
        check('song_info_real_sample_matches_live_logo',metrics['core_pixels']>250 and metrics['sample_core_rgb_mean_error']<18)
        w.undo();check('song_info_one_undo_restores_whole_project',w.project.to_dict()==before)
        raw=compose(w.project).replace(r'\bord2.500',r'\blur2\bord2.500');foreign=import_ass(raw);foreign.media=w.project.media;foreign.duration=w.project.duration;foreign.song_info=copy.deepcopy(a.song_info);snapshot=foreign.to_dict();result=compose(foreign)
        check('song_info_foreign_ass_preserves_existing_rows_effects',all(row in result.splitlines() for row in raw.splitlines()) and foreign.source_ass_active and foreign.to_dict()==snapshot)
        check('song_info_foreign_ass_overlay_not_imported_as_lyrics',len(import_ass(result).lines)==len(foreign.lines))
        foreign.style.position='top'
        # Use generated positioning for the actual collision probe.
        collision=copy.deepcopy(w.project);collision.song_info=copy.deepcopy(a.song_info);collision.song_info.update(title='明日へ',artist='',x=880,y=870,title_size=120);collision.style.size=120
        check('song_info_actual_layout_probe_detects_overlap_without_mutation',any(uid==line.id for uid,message in overlap_issues(collision)) and collision.lines[0].to_dict()==w.line.to_dict())
        manifest=json.loads((ASSETS/'compatibility/project-v028-source.json').read_text());legacy=(ASSETS/'compatibility/project-v028.py.txt').read_bytes()
        check('schema13_actual_release_parser_source_fingerprint',manifest['commit']=='14247a440fb7e51a3398f5c2c065565e9f5409a5' and hashlib.sha256(legacy).hexdigest()==manifest['sha256'])
        module=types.ModuleType('shengao._compat_v028_project');module.__package__='shengao';sys.modules[module.__name__]=module
        try:
            exec(compile(legacy,'released-v028-project.py','exec'),module.__dict__);old=module.Project.from_dict({'version':12,'lines':[]});rejected=False
            try:module.Project.from_dict(a.to_dict())
            except ValueError:rejected=True
            check('schema13_actual_v028_parser_reads12_rejects13',module.SCHEMA==12 and old.to_dict()['version']==12 and rejected)
        finally:sys.modules.pop(module.__name__,None)
        (out/'song-info-audit.json').write_text(json.dumps({'passed':True,'metrics':metrics,'media':'bundled synthetic tutorial','paid_api_calls':0,'legacy_parser_commit':manifest['commit'],'interpretation':'Controlled UI, portability, raw ASS preservation and actual encoded sample; not a finished MV or general color accuracy.'},ensure_ascii=False,indent=2),encoding='utf-8')
    finally:w.close();w.deleteLater();app.processEvents()
