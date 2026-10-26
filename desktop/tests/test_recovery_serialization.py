import json
import pytest
from studio_backend.settings import atomic_json
from test_reading_candidates_workflow import reading_window


def test_compact_atomic_json_preserves_unicode_values_and_rejects_partial_failure(tmp_path):
    path=tmp_path/'自动恢复.json';value={'歌词':'明日も歌う','时间':[0,1234],'审核':{'已确认':True}}
    atomic_json(path,value,compact=True);before=path.read_bytes()
    assert json.loads(before)==value and b'\n' not in before
    with pytest.raises(ValueError):atomic_json(path,{'invalid':float('nan')},compact=True)
    assert path.read_bytes()==before and not list(tmp_path.glob('*.tmp'))


def test_recovery_keeps_entire_project_pending_task_and_saved_cleanup(reading_window):
    w=reading_window;w.pending={'result':{'suggestions':[],'message':'保留的审核'},'context':{'uid':w.project.uid}};before=w.project.to_dict();w.save_recovery()
    raw=w.recovery_path().read_bytes();record=json.loads(raw)
    assert record['project']==before and record['pending']==w.pending and b'\n' not in raw and w.project.to_dict()==before
    w.pending=None;w.history.mark_saved();w.save_recovery();assert not w.recovery_path().exists()
