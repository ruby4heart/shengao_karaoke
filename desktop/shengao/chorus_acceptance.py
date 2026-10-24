"""Actual slower-repeat inference plus real dialog, worker and adoption QA."""
import copy
import hashlib
import json
import subprocess
import wave
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialogButtonBox,QScrollArea
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.provenance import create
from studio_backend.japanese import romaji
from studio_backend.chorus_workflow import path_for
from .paths import ASSETS,ffmpeg
from .project import Project,History,save_project,load_project
from .chorus_dialog import ChorusDialog
from .dialogs import ReviewDialog


def controlled_project(out):
    reference=json.loads((ASSETS/'alignment-demo/sample.json').read_text(encoding='utf-8'));parts=reference['mora']
    audio=ASSETS/'alignment-demo/pjs056_song.wav';media=out/'chorus-slower-repeat.wav'
    subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(audio),'-filter_complex',
        '[0:a]asplit=2[a][b];[b]atempo=0.8[slow];[a][slow]concat=n=2:v=0:a=1[out]',
        '-map','[out]','-ar','48000','-ac','1','-c:a','pcm_s16le',str(media)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    with wave.open(str(media),'rb') as wav:duration=round(wav.getnframes()*1000/wav.getframerate())
    def kata(text):return ''.join(chr(ord(c)+0x60) if 'ぁ'<=c<='ゖ' else c for c in text)
    units=[]
    for a,b in [(0,4),(4,23),(23,37)]:
        text=''.join(v['kana'] for v in parts[a:b]);kana=kata(text);begin=round(parts[a]['start']);end=round(parts[b-1]['end'])
        highlights=[Highlight(kata(v['kana']),round(v['start']),round(v['end']),'manual',create('manual',round(v['start']),round(v['end']),method='public_human_reference')) for v in parts[a:b]]
        units.append(Unit(text,begin,end,kana,romaji(kana),source='manual',highlights=highlights,reading_source='manual'))
    units[0].locked=True
    source=LyricLine('chorus-source',reference['text'],units[0].start,units[-1].end,units,kana=''.join(u.kana for u in units),romaji=' '.join(u.romaji for u in units),reviewed=True)
    start=16000+round(parts[0]['start']/.8)-150;end=min(duration,16000+round(parts[-1]['end']/.8)+150)
    target=LyricLine('chorus-target',source.text,start,end,[Unit(source.text,start,end,reference['kana'],romaji(reference['kana']),reading_source='dictionary')],translation='保留目标段译文')
    return Project(title='已校对副歌复用 · 公开变速控制',lines=[source,target],checks={source.id:{'reading':True}}),media


def exercise(app,StudioWindow,out,check,wait):
    project,media=controlled_project(out);w=StudioWindow(out/'chorus-home',test=True);w.playback.audio.setMuted(True);w.show()
    try:
        w.history=History(project);w.current=1;w.refresh();w.load_media(media)
        check('chorus_controlled_audio_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000))
        before=w.project.to_dict();w.history.mark_saved();ui=[];w.set_stage(1);w.pages.widget(1).ensureWidgetVisible(w.chorus_button,8,20);app.processEvents()
        entry_visible=w.chorus_button.visibleRegion().boundingRect().height()==w.chorus_button.height()
        def choose():
            d=next(d for d in w.findChildren(ChorusDialog) if d.isVisible());d.resize(760,450);d.audio.setCurrentIndex(d.audio.findData('original'));app.processEvents()
            d.findChild(QScrollArea).ensureWidgetVisible(d.voice);app.processEvents();footer=d.findChild(QDialogButtonBox)
            ui.append(d.voice.isChecked() and d.selected_ids()==['chorus-target'] and footer.geometry().bottom()<d.height())
            d.grab().save(str(out/'chorus-reuse-options.png'));d.apply.click()
        QTimer.singleShot(30,choose);w.chorus_button.click()
        check('chorus_actual_options_explicit_target_and_footer',entry_visible and ui==[True] and w.api.busy)
        check('chorus_new_request_keeps_source_and_neighbors',len(w.api.request['lines'])==1 and len(w.api.request['neighbor_lines'])==2 and w.api.request['source_line']['reviewed'])
        check('chorus_actual_worker_and_tifa_complete',wait(lambda:not w.api.busy and w.pending is not None,90000))
        result=copy.deepcopy(w.pending['result']);value=LyricLine.from_dict(result['suggestions'][0]);parts=[h for u in value.units for h in u.highlights]
        check('chorus_new_audio_one_model_and_37_mora',not result['partial'] and result['acoustic']['aligned']==1 and result['acoustic']['model_loads']==1 and len(parts)==37 and all(h.source=='acoustic' for h in parts))
        check('chorus_slower_repeat_is_not_source_axis',all(h.start>=16000 for h in parts) and value.end-value.start>1.1*(project.lines[0].end-project.lines[0].start))
        check('chorus_source_grouping_katakana_romaji_kept',[u.text for u in value.units]==[u.text for u in project.lines[0].units] and value.kana==project.lines[0].kana and value.romaji==project.lines[0].romaji)
        check('chorus_target_translation_and_source_locks_separate',value.translation==before['lines'][1]['translation'] and not any(u.locked for u in value.units))
        check('chorus_proposals_never_edit_or_confirm',w.project.to_dict()==before and not value.reviewed and not w.history.dirty)
        dialog=ReviewDialog(w.project,result,w.playback,w);dialog.show();app.processEvents();dialog.grab().save(str(out/'chorus-reuse-review.png'));dialog.reject()
        w.edit('验收：来源版本变更',lambda p:setattr(p.lines[0],'translation','临时来源变更'))
        w.apply_suggestions(result['suggestions'])
        check('chorus_late_source_version_blocks_adoption',w.pending is not None and w.project.lines[1].to_dict()==before['lines'][1])
        w.undo();check('chorus_revert_source_restores_exact_snapshot',w.project.to_dict()==before)
        w.apply_suggestions(result['suggestions'])
        check('chorus_adoption_keeps_source_and_original_media',w.pending is None and w.project.lines[0].to_dict()==before['lines'][0] and w.project.media==str(media))
        check('chorus_new_target_still_requires_confirmation',not w.project.lines[1].reviewed and not w.project.checks['chorus-target']['reading'])
        target=out/'已校对副歌复用.sgproj';save_project(w.project,target)
        check('chorus_project_roundtrip_keeps_new_audio_evidence',load_project(target).to_dict()==w.project.to_dict())
        w.undo();check('chorus_adoption_is_one_undo',w.project.to_dict()==before)
        uid=result['chorus_workflow']['id'];checkpoint=path_for(w.home,uid);modified=checkpoint.stat().st_mtime_ns
        w.resume_chorus_workflow(uid)
        check('chorus_completed_workflow_resumes_without_model',wait(lambda:not w.api.busy and w.pending is not None,15000) and checkpoint.stat().st_mtime_ns==modified and w.pending['result']['suggestions']==result['suggestions'])
        report={'passed':True,'real_acoustic_mora':37,'source_range':[project.lines[0].start,project.lines[0].end],
            'target_range':[value.start,value.end],'model_loads':1,'source_sha256':result['acoustic']['source_sha256'],
            'new_api_calls':0,'source_times_copied':False,'target_human_timing_reference':False,
            'interpretation':'PJS056 CC BY-SA 4.0 original plus a controlled atempo=0.8 repeat. Source uses existing public human labels; the repeat has no independent human annotation. Real target TIFA, Qt dialog, worker, immutable source, adoption, save, undo and checkpoint reuse; not general accuracy.'}
        (out/'chorus-reuse-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:w.close();app.processEvents()
