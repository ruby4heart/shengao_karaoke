"""Verify every declared file before using a frozen runtime as QA evidence."""
from pathlib import Path,PurePosixPath
import hashlib,json


def _digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def verify_runtime(runtime):
    runtime=Path(runtime).resolve();manifest=runtime/'package-manifest.json'
    raw=manifest.read_bytes();record=json.loads(raw)
    if not isinstance(record,dict) or record.get('application')!='Shengao Independent Studio':raise ValueError('Invalid package manifest')
    rows=record.get('files')
    if not isinstance(rows,list) or not rows:raise ValueError('Empty package manifest')
    expected=set();total=0
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Invalid package file record')
        name=row.get('path');size=row.get('size');sha=row.get('sha256')
        if not isinstance(name,str) or not name or '\\' in name or ':' in name:raise ValueError('Invalid package file path')
        relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix()!=name or name=='package-manifest.json':raise ValueError('Package file path escapes inventory')
        key=name.casefold()
        if key in expected:raise ValueError('Duplicate package file path')
        expected.add(key)
        if type(size) is not int or size<0 or not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('Invalid package file fingerprint')
        path=runtime.joinpath(*relative.parts)
        if not path.resolve().is_relative_to(runtime):raise ValueError('Package file resolves outside runtime')
        if not path.is_file() or path.stat().st_size!=size or _digest(path)!=sha:raise ValueError('Package file mismatch: '+name)
        total+=size
    actual={p.relative_to(runtime).as_posix().casefold() for p in runtime.rglob('*') if p.is_file() and p!=manifest}
    if actual!=expected:raise ValueError('Package contains missing or unlisted files')
    if manifest.read_bytes()!=raw:raise ValueError('Package manifest changed during verification')
    return {'application':record['application'],'version':record.get('version'),
            'manifest_sha256':hashlib.sha256(raw).hexdigest(),'verified_files':len(rows),
            'verified_bytes':total,'every_file_verified':True,'no_unlisted_files':True}
