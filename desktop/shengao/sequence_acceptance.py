"""Synthetic sequence controls through the real worker and Qt review path."""
import copy
import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialogButtonBox
from studio_backend.model import LyricLine,Unit
from .project import Project,History,save_project,load_project,file_stamp
from .dialogs import ReviewDialog
from .match_range_dialog import MatchRangeDialog


def exercise(app,StudioWindow,out,check,wait,media):
    w=StudioWindow(out/'sequence-home',test=True);w.playback.audio.setMuted(True);w.show()
    def heard(text,start):
        return LyricLine('control-'+str(start),text,start,start+len(text)*200,
            [Unit(c,start+i*200,start+(i+1)*200,source='recognition') for i,c in enumerate(text)]).to_dict()
    try:
        p=Project(title='受控文字顺序验收 · 合成音频，非演唱精度')
        p.lines=[LyricLine('missing','君と歌う',0,1500),LyricLine('anchor','間奏明け',3000,3800,reviewed=True),LyricLine('later','君と歌う',1600,2400)]
        p.transcript=[heard('間奏明け',3000),heard('追加',4200),heard('君と歌う',5000)]
        w.history=History(p);w.current=0;w.refresh();w.load_media(media)
        check('sequence_control_media_ready',wait(lambda:w.analysis_job is None and w.original_audio is not None,20000))
        p=w.project;p.transcript_stamp=file_stamp(p.media);w.history.mark_saved();before=p.to_dict()
        w.start_api('match',transcript=p.transcript)
        check('sequence_real_request_includes_human_context',len(w.api.request['lines'])==3 and w.api.request['lines'][1]['reviewed'])
        check('sequence_real_worker_returns_review',wait(lambda:not w.api.busy and w.pending is not None,15000))
        pending=copy.deepcopy(w.pending);result=pending['result'];values=result['suggestions'];sequence=result['sequence_review']
        check('sequence_omitted_verse_kept_and_later_repeat_resolved',values[0]['match']['status']=='unmatched' and values[0]['start']==0 and values[2]['match']['status']=='matched' and values[2]['start']==5000)
        check('sequence_human_position_retained',values[1]['start']==3000 and values[1]['end']==3800 and values[1]['reviewed'] and values[1]['match']['status']=='protected')
        check('sequence_extra_transcript_is_separate_candidate',any(v['text']=='追加' and v['start']==4200 for v in sequence['unassigned_transcript']))
        check('sequence_matching_is_read_only',w.project.to_dict()==before and not w.history.dirty)
        d=ReviewDialog(w.project,result,w.playback,w);d.resize(760,450);d.show();app.processEvents()
        footer=d.findChild(QDialogButtonBox)
        check('sequence_small_review_footer_reachable',footer.geometry().bottom()<d.height() and footer.isVisible())
        extra=next(i for i in range(d.sequence.selector.count()) if d.sequence.selector.itemData(i)['kind']=='unassigned_transcript')
        d.sequence.selector.setCurrentIndex(extra);d.sequence.listen.click()
        check('sequence_extra_audition_has_context',w.playback.range==(3850,4950));w.playback.stop()
        d.grab().save(str(out/'sequence-review-controls.png'));d.reject()
        def manual():
            dialog=next(d for d in w.findChildren(ReviewDialog) if d.isVisible())
            item=next(i for i in range(dialog.sequence.selector.count()) if dialog.sequence.selector.itemData(i)['kind']=='missing_lyric_candidate')
            dialog.sequence.selector.setCurrentIndex(item);dialog.sequence.manual.click()
        QTimer.singleShot(30,manual);w.review_pending()
        saved=json.loads(next((w.home/'desktop-tasks').glob('*/result.json')).read_text(encoding='utf-8'))
        check('sequence_manual_handoff_retains_task_and_original',w.pending is None and w.line.id=='missing' and w.project.to_dict()==before and saved['sequence_review']==sequence)
        # The later line has a deliberately wrong seed. A selected local range
        # fixes only that line using the same transcript, without a paid call.
        w.current=2;w.refresh()
        def choose():
            dialog=next(d for d in w.findChildren(MatchRangeDialog) if d.isVisible())
            dialog.begin.setValue(4900);dialog.end.setValue(5900);dialog.apply()
        QTimer.singleShot(30,choose);w.local_match()
        check('sequence_local_correction_uses_one_line_and_existing_text',w.api.request['action']=='match' and len(w.api.request['lines'])==1 and w.api.request['match_range']==[4900,5900] and w.api.request['transcript']==p.transcript)
        check('sequence_local_worker_returns',wait(lambda:not w.api.busy and w.pending is not None,15000))
        candidate=copy.deepcopy(w.pending['result']['suggestions'][0]);w.apply_suggestions([candidate])
        check('sequence_local_adoption_preserves_other_lines',w.line.start==5000 and [v.to_dict() for v in w.project.lines[:2]]==before['lines'][:2] and w.project.transcript==before['transcript'])
        target=out/'重复段局部纠正.sgproj';save_project(w.project,target)
        check('sequence_save_roundtrip_retains_text_candidates',load_project(target).to_dict()==w.project.to_dict())
        w.undo();check('sequence_local_correction_one_undo',w.project.to_dict()==before)
        audit={'passed':True,'matching_version':result['matching_version'],'sequence_review':sequence,
            'local_correction':{'input':[1600,2400],'output':[candidate['start'],candidate['end']],'range':[4900,5900]},
            'new_api_calls':0,'human_singing_accuracy':False,
            'interpretation':'Deliberately synthetic text/ASR controls on the generated demo audio. Tests omission, repeats, extra words, human anchors, actual worker, review, manual handoff and local correction. No claim that these words occur in the audio.'}
        (out/'sequence-match-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:w.close();app.processEvents()
