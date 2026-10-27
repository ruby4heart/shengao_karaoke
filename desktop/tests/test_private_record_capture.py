"""Fresh value checks may share private DTOs, never active mutable models."""
import copy
import json
import types

import pytest
from shengao.fast_snapshot import enable
from shengao.project import Project, History
from shengao.timing import set_time
from studio_backend import model, provenance


@pytest.fixture
def accelerated():
    previous, origin = model._SNAPSHOT_ACCELERATOR, provenance._ACCELERATOR
    assert enable()['enabled']
    try:
        yield
    finally:
        model._SNAPSHOT_ACCELERATOR, provenance._ACCELERATOR = previous, origin


def sample():
    from studio_backend.japanese import add_mora
    lines = []
    for index in range(2):
        start = 100+index*1000
        unit = model.Unit('明日', start, start+400, 'あした')
        add_mora(unit)
        line = model.LyricLine(str(index), '明日', start, start+400, [unit])
        line.reading_review = {'notes': {'a': ['one'], 'b': ['two']}}
        lines.append(line)
    return Project(lines=lines)


def test_unchanged_private_records_reused_only_after_complete_live_comparison(accelerated):
    p = sample(); before = p.to_dict(); result = p._capture_for_edit(before)
    assert result == before and result is not before
    assert all(a is b for a, b in zip(result['lines'], before['lines']))
    p.lines[0].units[0].highlights[0].timing_origin['current'][1] += 1
    changed = p._capture_for_edit(before)
    assert changed == p.to_dict() and changed['lines'][0] is not before['lines'][0]
    assert changed['lines'][1] is before['lines'][1]
    assert before['lines'][0]['units'][0]['highlights'][0]['timing_origin']['current'][1] != changed['lines'][0]['units'][0]['highlights'][0]['timing_origin']['current'][1]
    public = p.to_dict(); public['lines'][1]['reading_review']['notes']['a'].append('external')
    assert p.lines[1].reading_review['notes']['a'] == ['one']
    assert before['lines'][1]['reading_review']['notes']['a'] == ['one']


def test_type_signed_zero_dictionary_order_and_unusual_scalars_preserved(accelerated):
    for old, new in ((0, False), (0., -0.), ('word', ''.join(['wo', 'rd']))):
        p = sample(); p.lines[0].reading_review['extra'] = old; before = p.to_dict()
        p.lines[0].reading_review['extra'] = new; result = p._capture_for_edit(before)
        assert result['lines'][0] is not before['lines'][0]
        assert repr(result) == repr(p.to_dict())
    p = sample(); before = p.to_dict(); notes = p.lines[0].reading_review['notes']
    notes['a'] = notes.pop('a')
    result = p._capture_for_edit(before)
    assert list(result['lines'][0]['reading_review']['notes']) == ['b', 'a']
    assert result['lines'][0] is not before['lines'][0]


def test_legacy_omission_stays_out_of_arbitrary_nested_metadata(accelerated):
    p = sample(); p.lines[0].reading_review['extra'] = {'timing_origin': {}, 'fixed_edges': []}
    p.lines[0].reading_review['nested_unit'] = copy.deepcopy(p.lines[0].units[0])
    before = p.to_dict(); result = p._capture_for_edit(before)
    assert result == before and result['lines'][0] is before['lines'][0]
    assert result['lines'][0]['reading_review']['extra'] == {'timing_origin': {}, 'fixed_edges': []}
    assert 'reading_options' in result['lines'][0]['reading_review']['nested_unit']


def test_unusual_copy_hooks_keep_original_call_count(accelerated):
    events = []
    class Detail:
        def __init__(self, values): self.values = values
        def __deepcopy__(self, memo):
            events.append('copy'); return Detail(copy.deepcopy(self.values, memo))
        def __eq__(self, other): return isinstance(other, Detail) and self.values == other.values
    p = sample(); p.lines[0].reading_review['extra'] = Detail(['value'])
    before = p.to_dict(); events.clear(); expected = p.to_dict(); calls = events[:]
    events.clear(); actual = p._capture_for_edit(before)
    assert events == calls == ['copy'] and actual == expected
    assert actual['lines'][0] is not before['lines'][0]


def test_custom_getters_and_instance_serializers_are_not_skipped(accelerated, monkeypatch):
    p = sample(); before = p.to_dict(); calls = []
    def read_start(self):
        calls.append('start'); return vars(self)['start']
    with monkeypatch.context() as m:
        m.setattr(model.LyricLine, 'start', property(read_start), raising=False)
        result = p._capture_for_edit(before)
        assert result == before and calls == ['start', 'start']
        assert all(a is not b for a, b in zip(result['lines'], before['lines']))
    calls.clear(); serializer = model._LYRIC_SERIALIZER
    def custom(self):
        calls.append('serializer'); value = serializer(self); value['translation'] = 'custom'; return value
    p.lines[0].to_dict = types.MethodType(custom, p.lines[0])
    result = p._capture_for_edit(before)
    assert calls == ['serializer'] and result['lines'][0]['translation'] == 'custom'


def test_project_serializer_override_keeps_original_path(accelerated, monkeypatch):
    p = sample(); before = p.to_dict(); old = Project.to_dict; calls = []
    def custom(self):
        calls.append('project'); result = old(self); result['title'] = 'custom'; return result
    monkeypatch.setattr(Project, 'to_dict', custom)
    result = p._capture_for_edit(before)
    assert result['title'] == 'custom' and calls == ['project']


def test_cached_records_never_alias_active_models_saved_data_or_undo_cells(accelerated):
    h = History(sample()); original = h.project.to_dict(); old_project = h.project
    assert h.apply_line('one', 0, lambda line: set_time(line, -1, 110, 510))
    first = h.project.to_dict(); cache = h._applied_snapshot
    assert h.apply_line('two', 0, lambda line: set_time(line, -1, 120, 520))
    assert h._applied_snapshot['lines'][1] is cache['lines'][1]
    old_project.lines[1].text = 'old controller'
    assert h.project.lines[1].text == '明日'
    # Even accidental private-cache damage must not modify owned undo cells.
    cache['lines'][1]['text'] = 'damaged cache'
    assert h.undo() and h.project.to_dict() == first
    assert h.undo() and h.project.to_dict() == original
    assert h.redo() and h.project.to_dict() == first
    assert h.saved == original
    assert h.apply_line('after undo', 0, lambda line: set_time(line, -1, 130, 530))
    assert h.project.lines[1].text == '明日'


def test_missing_or_unavailable_cache_and_invalid_other_rows_still_checked(accelerated, monkeypatch):
    p = sample(); assert p._capture_for_edit(None) == p.to_dict()
    before = p.to_dict()
    with monkeypatch.context() as m:
        m.setattr(model, '_SNAPSHOT_ACCELERATOR', None)
        result = p._capture_for_edit(before)
        assert result == before and result['lines'][0] is not before['lines'][0]
    h = History(p)
    assert h.apply_line('one', 0, lambda line: set_time(line, -1, 110, 510))
    h.project.lines[1].start = True
    with pytest.raises(ValueError):
        h.apply_line('two', 0, lambda line: set_time(line, -1, 120, 520))
