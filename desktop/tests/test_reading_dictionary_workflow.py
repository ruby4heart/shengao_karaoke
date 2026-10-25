import copy,json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QFileDialog
from studio_backend.reading_dictionary import put
from shengao.reading_dictionary_dialog import DictionaryDialog
from test_reading_candidates_workflow import reading_window


def test_remember_song_is_one_undo_and_does_not_confirm_or_retime(reading_window):
    w=reading_window;before=w.project.to_dict();assert w.remember_current_reading('song')
    assert w.project.reading_dictionary['entries'][0]['kana']=='にんき'
    assert w.project.to_dict()['lines']==before['lines'] and w.project.checks==before['checks']
    assert 'song_dictionary' in w.reading_candidates.data['choices'][0]['sources']
    w.undo();assert w.project.to_dict()==before


def test_personal_dictionary_does_not_enter_project_and_has_separate_undo(reading_window):
    w=reading_window;before=w.project.to_dict();assert w.remember_current_reading('personal')
    assert w.project.to_dict()==before and w.reading_dictionary_store.read()['entries'][0]['text']=='人気'
    assert 'personal_dictionary' in w.reading_candidates.data['choices'][0]['sources']
    assert w.undo_personal_dictionary() and w.reading_dictionary_store.read()=={} and w.project.to_dict()==before


def test_manager_cancel_preserves_song_dictionary(reading_window):
    w=reading_window;before=w.project.to_dict()
    def cancel():
        dialog=QApplication.activeModalWidget();assert isinstance(dialog,DictionaryDialog)
        dialog.fill(put({},'星','せかい','特殊唱法'));dialog.reject()
    QTimer.singleShot(0,cancel);assert not w.manage_reading_dictionary('song') and w.project.to_dict()==before


def test_manager_save_preserves_lyrics_and_is_undoable(reading_window):
    w=reading_window;before=w.project.to_dict()
    def accept():
        dialog=QApplication.activeModalWidget();dialog.fill(put({},'星','せかい','特殊唱法'));dialog.accept()
    QTimer.singleShot(0,accept);assert w.manage_reading_dictionary('song')
    assert w.project.reading_dictionary['entries'][0]['kana']=='せかい' and w.project.to_dict()['lines']==before['lines']
    w.undo();assert w.project.to_dict()==before


def test_manager_import_export_operates_on_draft_only(qapp,tmp_path,monkeypatch):
    original=put({},'今日','きょう');other=put({},'星','せかい');path=tmp_path/'导入.json';path.write_text(json.dumps(other),encoding='utf-8');out=tmp_path/'导出.json'
    d=DictionaryDialog(original,'song');monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:(str(path),'json'));d.import_file()
    assert len(d.collect()['entries'])==2 and d.original==original
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a:(str(out),'json'));d.export_file()
    assert json.loads(out.read_text(encoding='utf-8'))==d.collect() and d.original==original;d.reject()
