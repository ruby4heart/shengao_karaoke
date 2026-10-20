"""Check final archives, selected source freshness and native DLL closure."""
import hashlib
import json
import os
from pathlib import Path
import zipfile
import pefile

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
NAME='ShengaoKaraoke-0.7.0-final-win64'
PACKAGE=DIST/NAME
source=DIST/'ShengaoKaraoke-0.7.0-source.zip'
portable=DIST/(NAME+'.zip')
reports={}
for path in (portable,source):
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        assert len(names)==len(set(names)),f'Duplicate entries: {path}'
        assert archive.testzip() is None,f'CRC failure: {path}'
        assert not any({'.git','.venv','__pycache__','.env'}&set(Path(name).parts) for name in names)
        if path==portable:
            for name in ('shengao-karaoke.exe','ffmpeg.exe','studio-worker.exe','使用说明.md','快速开始.txt','验收记录.md','package-manifest.json'):
                assert archive.read(NAME+'/'+name)==(PACKAGE/name).read_bytes(),name
            for item in (ROOT/'docs/images').glob('*.png'):
                assert archive.read(NAME+'/images/'+item.name)==item.read_bytes(),item.name
        else:
            assert archive.read('karaoke-studio/README.md')==(ROOT/'README.md').read_bytes(),'README freshness'
            janome=next((ROOT/'vendor/python').glob('*anome-0.5.0.tar.gz'))
            assert archive.read('karaoke-studio/vendor/python/'+janome.name)==janome.read_bytes(),'Janome corresponding source'
            for folder in ('native','scripts','docs'):
                for item in (ROOT/folder).glob('*'):
                    if item.is_file():
                        assert archive.read('karaoke-studio/'+folder+'/'+item.name)==item.read_bytes(),item
            for item in (ROOT/'backend').rglob('*'):
                if item.is_file() and not {'__pycache__','.pytest_cache'}&set(item.parts):
                    assert archive.read('karaoke-studio/'+item.relative_to(ROOT).as_posix())==item.read_bytes(),item
            for name in ('src/studio_panel.cpp','src/studio_shell.cpp','src/studio_workspace.cpp','src/studio_integration.cpp','src/main.cpp',
                         'src/frame_main.cpp','src/audio_karaoke.cpp','src/audio_karaoke.h','src/studio_karaoke.h',
                         'src/studio_karaoke_display.inc','src/studio_timing_drag.inc','src/studio_calibration.h',
                         'src/studio_correction.cpp','src/studio_correction_test.inc','src/studio_review.inc',
                         'src/studio_usability.cpp','src/studio_usability_test.inc','src/studio_pauses.h',
                         'src/audio_timing_karaoke.cpp','src/audio_timing.h','src/audio_display.cpp',
                         'src/meson.build','subprojects/ffmpeg/fftools/cmdutils.c'):
                assert archive.read('karaoke-studio/vendor/aegisub/'+name)==(ROOT/'vendor/aegisub'/name).read_bytes(),name
            for item in (ROOT/'docs/images').glob('*.png'):
                assert archive.read('karaoke-studio/docs/images/'+item.name)==item.read_bytes(),item.name
        reports[path.name]={'bytes':path.stat().st_size,'entries':len(names),
                            'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest()}

dependencies={}
for name in ('shengao-karaoke.exe','ffmpeg.exe','studio-worker.exe'):
    binary=pefile.PE(str(PACKAGE/name))
    imports=[entry.dll.decode() for entry in getattr(binary,'DIRECTORY_ENTRY_IMPORT',[])]
    imports += [entry.dll.decode() for entry in getattr(binary,'DIRECTORY_ENTRY_DELAY_IMPORT',[])]
    for dll in imports:
        assert ((PACKAGE/dll).exists() or (Path(os.environ['WINDIR'])/'System32'/dll).exists()
                or dll.lower().startswith(('api-ms-','ext-ms-'))),f'Missing {dll} required by {name}'
    dependencies[name]=imports
    binary.close()
(ROOT/'build/native-dependencies.json').write_text(json.dumps(dependencies,indent=2),encoding='utf-8')
(ROOT/'build/archive-check.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
(DIST/'SHA256SUMS.txt').write_text(''.join(f"{v['sha256']}  {k}\n" for k,v in reports.items()),encoding='utf-8')
(DIST/'SHA256SUMS-0.7.0.txt').write_text((DIST/'SHA256SUMS.txt').read_text(encoding='utf-8'),encoding='utf-8')
print(json.dumps(reports,indent=2))
print('PASS: archive CRC, unique entries, current sources/binaries, DLL dependencies, SHA256')
