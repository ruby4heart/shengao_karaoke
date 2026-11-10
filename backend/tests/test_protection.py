"""One protection model: every caller keeps its exact old answer, and the
stored fields it reads survive saving, reopening and snapshots."""
import copy
import itertools
import random
from types import SimpleNamespace as NS

import pytest

from studio_backend import analysis, continuity, draft, matching_context, protection, sound_gaps
from studio_backend.model import Highlight, LyricLine, Unit
from studio_backend.provenance import create
from studio_backend.romanization import set_manual


# The rules exactly as each module wrote them before they moved here.
def old_draft(line):
    return (line.locked or line.reviewed or any(u.locked or u.source == 'manual'
            or any(h.source == 'manual' or h.fixed_edges for h in u.highlights) for u in line.units))


def old_analysis(line, reviewed=True):
    return line.locked or (reviewed and line.reviewed) or any(u.locked or any(h.fixed_edges for h in u.highlights) for u in line.units)


def old_reading(line): return line.locked or any(u.locked for u in line.units)


def old_continuity(line):
    return line.locked or line.reviewed or any(u.locked for u in line.units) or line.match.get('status') in {'protected', 'unmatched', 'manual'}


def old_matching(line, replace_manual=False):
    def manual(item):
        origin = item.timing_origin
        return bool(getattr(item, 'fixed_edges', [])) or getattr(item, 'source', '') == 'manual' or origin.get('kind') == 'manual' or bool(
            set(origin.get('operations', [])) & {'manual_boundary', 'shift', 'stretch'})
    return line.locked or line.reviewed or (not replace_manual and manual(line)) or any(
        u.locked or (not replace_manual and (manual(u) or any(manual(h) for h in u.highlights) or u.reading_options.get('romaji', {}).get('mode') == 'manual' or u.reading_options.get('ruby', {}).get('mode', 'auto') != 'auto')) for u in line.units)


ORIGINS = [{}, {'kind': 'manual'}, {'kind': 'estimated', 'operations': ['shift']}, {'kind': 'character', 'operations': ['automatic_gap']},
           {'kind': 'acoustic', 'operations': ['manual_boundary', 'clamp']}, {'kind': 'word', 'operations': ['stretch']}]
READINGS = [{}, {'romaji': {'mode': 'manual'}}, {'romaji': {'mode': 'auto'}}, {'ruby': {'mode': 'auto'}}, {'ruby': {'mode': 'whole'}}, {'ruby': {'mode': 'off'}}]
SOURCES = ['estimated', 'manual', 'alignment', 'acoustic']
STATUSES = [None, 'protected', 'unmatched', 'manual', 'uncertain', 'matched']


def fake_line(rng):
    units = []
    for _ in range(rng.randint(0, 3)):
        highlights = [NS(source=rng.choice(SOURCES), fixed_edges=rng.choice([[], [], ['start'], ['start', 'end']]),
                         timing_origin=rng.choice(ORIGINS)) for _ in range(rng.randint(0, 3))]
        units.append(NS(locked=rng.random() < .15, source=rng.choice(SOURCES), highlights=highlights,
                        timing_origin=rng.choice(ORIGINS), reading_options=rng.choice(READINGS)))
    status = rng.choice(STATUSES)
    return NS(locked=rng.random() < .15, reviewed=rng.random() < .25, units=units, timing_origin=rng.choice(ORIGINS),
              match={} if status is None else {'status': status})


LINES = [fake_line(random.Random(seed)) for seed in range(3000)]


def test_every_existing_rule_gives_its_old_answer():
    for line in LINES:
        assert draft.protected(line) == bool(old_draft(line))
        assert analysis.protected(line) == bool(old_analysis(line))
        assert analysis.protected(line, reviewed=False) == bool(old_analysis(line, reviewed=False))
        assert analysis.reading_protected(line) == bool(old_reading(line))
        assert continuity.protected(line) == bool(old_continuity(line))
        assert matching_context.protected(line) == bool(old_matching(line))
        assert matching_context.protected(line, replace_manual=True) == bool(old_matching(line, replace_manual=True))
        assert protection.locked(line) == bool(old_reading(line))


