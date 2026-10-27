"""Application-specific QML imports; preserve PyInstaller's Qt dependency scan."""
from pathlib import Path
import sys
from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_qml_runtime import select

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()
qml_root = pyside6_library_info.location['QmlImportsPath']
qml_binaries, qml_datas = select(qml_binaries, qml_datas, qml_root,
                               Path(pyside6_library_info.qt_rel_dir)/'qml')
binaries += qml_binaries
datas += qml_datas
