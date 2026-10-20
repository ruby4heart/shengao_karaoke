import copy
from shengao.app import StudioWindow
from shengao.project import History
from shengao.dialogs import ReviewDialog

def test_candidate_review_is_local_and_preserves_recommendation_until_accept(qapp,tmp_path,project):
    w=StudioWindow(home=tmp_path/'home',test=True);w.history=History(project);w.current=0;w.playback.audio.setMuted(True)
    value=copy.deepcopy(project.lines[0].to_dict());candidate=copy.deepcopy(value)
    candidate['start']+=6000;candidate['end']+=6000
    for u in candidate['units']:
        u['start']+=6000;u['end']+=6000
        for h in u.get('highlights',[]):h['start']+=6000;h['end']+=6000
    value['match']={'status':'matched','score':.8,'coverage':1.,'recognized':'今日も歌う','reason':'文字及读音比较','candidates':[{**candidate,'score':.9,'coverage':1.,'recognized':'今日も歌う','method':'text'}]}
    value['reading_review']={'notice':'转录仅作为读音依据，需要试听','words':[{'text':'今日','before':'きょう','suggested':'きょう','basis':'transcript','reason':'同一时段的假名识别'}]}
    result={'suggestions':[value]};original=copy.deepcopy(result);dialog=ReviewDialog(project,result,w.playback,w)
    assert '当前读音' in dialog.details.toPlainText() and '同一时段' in dialog.details.toPlainText()
    assert not dialog.apply_button.isEnabled();dialog.check_all(True);assert dialog.apply_button.isEnabled()
    dialog.candidates.setCurrentIndex(1);assert dialog.selected()[0]['start']==7000
    assert result==original
    dialog.reject();assert w.project.lines[0].start==1000;assert not w.api.busy
    w.close();qapp.processEvents()


def test_legacy_v018_snapshots_adopt_without_false_manual_conflict(qapp,tmp_path):
    import json
    from pathlib import Path
    from shengao.project import Project
    fixture=Path(__file__).resolve().parents[2]/'backend/tests/fixtures/v018-offline-draft-state.json'
    state=json.loads(fixture.read_text(encoding='utf-8'));request=state['request'];rows=request['lines']
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    w.history=History(Project.from_dict({'version':6,'lines':rows}));w.current=0;w.refresh();before=w.project.to_dict()
    suggestions=next(s['result']['suggestions'] for s in reversed(state['stages']) if s.get('result',{}).get('suggestions'))
    w.pending={'action':'draft','result':{'suggestions':copy.deepcopy(suggestions)},'snapshots':{r['id']:r for r in rows}}
    w.apply_suggestions(suggestions)
    assert w.pending is None and all(line.units for line in w.project.lines)
    w.undo();assert w.project.to_dict()==before;w.close()