def test_samples_cover_each_reason_with_and_without_the_others():
    seen = {key: {protection.has(line, key) for line in LINES} for key in protection.REASONS}
    assert all(values == {True, False} for values in seen.values())
    for purpose in protection.PURPOSES:
        assert {protection.protected(line, purpose) for line in LINES} == {True, False}


def test_reasons_follow_one_table_and_explain_in_order():
    line = NS(locked=False, reviewed=True, units=[NS(locked=True, source='manual', timing_origin={}, reading_options={},
              highlights=[NS(source='estimated', fixed_edges=['start'], timing_origin={})])], timing_origin={}, match={'status': 'manual'})
    assert protection.reasons(line) == ['unit_locked', 'reviewed', 'manual_source', 'fixed_points', 'manual_timing', 'match_hold']
    assert protection.reasons(line, 'reading') == ['unit_locked']
    assert protection.reasons(line, 'smoothing', reviewed=False) == ['unit_locked', 'fixed_points']
    assert protection.reasons(line, 'matching', replace_manual=True) == ['unit_locked', 'reviewed']
    assert protection.explain(line, 'continuity') == '有词组已锁定、本句时间已确认、本句位置待确认或受保护'
    with pytest.raises(KeyError): protection.has(line, 'unknown')


def test_unit_range_lock_and_whole_line_service_selection():
    free = NS(locked=False, units=[NS(locked=False), NS(locked=False)])
    partly = NS(locked=False, units=[NS(locked=False), NS(locked=True)])
    whole = NS(locked=True, units=[])
    assert not protection.locked(partly, partly.units[:1]) and protection.locked(partly, partly.units[1:])
    with pytest.raises(ValueError, match='已锁定'): protection.ensure_unlocked(partly)
    protection.ensure_unlocked(partly, partly.units[:1])
    for action in protection.WHOLE_LINE_ACTIONS:
        assert [protection.selectable(x, action) for x in (free, partly, whole)] == [True, False, False]
    for action in ('segment', 'refine', 'draft'):
        assert [protection.selectable(x, action) for x in (free, partly, whole)] == [True, True, False]


def test_sound_gap_lock_uses_the_same_unit_rule():
    unit = Unit('星', 1000, 2000, 'ほし', 'hoshi', locked=True, highlights=[Highlight('ほ', 1000, 1400), Highlight('し', 1400, 2000)])
    other = Unit('空', 2000, 2600, 'そら', 'sora', highlights=[Highlight('そ', 2000, 2300), Highlight('ら', 2300, 2600)])
    line = LyricLine('l', '星空', 1000, 2600, [unit, other])
    assert sound_gaps.protected(line, unit, unit.highlights[0]) == '已锁定'
    assert sound_gaps.protected(line, other, other.highlights[0]) != '已锁定'


def stored_line():
    line = LyricLine('roman', '星', 1000, 2000, [Unit('星', 1000, 2000, 'ほし', 'hoshi', highlights=[
        Highlight('ほ', 1000, 1400, 'manual', fixed_edges=['start']),
        Highlight('し', 1400, 2000, 'estimated', timing_origin=create('manual', 1400, 2000))])], reviewed=True,
        match={'status': 'protected'})
    line = set_manual(line, 0, 'ho-shi')
    line.units[0].locked = True
    return line


def test_protection_survives_save_reopen_and_snapshots():
    line = stored_line(); before = protection.reasons(line)
    assert before == list(protection.REASONS)[1:]
    reopened = LyricLine.from_dict(copy.deepcopy(line.to_dict()))
    assert protection.reasons(reopened) == before and reopened.to_dict() == line.to_dict()
    for purpose, flags in itertools.product(protection.PURPOSES, [(True, False), (False, False), (True, True)]):
        assert protection.protected(reopened, purpose, *flags) == protection.protected(line, purpose, *flags)
