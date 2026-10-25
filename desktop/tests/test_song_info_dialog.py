import copy
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from shengao.song_info_dialog import SongInfoDialog
from shengao.song_info import own_event,event_parts
from shengao.subtitles import compose
from test_reading_candidates_workflow import reading_window


def test_real_private_draft_preview_and_cancel_preserve_player_and_project(reading_window):
    w=reading_window;before=w.project.to_dict();position=w.playback.canvas.position;dialog=SongInfoDialog(w.project,w)
    assert dialog.font.currentIndex()==0
    dialog.fields['title'].setPlainText('歌名');dialog.fields['artist'].setPlainText('歌手');dialog.enabled.setChecked(True);dialog.render_preview()
    assert dialog.apply.isEnabled() and not dialog.picture.pixmap().isNull() and not dialog.detail.pixmap().isNull()
    assert w.project.to_dict()==before and w.playback.canvas.position==position
    dialog.reject();assert dialog.renderer.closed and w.project.to_dict()==before


def test_apply_visible_controls_and_undo_preserve_manual_times_and_checks(reading_window):
    w=reading_window;before=w.project.to_dict();w.set_stage(3)
    assert w.song_info_button.isVisible()
    def choose():
        dialog=QApplication.activeModalWidget();dialog.fields['title'].setPlainText('歌の名前');dialog.fields['artist'].setPlainText('歌手')
        dialog.fields['title_color'].setText('#ff3366');dialog.fields['title_size'].setValue(64);dialog.period.setCurrentIndex(dialog.period.findData('range'))
        dialog.fields['start'].setValue(200);dialog.fields['end'].setValue(5000);dialog.enabled.setChecked(True);dialog.accept()
    QTimer.singleShot(0,choose);assert w.edit_song_info()
    assert w.project.song_info['title']=='歌の名前' and w.project.song_info['title_color']=='#ff3366'
    assert [v.to_dict() for v in w.project.lines]==before['lines'] and w.project.checks==before['checks']
    assert len([v for _,v in event_parts(compose(w.project)) if own_event(v)])==2
    w.undo();assert w.project.to_dict()==before


def test_empty_enabled_or_bad_period_stays_in_editor(reading_window):
    dialog=SongInfoDialog(reading_window.project,reading_window);dialog.enabled.setChecked(True)
    assert not dialog.apply.isEnabled() and '至少填写' in dialog.warning.text()
    dialog.fields['title'].setPlainText('歌名');dialog.period.setCurrentIndex(dialog.period.findData('range'));dialog.fields['end'].setValue(0)
    assert not dialog.apply.isEnabled();dialog.accept();assert dialog.result_settings is None
    dialog.reject()


def test_stale_project_rejects_draft_and_keeps_new_edit(reading_window):
    w=reading_window;old=copy.deepcopy(w.project.song_info)
    def change():
        dialog=QApplication.activeModalWidget();dialog.fields['title'].setPlainText('歌名');dialog.enabled.setChecked(True)
        w.project.note='后台新修改';dialog.accept()
    QTimer.singleShot(0,change);assert not w.edit_song_info()
    assert w.project.song_info==old and w.project.note=='后台新修改' and '已变化' in w.status.text()
