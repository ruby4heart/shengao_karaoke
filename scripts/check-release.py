"""Check a finished release before it goes out: both archives open cleanly, the portable ZIP is
exactly the accepted package, the source ZIP carries the current sources, and the SHA256 list matches.

  .venv-desktop\\Scripts\\python.exe scripts\\check-release.py
  .venv-desktop\\Scripts\\python.exe scripts\\check-release.py --version 0.32.0

The version defaults to the one in desktop/shengao/__init__.py. Reads dist\\ and the accepted
package in build\\desktop-dist\\shengao-karaoke, writes build\\archive-check.json and changes
nothing else. Exit code 0 when everything matches. Native DLL dependencies are checked by
scripts\\check-desktop-dependencies.py; licences by scripts\\check-licenses.py.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import zipfile
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from desktop_source_state import app_version

# Same filter as prepare-desktop-release.py uses when it writes the source ZIP.
SKIP_FOLDERS={'.git','.venv','.venv-desktop','__pycache__','.pytest_cache','packagecache'}
PRIVATE={'.git','.venv','.venv-desktop','__pycache__','.pytest_cache','.env'}
SOURCE_FOLDERS=('desktop','backend','scripts','docs','demo','vendor','native')
SOURCE_FILES=('README.md','meson.build','.gitignore')
SOURCE_PREFIX='karaoke-studio/'
REQUIRED=('shengao-karaoke.exe','ffmpeg.exe','shengao-audio.dll','shengao-render.dll','shengao-view.dll',
          '使用说明.md','首次使用指南.md','快速开始.txt','INDEPENDENT-STUDIO.txt','package-manifest.json',
          'licenses/THIRD-PARTY-LICENSES.md')
SHOWN=8


def names(version):
    base=f'ShengaoKaraoke-{version}'
    return {'package':base+'-final-win64','portable':base+'-final-win64.zip',
            'source':base+'-source.zip','sums':f'SHA256SUMS-{version}.txt'}


def tree(folder):
    for directory,folders,files in os.walk(folder):
        folders[:]=[x for x in folders if x not in SKIP_FOLDERS]
        for name in files:
            if name in {'.git','.env'} or name.endswith(('.pyc','.pyo')):continue
            yield Path(directory)/name


def file_crc(path):
    value=0
    with path.open('rb') as stream:
        while chunk:=stream.read(1<<20):value=zlib.crc32(chunk,value)
    return value


def file_sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def listing(title,items):
    items=sorted(items)
    more=f' 等 {len(items)} 个' if len(items)>SHOWN else ''
    return title+'：'+'、'.join(items[:SHOWN])+more


def common(archive):
    """Problems no archive may have."""
    problems=[];entries=archive.namelist()
    if len(entries)!=len(set(entries)):problems.append('有重复的文件条目')
    private=[n for n in entries if PRIVATE&set(Path(n).parts) or n.endswith(('.pyc','.pyo'))]
    if private:problems.append(listing('包含不该发布的文件',private))
    return problems


def check_portable(path,package,version):
    """The portable ZIP holds exactly the files of the accepted package, byte for byte."""
    prefix=names(version)['package']+'/'
    with zipfile.ZipFile(path) as archive:
        problems=common(archive);entries=[i for i in archive.infolist() if not i.is_dir()]
        outside=[i.filename for i in entries if not i.filename.startswith(prefix)]
        if outside:problems.append(listing(f'有文件不在 {prefix} 文件夹里',outside))
        try:raw=archive.read(prefix+'package-manifest.json');manifest=json.loads(raw)
        except (KeyError,ValueError):return problems+['缺少或读不懂 package-manifest.json'],len(entries)
        if manifest.get('version')!=version:problems.append(f'运行包版本是 {manifest.get("version")}，不是 {version}')
        accepted=Path(package)/'package-manifest.json'
        if not accepted.is_file():problems.append(f'找不到验收过的运行包：{package}')
        elif accepted.read_bytes()!=raw:problems.append('便携包里的文件清单和验收过的运行包不同（可能是旧包）')
        missing=[n for n in REQUIRED if prefix+n not in archive.NameToInfo]
        if missing:problems.append(listing('缺少必需文件',missing))
        expected={prefix+f['path']:f['sha256'] for f in manifest.get('files',[])}
        present={i.filename for i in entries}
        absent=[n[len(prefix):] for n in expected if n not in present]
        if absent:problems.append(listing('清单里的文件不在包里',absent))
        extra=[n[len(prefix):] for n in present-set(expected)-{prefix+'package-manifest.json'} if n.startswith(prefix)]
        if extra:problems.append(listing('有清单里没有的文件',extra))
        broken=[];changed=[]
        for info in entries:
            digest=hashlib.sha256()
            try:
                with archive.open(info) as stream:
                    while chunk:=stream.read(1<<20):digest.update(chunk)
            except (zipfile.BadZipFile,zlib.error,EOFError):broken.append(info.filename);continue
            if info.filename in expected and digest.hexdigest()!=expected[info.filename]:changed.append(info.filename[len(prefix):])
        if broken:problems.append(listing('文件损坏（校验不符）',broken))
        if changed:problems.append(listing('内容和清单记录的不同',changed))
    return problems,len(entries)


def check_source(path,root):
    """The source ZIP carries the current sources and nothing outside the published folders."""
    root=Path(root)
    with zipfile.ZipFile(path) as archive:
        problems=common(archive);entries={i.filename:i for i in archive.infolist() if not i.is_dir()}
        bad=archive.testzip()
        if bad:problems.append('文件损坏（校验不符）：'+bad)
        allowed=set(SOURCE_FOLDERS)
        outside=[n for n in entries if not n.startswith(SOURCE_PREFIX)
                 or (n[len(SOURCE_PREFIX):].split('/')[0] not in allowed and n[len(SOURCE_PREFIX):] not in (*SOURCE_FILES,'SOURCE-NOTES.txt'))]
        if outside:problems.append(listing('有文件不在发布的源码文件夹里',outside))
        if SOURCE_PREFIX+'SOURCE-NOTES.txt' not in entries:problems.append('缺少 SOURCE-NOTES.txt')
        current=[p for folder in SOURCE_FOLDERS for p in tree(root/folder)]
        current+=[root/name for name in SOURCE_FILES if (root/name).is_file()]
        missing=[];stale=[];wanted=set()
        for item in current:
            name=SOURCE_PREFIX+item.relative_to(root).as_posix();wanted.add(name);info=entries.get(name)
            if info is None:missing.append(name[len(SOURCE_PREFIX):])
            elif info.file_size!=item.stat().st_size or info.CRC!=file_crc(item):stale.append(name[len(SOURCE_PREFIX):])
        if missing:problems.append(listing('源码包缺少当前源码里的文件',missing))
        if stale:problems.append(listing('源码包里的文件不是当前版本',stale))
        gone=[n[len(SOURCE_PREFIX):] for n in entries if n not in wanted and n!=SOURCE_PREFIX+'SOURCE-NOTES.txt' and n not in outside]
        if gone:problems.append(listing('源码包里有当前源码已经没有的文件',gone))
    return problems,len(entries)


def check_sums(path,files):
    """SHA256SUMS lists exactly the two archives with their current digests."""
    if not path.is_file():return [f'找不到 {path.name}'],{}
    problems=[];listed={}
    for row in path.read_text(encoding='utf-8').splitlines():
        parts=row.split()
        if len(parts)!=2:problems.append('看不懂这一行：'+row);continue
        listed[parts[1]]=parts[0]
    digests={}
    for item in files:
        if not item.is_file():continue
        digests[item.name]=file_sha(item)
        if item.name not in listed:problems.append(f'没有列出 {item.name}')
        elif listed[item.name]!=digests[item.name]:problems.append(f'{item.name} 的 SHA256 和文件不符')
    extra=set(listed)-{f.name for f in files}
    if extra:problems.append(listing('列出了不属于本版的文件',extra))
    return problems,digests


def check(root,version):
    root=Path(root);dist=root/'dist';n=names(version)
    portable=dist/n['portable'];source=dist/n['source'];sums=dist/n['sums']
    report={'version':version,'archives':{},'checks':[]}
    for title,path,run in [('便携包',portable,lambda p:check_portable(p,root/'build/desktop-dist/shengao-karaoke',version)),
                           ('源码包',source,lambda p:check_source(p,root))]:
        if not path.is_file():problems,entries=[f'找不到 {path.name}'],0
        else:
            try:problems,entries=run(path)
            except zipfile.BadZipFile as error:problems,entries=[f'打不开：{error}'],0
        report['checks'].append({'name':title,'file':path.name,'passed':not problems,'problems':problems})
        if path.is_file():report['archives'][path.name]={'bytes':path.stat().st_size,'entries':entries}
    problems,digests=check_sums(sums,[portable,source])
    for name,digest in digests.items():report['archives'].setdefault(name,{})['sha256']=digest
    report['checks'].append({'name':'SHA256 列表','file':sums.name,'passed':not problems,'problems':problems})
    report['passed']=all(c['passed'] for c in report['checks'])
    return report


def text(report):
    lines=[]
    for item in report['checks']:
        lines.append(f"[{'通过' if item['passed'] else '失败'}] {item['name']} {item['file']}")
        lines+=['         '+p for p in item['problems']]
    lines.append(f"\n{report['version']} 的发行包{'全部核对通过' if report['passed'] else '有问题，先不要发布'}")
    return '\n'.join(lines)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--version',help='要核对的版本（默认取 desktop/shengao/__init__.py）')
    parser.add_argument('--root',type=Path,default=ROOT,help='源码根目录（默认本仓库）')
    args=parser.parse_args(argv)
    try:sys.stdout.reconfigure(errors='replace')
    except (AttributeError,ValueError):pass
    version=args.version or app_version(args.root)
    report=check(args.root,version)
    out=Path(args.root)/'build'/'archive-check.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(text(report))
    return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())
