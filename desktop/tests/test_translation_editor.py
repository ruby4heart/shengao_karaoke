from studio_backend.translation import manual,record_suggestion,info
from test_reading_candidates_workflow import reading_window


def test_manual_translation_source_and_measured_width_keep_time_and_reading_checks(reading_window):
    w=reading_window;before=w.project.to_dict();w.translation.setText('这是我的译文');w.edit_translation()
    assert info(w.line)['source']=='manual' and w.line.translation=='这是我的译文'
    assert w.line.units[0].highlights[1].start==1210 and w.line.reviewed and w.project.checks['line']['reading']
    assert '6 字符' in w.translation_length.text() and '安全宽度' in w.translation_length.text()
    w.undo();assert w.project.to_dict()==before


def test_saved_suggestion_can_be_adopted_and_undone_without_rewriting_lyrics(reading_window):
    w=reading_window;w.project.lines[0]=manual(w.line,'手工译文');record_suggestion(w.line,w.line,'新的译文');w.refresh();before=w.project.to_dict()
    assert not w.accept_translation_button.isHidden()
    assert w.accept_translation() and w.line.translation=='新的译文' and w.line.text=='人気の街'
    assert w.line.reviewed and w.project.checks['line']['reading'];w.undo();assert w.project.to_dict()==before


def test_translation_confirmation_is_independent_and_locked_field_is_readonly(reading_window):
    w=reading_window;w.translation.setText('译文');w.edit_translation();w.translation_confirm.setChecked(True)
    assert info(w.line)['confirmed'] and w.line.reviewed and w.project.checks['line']['reading']
    w.line.locked=True;w.refresh();assert w.translation.isReadOnly() and not w.translation_confirm.isEnabled()
