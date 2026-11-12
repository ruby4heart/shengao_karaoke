"""Release licence and resource check against the third-party inventory.

  .venv-desktop\\Scripts\\python.exe scripts\\check-licenses.py
      核对当前源码树：清单格式、与代码里固定指纹是否一致、文档的非商业说明，
      以及本机已有的第三方文件指纹。只在完整源码 ZIP 里才有的大文件（vendor 下的
      模型、FFmpeg、Aegisub 源码等）不在时记为“跳过”。

  .venv-desktop\\Scripts\\python.exe scripts\\check-licenses.py --full
      同上，但清单里的源码文件必须全部存在且指纹一致（用于解压后的完整源码 ZIP，
      或已放好 vendor 的 Windows 开发树）。

  .venv-desktop\\Scripts\\python.exe scripts\\check-licenses.py --package build\\desktop-dist\\shengao-karaoke
      核对运行包：清单里标为随包的文件必须全部存在、指纹一致；在 Windows 上还会
      运行包内 ffmpeg.exe -L，确认它是 LGPL 构建（未启用 GPL 和 nonfree）。

清单在 desktop/assets/licenses/THIRD-PARTY-INVENTORY.json，说明见 docs/THIRD-PARTY-LICENSES.md。
退出码 0 表示没有失败项。
"""
from pathlib import Path
import argparse, ast, hashlib, json, os, re, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'desktop' / 'assets' / 'licenses' / 'THIRD-PARTY-INVENTORY.json'
REQUIRED = {'shengao', 'aegisub', 'fonts', 'ffmpeg', 'demucs', 'tifa-code', 'tifa-model'}
HEX64 = re.compile(r'^[0-9a-f]{64}$')

# Text that must tell the reader the singing model is non-commercial.
NOTICE_FILES = ('README.md', 'docs/DESKTOP-USER-GUIDE.md', 'docs/THIRD-PARTY-LICENSES.md',
                'desktop/assets/快速开始.txt', 'vendor/GIT-SOURCE-NOTES.md')
# Places a commercial claim could slip into.
CLAIM_GLOBS = ('README.md', 'docs/*.md', 'docs/releases/*.md', 'desktop/assets/*.txt',
               'desktop/shengao/*.py', 'vendor/GIT-SOURCE-NOTES.md')
COMMERCIAL = re.compile(r'商用|商业用途|商业使用|商业授权|可商业|商业化|commercial(?:ly)?', re.I)
NEGATION = re.compile(r'不|非|未|无|没有|禁止|勿|限|并不|not\b|non-?commercial|\bno\b|never', re.I)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def matches(data, expected, text=False):
    """Byte-exact, or for text files also after Git changing CRLF/LF line endings."""
    if digest(data) == expected: return True
    if not text: return False
    lf = data.replace(b'\r\n', b'\n')
    return expected in {digest(lf), digest(lf.replace(b'\n', b'\r\n'))}


def load(path=MANIFEST):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def check_manifest(manifest):
    """Every component names its source, licence and fixed fingerprints."""
    problems = []
    components = manifest.get('components') or []
    ids = [c.get('id') for c in components]
    if len(ids) != len(set(ids)): problems.append('清单里有重复的组件编号')
    for missing in sorted(REQUIRED - set(ids)): problems.append(f'清单缺少必需组件：{missing}')
    if 'product_statement' not in manifest or '非商业' not in manifest['product_statement'] or '不宣称可商用' not in manifest['product_statement']:
        problems.append('清单的整体说明没有写明“非商业”和“不宣称可商用”')
    for c in components:
        name = c.get('id') or '?'
        for field in ('name', 'version', 'license', 'use'):
            if not str(c.get(field) or '').strip(): problems.append(f'{name}：缺少 {field}')
        upstream = c.get('upstream') or []
        if not upstream or any(not str(u).startswith('https://') for u in upstream):
            problems.append(f'{name}：来源地址必须是 https 链接')
        files = c.get('files') or []
        if not any(f.get('role') == 'artifact' or f.get('role') == 'license' for f in files):
            problems.append(f'{name}：没有任何带指纹的文件')
        for where in ('source', 'package'):
            here = [f for f in files if f.get('in') == where]
            if here and not any(f.get('role') == 'license' for f in here) and not c.get('license_file_note'):
                problems.append(f'{name}：{"源码" if where == "source" else "运行包"}里没有许可文件')
        for f in files:
            if f.get('in') not in {'source', 'package'}: problems.append(f'{name}：{f.get("path")} 的位置无效')
            if f.get('role') not in {'artifact', 'license', 'provenance'}: problems.append(f'{name}：{f.get("path")} 的类别无效')
            if not HEX64.match(str(f.get('sha256', ''))): problems.append(f'{name}：{f.get("path")} 的指纹不是 64 位 SHA256')
            path = str(f.get('path', ''))
            if not path or path.startswith(('/', '\\')) or '..' in Path(path).parts or ':' in path:
                problems.append(f'{name}：路径 {path!r} 必须是相对路径')
    noncommercial = [c for c in components if c.get('noncommercial')]
    if not any(c.get('id') == 'tifa-model' for c in noncommercial):
        problems.append('TIFA 模型权重没有标为非商业')
    for c in noncommercial:
        if 'NC' not in c.get('license', '') or '非商业' not in c.get('restriction', ''):
            problems.append(f'{c.get("id")}：标为非商业，但许可或限制说明不完整')
    for c in components:
        if not c.get('noncommercial') and re.search(r'-NC-|NonCommercial|非商业', c.get('license', '')):
            problems.append(f'{c.get("id")}：许可含非商业条款，但没有标为非商业')
    return problems


