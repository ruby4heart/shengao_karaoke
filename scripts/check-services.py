"""Online service compatibility check: mock scenarios on this computer, or one real request per service.

  .venv-desktop\\Scripts\\python.exe scripts\\check-services.py
      模拟（默认）：在本机起一个假的服务，按三家官方文档的请求与返回格式逐项检查
      上传参数、超时、限流、取消、报错解析、付费未知登记、缓存和长素材限制。不联网。

  .venv-desktop\\Scripts\\python.exe scripts\\check-services.py --real
  .venv-desktop\\Scripts\\python.exe scripts\\check-services.py --real --only elevenlabs deepseek
      真实：用软件“API 设置”里保存的密钥，把自带的 16 秒公开歌声样例 PJS056
      （CC BY-SA 4.0）发给 ElevenLabs（识别、对齐各一次）和 Microsoft AI（识别一次），
      把一句短歌词发给 DeepSeek（注音一次），会产生少量费用；另用一个故意写错的
      密钥向每家各发一次，确认“密钥无效”能被正确识别（被拒绝的请求不计费）。
      开始前会先列出要发送的内容并询问；加 --yes 跳过询问。

模拟报告写到 tmp\\service-check-mock.json；真实报告写到软件自己的数据文件夹
（service-checks 子文件夹），不进仓库。两种报告都标明“模拟”或“真实”，不会混在一起。
退出码 0 表示没有失败项。
"""
from pathlib import Path
import argparse, asyncio, json, os, platform, shutil, sys, tempfile, time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from studio_backend import api, media, service_check
from studio_backend.settings import Settings, default_home

SERVICES = {'elevenlabs': 'ElevenLabs', 'mai': 'Microsoft AI 转写', 'deepseek': 'DeepSeek'}
WRONG_KEY = 'shengao-deliberately-invalid-key-check'


def mock(args):
    print('【模拟】本机假服务，不联网；按 2026-11-12 核对的官方文档格式检查\n')
    started = time.time()
    def progress(item, problems):
        print(f"  [{'通过' if not problems else '失败'}] {SERVICES[item.service]}：{item.title}")
        for problem in problems: print('         ' + problem)
    with tempfile.TemporaryDirectory(prefix='shengao-service-mock-') as folder:
        results = asyncio.run(service_check.run_mock(folder, set(args.only_scenarios or ()), progress))
    failed = sum(bool(p) for _, p, _ in results)
    print(f'\n共 {len(results)} 项：通过 {len(results) - failed}，失败 {failed}（{time.time() - started:.1f} 秒）')
    report = {'evidence': '模拟', 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'python': sys.version.split()[0],
              'platform': platform.platform(), 'docs_checked': '2026-11-12',
              'scenarios': [{'name': item.name, 'service': item.service, 'title': item.title, 'passed': not problems,
                             'problems': problems, 'seconds': round(seconds, 2)} for item, problems, seconds in results]}
    write(args.out or ROOT / 'tmp' / 'service-check-mock.json', report)
    return 1 if failed or not results else 0


def ffmpeg_on_path():
    """The worker finds FFmpeg on PATH; borrow the desktop's bundled copy if needed."""
    try: media.ffmpeg_executable(); return True
    except ValueError: pass
    try:
        sys.path.insert(0, str(ROOT / 'desktop'))
        from shengao import paths
        os.environ['PATH'] = str(Path(paths.ffmpeg()).parent) + os.pathsep + os.environ.get('PATH', '')
        media.ffmpeg_executable(); return True
    except (ImportError, ValueError): return False


