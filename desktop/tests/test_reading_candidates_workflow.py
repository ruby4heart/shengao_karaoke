import copy
import pytest
from shengao.app import StudioWindow
from shengao.project import History,Project,save_project,load_project
from studio_backend.model import LyricLine,Unit,Highlight


@pytest.fixture
def reading_window(qapp,tmp_path,video):
    w=StudioWindow(tmp_path/'home',test=True);w.playback.audio.setMuted(True)
    parts=[Highlight(k,a,b,'manual') for k,a,b in [('に',1000,1100),('ん',1210,1400),('き',1400,1800)]]
    parts[1].fixed_edges=['start']
    line=LyricLine('line','人気の街',900,3000,[Unit('人気',1000,1800,'にんき',highlights=parts),Unit('の街',1900,3000,'のまち')],reviewed=True)
    w.history=History(Project(media=str(video),duration=6000,lines=[line]));w.project.checks={'line':{'reading':True}}
    w.current=0;w.refresh();w.set_stage(2);w.calibration_tabs.setCurrentIndex(1);w.granularity.setCurrentIndex(w.granularity.findData('words'));w.select_target(0,-1);w.show();qapp.processEvents()
    try:yield w
    finally:w.close();qapp.processEvents()


def select(widget,kana):
    index=widget.choices.findData(kana);assert index>=0;widget.choices.setCurrentIndex(index)


def test_reading_candidates_follow_word_and_confirmation_mode(reading_window):
    w=reading_window;panel=w.reading_candidates;before=w.project.to_dict()
    assert panel.isVisible() and '人気' in panel.title.text() and not panel.apply.isEnabled()
    select(panel,'ひとけ');assert panel.apply.isEnabled() and '保留 3' in panel.change.text()
    assert w.project.to_dict()==before
    w.calibration_tabs.setCurrentIndex(0);assert panel.isHidden()
    w.calibration_tabs.setCurrentIndex(1);w.select_target(1,-1);assert 'の街' in panel.title.text()


def test_chosen_reading_adopts_once_and_undo_restores_confirmation_and_fixed_axis(reading_window):
    w=reading_window;before=w.project.to_dict();select(w.reading_candidates,'ひとけ');w.reading_candidates.apply.click()
    assert w.line.units[0].kana=='ひとけ' and not w.line.reviewed and not w.project.checks['line']['reading']
    assert w.line.units[0].highlights[1].start==1210 and w.line.units[0].highlights[1].fixed_edges==['start']
    assert w.line.to_dict()['units'][1]==before['lines'][0]['units'][1]
    w.undo();assert w.project.to_dict()==before


def test_changed_confirmation_rejects_stale_choice(reading_window):
    w=reading_window;panel=w.reading_candidates;select(panel,'ひとけ');payload={'context':copy.deepcopy(panel.context),'original':copy.deepcopy(panel.data['original']),'word':0,'kana':'ひとけ'}
    w.project.checks['line']['reading']=False;before=w.project.to_dict()
    assert not w.apply_reading_candidate(payload) and w.project.to_dict()==before
    assert '已变化' in w.status.text()


def test_mismatched_media_transcript_is_not_offered(reading_window):
    w=reading_window;w.project.transcript=[LyricLine('asr','はな',1000,1800).to_dict()];w.project.transcript_stamp={'path':'other','size':1,'modified_ns':1};w.refresh_reading_candidates()
    assert '版本不同' in w.reading_candidates.notice.text()
    assert all('transcript' not in c['sources'] for c in w.reading_candidates.data['choices'])


def test_locked_word_disables_adoption_and_listening_uses_original_range(reading_window):
    w=reading_window;w.line.units[0].locked=True;w.refresh_reading_candidates();select(w.reading_candidates,'ひとけ')
    assert not w.reading_candidates.apply.isEnabled() and '锁定' in w.reading_candidates.change.text()
    w.reading_candidates.listen.click();assert w.playback.range==(820,1980)


def test_chosen_reading_evidence_survives_project_save(reading_window,tmp_path):
    w=reading_window;select(w.reading_candidates,'ひとけ');w.reading_candidates.apply.click()
    path=tmp_path/'候选校对.sgproj';save_project(w.project,path);loaded=load_project(path)
    assert loaded.to_dict()==w.project.to_dict()
    assert loaded.lines[0].reading_review['manual_choices'][0]['chosen']=='ひとけ'


def test_neighbor_lock_does_not_block_reading_of_selected_word(reading_window):
    w=reading_window;w.line.units[1].locked=True;w.refresh_reading_candidates();before=w.line.to_dict()['units'][1]
    select(w.reading_candidates,'ひとけ');assert w.reading_candidates.apply.isEnabled();w.reading_candidates.apply.click()
    assert w.line.units[0].kana=='ひとけ' and w.line.to_dict()['units'][1]==before
