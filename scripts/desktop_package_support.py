"""Postprocess runtime DLL search collisions and write a verifiable manifest."""
from pathlib import Path
import hashlib
import json
from desktop_source_state import app_version

def finalize(package):
    package=Path(package).resolve()
    # Qt 6.12 uses the Windows system ICU API (unversioned ucnv_* exports).
    # PyInstaller can pick Poppler's different, same-named ICU from build PATH.
    # It must never shadow Windows System32/icuuc.dll in the standalone app.
    for name in ('icuuc.dll','icudt78.dll'):
        path=(package/'_internal'/name).resolve()
        assert path.is_relative_to(package)
        path.unlink(missing_ok=True)
    records=[]
    for path in package.rglob('*'):
        if path.is_file() and path.name!='package-manifest.json':
            records.append({'path':str(path.relative_to(package)).replace('\\','/'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size})
    (package/'package-manifest.json').write_text(json.dumps({'application':'Shengao Independent Studio','version':app_version(Path(__file__).resolve().parents[1]),'files':records},indent=2),encoding='utf-8')
    return records
