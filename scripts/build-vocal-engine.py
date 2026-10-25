"""Build the offline CPU engine in its isolated, pinned environment."""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import shutil
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'scripts'))
from vocal_source_state import state
from python_tls_resources import pyinstaller_arguments
from vocal_build_environment import validate_environment
environment=validate_environment(root/'desktop/vocal-requirements.lock')
before=state(root)
command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--console','--name','shengao-vocals','--distpath','build/vocal-dist','--workpath','build/vocal-pyinstaller','--specpath','build','--collect-all','demucs','--collect-all','julius','--collect-all','omegaconf','--hidden-import','demucs.htdemucs','--hidden-import','demucs.hdemucs','--hidden-import','demucs.transformer','--exclude-module','tkinter','--exclude-module','PySide6','desktop/vocal_engine.py']
# The official 2022 checkpoint pickles these NumPy 1.x compatibility names.
# NumPy 2's regular hook collects _core, but pickle imports are not visible
# to static analysis; they must remain available in the frozen process.
command[-1:-1]=['--hidden-import','numpy.core.multiarray','--hidden-import','numpy.core.numeric','--hidden-import','numpy.core._multiarray_umath']
command[-1:-1]=['--paths',str(root/'vendor/tifa'),'--hidden-import','alignment_engine','--hidden-import','inference.backend','--hidden-import','modules.backbones.jebf','--collect-all','g2pflow','--collect-all','librosa','--collect-all','numba']
command[-1:-1]=pyinstaller_arguments(root)
subprocess.run(command,cwd=root,check=True)
package=root/'build/vocal-dist/shengao-vocals'
model=root/'vendor/vocal-model'
for path in model.iterdir():
    if path.is_file():shutil.copy2(path,package/path.name)
for name in ('tifa','tifa-model'):
    shutil.copytree(root/'vendor'/name,package/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
licenses=package/'licenses';licenses.mkdir(exist_ok=True)
for dist in metadata.distributions():
    dest=licenses/dist.metadata['Name'];dest.mkdir(exist_ok=True)
    (dest/'METADATA.txt').write_text(dist.read_text('METADATA') or '',encoding='utf-8')
    for entry in dist.files or []:
        path=Path(dist.locate_file(entry))
        if path.is_file() and any(word in path.name.lower() for word in ('license','copying','notice')):
            relative=Path(str(entry).replace('..','_'));target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
for name in ('LICENSE.txt','LICENSE'):
    path=Path(sys.base_prefix)/name
    if path.is_file():shutil.copy2(path,licenses/'Python-LICENSE.txt')
assert state(root)==before,'Vocal engine sources changed during build'
(package/'engine-sources.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
(package/'engine-environment.json').write_text(json.dumps(environment,indent=2),encoding='utf-8')
print(json.dumps({'engine':str(package),'files':sum(p.is_file() for p in package.rglob('*')),'bytes':sum(p.stat().st_size for p in package.rglob('*') if p.is_file())}))
