import copy
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QDialogButtonBox
from shengao.app import StudioWindow
from shengao.dialogs import ReviewDialog
from shengao.match_range_dialog import MatchRangeDialog
from shengao.project import Project,History
from studio_backend.model import LyricLine,Unit
from studio_backend.matching import match_lyrics


def fixture():
    lines=[LyricLine('first','君と歌う',0,5000),LyricLine('bridge','間奏明け',5000,10000),LyricLine('last','君と歌う',10000,15000)]
    def heard(text,start):
        return LyricLine('asr-'+str(start),text,start,start+len(text)*200,
                         [Unit(c,start+i*200,start+(i+1)*200,source='recognition') for i,c in enumerate(text)])
    transcript=[heard('間奏明け',10000),heard('どこまでも',13000),heard('君と歌う',15000)]
    project=Project();project.lines=lines;project.duration=20000;project.transcript=[v.to_dict() for v in transcript]
    return project,match_lyrics(lines,transcript)


def test_sequence_review_auditions_extra_and_hands_off_without_adopting(qapp,tmp_path,monkeypatch):
    project,result=fixture();w=StudioWindow(tmp_path/'home',test=True);w.history=History(project);w.current=0;w.refresh()
    before=w.project.to_dict();original=copy.deepcopy(result);calls=[]
    monkeypatch.setattr(w.playback,'audition',lambda *args:calls.append(args))
    d=ReviewDialog(project,result,w.playback,w);seq=d.sequence
    extra=next(i for i in range(seq.selector.count()) if seq.selector.itemData(i)['kind']=='unassigned_transcript')
    seq.selector.setCurrentIndex(extra);seq.listen.click()
    assert calls and calls[0][0]<=13000 and 14000<=calls[0][1] and calls[0][1]-calls[0][0]<=12000
    assert not d.apply_button.isEnabled() and all(d.table.item(i,0).checkState()==Qt.CheckState.Unchecked for i in range(d.table.rowCount()))
    target=seq.target();seq.manual.click()
    assert d.manual_uid==target and not d.rematch_uid and QDialog.result(d)==QDialog.DialogCode.Rejected
    assert w.project.to_dict()==before and result==original;w.close()


def test_correct_range_handoff_saves_previous_result_then_matches_only_that_line(qapp,tmp_path,monkeypatch):
    project,result=fixture();w=StudioWindow(tmp_path/'home',test=True);w.history=History(project);w.current=2;w.refresh();before=w.project.to_dict()
    w.pending={'action':'match','result':result,'snapshots':{v.id:v.to_dict() for v in project.lines},'context':{}}
    def review(d):
        index=next(i for i in range(d.sequence.selector.count()) if d.sequence.selector.itemData(i)['kind']=='missing_lyric_candidate')
        d.sequence.selector.setCurrentIndex(index);d.sequence.rematch.click();return QDialog.DialogCode.Rejected
    def choose_range(d):
        d.begin.setValue(14000);d.end.setValue(17000);d.apply();return QDialog.DialogCode.Accepted
    calls=[];monkeypatch.setattr(ReviewDialog,'exec',review);monkeypatch.setattr(MatchRangeDialog,'exec',choose_range)
    monkeypatch.setattr(w,'start_api',lambda action,**kwargs:calls.append((action,kwargs)))
    w.review_pending()
    assert len(calls)==1 and calls[0][0]=='match' and calls[0][1]['line_ids']==['first']
    assert calls[0][1]['match_range']==[14000,17000] and calls[0][1]['transcript']==project.transcript
    assert calls[0][1]['rematch_confirmed'] and w.pending is None and w.line.id=='first' and w.project.to_dict()==before
    saved=json.loads(next((w.home/'desktop-tasks').glob('*/result.json')).read_text(encoding='utf-8'))
    assert saved['sequence_review']==result['sequence_review'] and saved['suggestions']==result['suggestions'];w.close()


def test_small_review_window_keeps_footer_reachable_and_body_scrollable(qapp,tmp_path):
    project,result=fixture();w=StudioWindow(tmp_path/'home',test=True)
    d=ReviewDialog(project,result,w.playback,w);d.resize(700,430);d.show();qapp.processEvents()
    buttons=d.findChild(QDialogButtonBox)
    assert buttons.isVisible() and buttons.geometry().bottom()<d.height() and d.sequence.rematch.isEnabled()
    from PySide6.QtWidgets import QScrollArea
    assert d.findChild(QScrollArea).verticalScrollBar().maximum()>0
    d.reject();w.close()


def test_selecting_alternative_retains_its_timing_origin_and_source_mapping(qapp,tmp_path):
    project=Project();project.lines=[LyricLine('line','君と歌う',0,5000)]
    source=[LyricLine('a','君と歌う',1000,2000),LyricLine('b','君と歌う',15000,16000)]
    result=match_lyrics(project.lines,source);w=StudioWindow(tmp_path/'home',test=True)
    d=ReviewDialog(project,result,w.playback,w);d.candidates.setCurrentIndex(2)
    value=d.values[0];choice=result['suggestions'][0]['match']['candidates'][1]
    assert value['start']==15000 and value['timing_origin']==choice['timing_origin']
    assert value['match']['source_spans']==choice['source_spans'] and value['match']['status']=='uncertain'
    assert not value['reviewed'] and result['suggestions'][0]['start']!=15000
    d.reject();w.close()


def test_whole_song_request_retains_confirmed_context_and_review_cannot_select_it(qapp,tmp_path,monkeypatch):
    project,result=fixture();project.lines[1].reviewed=True
    project.lines[1].start=10000;project.lines[1].end=10800
    w=StudioWindow(tmp_path/'home',test=True);w.history=History(project);w.current=0;w.refresh();requests=[]
    monkeypatch.setattr(w.api,'start',lambda request:requests.append(copy.deepcopy(request)))
    w.start_api('match',transcript=project.transcript)
    assert len(requests)==1 and [v['id'] for v in requests[0]['lines']]==['first','bridge','last']
    assert requests[0]['lines'][1]['reviewed']
    actual=match_lyrics([LyricLine.from_dict(v) for v in requests[0]['lines']],[LyricLine.from_dict(v) for v in project.transcript])
    assert actual['suggestions'][0]['match']['status']=='unmatched'
    d=ReviewDialog(project,actual,w.playback,w);d.check_all(True)
    assert 'bridge' not in [v['id'] for v in d.selected()] and not d.table.item(1,0).flags()&Qt.ItemFlag.ItemIsUserCheckable
    d.reject();w.close()
