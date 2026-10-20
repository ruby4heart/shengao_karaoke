"""Stage self-contained binaries and auditable sources; never include user data."""
import argparse
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
NAME='ShengaoKaraoke-0.7.0-final-win64'


def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if source.is_dir():
        shutil.copytree(source,target,dirs_exist_ok=True)
    else:
        shutil.copy2(source,target)


def files(root):
    for directory,folders,names in os.walk(root):
        folders[:]=[name for name in folders if name not in {'.git','__pycache__','.pytest_cache','packagecache'}]
        for name in names:
            if name in {'.git','.env'}:
                continue
            yield Path(directory)/name


def zip_folder(source,output):
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in files(source):
            archive.write(path,source.name+'/'+path.relative_to(source).as_posix())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--source',action='store_true')
    parser.add_argument('--output-name',default=NAME)
    args=parser.parse_args()
    if not args.output_name.startswith('ShengaoKaraoke-') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._' for c in args.output_name):
        raise ValueError('Invalid package directory name')
    stage=(DIST/args.output_name).resolve()
    if not stage.is_relative_to(DIST.resolve()) or stage.parent!=DIST.resolve():
        raise ValueError('Package target escaped the workspace distribution directory')
    marker=stage/'package-manifest.json'
    if stage.exists():
        if not args.refresh or not marker.is_file():
            raise ValueError('Package target already exists; only a marked generated package may be refreshed')
        previous=json.loads(marker.read_text(encoding='utf-8'))
        actual={path.relative_to(stage).as_posix() for path in stage.rglob('*') if path.is_file()}
        extra=actual-set(previous['files_sha256'])-{'package-manifest.json'}
        if extra or any(path.is_symlink() or not path.resolve().is_relative_to(stage) for path in stage.rglob('*')):
            raise ValueError('Package contains unexpected files or links; preserve them before refreshing: '+str(sorted(extra)))
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    source=ROOT/'vendor/aegisub'
    build=ROOT/'build/baseline'
    copy(build/'shengao-karaoke.exe',stage/'shengao-karaoke.exe')
    copy(build/'subprojects/ffmpeg/ffmpeg.exe',stage/'ffmpeg.exe')
    copy(ROOT/'build/worker-dist/studio-worker/studio-worker.exe',stage/'studio-worker.exe')
    copy(ROOT/'build/worker-dist/studio-worker/_internal',stage/'_internal')
    # Application-local Microsoft runtime; no administrator installation is needed.
    candidates=list(Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)')).glob(
        'Microsoft Visual Studio/*/BuildTools/VC/Redist/MSVC/*/x64/Microsoft.VC*.CRT'))
    if not candidates:
        raise ValueError('MSVC redistributable runtime directory not found')
    crt=sorted(candidates)[-1]
    for dll in crt.glob('*.dll'):
        copy(dll,stage/dll.name)
    for folder in ('autoload','include','demos'):
        copy(source/'automation'/folder,stage/'automation'/folder)
    copy(ROOT/'demo',stage/'demo')
    copy(ROOT/'docs/使用说明.md',stage/'使用说明.md')
    copy(ROOT/'docs/快速开始.txt',stage/'快速开始.txt')
    copy(ROOT/'docs/V07-USABILITY.md',stage/'验收记录.md')
    if (ROOT/'docs/images').is_dir():
        copy(ROOT/'docs/images',stage/'images')
    for name in ('install.ps1','install.cmd'):
        copy(ROOT/'scripts'/name,stage/name)
    install=stage/'install.ps1'
    install.write_text(install.read_text(encoding='utf-8-sig'),encoding='utf-8-sig')
    (stage/'installer_config.json').write_text(json.dumps({'App':{'Language':'zh_CN','Auto':{'Check For Updates':False}}}),encoding='utf-8')
    spec=importlib.util.spec_from_file_location('compile_locale',ROOT/'scripts/compile-locale.py')
    compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)
    compiler.compile_catalog(source/'po/zh_CN.po',stage/'locale/zh_CN/aegisub.mo')
    compiler.compile_catalog(source/'subprojects/wxWidgets/locale/zh_CN.po',stage/'locale/zh_CN/wxstd.mo')
    license_dir=stage/'licenses';license_dir.mkdir()
    copy(source/'packages/win_installer/license.txt',license_dir/'Aegisub.txt')
    copy(Path(sys.base_prefix)/'LICENSE.txt',license_dir/'Python-LICENSE.txt')
    (license_dir/'Shengao-MIT.txt').write_text('''MIT License

Copyright (c) 2026 Shengao Karaoke Studio contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
''',encoding='utf-8')
    for dependency in (source/'subprojects').iterdir():
        if not dependency.is_dir() or dependency.name in {'packagecache','packagefiles'}:
            continue
        for path in files(dependency):
            relative=path.relative_to(dependency)
            if len(relative.parts)<=3 and path.name.lower().startswith(('copying','license','licence','copyright','ftl','bsl')):
                copy(path,license_dir/dependency.name/relative)
    for distribution in importlib.metadata.distributions():
        name=distribution.metadata.get('Name','unknown')
        if name.lower().replace('_','-') not in {'aiohttp','aiosignal','aiohappyeyeballs','attrs','frozenlist','multidict','propcache','yarl','pillow','idna','pyinstaller',
                'pydantic','pydantic-core','setuptools','packaging','typing-extensions','typing-inspection','annotated-types','rapidfuzz','janome'}:
            continue
        for item in distribution.files or []:
            if item.name.lower().startswith(('license','copying','notice')):
                copy(Path(distribution.locate_file(item)),license_dir/'python'/name/item.name)
    (stage/'THIRD-PARTY-NOTICES.txt').write_text(
        'Shengao Karaoke Studio is independently maintained and based on Aegisub 3.5.0.\n'
        'Original Aegisub authors do not endorse this software. Original notices are preserved in licenses/ and the source archive.\n'
        'The native editor and FFmpeg are built using the included dependency sources. FFmpeg GPL and nonfree options are disabled.\n'
        'Python runtime and bundled module licenses are included in _internal/ and licenses/python/.\n'
        'Microsoft Visual C++ runtime DLLs are redistributed application-locally from the installed Visual Studio redistributable set.\n'
        'The corresponding source archive is ShengaoKaraoke-0.7.0-source.zip. Windows and proprietary API services are external components.\n'
        'No API keys, task caches, user media, or user configuration files are included.\n',encoding='utf-8')
    checksums={path.relative_to(stage).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in files(stage)}
    marker.write_text(json.dumps({'version':'0.7.0','architecture':'x64','files_sha256':checksums},indent=2),encoding='utf-8')
    zip_folder(stage,DIST/(args.output_name+'.zip'))
    print('Portable package:',stage,flush=True)
    if args.source:
        output=DIST/'ShengaoKaraoke-0.7.0-source.zip'
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for folder in ('vendor','native','backend','scripts','docs','demo'):
                for path in files(ROOT/folder):
                    archive.write(path,'karaoke-studio/'+path.relative_to(ROOT).as_posix())
            archive.write(ROOT/'README.md','karaoke-studio/README.md')
            archive.writestr('karaoke-studio/SOURCE-NOTES.txt',
                'Based on user-supplied Aegisub 3.5.0 source, local snapshot 211e7aa.\n'
                'Studio changes are recorded by scripts/apply-studio.py and native/.\n'
                'Downloaded Meson dependency sources, wrap definitions and their original licenses are included.\n'
                'Git administrative data, binary caches, user projects and secrets are excluded.\n')
        print('Source package:',output,flush=True)


if __name__=='__main__':
    main()
