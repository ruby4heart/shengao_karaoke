from studio_backend.model import Unit,LyricLine
from studio_backend.romanization import set_manual
from studio_backend.matching_context import protected


def test_manual_roman_override_is_preserved_by_default_matching_but_explicit_local_redo_is_available():
    old=LyricLine('roman','星',1000,2000,[Unit('星',1000,2000,'ほし','hoshi',reading_source='dictionary')])
    assert not protected(old)
    written=set_manual(old,0,'Hoshi!');assert protected(written) and not protected(written,replace_manual=True)
