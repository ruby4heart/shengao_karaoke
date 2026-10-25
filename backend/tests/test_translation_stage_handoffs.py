import pytest
from studio_backend.model import LyricLine,Unit
from studio_backend.translation import manual,confirm,info,record_suggestion
from studio_backend.chorus_reuse import prepare
from studio_backend.analysis import aligned_words
from studio_backend.draft import keep_readings


@pytest.mark.parametrize('stage',['chorus','character_alignment','draft_stage'])
def test_nontranslation_stage_keeps_human_translation_confirmation_and_saved_draft(stage):
    old=confirm(manual(LyricLine('kept','星',3000,5000,[Unit('星',3000,5000,'ほし','hoshi',reading_source='dictionary')]),'人工译文'),True);record_suggestion(old,old,'先前译文候选')
    source=LyricLine('source','星',1000,2000,[Unit('星',1000,2000,'ほし','hoshi',reading_source='dictionary')],reviewed=True)
    if stage=='chorus':value=prepare(source,old,True)
    elif stage=='character_alignment':value=aligned_words(LyricLine(old.id,old.text,3500,5500,[Unit('星',3500,5500)]),old)
    else:value=LyricLine.from_dict(keep_readings(LyricLine(old.id,old.text,3500,5500).to_dict(),old.to_dict()))
    assert value.translation==old.translation and info(value)==info(old)
    assert value.reading_review['translation_suggestion']==old.reading_review['translation_suggestion']
    assert value.text==old.text


def test_legacy_stage_without_translation_does_not_gain_fields_or_change_identity():
    old=LyricLine('legacy','星',3000,5000).to_dict();row=LyricLine('legacy','星',3500,5500).to_dict()
    assert keep_readings(row,old) is row
