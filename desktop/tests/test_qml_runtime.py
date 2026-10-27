from pathlib import Path
import importlib.util
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('qt_qml_runtime', ROOT/'scripts/qt_qml_runtime.py')
qml = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qml)


def test_actual_preview_imports_have_complete_audited_plugins():
    import PySide6
    qt = Path(PySide6.__file__).parent
    assert set(qml.scan(ROOT, qt)['modules']) == qml.MODULES


def test_collection_excludes_nested_unrelated_modules(tmp_path):
    for module in (*qml.MODULES, 'QtQuick/Unrelated/ThreeD', 'QtQuick/Controls'):
        folder = tmp_path/module
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'qmldir').write_text('module '+module)
        (folder/'plugin.dll').write_bytes(b'fixture')
        (folder/'types.qmltypes').write_text('fixture')
    # Simulate a helper returning an entire parent directory. A nested module
    # must still be excluded, even below an allowed QtQuick directory.
    binaries, datas = qml.select([], [(str(tmp_path/'QtQuick'), 'ignored'),
                                    (str(tmp_path/'QtQml'), 'ignored'),
                                    (str(tmp_path/'QtMultimedia'), 'ignored')],
                                 tmp_path, 'PySide6/qml')
    assert not binaries
    assert len(datas) == len(qml.MODULES)*3
    for source, destination in datas:
        assert qml.owner(source, tmp_path) in qml.MODULES
        assert destination == 'PySide6/qml/'+Path(source).parent.relative_to(tmp_path).as_posix()


def test_collection_rejects_missing_required_module_and_outside_input(tmp_path):
    (tmp_path/'QtQuick').mkdir()
    (tmp_path/'QtQuick/qmldir').write_text('module QtQuick')
    with pytest.raises(ValueError, match='omitted'):
        qml.select([], [(str(tmp_path/'QtQuick'), '.')], tmp_path, 'PySide6/qml')
    with pytest.raises(ValueError, match='outside'):
        qml.owner(tmp_path.parent, tmp_path)
