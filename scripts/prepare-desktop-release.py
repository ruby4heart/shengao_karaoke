"""Publish a fresh portable/source pair only after current-source acceptance.

Never overwrites an existing release. Old versions and user data are untouched.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import zipfile
from desktop_source_state import snapshot

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--version',required=True);args=parser.parse_args()
version=args.version
assert re.fullmatch(r'\d+\.\d+\.\d+',version),'Use a final semantic version, not a development build'
source=ROOT/'build/desktop-dist/shengao-karaoke';dist=ROOT/'dist';name=f'ShengaoKaraoke-{version}-final-win64';target=dist/name
manifest=json.loads((source/'package-manifest.json').read_text(encoding='utf-8'))
assert manifest['version']==version,'Build version is not final'
assert snapshot(ROOT)==json.loads((ROOT/'build/desktop-build-sources.json').read_text()),'Build sources are stale'
assert snapshot(ROOT)==json.loads((ROOT/'build/desktop-test-sources.json').read_text())['sources'],'Full regression sources are stale or no full successful run'
acceptance=json.loads((ROOT/'build/desktop-package-acceptance.json').read_text())
assert acceptance['passed'] and acceptance['checks']>=29
assert acceptance['manifest_sha256']==hashlib.sha256((source/'package-manifest.json').read_bytes()).hexdigest(),'Executable acceptance is stale'
for directory in ['timeline-full-pixels','timeline-full-pixels-dpi150']:
    record=json.loads((ROOT/'tmp'/directory/'report.json').read_text())
    assert record['passed'] and len(record['cases'])==6 and record['sources']==snapshot(ROOT),'Timeline pixel acceptance is stale'
for item in manifest['files']:
    path=source/item['path'];assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],item['path']
portable=dist/(name+'.zip');sources=dist/f'ShengaoKaraoke-{version}-source.zip'
assert not any(p.exists() for p in [target,portable,sources]),'Keep existing releases; choose a new version'
assert target.resolve().parent==dist.resolve()
shutil.copytree(source,target)
def files(folder):
    for directory,folders,names in os.walk(folder):
        folders[:]=[x for x in folders if x not in {'.git','.venv','.venv-desktop','__pycache__','.pytest_cache','packagecache'}]
        for name in names:
            if name in {'.git','.env'} or name.endswith(('.pyc','.pyo')):continue
            path=Path(directory)/name
            assert not path.is_symlink(),path
            yield path
with zipfile.ZipFile(portable,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for path in files(target):archive.write(path,name+'/'+path.relative_to(target).as_posix())
with zipfile.ZipFile(sources,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for folder in ['desktop','backend','scripts','docs','demo','vendor','native']:
        for path in files(ROOT/folder):archive.write(path,'karaoke-studio/'+path.relative_to(ROOT).as_posix())
    for name in ['README.md','meson.build','.gitignore']:
        archive.write(ROOT/name,'karaoke-studio/'+name)
    archive.writestr('karaoke-studio/SOURCE-NOTES.txt','Independent Qt studio; see docs/DESKTOP-BUILD.md.\nAegisub application framework is not built. Original audio/drawing and dependency sources and notices are retained.\nNo user projects, API credentials, task caches, development environments or original user media are included.\n')
records=[]
for path in [portable,sources]:
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist();assert len(names)==len(set(names)) and archive.testzip() is None
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    records.append({'file':path.name,'size':path.stat().st_size,'sha256':digest})
(dist/f'SHA256SUMS-{version}.txt').write_text(''.join(f"{r['sha256']}  {r['file']}\n" for r in records),encoding='utf-8')
(ROOT/'build/desktop-release.json').write_text(json.dumps({'version':version,'files':records},indent=2),encoding='utf-8')
print(json.dumps({'version':version,'files':records},indent=2))
