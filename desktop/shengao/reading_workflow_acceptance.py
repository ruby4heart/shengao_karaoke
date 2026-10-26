"""Actual six-part editing workflow; synthetic lyrics, no cloud calls."""
import copy,json,shutil,subprocess
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QFileDialog,QDialogButtonBox
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.reading_dictionary import put
from studio_backend.convert import annotation_suggestion
from studio_backend.translation import info
from .project import Project,History,SCHEMA,save_project,load_project
from .paths import ASSETS,ffmpeg
from .reading_dictionary_dialog import DictionaryDialog
from .ruby_dialog import RubyDialog
from .romanization_dialog import RomanizationDialog
from .tail_dialog import TailDialog
from .dialogs import ReviewDialog
from .subtitle_files import export_subtitle
from .subtitles import compose
from .fonts import bundled_fonts


def exercise(app,StudioWindow,out,check,wait):
    import numpy as np
    from PIL import Image
    out=Path(out);observed={};metrics={}
    first=LyricLine('reading-axis','人気',900,2300,[Unit('人気',1000,1800,'にんき','ninki',highlights=[Highlight('に',1000,1100,'manual'),Highlight('ん',1210,1400,'manual',fixed_edges=['start']),Highlight('き',1400,1800,'manual')],reading_source='dictionary')],reviewed=True)
    star=LyricLine('reading-star','お星様',3000,5500,[Unit('お星様',3000,5500,'おほしさま','ohoshisama',highlights=[Highlight(k,3000+i*500,3500+i*500,'manual') for i,k in enumerate('おほしさま')],reading_source='dictionary')],reviewed=True)
    w=StudioWindow(out/'reading-workflow-home',test=True);w.playback.audio.setMuted(True);w.show()
    def schedule(fn):
        def invoke():
            dialog=QApplication.activeModalWidget()
            try:fn(dialog)
            except Exception as error:
                observed['error']=repr(error)
                if dialog is not None:dialog.reject()
        QTimer.singleShot(25,invoke)
    def same_axis(a,b):
        return (a.start,a.end,[(u.start,u.end,[(h.start,h.end,h.fixed_edges) for h in u.highlights]) for u in a.units])==(b.start,b.end,[(u.start,u.end,[(h.start,h.end,h.fixed_edges) for h in u.highlights]) for u in b.units])
    def select(row):
        w.current=row;w.refresh();w.set_stage(2);w.calibration_tabs.setCurrentIndex(1);w.granularity.setCurrentIndex(w.granularity.findData('words'));w.select_target(0,-1);app.processEvents()
    try:
        w.history=History(Project(title='合成练习：日语读音完整校对',lines=[first,star],checks={x.id:{'reading':True} for x in [first,star]}));w.current=0;w.refresh();w.load_media(ASSETS/'demo/tutorial.mp4')
        check('reading_workflow_actual_media_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000));w.project.style.show_romaji=True;w.project.style.show_translation=True;select(0)
        before=w.project.to_dict();remembered=w.remember_current_reading('song')
        check('reading_dictionary_song_entry_keeps_axes_and_confirmations',remembered and w.project.reading_dictionary['entries'][0]['kana']=='にんき' and w.project.to_dict()['lines']==before['lines'] and w.project.checks==before['checks'])
        w.undo();check('reading_dictionary_song_entry_one_undo',w.project.to_dict()==before);w.redo()
        before=w.project.to_dict();remembered=w.remember_current_reading('personal')
        check('reading_dictionary_personal_does_not_enter_project',remembered and w.project.to_dict()==before and w.reading_dictionary_store.read()['entries'][0]['text']=='人気')
        check('reading_dictionary_personal_separate_undo',w.undo_personal_dictionary() and w.reading_dictionary_store.read()=={} and w.project.to_dict()==before)
        incoming=out/'reading-dictionary-import.json';exported=out/'reading-dictionary-export.json';incoming.write_text(json.dumps(put({},'星','せかい','合成練習用の特殊唱法'),ensure_ascii=False),encoding='utf-8')
        def dictionary(d):
            assert isinstance(d,DictionaryDialog)
            original_open,original_save=QFileDialog.getOpenFileName,QFileDialog.getSaveFileName
            try:
                QFileDialog.getOpenFileName=lambda *a,**k:(str(incoming),'json');d.import_button.click()
                QFileDialog.getSaveFileName=lambda *a,**k:(str(exported),'json');d.export_button.click()
            finally:QFileDialog.getOpenFileName,QFileDialog.getSaveFileName=original_open,original_save
            observed['dictionary_draft']=d.collect();observed['dictionary_unapplied']=w.project.to_dict()==before;d.grab().save(str(out/'reading-dictionary-options.png'));d.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        schedule(dictionary);changed=w.manage_reading_dictionary('song')
        check('reading_dictionary_actual_import_export_and_explicit_save',changed and not observed.get('error') and observed.get('dictionary_unapplied') and len(w.project.reading_dictionary['entries'])==2 and json.loads(exported.read_text(encoding='utf-8'))==w.project.reading_dictionary)
        before=w.project.to_dict();schedule(lambda d:d.reject());changed=w.manage_reading_dictionary('song')
        check('reading_dictionary_cancel_keeps_saved_project',not changed and w.project.to_dict()==before)
        select(1);before=w.project.to_dict();position=w.playback.canvas.position
        def ruby(d):
            assert isinstance(d,RubyDialog);d.mode.setCurrentIndex(d.mode.findData('custom'));d.table.setCurrentCell(0,0)
            for field,value in zip(d.fields,[2,2,2,3]):field.setValue(value)
            d.update.click()
            for field,value in zip(d.fields,[3,3,4,5]):field.setValue(value)
            d.add.click();d.render_preview();observed['ruby_actual_frame']=not d.picture.pixmap().isNull();observed['ruby_unapplied']=w.project.to_dict()==before and w.playback.canvas.position==position;d.grab().save(str(out/'reading-ruby-correspondence.png'));d.apply.click()
        schedule(ruby);changed=w.edit_ruby_correspondence()
        check('reading_ruby_actual_character_range_controls_and_preview',changed and not observed.get('error') and observed.get('ruby_actual_frame') and observed.get('ruby_unapplied') and w.line.units[0].reading_options['ruby']['spans']==[[1,2,1,3],[2,3,3,5]])
        check('reading_ruby_visual_only_keeps_axis_and_checks',same_axis(star,w.line) and w.line.reviewed and w.project.checks[star.id]['reading'])
        w.undo();check('reading_ruby_one_undo_restores_entire_project',w.project.to_dict()==before);w.redo();select(1)
        before=w.project.to_dict()
        def automatic(d):
            assert isinstance(d,RomanizationDialog);d.mode.setCurrentIndex(d.mode.findData('auto'));d.system.setCurrentIndex(d.system.findData('kunrei'));d.default.setChecked(True);d.grab().save(str(out/'reading-romanization-options.png'));d.apply.click()
        schedule(automatic);changed=w.edit_romanization()
        check('reading_roman_actual_rule_and_explicit_new_word_default',changed and w.line.units[0].romaji=='ohosisama' and w.project.reading_preferences['romaji']['system']=='kunrei')
        check('reading_roman_display_only_keeps_kana_axis_and_checks',w.line.units[0].kana=='おほしさま' and same_axis(star,w.line) and w.line.reviewed and w.project.checks[star.id]['reading'])
        w.undo();check('reading_roman_rules_and_default_are_one_undo',w.project.to_dict()==before);w.redo();select(1)
        def handwrite(d):d.mode.setCurrentIndex(d.mode.findData('manual'));d.manual.setText('OHOSHI-SAMA');d.apply.click()
        schedule(handwrite);changed=w.edit_romanization()
        check('reading_roman_manual_override_has_visible_source',changed and w.line.units[0].romaji=='OHOSHI-SAMA' and w.line.units[0].reading_options['romaji']['mode']=='manual' and '手写' in w.reading_candidates.romanization_state.text())
        before=w.project.to_dict();w.translation.setText('星光'*100);w.edit_translation()
        check('reading_translation_actual_manual_input_and_width_warning',info(w.line)['source']=='manual' and '较长' in w.translation_length.text() and same_axis(star,w.line) and w.project.checks[star.id]['reading'])
        w.undo();check('reading_translation_one_undo_keeps_roman_and_ruby',w.project.to_dict()==before)
        w.translation.setText('与星光作伴');w.edit_translation();w.translation_confirm.setChecked(True)
        check('reading_translation_confirmation_is_independent',info(w.line)['confirmed'] and w.line.reviewed and w.project.checks[star.id]['reading'])
        before=w.project.to_dict();annotation={'groups':[{'text':u.text,'kana':u.kana,'romaji':'untrusted-model-spelling'} for u in w.line.units],'translation':'AI 的星光译文候选'}
        candidate=annotation_suggestion(w.line,annotation,w.project.reading_preferences['romaji'])
        w.pending={'action':'annotate','folder':str(out/'reading-text-suggestion-task'),'result':{'suggestions':[candidate.to_dict()]},'snapshots':{w.line.id:w.line.to_dict()},'checks':copy.deepcopy(w.project.checks)}
        def review(d):
            assert isinstance(d,ReviewDialog);d.check_all(True);observed['review_selected']=len(d.selected())==1;d.grab().save(str(out/'reading-text-only-review.png'));d.accept()
        schedule(review);w.review_pending()
        check('reading_text_native_review_keeps_manual_translation_and_timing',not w.pending and observed.get('review_selected') and w.line.translation=='与星光作伴' and w.line.reading_review['translation_suggestion']['text']==annotation['translation'] and w.line.reviewed and w.project.checks[star.id]['reading'])
        check('reading_text_native_review_keeps_manual_roman_and_ruby',w.line.units[0].romaji=='OHOSHI-SAMA' and w.line.units[0].reading_options==before['lines'][1]['units'][0]['reading_options'])
        before=w.project.to_dict();check('reading_translation_saved_draft_adoption',w.accept_translation() and w.line.translation==annotation['translation'] and not info(w.line)['confirmed'] and w.line.reviewed and w.project.checks[star.id]['reading']);w.undo()
        check('reading_translation_saved_draft_one_undo',w.project.to_dict()==before)
        select(0);before=w.project.to_dict();annotation={'groups':[{'text':'人気','kana':'ひとけ','romaji':'model'}],'translation':'人影'};candidate=annotation_suggestion(w.line,annotation,w.project.reading_preferences['romaji']).to_dict();bad=copy.deepcopy(candidate);bad['units'][0]['highlights'][1]['start']+=10
        w.pending={'action':'annotate','result':{'suggestions':[bad]},'snapshots':{w.line.id:w.line.to_dict()},'checks':copy.deepcopy(w.project.checks)};w.apply_suggestions([bad])
        check('reading_text_forged_time_is_rejected_and_result_retained',w.pending is not None and w.project.to_dict()==before and '固定边界' in w.status.text())
        w.pending['result']['suggestions']=[candidate];w.apply_suggestions([candidate])
        check('reading_text_valid_reading_keeps_real_manual_and_fixed_axis',not w.pending and w.line.units[0].kana=='ひとけ' and same_axis(first,w.line) and not w.project.checks[first.id]['reading'])
        from studio_backend.romanization import set_manual
        w.edit('受控工程中明确手写罗马音',lambda p:p.lines.__setitem__(0,set_manual(p.lines[0],0,'HI-TO-KE')));select(0);before=w.project.to_dict()
        def tail(d):
            assert isinstance(d,TailDialog);d.combo.setCurrentIndex(d.combo.count()-1);d.reading.setText('き');d.apply_reading();d.accept_changes()
        schedule(tail);w.inspect_tail()
        check('reading_legacy_tail_manual_roman_kept',w.line.units[0].kana=='ひとき' and w.line.units[0].romaji=='HI-TO-KE' and w.line.units[0].reading_options['romaji']['basis']=='ひとけ' and same_axis(first,w.line))
        w.undo();check('reading_legacy_tail_one_undo',w.project.to_dict()==before)
        target=out/'日语读音完整校对.sgproj';ass=out/'日语读音完整校对.ass';save_project(w.project,target);export_subtitle(w.project,ass);reopened=load_project(target);imported=load_project(ass)
        check('reading_workflow_current_schema_project_and_own_ass_roundtrip',SCHEMA==14 and reopened.to_dict()==w.project.to_dict() and compose(imported)==compose(w.project) and imported.reading_dictionary==w.project.reading_dictionary and imported.reading_preferences==w.project.reading_preferences)
        select(1);w.show_editor_widget(w.reading_candidates.apply);w.grab().save(str(out/'reading-workflow-inline.png'));w.render_subtitles();active=w.playback.canvas.renderer.rgba(640,360,4020);Image.frombytes('RGBA',(640,360),active).save(out/'reading-workflow-subtitles.png')
        fonts=out/'reading-workflow-fonts';fonts.mkdir()
        for font in bundled_fonts():shutil.copy2(font.path,fonts/Path(font.path).name)
        (out/'reading-workflow.ass').write_text(compose(w.project),encoding='utf-8-sig')
        result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=black:s=640x360:r=25:d=5','-vf','ass=reading-workflow.ass:fontsdir=reading-workflow-fonts','-ss','4.02','-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'],cwd=out,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        expected=np.frombuffer(active,np.uint8).reshape(360,640,4);expected=expected[:,:,:3].astype(np.float32)*expected[:,:,3:4]/255;actual=np.frombuffer(result.stdout,np.uint8).reshape(360,640,4)[:,:,:3].astype(np.float32) if result.returncode==0 else np.zeros((360,640,3));mask=np.max(expected,axis=2)>20
        metrics={'subtitle_pixels':int(mask.sum()),'ffmpeg_mean_rgb_error':float(np.mean(np.abs(expected[mask]-actual[mask]))),'ffmpeg_mask_different_pixels':int(np.logical_xor(np.max(actual,axis=2)>20,mask).sum())}
        check('reading_workflow_actual_ruby_roman_translation_ffmpeg_matches_preview',result.returncode==0 and metrics['subtitle_pixels']>150 and metrics['ffmpeg_mean_rgb_error']<18 and metrics['ffmpeg_mask_different_pixels']<150)
        (out/'reading-workflow-audit.json').write_text(json.dumps({'passed':True,'schema':SCHEMA,'actual_qt':True,'actual_libass':True,'actual_ffmpeg':True,'synthetic_lyrics':True,'audio_source':'bundled synthetic tutorial.mp4','new_api_calls':0,'text_model_response':'controlled local fixture, not a service compatibility claim','human_singing_accuracy':False,'metrics':metrics,'goals':['4.1','4.2','4.3','4.4','4.5','4.8']},ensure_ascii=False,indent=2),encoding='utf-8')
    finally:w.close();app.processEvents()
