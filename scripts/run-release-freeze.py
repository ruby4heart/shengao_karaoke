"""发布前冻结（ToDo 11.7）：在已提交的源码上，一条命令依次跑完回归、打包、验收和发行检查，生成发布要用的证据。

  .venv-desktop\\Scripts\\python.exe scripts\\run-release-freeze.py
  .venv-desktop\\Scripts\\python.exe scripts\\run-release-freeze.py --list
  .venv-desktop\\Scripts\\python.exe scripts\\run-release-freeze.py --resume

版本号取 desktop/shengao/__init__.py。必须在 Windows 上、所有改动都已提交时运行；遇到第一个
失败就停下，说明是哪一步、完整输出在哪。源码和提交都没变时，可以用 --resume 从失败的那一步
接着跑；改了源码就要提交后重新完整跑。

全部通过后写 build\\vNNN-evidence（完整的本机证据）和 build\\desktop-final-audit-vNNN.json，
之后 package-public-evidence.py 和 publish-github-release.py 可以直接使用。
本脚本不联网、不调用收费接口、不打标签、不发布任何东西。
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from desktop_source_state import app_version, snapshot

KEYS=('ELEVENLABS_API_KEY','MAI_SPEECH_KEY','DEEPSEEK_API_KEY')   # never reach any step
PACKAGE=Path('build')/'desktop-dist'/'shengao-karaoke'


class Failure(Exception):
    """A step finished but its evidence is missing or says it did not pass."""


class Step:
    def __init__(self,name,title,command,env=None,before=None,after=None):
        self.name=name;self.title=title;self.command=[str(x) for x in command]
        self.env=env or {};self.before=before;self.after=after


def label(version):
    """Local acceptance label: 0.32.0 -> v032, 0.10.1 -> v0101, 1.0.0 -> v100."""
    major,minor,patch=(int(x) for x in version.split('.'))
    return f'v{major}{minor:02d}'+(str(patch) if patch else '')


def read_json(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):raise Failure(f'没有生成可读的结果：{path}')


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def fresh(folder,root):
    """Empty a generated folder under build\\ or tmp\\ before a step writes it again."""
    folder=Path(folder).resolve()
    assert any(folder.is_relative_to((Path(root)/x).resolve()) for x in ('build','tmp')),folder
    def clear():
        if folder.exists():shutil.rmtree(folder)
    return clear


def copy_file(source,target):
    def after():
        if not Path(source).is_file():raise Failure(f'没有生成 {source}')
        Path(target).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        return {}
    return after


def self_test(folder):
    def after():
        report=read_json(Path(folder)/'report.json')
        if not report.get('passed'):raise Failure(f'自检报告没有通过：{Path(folder)/"report.json"}')
        return {'checks':len(report.get('checks',[]))}
    return after


def standalone(root,target):
    """test-desktop-package.py leaves its report in tmp\\; keep a copy as this scale's evidence."""
    def after():
        record=read_json(Path(root)/'build'/'desktop-package-acceptance.json')
        manifest=Path(root)/PACKAGE/'package-manifest.json'
        if not record.get('passed') or record.get('manifest_sha256')!=sha(manifest):
            raise Failure('独立包验收记录没有通过，或者不是当前运行包的记录')
        source=Path(record['report']).parent;target.mkdir(parents=True,exist_ok=True)
        for item in source.iterdir():
            if item.is_file() and item.suffix in {'.json','.log'}:shutil.copy2(item,target/item.name)
        report=read_json(target/'report.json')
        if not report.get('passed'):raise Failure(f'独立包自检报告没有通过：{target/"report.json"}')
        return {'checks':len(report.get('checks',[])),'output':str(source)}
    return after


def timeline(source,target):
    def after():
        report=read_json(Path(source)/'report.json')
        if not report.get('passed') or len(report.get('cases',[]))!=6:raise Failure(f'时间轴对照没有通过：{Path(source)/"report.json"}')
        target.mkdir(parents=True,exist_ok=True);shutil.copy2(Path(source)/'report.json',target/'report.json')
        for image in Path(source).glob('*.png'):shutil.copy2(image,target/image.name)
        return {'cases':6}
    return after


