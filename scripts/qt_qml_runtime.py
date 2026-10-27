"""Collect only the QML modules used by the private preview scaler.

Keep Qt's dependency discovery for the selected plugins. Do not bundle the
entire installed QML catalog, which also contains unrelated editor/3D modules.
The import scanner must agree with this audited set before every build.
"""
from pathlib import Path, PurePosixPath
import json
import subprocess


MODULES = frozenset(('QtQuick', 'QtQml', 'QtQml/Models',
                     'QtQml/WorkerScript', 'QtMultimedia'))


def scan(root, qt):
    root, qt = Path(root), Path(qt)
    result = subprocess.run(
        [str(qt/'qmlimportscanner.exe'), '-rootPath', str(root/'desktop/assets'),
         '-importPath', str(qt/'qml')], capture_output=True, text=True,
        encoding='utf-8', check=True, timeout=60,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    records = json.loads(result.stdout)
    found = {record['relativePath'].replace('\\', '/')
             for record in records if record.get('path')}
    if found != MODULES:
        raise ValueError('QML imports changed; audit the runtime module set: '+str(sorted(found)))
    for record in records:
        if not record.get('path'):
            continue
        folder = (qt/'qml'/record['relativePath']).resolve()
        if not folder.is_relative_to((qt/'qml').resolve()) or not (folder/'qmldir').is_file():
            raise ValueError('Missing QML module: '+record['name'])
        if record.get('plugin') and not (folder/(record['plugin']+'.dll')).is_file():
            raise ValueError('Missing QML plugin: '+record['name'])
    return {'modules': sorted(found), 'imports': records}


def owner(path, qml_root):
    """Nearest qmldir wins, including modules nested below QtQuick itself."""
    path, qml_root = Path(path).resolve(), Path(qml_root).resolve()
    if not path.is_relative_to(qml_root):
        raise ValueError('QML input is outside the Qt import directory')
    folder = path if path.is_dir() else path.parent
    while folder != qml_root:
        if (folder/'qmldir').is_file():
            return folder.relative_to(qml_root).as_posix()
        folder = folder.parent
    return None


def select(binaries, datas, qml_root, destination):
    """Expand data directories before filtering, so children cannot leak in."""
    qml_root = Path(qml_root).resolve()
    destination = PurePosixPath(str(destination).replace('\\', '/'))

    def filtered(records):
        result = {}
        for name, _ in records:
            entry = Path(name)
            for path in sorted(entry.rglob('*')) if entry.is_dir() else (entry,):
                if path.is_file() and owner(path, qml_root) in MODULES:
                    relative = path.resolve().relative_to(qml_root)
                    result[str(path)] = str(destination/PurePosixPath(relative.parent.as_posix()))
        return sorted(result.items())

    selected_binaries, selected_datas = filtered(binaries), filtered(datas)
    descriptors = {owner(name, qml_root) for name, _ in selected_datas
                   if Path(name).name == 'qmldir'}
    if descriptors != MODULES:
        raise ValueError('QML collection omitted required modules: '+str(sorted(MODULES-descriptors)))
    return selected_binaries, selected_datas
