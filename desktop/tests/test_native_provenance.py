"""The optional certifier must preserve complete Python validation and hooks."""
import copy
import gc
import sys

import pytest
from shengao.fast_snapshot import enable
from studio_backend import model, provenance as p


@pytest.fixture
def native():
    old_model, old_origin = model._SNAPSHOT_ACCELERATOR, p._ACCELERATOR
    status = enable()
    assert status['enabled'] and p._ACCELERATOR is not None, status
    module = model._SNAPSHOT_ACCELERATOR[0]
    context = p._ACCELERATOR[1]
    try:
        yield module, context, p._ACCELERATOR
    finally:
        model._SNAPSHOT_ACCELERATOR, p._ACCELERATOR = old_model, old_origin


def record(**changes):
    return dict(version=1, kind='estimated', provider='local', method='mora',
                reference=[10, 200], current=[10, 200], **changes)


def outcome(value, accelerator):
    previous = p._ACCELERATOR
    p._ACCELERATOR = accelerator
    try:
        try:
            p.validate(value)
        except Exception as error:
            return type(error), str(error)
        return None
    finally:
        p._ACCELERATOR = previous


def test_certified_values_match_python_for_all_supported_kinds_and_providers(native):
    module, context, accelerated = native
    values = [{}]
    for kind in p.KINDS:
        for provider in p.PROVIDERS:
            value = record(reading='きょ' * 10000, parent_kinds=sorted(p.KINDS),
                           operations=sorted(p.OPERATIONS))
            value.update(kind=kind, provider=provider, method='m' * 80,
                         reference=[0, 10**100], current=[10**80, 10**100])
            values.append(value)
    for value in values:
        assert module.origin_valid(context, value)
        assert outcome(value, None) == outcome(value, accelerated) is None


def test_invalid_plain_records_keep_exact_python_errors(native):
    module, context, accelerated = native
    values = [None, False, 0, [], {'extra': 1}, {'version': 1}]
    for key, candidates in {
        'version': [True, 0, 2, 1.0, 10**100],
        'kind': [None, 'invalid', 2], 'provider': [None, 'invalid'],
        'method': [None, b'name', 'm' * 81],
        'reference': [None, (), [1], [False, 2], [1., 2], [-1, 2], [3, 2]],
        'current': [None, [0, False], [-1, 2], [3, 2]],
        'reading': [None, 3, 'r' * 20001],
        'parent_kinds': [None, (), ['invalid'], ['word', 'word'], [False]],
        'operations': [None, (), ['invalid'], ['shift', 'shift'], [0]],
    }.items():
        for candidate in candidates:
            value = record(); value[key] = candidate; values.append(value)
    values += [{**record(), 'extra': 1}, {**record(), 1: 'unknown key'}]
    for value in values:
        assert not module.origin_valid(context, value)
        expected = outcome(value, None)
        assert expected is not None and outcome(value, accelerated) == expected


def test_uncommon_mapping_and_list_hooks_run_only_in_original_validator(native):
    module, context, accelerated = native
    def factory(events, mode):
        class Mapping(dict):
            def __bool__(self):
                events.append('truth'); return bool(len(self))
        class Pair(list):
            def __len__(self):
                events.append('length'); return super().__len__()
            def __getitem__(self, index):
                events.append(('item', index)); return super().__getitem__(index)
        if mode == 'mapping':
            return Mapping(record())
        if mode == 'empty':
            return Mapping()
        value = record(); value['current'] = Pair([10, 200]); return value
    for mode in ('mapping', 'empty', 'pair'):
        events = []; value = factory(events, mode)
        assert not module.origin_valid(context, value) and events == []
        outcome(value, None); expected = events[:]
        events = []; value = factory(events, mode)
        assert outcome(value, accelerated) is None and events == expected


def test_changed_schema_constants_fall_back_to_current_python_rules(native, monkeypatch):
    module, context, accelerated = native
    value = record(); value['kind'] = 'new-kind'
    assert not module.origin_valid(context, value)
    monkeypatch.setattr(p, 'KINDS', p.KINDS | {'new-kind'})
    assert outcome(value, None) == outcome(value, accelerated) is None


def test_direct_invalid_mutation_is_not_cached_as_valid(native):
    from shengao.project import Project
    from studio_backend.model import LyricLine, Unit, Highlight
    value = record()
    h = Highlight('あ', 10, 200, timing_origin=copy.deepcopy(value))
    unit = Unit('明日', 10, 200, 'あ', highlights=[h], timing_origin=copy.deepcopy(value))
    project = Project(lines=[LyricLine('one', '明日', 10, 200, [unit], timing_origin=copy.deepcopy(value))])
    project.validate()
    h.timing_origin['current'][1] = -1
    with pytest.raises(ValueError, match='时间来源范围无效'):
        project.validate()


def test_native_context_references_and_invalid_capsules_are_safe(native):
    module, context, _ = native
    before = sys.getrefcount(p.KINDS)
    for _ in range(100):
        temporary = module.origin_context(p._FIELDS, p.KINDS, p.PROVIDERS, p._CHANGES)
        for _ in range(20):
            assert module.origin_valid(temporary, record())
    del temporary; gc.collect()
    after = sys.getrefcount(p.KINDS)
    assert after == before
    with pytest.raises((ValueError, TypeError)):
        module.origin_valid(object(), record())
    for fields in (set(p._FIELDS), p._FIELDS | {'new-field'}, frozenset({1})):
        with pytest.raises(ValueError):
            module.origin_context(fields, p.KINDS, p.PROVIDERS, p._CHANGES)
