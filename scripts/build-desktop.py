"""Build the independent Qt executable; never package the old Aegisub editor."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
import importlib.util
import zipfile
from desktop_package_support import finalize
from desktop_source_state import snapshot
from vocal_source_state import state as vocal_state
from python_tls_resources import pyinstaller_arguments
from json_runtime_sources import verify as verify_json_runtime

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'desktop'),str(root/'backend')]
from shengao.fast_snapshot import verify as verify_snapshot
verify_snapshot(root/'build/desktop',root/'desktop/native/snapshot.c')
verify_json_runtime(root)
before=snapshot(root)
vocal=root/'build/vocal-dist/shengao-vocals'
assert vocal_state(root)==json.loads((vocal/'engine-sources.json').read_text()),'Rebuild the local vocal engine before packaging'
for name in ['shengao-audio.dll','shengao-render.dll','shengao-view.dll']:
    if not (root/'build'/'desktop'/name).is_file():raise SystemExit('Build native desktop modules first: '+name)
command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
 '--name','shengao-karaoke','--distpath','build/desktop-dist','--workpath','build/desktop-pyinstaller',
 '--specpath','build','--paths','desktop','--paths','backend','--collect-all','janome','--icon',str(root/'desktop'/'assets'/'shengao.ico'),
 '--add-data',str(root/'desktop'/'assets')+';assets']
for module in ['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick','PySide6.QtPdf','tkinter','torch','torchaudio','demucs']:
    command+=['--exclude-module',module]
command+=pyinstaller_arguments(root)+['desktop/main.py']
subprocess.run(command,cwd=root,check=True)
package=root/'build'/'desktop-dist'/'shengao-karaoke'
shutil.copytree(vocal,package/'vocal-engine',dirs_exist_ok=True)
# Numba's optional TBB extension is included by its upstream hook. Complete
# its PE dependency even though TIFA's Viterbi currently runs serially. Keep
# this redistributable at the audio subprocess's DLL root, outside Qt's root.
wheel=root/'vendor/tbb-runtime/tbb-2023.2.0-py3-none-win_amd64.whl'
assert hashlib.sha256(wheel.read_bytes()).hexdigest()=='b39121cbdaff350fc61a448766cbb26807c523491d66e364838c9feeb3c6a0eb','TBB redistributable failed verification'
with zipfile.ZipFile(wheel) as archive:
    (package/'vocal-engine/_internal/tbb12.dll').write_bytes(archive.read('tbb-2023.2.0.data/data/Library/bin/tbb12.dll'))
    notices=package/'vocal-engine/licenses/Intel-oneTBB';notices.mkdir(parents=True,exist_ok=True)
    for name in ['tbb-2023.2.0.dist-info/LICENSE.txt','tbb-2023.2.0.data/data/Library/share/doc/tbb/licensing/third-party-programs.txt','tbb-2023.2.0.dist-info/METADATA']:
        (notices/Path(name).name).write_bytes(archive.read(name))
    shutil.copy2(root/'vendor/tbb-runtime/SOURCE.json',notices/'SOURCE.json')
for name in ['shengao-audio.dll','shengao-render.dll','shengao-view.dll']:shutil.copy2(root/'build'/'desktop'/name,package/name)
for name in ('_shengao_snapshot.pyd','snapshot-native.json'):shutil.copy2(root/'build/desktop'/name,package/name)
shutil.copytree(root/'vendor/orjson/licenses',package/'licenses/orjson',dirs_exist_ok=True)
shutil.copy2(root/'vendor/orjson/SOURCES.json',package/'licenses/orjson/SOURCES.json')
baseline=root/'vendor'/'desktop-runtime'
if not (baseline/'ffmpeg.exe').exists():baseline=root/'dist'/'ShengaoKaraoke-0.7.0-final-win64'
shutil.copy2(baseline/'ffmpeg.exe',package/'ffmpeg.exe')
for path in baseline.glob('*.dll'):shutil.copy2(path,package/path.name)
shutil.copytree(baseline/'licenses',package/'licenses',dirs_exist_ok=True)
if (root/'desktop'/'assets'/'licenses').exists():shutil.copytree(root/'desktop'/'assets'/'licenses',package/'licenses'/'Independent-Qt',dirs_exist_ok=True)
qt=Path(importlib.util.find_spec('PySide6').origin).parent
for folder in [qt/'licenses',qt/'Qt'/'licenses']:
    if folder.is_dir():shutil.copytree(folder,package/'licenses'/'Qt',dirs_exist_ok=True)
for name in ['NotoSans-LICENSE.txt','NotoSerif-LICENSE.txt','NotoSerif-Black-LICENSE.txt','BIZUD-LICENSE.txt','SOURCES.json']:
    shutil.copy2(root/'desktop'/'assets'/'fonts'/name,package/'licenses'/name)
(package/'licenses'/'Shengao-Audio-Sources.json').write_bytes((root/'desktop'/'native'/'aegisub'/'SOURCES.json').read_bytes())
(package/'licenses'/'Shengao-Timeline-Sources.json').write_bytes((root/'desktop'/'native'/'aegisub'/'TIMELINE-SOURCES.json').read_bytes())
(package/'INDEPENDENT-STUDIO.txt').write_text('声稿 · 独立卡拉 OK 工作台\n完整解压后运行 shengao-karaoke.exe。无需安装 Python 或 Aegisub。\n第一次使用请查看“快速开始.txt”或“使用说明.md”，也可在软件中打开离线练习。\n',encoding='utf-8-sig')
shutil.copy2(root/'desktop'/'assets'/'快速开始.txt',package/'快速开始.txt')
shutil.copy2(root/'docs'/'DESKTOP-USER-GUIDE.md',package/'使用说明.md')
shutil.copy2(root/'docs'/'ROMANIZATION-REFERENCES.md',package/'ROMANIZATION-REFERENCES.md')
guide=(root/'docs'/'DESKTOP-USER-GUIDE.md').read_text(encoding='utf-8')
for relative in set(re.findall(r'!\[[^\]]*\]\((images/[^)]+)\)',guide)):
    image=(root/'docs'/relative).resolve();assert image.is_relative_to((root/'docs/images').resolve()) and image.is_file()
    destination=package/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(image,destination)
after=snapshot(root)
if after!=before:
    (package/'package-manifest.json').unlink(missing_ok=True)
    raise SystemExit('源码或原生模块在构建时发生变化；本次运行包不作为有效发行包，请重新构建。')
records=finalize(package)
(root/'build'/'desktop-build-sources.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
print(json.dumps({'package':str(package),'files':len(records),'bytes':sum(x['size'] for x in records)}))