def real(args):
    home = Path(args.home) if args.home else default_home()
    settings = Settings(home)
    try: keys = {name: settings.key(name) for name in SERVICES}
    except Exception as error:  # DPAPI is Windows only; a damaged settings file also lands here
        print(f'读不到保存的密钥：{error}'); return 2
    wanted = [name for name in (args.only or SERVICES) if name in SERVICES]
    ready = [name for name in wanted if keys.get(name)]
    for name in wanted:
        if name not in ready: print(f'跳过 {SERVICES[name]}：API 设置里没有保存密钥')
    if 'mai' in ready and not settings.read().get('mai', {}).get('endpoint'):
        print('跳过 Microsoft AI 转写：API 设置里没有填写 Azure 地址'); ready.remove('mai')
    if not ready: print('没有可检查的服务。'); return 2
    plan = service_check.real_requests(args.language)
    print('【真实】将用你保存的密钥发送以下请求（会产生少量费用）：')
    for name in ready:
        for check, request in plan[name]:
            what = '一句歌词文字' if request['action'] == 'annotate' else '16 秒 PJS056 公开样例音频' + ('及其歌词' if request['action'] == 'align' else '')
            print(f'  · {SERVICES[name]}：{check}（{what}）')
        print(f'  · {SERVICES[name]}：故意写错的密钥一次（应被拒绝，不计费）')
    if not args.yes and input('\n确认发送？输入 y 后回车：').strip().lower() != 'y':
        print('已取消，没有发送任何请求。'); return 2
    if any(r['action'] != 'annotate' for name in ready for _, r in plan[name]) and not ffmpeg_on_path():
        print('找不到 FFmpeg，音频类检查无法提取音轨；请把 FFmpeg 加入 PATH 后重试。'); return 2
    stamp = time.strftime('%Y%m%d-%H%M%S')
    folder = home / 'service-checks' / f'{stamp}-real'
    reference = json.loads((service_check.REAL_SAMPLE / 'sample.json').read_text(encoding='utf-8'))
    rows = []
    for name in ready:
        for check, request in plan[name]:
            print(f'\n  {SERVICES[name]}：{check} …', flush=True)
            row = asyncio.run(service_check.real_check(check, request, home, folder))
            row['service'] = name; row['passed'] = row['ok'] and bool(row.get('lines') or row.get('kana'))
            if check == 'elevenlabs-align' and row.get('span_ms'):
                row['reference_span_ms'] = [round(reference['mora'][0]['start']), round(reference['mora'][-1]['end'])]
                row['start_error_ms'] = row['span_ms'][0] - row['reference_span_ms'][0]
                row['end_error_ms'] = row['span_ms'][1] - row['reference_span_ms'][1]
            rows.append(row); show(row)
        rows.append(wrong_key(name, plan[name][0], settings, folder)); show(rows[-1])
    failed = sum(not row['passed'] for row in rows)
    print(f'\n共 {len(rows)} 项：通过 {len(rows) - failed}，失败 {failed}')
    write(args.out or folder / 'report.json',
          {'evidence': '真实', 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'python': sys.version.split()[0],
           'platform': platform.platform(), 'language': args.language, 'sample': 'PJS056 16 s, CC BY-SA 4.0',
           'checks': rows})
    return 1 if failed else 0


def wrong_key(name, first, settings, folder):
    """The same request with a deliberately wrong key, in a scratch folder: must be rejected."""
    check, request = first
    with tempfile.TemporaryDirectory(prefix='shengao-wrong-key-') as scratch:
        endpoint = settings.read().get('mai', {}).get('endpoint', '')
        (Path(scratch) / 'settings.json').write_text(json.dumps({'mai': {'endpoint': endpoint}}), encoding='utf-8')
        print(f'\n  {SERVICES[name]}：故意写错的密钥 …', flush=True)
        with service_check.patched((Settings, 'key', lambda self, provider: WRONG_KEY)):
            row = asyncio.run(service_check.real_check(f'{name}-wrong-key', request, scratch, folder))
    row['service'] = name
    row['passed'] = row['stage'] == 'service_rejected' and row['http_status'] in {401, 403}
    return row


def show(row):
    print(f"  [{'通过' if row['passed'] else '失败'}] {row['check']}：{row['seconds']} 秒，"
          f"HTTP {row.get('http_status')}，阶段 {row.get('stage') or '完成'}，请求编号 {row.get('request_id') or '无'}")
    if row.get('text'): print(f"         返回文字：{row['text']}（{row['lines']} 行，{row['span_ms'][0]}–{row['span_ms'][1]} ms）")
    if 'start_error_ms' in row: print(f"         与人工标注相比：句首 {row['start_error_ms']:+} ms，句尾 {row['end_error_ms']:+} ms")
    if row.get('kana'): print(f"         假名：{row['kana']}")
    if row.get('message'): print(f"         {row['message']}")
    if row.get('error_code'): print(f"         错误代码：{row['error_code']}")


def write(path, report):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'); print('报告：' + str(path))
    except OSError as error: print(f'报告没有写出（{error}）')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--real', action='store_true', help='真实发送（默认只做本机模拟）')
    parser.add_argument('--only', nargs='*', choices=list(SERVICES), help='真实检查只发给这些服务')
    parser.add_argument('--only-scenarios', nargs='*', help='模拟只运行这些场景（名称见报告中的 name）')
    parser.add_argument('--language', default='ja', help='真实识别使用的语言代码（默认 ja）')
    parser.add_argument('--home', help='软件数据文件夹（默认与桌面版相同）')
    parser.add_argument('--yes', action='store_true', help='真实检查不再询问')
    parser.add_argument('--out', type=Path, help='JSON 报告位置')
    args = parser.parse_args(argv)
    try: sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError): pass
    return real(args) if args.real else mock(args)


if __name__ == '__main__': sys.exit(main())