def check_files(manifest, base, where, required):
    """Return rows (component, path, status, detail); status is 通过/失败/跳过."""
    rows = []
    base = Path(base)
    for c in manifest['components']:
        for f in c['files']:
            if f['in'] != where: continue
            path = base / f['path']
            if not path.is_file():
                rows.append((c['id'], f['path'], '失败' if required else '跳过',
                             '缺少文件' if required else '本机没有（只在完整源码 ZIP 里）'))
            elif matches(path.read_bytes(), f['sha256'], f.get('text', False)):
                rows.append((c['id'], f['path'], '通过', ''))
            else:
                rows.append((c['id'], f['path'], '失败', f'指纹不符，应为 {f["sha256"][:16]}…，实际 {digest(path.read_bytes())[:16]}…'))
    return rows


def _literal(path, name):
    """A module-level constant read without importing the module (earlier constants may be referenced)."""
    known = {}
    class Inline(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.Constant(known[node.id]) if node.id in known else node
    for node in ast.parse(Path(path).read_text(encoding='utf-8')).body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)): continue
        try: known[node.targets[0].id] = ast.literal_eval(Inline().visit(node.value))
        except ValueError: continue
        if node.targets[0].id == name: return known[name]
    raise KeyError(f'{Path(path).name} 里找不到 {name}')


def code_pins(root):
    """Fingerprints the code itself enforces, keyed by the source path the manifest uses."""
    root = Path(root)
    pins = {}
    for name, sha in _literal(root / 'desktop/audio_contract.py', 'TIFA_FILES').items():
        pins['vendor/tifa-model/' + name] = sha
    pins['vendor/vocal-model/955717e8-8726e21a.th'] = _literal(root / 'desktop/vocal_engine.py', 'MODEL_SHA256')
    for name, (_, sha) in _literal(root / 'scripts/json_runtime_sources.py', 'FILES').items():
        pins['vendor/orjson/' + name] = sha
    pins['vendor/python-tls/codex-rejected-cas.pem'] = _literal(root / 'scripts/python_tls_resources.py', 'SHA256')
    build = (root / 'scripts/build-desktop.py').read_text(encoding='utf-8')
    found = re.search(r"tbb-2023\.2\.0-py3-none-win_amd64\.whl'.*?=='([0-9a-f]{64})'", build, re.S)
    if found: pins['vendor/tbb-runtime/tbb-2023.2.0-py3-none-win_amd64.whl'] = found.group(1)
    for item in json.loads((root / 'desktop/assets/fonts/SOURCES.json').read_text(encoding='utf-8')):
        pins['desktop/assets/fonts/' + item['file']] = item['sha256']
    for item in json.loads((root / 'desktop/assets/licenses/Original-Audio/SOURCES.json').read_text(encoding='utf-8')):
        pins[item['source']] = item['sha256']
    return pins


def check_pins(manifest, root):
    """The inventory and the code must not disagree about any fingerprint."""
    problems = []
    listed = {f['path']: f['sha256'] for c in manifest['components'] for f in c['files'] if f['in'] == 'source'}
    for path, sha in code_pins(root).items():
        if path not in listed: problems.append(f'代码固定了 {path}，但清单里没有')
        elif listed[path] != sha: problems.append(f'{path}：清单指纹与代码里固定的不一致')
    tifa = next(c for c in manifest['components'] if c['id'] == 'tifa-model')
    if not any(f['path'].endswith('model.pt') and f['sha256'] == _literal(Path(root) / 'desktop/audio_contract.py', 'TIFA_MODEL_SHA256') for f in tifa['files']):
        problems.append('TIFA 模型指纹与程序运行时校验的不一致')
    return problems


def sentences(text):
    return [s for s in re.split(r'(?<=[。！？!?；;])|\n', text) if s.strip()]


def commercial_claims(text):
    """Sentences that mention commercial use without any limiting word."""
    return [s.strip() for s in sentences(text) if COMMERCIAL.search(s) and not NEGATION.search(s)]


def check_wording(root):
    problems = []
    root = Path(root)
    for name in NOTICE_FILES:
        path = root / name
        if not path.is_file(): problems.append(f'找不到 {name}'); continue
        text = path.read_text(encoding='utf-8-sig')
        if '非商业' not in text: problems.append(f'{name} 没有写明歌声模型限非商业用途')
    seen = set()
    for pattern in CLAIM_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path in seen or not path.is_file(): continue
            seen.add(path)
            for claim in commercial_claims(path.read_text(encoding='utf-8-sig', errors='replace')):
                problems.append(f'{path.relative_to(root).as_posix()}：疑似宣称可商用：{claim[:80]}')
    return problems


