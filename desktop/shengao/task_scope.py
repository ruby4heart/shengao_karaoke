"""Which lines a background task may take, decided by the shared protection rules.

The worker refuses whole-line cloud requests that contain any lock.  Picking
the range here with the same rules means a locked word group is left out up
front (or explained right away for a single line) instead of failing the whole
task after it has started, and the editor stays usable while the task runs.
"""
from studio_backend.protection import (LOCKED_MESSAGE, RANGE_LOCKED_MESSAGE, WHOLE_LINE_ACTIONS,
                                       locked, protected, selectable)

CHANGED = '歌词选择已变化，请重新选择范围'
NOTHING = '当前范围已经确认或锁定；可以选中具体一句再操作'


def api_lines(project, action, current=None, only_current=False, line_ids=None):
    """Return ``(lines, message)``; a message means the task must not start."""
    if line_ids is not None:
        lines = [line for line in project.lines if line.id in line_ids]
        if len(lines) != len(set(line_ids)): return [], CHANGED
        if any(locked(line) for line in lines): return [], RANGE_LOCKED_MESSAGE
    elif only_current and current is not None:
        if action in WHOLE_LINE_ACTIONS and locked(current): return [], LOCKED_MESSAGE
        lines = [current]
    elif action in {'match', 'transcribe_match'}:
        # Confirmed/locked rows remain immutable context for whole-song
        # matching. Removing them here would let repeated verses cross the
        # very human positions that the backend is meant to respect.
        lines = list(project.lines) if any(not protected(x, 'matching') for x in project.lines) else []
    elif action in {'refine', 'annotate'}:
        lines = [x for x in project.lines if selectable(x, action) and not project.checks.get(x.id, {}).get('reading')]
    else:
        lines = [x for x in project.lines if not x.reviewed and selectable(x, action)]
    if not lines: return [], NOTHING
    return lines, ''


def left_out(project, lines):
    """Count of locked lines a whole-song task skipped, for the start message."""
    chosen = {line.id for line in lines}
    return sum(1 for line in project.lines if line.id not in chosen and locked(line) and not line.locked)
