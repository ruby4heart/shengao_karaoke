"""Actual Qt, libass and bundled FFmpeg evidence, using synthetic lyrics only."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
from PySide6.QtCore import QTimer,QRect
from PySide6.QtWidgets import QDialogButtonBox
from studio_backend.model import LyricLine,Unit,Highlight
from .color_dialog import ColorDialog
from .color_states import default_profile,effective_profile,update_settings
from .fonts import bundled_fonts
from .paths import ffmpeg
from .project import Project,History,SCHEMA,save_project,load_project
from .subtitles import compose
from .subtitle_files import export_subtitle


def exercise(w,app,out,check):
    import numpy as np
    backup=(w.history,w.current,w.path,w.pending,w.stage,set(w._selected_lyric_ids),w._selection_uid)
    observed={};metrics={};out=Path(out)
    def dialog():return next(d for d in w.findChildren(ColorDialog) if d.isVisible())
    def schedule(fn):
        def safe():
            try:fn(dialog())
            except Exception as error:
                observed['error']=type(error).__name__
                for d in w.findChildren(ColorDialog):
                    if d.isVisible():d.reject()
        QTimer.singleShot(25,safe)
    def count(raw,rgb):
        data=np.frombuffer(raw,np.uint8).reshape(-1,4)
        return int(np.sum(np.all(data[:,:3]==np.array(rgb),axis=1)&(data[:,3]>240)))
    try:
        parts=[Highlight(k,1000+round(1000*i/6),1000+round(1000*(i+1)/6),'manual') for i,k in enumerate(['きょ','う','も','う','た','う'])]
        first=LyricLine('color-a','今日も歌う',1000,2000,[Unit('今日も歌う',1000,2000,kana='きょうもうたう',romaji='kyou mo utau',source='manual',locked=True,highlights=parts)],kana='きょうもうたう',romaji='kyou mo utau',translation='今天也歌唱',locked=True,reviewed=True,display_start=0,display_end=4500)
        second=LyricLine('color-b','明日も歌う',2400,3400,display_start=1500,display_end=5000)
        p=Project(title='三状态配色检查',lines=[first,second],checks={'color-a':{'reading':True}})
        p.style=w.preset_style(3);p.style.display_mode='alternating';p.style.size=120;p.style.ruby_size=42;p.style.outline=2;p.style.shadow=4;p.style.show_romaji=p.style.show_translation=True
        w.history=History(p);w.current=0;w.path=None;w.pending=None;w.refresh();w.set_stage(3)
        w.pages.widget(3).ensureWidgetVisible(w.color_states_button,8,20);app.processEvents()
        check('colors_actual_entry_visible',w.color_states_button.isVisible() and w.color_states_button.visibleRegion().boundingRect().height()==w.color_states_button.height())
        before=w.project.to_dict();position=w.playback.canvas.position
        def configure(d):
            observed['scope']=d.scope.currentData()=='global' and d.role.count()==4 and d.state.count()==3
            d.preset.setCurrentIndex(d.preset.findData('ruby'));d.apply_preset.click()
            for state,fill,outline,shadow,bg in [('waiting','#ff0000','#ff00ff','#ff8000','#202040'),('singing','#00ff00','#00ffff','#8000ff','#203020'),('sung','#ffff00','#0000ff','#ffffff','#302020')]:
                d.state.setCurrentIndex(d.state.findData(state));d.fields['primary'].hex.setText(fill);d.fields['outline'].hex.setText(outline);d.fields['shadow'].hex.setText(shadow)
                d.fields['shadow'].opacity.setValue(100);d.box_color.hex.setText(bg);d.box_color.opacity.setValue(80);d.box_enabled.setChecked(True)
            for role,color in [('ruby','#ff8800'),('romaji','#88ff00'),('translation','#8888ff')]:
                d.role.setCurrentIndex(d.role.findData(role));d.fields['primary'].hex.setText(color);d.fields['shadow'].opacity.setValue(65)
            d.previewRequested.emit('sung');app.processEvents()
            observed['readonly']=w.project.to_dict()==before and w.playback.canvas.position==position
            candidate=d.candidate['global'];observed['layers']=all(len(candidate['layers'][r])==3 for r in ['lyrics','ruby','romaji','translation']) and candidate['box']['enabled'] and candidate['box']['states']['singing']['opacity']==80 and candidate['layers']['translation']['sung']['shadow']['opacity']==65
            buttons=[d.restore,d.reset,d.buttons.button(QDialogButtonBox.StandardButton.Ok),d.buttons.button(QDialogButtonBox.StandardButton.Cancel)]
            observed['footer']=all(d.rect().contains(QRect(b.mapTo(d,b.rect().topLeft()),b.size())) for b in buttons)
            d.grab().save(str(out/'color-state-options.png'));d.accept_changes()
        schedule(configure);w.color_states_button.click()
        check('colors_actual_scope_and_three_states',observed.get('scope') and not observed.get('error'))
        check('colors_live_preview_readonly_and_no_seek',observed.get('readonly'))
        check('colors_all_roles_alpha_and_independent_background',observed.get('layers'))
        after_first=w.project.to_dict()
        check('colors_adoption_preserves_axis_readings_locks_checks',bool(w.project.color_styles) and after_first['lines']==before['lines'] and after_first['checks']==before['checks'] and w.playback.canvas.position==position)
        w.render_subtitles();renderer=w.playback.canvas.renderer
        waiting=renderer.rgba(640,360,520);active=renderer.rgba(640,360,1520);sung=renderer.rgba(640,360,2100)
        metrics['waiting_red']=count(waiting,(255,0,0));metrics['overlap_yellow']=count(sung,(255,255,0));metrics['overlap_red']=count(sung,(255,0,0));metrics['active_green']=count(active,(0,255,0));metrics['active_white']=count(active,(255,255,255))
        (out/'color-pixel-draft.json').write_text(json.dumps({'metrics':metrics,'project':w.project.to_dict()},ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'color-pixel-draft.ass').write_text(compose(w.project),encoding='utf-8-sig')
        from PIL import Image
        Image.frombytes('RGBA',(640,360),waiting).save(out/'colors-waiting.png');Image.frombytes('RGBA',(640,360),active).save(out/'colors-singing.png');Image.frombytes('RGBA',(640,360),sung).save(out/'colors-overlap.png')
        check('colors_real_waiting_and_sung_fill_pixels',metrics['waiting_red']>10 and metrics['overlap_yellow']>10)
        check('colors_two_rows_and_unsegmented_draft_remain_visible',metrics['overlap_red']>10 and metrics['overlap_yellow']>10 and w.project.lines[1].units==[])
        check('colors_real_sweep_and_original_manual_mora',metrics['active_green']>10 and metrics['active_white']>10 and w.project.lines[0].to_dict()['units'][0]['highlights']==before['lines'][0]['units'][0]['highlights'])
        fonts=out/'color-fonts';fonts.mkdir()
        for font in bundled_fonts():shutil.copy2(font.path,fonts/Path(font.path).name)
        (out/'colors.ass').write_text(compose(w.project),encoding='utf-8-sig')
        result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=black:s=640x360:r=25:d=3','-vf','ass=colors.ass:fontsdir=color-fonts','-ss','1.52','-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'],cwd=out,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        expected=np.frombuffer(active,np.uint8).reshape(360,640,4);expected=expected[:,:,:3].astype(np.float32)*expected[:,:,3:4]/255
        actual=np.frombuffer(result.stdout,np.uint8).reshape(360,640,4)[:,:,:3].astype(np.float32) if result.returncode==0 else np.zeros((360,640,3))
        mask=np.max(expected,axis=2)>20;metrics['ffmpeg_mean_rgb_error']=float(np.mean(np.abs(expected[mask]-actual[mask])));metrics['ffmpeg_mask_different_pixels']=int(np.logical_xor(np.max(actual,axis=2)>20,mask).sum())
        check('colors_actual_ffmpeg_matches_live_pixels',result.returncode==0 and mask.sum()>150 and metrics['ffmpeg_mean_rgb_error']<18 and metrics['ffmpeg_mask_different_pixels']<100)
        check('colors_footer_reachable_at_current_scale',observed.get('footer'))
        def local(d):
            d.scope.setCurrentIndex(d.scope.findData('current'));d.state.setCurrentIndex(d.state.findData('sung'));d.fields['primary'].hex.setText('#112233');d.accept_changes()
        schedule(local);w.edit_color_states()
        check('colors_current_override_targets_only_one_line',set(w.project.color_styles['lines'])=={'color-a'} and w.project.color_styles['global']==after_first['color_styles']['global'] and effective_profile(w.project.color_styles,'color-a')['layers']['lyrics']['sung']['primary']['color']=='#112233')
        after_local=w.project.to_dict()
        def quick(d):observed['quick']=d.scope.currentData()=='current' and d.state.currentData()=='singing';d.reject()
        schedule(quick);w.choose_color('highlight')
        check('colors_quick_button_uses_detailed_current_profile',observed.get('quick') and w.project.to_dict()==after_local)
        path=out/'三状态配色.sgproj';save_project(w.project,path);reopened=load_project(path)
        ass=out/'三状态配色.ass';export_subtitle(w.project,ass);imported=load_project(ass)
        portable=all(value.color_styles==w.project.color_styles and [v.to_dict() for v in value.lines]==after_local['lines'] and value.checks==w.project.checks for value in (reopened,imported))
        check('colors_current_schema_save_and_own_ass_reopen',SCHEMA==14 and portable and compose(reopened)==compose(w.project)==compose(imported))
        w.undo();check('colors_local_override_one_undo',w.project.to_dict()==after_first)
        w.undo();schedule(lambda d:d.reject());cancelled=not w.edit_color_states()
        check('colors_global_adoption_one_undo_and_cancel',cancelled and w.project.to_dict()==before)
        late=default_profile(w.project.style);late['layers']['lyrics']['waiting']['primary']['color']='#0000ff'
        def late_edit(d):
            d.fields['primary'].hex.setText('#ff0000');w.edit('验收中的另一次配色修改',lambda p:setattr(p,'color_styles',update_settings({},late)));d.accept_changes()
        schedule(late_edit);accepted=w.edit_color_states()
        protected=not accepted and w.project.color_styles==update_settings({},late);w.undo()
        check('colors_late_change_keeps_current_and_one_undo',protected and w.project.to_dict()==before)
        (out/'color-state-audit.json').write_text(json.dumps({'passed':True,'schema':SCHEMA,'controls':16,'metrics':metrics,'synthetic_lyrics':True,'actual_qt':True,'actual_libass':True,'actual_ffmpeg':True,'new_api_calls':0,'human_timing_accuracy':False},indent=2),encoding='utf-8')
    finally:
        w.history,w.current,w.path,w.pending,stage,selection,selection_uid=backup;w._selected_lyric_ids=selection;w._selection_uid=selection_uid;w.refresh();w.set_stage(stage)
