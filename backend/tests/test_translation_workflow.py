import copy
import pytest
from studio_backend.model import LyricLine,Unit,Highlight
from studio_backend.translation import manual,info,record_suggestion,accept_suggestion,confirm,carry_after_lyric_edit
from studio_backend.convert import annotation_suggestion


def line():return LyricLine('t','星',1000,2000,[Unit('星',1000,2000,'ほし',highlights=[Highlight('ほ',1000,1400,'manual'),Highlight('し',1400,2000,'manual')])],reviewed=True)


def test_manual_translation_changes_no_lyrics_reading_or_human_time():
    old=line();before=copy.deepcopy(old);value=manual(old,'手工译文')
    assert old==before and value.text==old.text and value.units==old.units and value.reviewed
    assert info(value)['source']=='manual' and not info(value)['confirmed']


def test_text_model_preserves_manual_translation_and_stores_separate_candidate():
    old=manual(line(),'手工译文');value=annotation_suggestion(old,{'groups':[{'text':'星','kana':'ほし','romaji':'hoshi'}],'translation':'星光'})
    assert value.translation=='手工译文' and value.reading_review['translation_suggestion']['text']=='星光'
    adopted=accept_suggestion(value);assert adopted.translation=='星光' and adopted.units==value.units and adopted.text==old.text


def test_blank_manual_translation_and_legacy_nonempty_are_not_overwritten():
    for old in [manual(line(),''),line()]:
        if not old.reading_review:old.translation='旧译文'
        candidate=copy.deepcopy(old);record_suggestion(old,candidate,'新建议');assert candidate.translation==old.translation


def test_confirmed_draft_is_protected_and_rewording_invalidates_old_suggestion():
    old=line();record_suggestion(old,old,'星光');old=confirm(old,True);candidate=copy.deepcopy(old);record_suggestion(old,candidate,'新建议');assert candidate.translation=='星光'
    changed=LyricLine('t','月',1000,2000,translation=old.translation);carry_after_lyric_edit(candidate,changed)
    with pytest.raises(ValueError,match='原文已变化'):accept_suggestion(changed)
    assert changed.reading_review['translation_original_changed']


def test_unconfirmed_deepseek_draft_can_be_compared_with_new_draft():
    old=line();record_suggestion(old,old,'初稿');candidate=copy.deepcopy(old);record_suggestion(old,candidate,'二次建议')
    assert candidate.translation=='二次建议' and not info(candidate)['confirmed'] and candidate.units==old.units
