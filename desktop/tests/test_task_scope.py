"""Background task ranges and editing share one protection model."""
import pytest

from shengao import task_scope
from shengao.project import History, load_project, save_project
from shengao.timing import merge_words, shift_following
from studio_backend import protection
from tests.test_version_history import shifted


@pytest.fixture
def song(project):
    first = project.lines[0]
    project.lines = [first, shifted(first, 'b', 6000), shifted(first, 'c', 12000), shifted(first, 'd', 18000)]
    project.lines[1].units[1].locked = True          # one locked word group
    project.lines[2].locked = True                   # a locked line
    project.lines[3].reviewed = True                 # a confirmed line
    project.validate()
    return project


def ids(lines): return [x.id for x in lines]


def test_whole_line_services_leave_locked_word_groups_out(song):
    for action in ('align', 'annotate'):
        lines, message = task_scope.api_lines(song, action)
        assert not message and 'b' not in ids(lines) and 'c' not in ids(lines)
        assert not any(protection.locked(x) for x in lines)      # the worker's own check now passes
        assert task_scope.left_out(song, lines) == 1
    assert ids(task_scope.api_lines(song, 'align')[0]) == ['demo']
    assert ids(task_scope.api_lines(song, 'annotate')[0]) == ['demo', 'd']


def test_local_tasks_keep_their_existing_ranges(song):
    assert ids(task_scope.api_lines(song, 'segment')[0]) == ['demo', 'b']
    assert ids(task_scope.api_lines(song, 'refine')[0]) == ['demo', 'b', 'd']
    # The demo timing is hand-made, so whole-song matching has nothing it may move;
    # once one line is automatic again every line goes along as fixed context.
    assert task_scope.api_lines(song, 'match') == ([], task_scope.NOTHING)
    for u in song.lines[0].units:
        u.source = 'estimated'; u.timing_origin = {}
        for h in u.highlights: h.source = 'estimated'; h.timing_origin = {}; h.fixed_edges = []
    song.lines[0].timing_origin = {}
    assert ids(task_scope.api_lines(song, 'match')[0]) == ['demo', 'b', 'c', 'd']
    song.checks['demo'] = {'reading': True}
    assert ids(task_scope.api_lines(song, 'refine')[0]) == ['b', 'd']


def test_single_line_and_explicit_ranges_explain_locks_before_starting(song):
    assert task_scope.api_lines(song, 'align', song.lines[1], only_current=True) == ([], protection.LOCKED_MESSAGE)
    assert ids(task_scope.api_lines(song, 'segment', song.lines[1], only_current=True)[0]) == ['b']
    assert task_scope.api_lines(song, 'segment', line_ids=['demo', 'b']) == ([], protection.RANGE_LOCKED_MESSAGE)
    assert task_scope.api_lines(song, 'segment', line_ids=['demo', 'gone']) == ([], task_scope.CHANGED)
    assert ids(task_scope.api_lines(song, 'segment', line_ids=['demo', 'd'])[0]) == ['demo', 'd']


def test_nothing_left_is_reported(song):
    for line in song.lines: line.locked = True
    assert task_scope.api_lines(song, 'align') == ([], task_scope.NOTHING)
    assert task_scope.api_lines(song, 'match') == ([], task_scope.NOTHING)


def test_locks_and_confirmations_survive_save_reopen_and_undo(song, tmp_path):
    history = History(song)
    before = {x.id: protection.reasons(x) for x in song.lines}
    history.apply('锁定第一句词组', lambda p: setattr(p.lines[0].units[0], 'locked', True))
    with pytest.raises(ValueError, match='锁定'):
        history.apply('移动边界', lambda p: p.lines.__setitem__(0, shift_following(p.lines[0], p.lines[0].units[0].end, 10)))
    with pytest.raises(ValueError, match='所选词组已锁定'): merge_words(history.project.lines[0], 0, 1)
    assert merge_words(history.project.lines[0], 1, 2).units[0].locked     # unlocked groups stay editable
    path = tmp_path / 'song.sgproj'; save_project(history.project, path)
    reopened = load_project(path)
    assert {x.id: protection.reasons(x) for x in reopened.lines} == {x.id: protection.reasons(x) for x in history.project.lines}
    assert task_scope.api_lines(reopened, 'align') == ([], task_scope.NOTHING)
    assert history.undo() and {x.id: protection.reasons(x) for x in history.project.lines} == before
    assert ids(task_scope.api_lines(history.project, 'align')[0]) == ['demo']