def ffmpeg_license(executable):
    """'LGPL', 'GPL' or 'nonfree' from ffmpeg -L; None if it cannot run here."""
    try:
        result = subprocess.run([str(executable), '-hide_banner', '-L'], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    text = ' '.join((result.stdout + result.stderr).decode('utf-8', 'replace').split())  # -L wraps lines
    if 'nonfree parts compiled in' in text or 'not legally redistributable' in text: return 'nonfree'
    if 'Lesser General Public License' in text: return 'LGPL'
    if 'General Public License' in text: return 'GPL'
    return None


def check_ffmpeg(path):
    if not Path(path).is_file(): return '跳过', '本机没有 ffmpeg.exe'
    kind = ffmpeg_license(path)
    if kind is None: return '跳过', '这台电脑不能运行它，或输出里没有许可说明（Windows 上会实际检查）'
    if kind == 'LGPL': return '通过', 'ffmpeg -L 显示 LGPL 构建'
    return '失败', f'ffmpeg -L 显示 {kind} 构建，与清单写的 LGPL 不符'


def check_package_notices(manifest, package):
    """The build copies the inventory and this explanation into licenses/; both must be there."""
    package = Path(package)
    inventory = package / 'licenses' / 'Independent-Qt' / 'THIRD-PARTY-INVENTORY.json'
    missing = [p.relative_to(package).as_posix() for p in (inventory, package / 'licenses' / 'THIRD-PARTY-LICENSES.md') if not p.is_file()]
    if missing: return '失败', '缺少 ' + '、'.join(missing)
    try: bundled = json.loads(inventory.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error: return '失败', f'随包清单读不出来：{error}'
    if bundled != manifest: return '失败', '随包清单与源码里的不同（运行包可能是旧版本构建的）'
    return '通过', ''


def run(root=ROOT, package=None, full=False, manifest_path=None, show=print):
    manifest = load(manifest_path or Path(root) / 'desktop/assets/licenses/THIRD-PARTY-INVENTORY.json')
    report = {'mode': 'package' if package else ('full-source' if full else 'source'), 'checks': []}
    def add(group, item, status, detail=''):
        report['checks'].append({'group': group, 'item': item, 'status': status, 'detail': detail})
        quiet = group == '文件' and (status == '通过' or (status == '跳过' and not required))
        if not quiet: show(f'  [{status}] {group}：{item}' + (f'（{detail}）' if detail else ''))
    required = bool(package or full)
    problems = check_manifest(manifest)
    add('清单', f'{len(manifest["components"])} 个组件的来源、许可和指纹', '失败' if problems else '通过', '；'.join(problems))
    if package:
        rows = check_files(manifest, package, 'package', required=True)
        add('清单', '运行包里附带清单与许可说明', *check_package_notices(manifest, package))
        add('FFmpeg 许可', 'ffmpeg.exe', *check_ffmpeg(Path(package) / 'ffmpeg.exe'))
    else:
        pins = check_pins(manifest, root)
        add('代码指纹', '清单与程序里固定的指纹一致', '失败' if pins else '通过', '；'.join(pins))
        wording = check_wording(root)
        add('文档说明', '写明歌声模型限非商业用途，没有宣称可商用', '失败' if wording else '通过', '；'.join(wording))
        rows = check_files(manifest, root, 'source', required=full)
        if full: add('FFmpeg 许可', 'vendor/desktop-runtime/ffmpeg.exe', *check_ffmpeg(Path(root) / 'vendor/desktop-runtime/ffmpeg.exe'))
    for component, path, status, detail in rows: add('文件', f'{component} · {path}', status, detail)
    passed = sum(r[2] == '通过' for r in rows); skipped = sum(r[2] == '跳过' for r in rows)
    show(f'  [{"通过" if passed + skipped == len(rows) else "失败"}] 文件：{len(rows)} 个{"运行包" if package else "源码"}文件，'
         f'指纹一致 {passed} 个' + (f'，{skipped} 个只在完整源码 ZIP 里、本次跳过（加 --full 核对）' if skipped else ''))
    counts = {s: sum(r['status'] == s for r in report['checks']) for s in ('通过', '失败', '跳过')}
    report['counts'] = counts
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--package', type=Path, help='核对这个运行包文件夹')
    parser.add_argument('--full', action='store_true', help='源码文件必须全部存在（完整源码 ZIP）')
    parser.add_argument('--root', type=Path, default=ROOT, help='源码根目录（默认本仓库）')
    parser.add_argument('--out', type=Path, help='JSON 报告位置')
    args = parser.parse_args(argv)
    try: sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError): pass
    where = f'运行包 {args.package}' if args.package else ('完整源码 ' if args.full else '源码 ') + str(args.root)
    print(f'发行许可与资源核对：{where}\n')
    report = run(args.root, args.package, args.full)
    c = report['counts']
    print(f'\n共 {sum(c.values())} 项：通过 {c["通过"]}，失败 {c["失败"]}，跳过 {c["跳过"]}')
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('报告：' + str(args.out))
    return 1 if c['失败'] else 0


if __name__ == '__main__': sys.exit(main())
