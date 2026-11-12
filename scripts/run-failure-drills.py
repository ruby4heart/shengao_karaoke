"""Recovery drills: damaged files, moved paths, full disk, forced exit, interrupted render, failed model process.

Every drill works on copies in its own temporary folder; real projects,
settings and caches are never touched. A full disk is simulated with the
operating system's own "disk full" error, a forced exit with a separate
Python process that dies before its final rename, an interrupted render with
a stand-in encoder process, and a failed model with a child process that
exits the way a crashed or out-of-memory model would.

  .venv-desktop\\Scripts\\python.exe scripts\\run-failure-drills.py
  .venv-desktop\\Scripts\\python.exe scripts\\run-failure-drills.py --only damaged_project full_on_save

Prints one line per drill and writes the full report as JSON (default:
tmp\\failure-drills.json). Exit code 0 when no drill failed.
"""
from pathlib import Path
import argparse,json,platform,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'desktop'))
from shengao import failure_drill

MARK={'passed':'通过','failed':'失败','skipped':'跳过'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--only',nargs='*',help='只运行这些演练（名称见报告中的 name）')
    parser.add_argument('--out',type=Path,default=ROOT/'tmp'/'failure-drills.json',help='JSON 报告位置')
    args=parser.parse_args(argv)
    try:sys.stdout.reconfigure(errors='replace')
    except (AttributeError,ValueError):pass
    started=time.time();results=failure_drill.run(set(args.only) if args.only else None)
    if args.only and not results:print('没有找到这些演练：'+'、'.join(args.only));return 2
    group=None
    for row in results:
        if row['group']!=group:group=row['group'];print(f'\n【{group}】')
        print(f"  [{MARK[row['state']]}] {row['title']}")
        detail=row['detail'] if row['state']=='failed' else row['detail'].splitlines()[0]
        print('         '+detail.replace('\n','\n         '))
    count={state:sum(r['state']==state for r in results) for state in MARK}
    print(f"\n共 {len(results)} 项：通过 {count['passed']}，失败 {count['failed']}，跳过 {count['skipped']}（{time.time()-started:.1f} 秒）")
    report={'created':time.strftime('%Y-%m-%d %H:%M:%S'),'python':sys.version.split()[0],'platform':platform.platform(),
            'summary':count,'drills':results}
    try:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('报告：'+str(args.out))
    except OSError as error:print(f'报告没有写出（{error}）')
    return 1 if count['failed'] else 0


if __name__=='__main__':sys.exit(main())