def plan(root,version,evidence,python=sys.executable):
    """Every step, in order. Earlier steps make what later ones check."""
    root=Path(root);package=root/PACKAGE;dist=root/'dist'
    portable=dist/f'ShengaoKaraoke-{version}-final-win64.zip';source=dist/f'ShengaoKaraoke-{version}-source.zip'
    normal={'QT_SCALE_FACTOR':None};dpi150={'QT_SCALE_FACTOR':'1.5'}
    tools=[p for p in (root/'vendor'/'desktop-runtime',dist/'ShengaoKaraoke-0.7.0-final-win64') if p.is_dir()]
    home=root/'tmp'/('release-freeze-home-'+label(version))
    development={**normal,'QT_QPA_PLATFORM':'offscreen','SHENGAO_HOME':str(home),
                 'PYTHONPATH':os.pathsep.join([str(root/'desktop'),str(root/'backend')]),
                 'PATH':os.pathsep.join([*map(str,tools),os.environ.get('PATH','')])}
    pixels=root/'tmp'/'timeline-full-pixels';pixels150=root/'tmp'/'timeline-full-pixels-dpi150'
    return [
        Step('regression','完整源码回归（desktop 和 backend 全部测试）',[python,'scripts/test-desktop.py'],normal),
        Step('build','构建独立运行包',[python,'scripts/build-desktop.py'],normal),
        Step('dependencies','运行包全部 DLL 依赖',[python,'scripts/check-desktop-dependencies.py'],normal,
             after=copy_file(root/'build'/'desktop-dependencies.json',evidence/'desktop-dependencies.json')),
        Step('development','开发版自检',[python,'desktop/main.py','--self-test','--output',evidence/'development'],development,
             before=fresh(home,root),after=self_test(evidence/'development')),
        Step('standalone-normal','独立包自检（正常缩放）',[python,'scripts/test-desktop-package.py'],normal,
             after=standalone(root,evidence/'standalone-normal')),
        Step('standalone-dpi150','独立包自检（150% 缩放）',[python,'scripts/test-desktop-package.py'],dpi150,
             after=standalone(root,evidence/'standalone-dpi150')),
        Step('timeline-normal','原版时间轴逐像素对照（正常缩放）',[python,'scripts/compare-timeline-scene.py','--output',pixels],normal,
             before=fresh(pixels,root),after=timeline(pixels,evidence/'timeline-full-pixels')),
        Step('timeline-dpi150','原版时间轴逐像素对照（150% 缩放）',[python,'scripts/compare-timeline-scene.py','--output',pixels150],dpi150,
             before=fresh(pixels150,root),after=timeline(pixels150,evidence/'timeline-full-pixels-dpi150')),
        Step('window-checks','窗口检查（正常、150%、关闭可选优化）',
             [python,'scripts/run-window-checks.py','--package',package,'--out',evidence/'window-checks'],normal),
        Step('failure-drills','故障演练',[python,'scripts/run-failure-drills.py','--out',evidence/'failure-drills.json'],normal),
        Step('services','外部服务兼容（本机模拟，不联网）',[python,'scripts/check-services.py','--out',evidence/'services-simulated.json'],normal),
        Step('licenses','许可与第三方资源（完整源码和运行包）',
             [python,'scripts/check-licenses.py','--full','--package',package,'--out',evidence/'licenses.json'],normal),
        Step('prepare','生成便携包、源码包和 SHA256',[python,'scripts/prepare-desktop-release.py','--version',version],normal),
        Step('archives','核对两个发行包',[python,'scripts/check-release.py','--version',version],normal,
             after=copy_file(root/'build'/'archive-check.json',evidence/'archive-check.json')),
        Step('privacy','隐私检查（发行包里没有密钥和私人素材）',[python,'scripts/check-privacy.py','--archives',portable,source],normal),
    ]


def execute(step,log,root):
    """Run one step with its output shown live and kept in its log."""
    env={k:v for k,v in os.environ.items() if k not in KEYS};env['PYTHONIOENCODING']='utf-8'
    for key,value in step.env.items():
        if value is None:env.pop(key,None)
        else:env[key]=value
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('wb') as file,subprocess.Popen(step.command,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT) as process:
        for line in process.stdout:
            file.write(line);sys.stdout.buffer.write(line);sys.stdout.buffer.flush()
        return process.wait()


def git(root,*args):
    return subprocess.run(['git',*args],cwd=root,capture_output=True,text=True,check=True).stdout.strip()


def readme(version,tag,commit,stamp,records):
    lines=[f'声稿 {version} 发布前冻结证据（{tag}）',f'提交：{commit}',f'完成时间：{stamp}','',f'全部 {len(records)} 步通过：']
    lines+=[f"  {i}. {r['title']}（{r['seconds']:.0f} 秒）" for i,r in enumerate(records,1)]
    lines+=['','内容：',
            f'  desktop-final-audit-{tag}.json  总审计；发布脚本只认这份',
            f'  SHA256SUMS-{version}.txt  便携包和源码包的指纹',
            '  development、standalone-normal、standalone-dpi150  开发版与两档缩放独立包的自检报告',
            '  timeline-full-pixels、timeline-full-pixels-dpi150  原版时间轴逐像素对照',
            '  window-checks  窗口检查报告和截图（合成素材）',
            '  failure-drills.json、services-simulated.json、licenses.json、archive-check.json、desktop-dependencies.json  其余检查的报告',
            '  logs  每一步的完整输出','',
            '这个文件夹只留在本机。公开的精简证据用 package-public-evidence.py 生成，不含私人工程、缓存和 MV 画面。','']
    return '\n'.join(lines)


