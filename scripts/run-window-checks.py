"""Window checks at normal and 150 % scale and with every optional speed-up off: window sizes, save and reopen, failure recovery, render cancel.

Each run starts its own offscreen instance of the program with its own
settings folder inside the output folder; nothing appears on screen and the
person's projects, settings and caches are never touched.

  .venv-desktop\\Scripts\\python.exe scripts\\run-window-checks.py
  .venv-desktop\\Scripts\\python.exe scripts\\run-window-checks.py --package build\\desktop-dist\\shengao-karaoke

The third run (basic) starts with GPU preview off and one background task at a
time, saved in its own settings folder the way the settings window saves them,
so the whole flow is shown to work without the optional speed-ups.

Prints every check in Chinese, writes report.json, window-layout.json and a
picture per window size into tmp\\window-checks\\normal, ...\\dpi150 and ...\\basic.
Exit code 0 when every run passed.
"""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]

RUNS=(('normal','正常缩放（100%）',None),('dpi150','150% 缩放',('QT_SCALE_FACTOR','1.5')),
      ('basic','关闭可选优化（不用 GPU 预览、后台一次只做 1 个任务）',None))
# Settings each run starts with; the same names the settings window writes.
PREFERENCES={'basic':{'preview_gpu':False,'local_worker_limit':1}}
DROP={'PYTHONPATH','PYTHONHOME','ELEVENLABS_API_KEY','MAI_SPEECH_KEY','DEEPSEEK_API_KEY',
      'QT_SCALE_FACTOR','QT_SCREEN_SCALE_FACTORS','QT_AUTO_SCREEN_SCALE_FACTOR','QT_FONT_DPI'}


def command(package,out):
    if package:return [str(Path(package)/'shengao-karaoke.exe'),'--window-check','--output',str(out)]
    return [sys.executable,str(ROOT/'desktop'/'main.py'),'--window-check','--output',str(out)]


def run_once(package,out,extra,preferences=None):
    if out.exists():shutil.rmtree(out)
    out.mkdir(parents=True)
    if preferences:
        (out/'home').mkdir();(out/'home'/'workspace.json').write_text(json.dumps(preferences),encoding='utf-8')
    env={k:v for k,v in os.environ.items() if k not in DROP}
    env['QT_QPA_PLATFORM']='offscreen';env['SHENGAO_HOME']=str(out/'home')
    if extra:env[extra[0]]=extra[1]
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    try:
        result=subprocess.run(command(package,out),env=env,cwd=out,capture_output=True,timeout=600,creationflags=flags)
        code=result.returncode;(out/'stdout.log').write_bytes(result.stdout);(out/'stderr.log').write_bytes(result.stderr)
    except subprocess.TimeoutExpired:code='timeout'
    try:report=json.loads((out/'report.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):report=None
    return code,report


def show(title,code,report,out,preferences=None):
    print(f'\n【{title}】')
    if report is None:
        why='超过 10 分钟没有结束' if code=='timeout' else f'程序退出码 {code}，没有写出报告'
        print(f'  [失败] {why}；完整输出见 {out/"stderr.log"}')
        try:tail=(out/'stderr.log').read_text(encoding='utf-8',errors='replace').strip().splitlines()[-3:]
        except OSError:tail=[]
        for line in tail:print('         '+line)
        return False
    print(f"  画面倍率 {report.get('device_pixel_ratio')}，用时 {report.get('seconds')} 秒")
    settings_ok=True
    if 'preview_gpu' in report:
        print(f"  可选优化：GPU 预览{'开' if report['preview_gpu'] else '关'}，后台任务并行数 {report.get('worker_limit') or '系统默认'}"
              f"（线程上限 {report.get('thread_limit')}），轻量预览{'开' if report.get('light_preview') else '关'}")
    if preferences:
        settings_ok=report.get('preview_gpu')==preferences['preview_gpu'] and report.get('worker_limit')==preferences['local_worker_limit']
        if report.get('worker_limit'):settings_ok=settings_ok and report.get('thread_limit')==report['worker_limit']
        print(f"  [{'通过' if settings_ok else '失败'}] 启动时读取了关闭可选优化的设置")
    for group in report.get('groups',[]):
        if not group.get('completed'):
            print(f"  [失败] “{group['title']}”没有做完")
            if group.get('error'):print('         '+group['error'].strip().replace('\n','\n         '))
    for row in report.get('checks',[]):
        if row['name'].startswith('layout_'):continue
        print(f"  [{'通过' if row['passed'] else '失败'}] {row['title'] or row['name']}")
    for case in report.get('layout',[]):
        print(f"  [{'通过' if not case['problems'] else '失败'}] 窗口尺寸：{case['label']}")
        for problem in case['problems']:print('         '+problem)
    passed=bool(report.get('passed')) and code==0 and settings_ok
    if not passed and not report.get('checks'):print(f'  [失败] 没有完成任何检查；最后的状态：{report.get("last_status","")}')
    return passed


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--package',type=Path,help='检查打包好的程序（文件夹里有 shengao-karaoke.exe）；不写则检查源码')
    parser.add_argument('--out',type=Path,default=ROOT/'tmp'/'window-checks',help='输出文件夹')
    parser.add_argument('--only',choices=[key for key,_,_ in RUNS],help='只跑其中一种')
    args=parser.parse_args(argv)
    try:sys.stdout.reconfigure(errors='replace')
    except (AttributeError,ValueError):pass
    if args.package and not (args.package/'shengao-karaoke.exe').is_file():
        print(f'找不到 {args.package/"shengao-karaoke.exe"}');return 2
    results=[]
    for key,title,extra in RUNS:
        if args.only and key!=args.only:continue
        out=(args.out/key).resolve();code,report=run_once(args.package,out,extra,PREFERENCES.get(key))
        results.append(show(title,code,report,out,PREFERENCES.get(key)))
    print(f"\n{'全部通过' if all(results) else '有检查没有通过'}；报告和截图在 {args.out.resolve()}")
    return 0 if all(results) else 1


if __name__=='__main__':sys.exit(main())
