"""Real bundled-model / public human-reference acceptance in our own Qt view."""
import copy
import json
from pathlib import Path
from .paths import ASSETS
from .project import Project,History,save_project,load_project
from .dialogs import ReviewDialog
from studio_backend.model import LyricLine,Unit,Highlight

def exercise(app,StudioWindow,out,check,wait):
    reference=json.loads((ASSETS/'alignment-demo/sample.json').read_text(encoding='utf-8'))
    duration=reference['duration'];text=reference['text'];kana=reference['kana'];anchor=5;parts=reference['mora'];fixed=parts[anchor]
    a=round(fixed['start']);b=round(fixed['end']);highlights=[]
    for i,m in enumerate(parts):
        start=round(a*i/anchor) if i<anchor else a if i==anchor else b+round((duration-b)*(i-anchor-1)/(len(parts)-anchor-1))
        end=round(a*(i+1)/anchor) if i<anchor else b if i==anchor else b+round((duration-b)*(i-anchor)/(len(parts)-anchor-1))
        highlights.append(Highlight(m['kana'],start,end,'manual' if i==anchor else 'estimated'))
    line=LyricLine('pjs056',text,0,duration,[Unit(text,0,duration,kana,highlights=highlights)],kana=kana)
    w=StudioWindow(out/'acoustic-home',test=True);w.playback.audio.setMuted(True);w.show()
    try:
        w.history=History(Project(lines=[line],checks={line.id:{'reading':True}}));w.current=0;w.refresh()
        w.load_media(ASSETS/'alignment-demo/pjs056_song.wav')
        check('public_singing_sample_loads',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000))
        w.set_stage(2);before=w.project.to_dict();w.acoustic_button.click()
        check('acoustic_action_starts_without_editing_axis',w.source_job is not None and w.project.to_dict()==before)
        check('actual_tifa_inference_returns_in_frozen_or_dev',wait(lambda:w.source_job is None and w.pending is not None,90000))
        check('acoustic_results_require_review',w.project.to_dict()==before and w.acoustic_review.isVisible())
        result=w.pending['result'];candidate=result['suggestions'][0];new=candidate['units'][0]['highlights']
        check('acoustic_manual_anchor_and_readings_kept',new[anchor]==before['lines'][0]['units'][0]['highlights'][anchor] and candidate['text']==text and candidate['kana']==kana)
        check('acoustic_real_model_digest_and_evidence',candidate['timing_evidence']['model_sha256']=='8d9bf896da1827f36bf135f80c7ab1fc4f3c1d48f328818b8402c9527c0f014b' and len(candidate['timing_evidence']['runs'])==2)
        errors=[{'kana':h['kana'],'start':h['start'],'end':h['end'],'reference_start':m['start'],'reference_end':m['end'],'onset_error_ms':h['start']-m['start'],'offset_error_ms':h['end']-m['end'],'manual_anchor':i==anchor} for i,(h,m) in enumerate(zip(new,parts))]
        onset=sorted(abs(e['onset_error_ms']) for e in errors if not e['manual_anchor']);offset=sorted(abs(e['offset_error_ms']) for e in errors if not e['manual_anchor'])
        metrics={'count':len(onset),'onset_mean_ms':sum(onset)/len(onset),'onset_median_ms':onset[len(onset)//2],'onset_max_ms':max(onset),'offset_mean_ms':sum(offset)/len(offset),'offset_max_ms':max(offset),'errors':errors,'reference':reference,'interpretation':'One public sample only; training overlap unknown. Human label grouping and the shipped kana adapter are used. The one human anchor is excluded from error statistics. Not user-MV ground truth or general accuracy.'}
        (out/'acoustic-human-reference.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
        check('acoustic_sample_mora_count_and_bounded_reference_error',len(new)==len(parts) and len(onset)==36 and metrics['onset_median_ms']<100 and metrics['onset_max_ms']<250)
        dialog=ReviewDialog(w.project,result,w.playback,w);dialog.show();app.processEvents()
        check('acoustic_review_compares_each_mora_and_auditions',dialog.acoustic_mora.count()==len(parts) and not dialog.apply_button.isEnabled() and '人工固定' in dialog.details.toPlainText())
        dialog.acoustic_listen.click()
        check('acoustic_review_plays_actual_mora_with_context',w.playback.range==(max(0,new[0]['start']-120),new[0]['end']+120) and w.playback.audio.isMuted())
        dialog.grab().save(str(out/'acoustic-review.png'));dialog.check_all(True);w.apply_suggestions(dialog.selected());dialog.reject()
        check('acoustic_adoption_keeps_reading_confirmation_and_needs_time_review',w.project.checks[line.id]['reading'] and not w.line.reviewed and not w.pending)
        w.playback.seek(6200);app.processEvents();w.grab().save(str(out/'acoustic-axis.png'))
        target=out/'歌声音节工程.sgproj';save_project(w.project,target)
        check('acoustic_evidence_saves_and_reopens',load_project(target).to_dict()==w.project.to_dict())
        w.undo();check('acoustic_adoption_one_undo',w.project.to_dict()==before)
    finally:w.close();app.processEvents()