def freeze(root=ROOT,argv=None,run=execute,git=git,windows=None):
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--list',action='store_true',help='只列出步骤，不运行')
    parser.add_argument('--resume',action='store_true',help='源码和提交都没变时，跳过上次已通过的步骤')
    args=parser.parse_args(argv)
    root=Path(root);version=app_version(root);tag=label(version)
    evidence=root/'build'/(tag+'-evidence');progress_path=evidence/'freeze-progress.json'
    audit_name=f'desktop-final-audit-{tag}.json'
    steps=plan(root,version,evidence)
    if args.list:
        print(f'声稿 {version}（{tag}）发布前冻结共 {len(steps)} 步：')
        for i,step in enumerate(steps,1):print(f'  {i:2}. {step.title}  [{step.name}]')
        return 0
    def stop(message):
        print('[停止] '+message);return 2
    if not (os.name=='nt' if windows is None else windows):return stop('发布前冻结要在 Windows 上运行（要用打包好的 shengao-karaoke.exe）。')
    if git(root,'status','--porcelain'):return stop('有还没提交的改动。冻结只认已提交的源码：先提交，再运行。')
    commit=git(root,'rev-parse','HEAD');sources=snapshot(root)
    if (evidence/audit_name).is_file():
        return stop(f'{version} 已经冻结过（{evidence/audit_name}）。要重新冻结，请换一个新版本号。')
    release=[root/'dist'/n for n in (f'ShengaoKaraoke-{version}-final-win64.zip',f'ShengaoKaraoke-{version}-source.zip',
                                     f'ShengaoKaraoke-{version}-final-win64',f'SHA256SUMS-{version}.txt')]
    records=[]
    if args.resume:
        try:progress=json.loads(progress_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):return stop('没有找到上次的进度，请去掉 --resume 重新完整运行。')
        if progress.get('version')!=version or progress.get('commit')!=commit or progress.get('sources')!=sources:
            return stop('源码或提交和上次不一样，不能接着跑。请去掉 --resume 重新完整运行。')
        records=[r for r in progress.get('steps',[]) if r.get('passed')]
    else:
        if found:=[p.name for p in release if p.exists()]:
            return stop(f'dist 里已有这个版本的发行文件：{"、".join(found)}。如果是上次没跑完留下的，先删掉它们，或者用 --resume 接着跑。')
        if evidence.exists():
            print(f'删除上次没跑完的证据文件夹 {evidence}');shutil.rmtree(evidence)
    evidence.mkdir(parents=True,exist_ok=True)
    done={r['name'] for r in records}
    def save():
        progress_path.write_text(json.dumps({'version':version,'commit':commit,'sources':sources,'steps':records},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'声稿 {version}（{tag}）发布前冻结，提交 {commit[:12]}，共 {len(steps)} 步')
    for index,step in enumerate(steps,1):
        if step.name in done:
            print(f'\n[已通过] 第 {index} 步：{step.title}（上次已通过，跳过）');continue
        print(f'\n== 第 {index}/{len(steps)} 步：{step.title}',flush=True)
        log=evidence/'logs'/(step.name+'.log');started=time.monotonic()
        try:
            if step.before:step.before()
            code=run(step,log,root)
            if code!=0:raise Failure(f'退出码 {code}')
            details=step.after() if step.after else {}
        except Failure as error:
            save()
            print(f'\n[失败] 第 {index} 步「{step.title}」没有通过：{error}')
            print(f'完整输出：{log}')
            print('排除问题后：没改源码可以加 --resume 从这一步接着跑；改了源码要先提交，再重新完整运行。')
            return 1
        records.append({'name':step.name,'title':step.title,'passed':True,'seconds':round(time.monotonic()-started,1),
                        'log':log.relative_to(evidence).as_posix(),'details':details})
        save();print(f'[通过] 第 {index} 步：{step.title}')
    if snapshot(root)!=sources or git(root,'rev-parse','HEAD')!=commit or git(root,'status','--porcelain'):
        print('\n[失败] 冻结期间源码或提交发生了变化，这次的结果不能用于发布。请提交后重新完整运行。');return 1
    sums=root/'dist'/f'SHA256SUMS-{version}.txt';shutil.copy2(sums,evidence/sums.name)
    stamp=datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    release_record=read_json(root/'build'/'desktop-release.json')
    audit={'passed':True,'version':version,'label':tag,'tag':'v'+version,'commit':commit,'frozen_at':stamp,
           'platform':platform.platform(),'python':platform.python_version(),
           'manifest_sha256':sha(root/PACKAGE/'package-manifest.json'),'release':release_record.get('files',[]),
           'steps':records,'sources':sources}
    text=json.dumps(audit,ensure_ascii=False,indent=2)
    (evidence/audit_name).write_text(text,encoding='utf-8');(root/'build'/audit_name).write_text(text,encoding='utf-8')
    (evidence/'README.txt').write_text(readme(version,tag,commit,stamp,records),encoding='utf-8')
    print(f'\n全部 {len(steps)} 步通过。证据在 {evidence}')
    print(f'发行包：{root/"dist"}（{"、".join(r["file"] for r in audit["release"])}）')
    print('还没有打标签、推送或发布。决定发布时按 docs\\DESKTOP-BUILD.md 的“发布”一节操作。')
    return 0


def main(argv=None):
    try:sys.stdout.reconfigure(errors='replace')
    except (AttributeError,ValueError):pass
    return freeze(argv=argv)


if __name__=='__main__':sys.exit(main())
