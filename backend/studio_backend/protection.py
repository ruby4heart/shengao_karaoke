"""One description of what automatic work must leave alone.

Saving, reopening, undo, background suggestions and every editing tool read
the same stored fields (lock flags, the confirmed flag, sources, fixed points,
timing origins and reading modes).  This module names each kind of protection
once and says, per kind of work, which of them apply.  Callers ask here instead
of repeating their own ``locked or any(...)`` expressions, so a rule cannot
drift between the editor, the worker and the review step.
"""

LOCKED_MESSAGE = '本句或词组已锁定，请先解除锁定。'
RANGE_LOCKED_MESSAGE = '所选范围包含锁定内容，请先解除锁定'

# Every reason a line can be protected, in the order they are explained.
REASONS = {
    'locked': '整句已锁定',
    'unit_locked': '有词组已锁定',
    'reviewed': '本句时间已确认',
    'manual_source': '有人工调整的时间',
    'fixed_points': '有固定点',
    'manual_timing': '有人工时间记录',
    'manual_reading': '有人工指定的罗马音或注音',
    'match_hold': '本句位置待确认或受保护',
}

# Which reasons stop each kind of automatic work.
#   draft:      a staged first draft keeps every human timing it can see.
#   smoothing:  closing short gaps inside a line (reviewed is optional).
#   reading:    rewriting kana/romaji; timing confirmation does not apply.
#   matching:   placing lyrics against a transcript; ``replace_manual`` drops
#               the manual-history reasons when the person asked to redo them.
#   continuity: joining automatic edges across lines.
#   service:    a cloud request that rewrites the whole line.
PURPOSES = {
    'draft': frozenset({'locked', 'unit_locked', 'reviewed', 'manual_source', 'fixed_points'}),
    'smoothing': frozenset({'locked', 'unit_locked', 'reviewed', 'fixed_points'}),
    'reading': frozenset({'locked', 'unit_locked'}),
    'matching': frozenset({'locked', 'unit_locked', 'reviewed', 'manual_timing', 'manual_reading'}),
    'continuity': frozenset({'locked', 'unit_locked', 'reviewed', 'match_hold'}),
    'service': frozenset({'locked', 'unit_locked'}),
}
REPLACEABLE = frozenset({'manual_timing', 'manual_reading'})
MATCH_HOLD = frozenset({'protected', 'unmatched', 'manual'})

# Cloud actions that send whole lines; the worker refuses any lock among them,
# so the editor must never include a locked line in their range.
WHOLE_LINE_ACTIONS = frozenset({'annotate', 'align', 'transcribe'})


def locked(line, units=None):
    """True when the line or any of the given units (default: all) is locked."""
    return bool(line.locked or any(u.locked for u in (line.units if units is None else units)))


def ensure_unlocked(line, units=None, message=LOCKED_MESSAGE):
    if locked(line, units): raise ValueError(message)


def manual_timing(item):
    """Fixed points, a manual source, or a timing history written by a person."""
    origin = getattr(item, 'timing_origin', {}) or {}
    return bool(getattr(item, 'fixed_edges', [])) or getattr(item, 'source', '') == 'manual' or origin.get('kind') == 'manual' or bool(
        set(origin.get('operations', [])) & {'manual_boundary', 'shift', 'stretch'})


def manual_reading(unit):
    options = unit.reading_options
    return options.get('romaji', {}).get('mode') == 'manual' or options.get('ruby', {}).get('mode', 'auto') != 'auto'


def has(line, reason):
    units = line.units
    if reason == 'locked': return bool(line.locked)
    if reason == 'unit_locked': return any(u.locked for u in units)
    if reason == 'reviewed': return bool(line.reviewed)
    if reason == 'manual_source': return any(u.source == 'manual' or any(h.source == 'manual' for h in u.highlights) for u in units)
    if reason == 'fixed_points': return any(h.fixed_edges for u in units for h in u.highlights)
    if reason == 'manual_timing': return manual_timing(line) or any(manual_timing(u) or any(manual_timing(h) for h in u.highlights) for u in units)
    if reason == 'manual_reading': return any(manual_reading(u) for u in units)
    if reason == 'match_hold': return line.match.get('status') in MATCH_HOLD
    raise KeyError(reason)


def rules(purpose, reviewed=True, replace_manual=False):
    chosen = PURPOSES[purpose]
    if not reviewed: chosen = chosen - {'reviewed'}
    if replace_manual: chosen = chosen - REPLACEABLE
    return chosen


def reasons(line, purpose=None, reviewed=True, replace_manual=False):
    """Protection reasons present on the line, limited to one purpose if given."""
    wanted = REASONS if purpose is None else rules(purpose, reviewed, replace_manual)
    return [key for key in REASONS if key in wanted and has(line, key)]


def protected(line, purpose, reviewed=True, replace_manual=False):
    return any(has(line, key) for key in REASONS if key in rules(purpose, reviewed, replace_manual))


def explain(line, purpose=None):
    return '、'.join(REASONS[key] for key in reasons(line, purpose))


def selectable(line, action):
    """Whether whole-song automatic work may include this line."""
    return not (locked(line) if action in WHOLE_LINE_ACTIONS else line.locked)
