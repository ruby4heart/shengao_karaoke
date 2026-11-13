"""Release freeze (ToDo 11.7): one command runs every regression, packaging and release check in
order on committed sources, stops at the first failure, and leaves exactly the evidence that
package-public-evidence.py and publish-github-release.py read. check-release.py checks the
archives of the current version instead of a fixed old one.

The real steps need Windows, the built package and the full vendor tree; here every step is
stubbed and only writes what the real one would, so ordering, stopping, resuming and the audit
are what is tested."""
from pathlib import Path
import hashlib, importlib.util, json, os, sys, zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, file):
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(ROOT / 'scripts'))
    return module


@pytest.fixture(scope='module')
def freeze():
    return load('run_release_freeze', 'run-release-freeze.py')


@pytest.fixture(scope='module')
def release():
    return load('check_release', 'check-release.py')


VERSION = '0.32.0'


def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
    return path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_package(root, version=VERSION):
    """A tiny accepted package with every required file and its manifest."""
    package = root / 'build/desktop-dist/shengao-karaoke'
    files = {name: f'{name} body'.encode() for name in
             ('shengao-karaoke.exe', 'ffmpeg.exe', 'shengao-audio.dll', 'shengao-render.dll', 'shengao-view.dll',
              '使用说明.md', '首次使用指南.md', '快速开始.txt', 'INDEPENDENT-STUDIO.txt',
              'licenses/THIRD-PARTY-LICENSES.md', '_internal/python312.dll')}
    for name, data in files.items(): write(package / name, data)
    manifest = {'application': 'Shengao Independent Studio', 'version': version,
                'files': [{'path': n, 'sha256': sha(d), 'size': len(d)} for n, d in files.items()]}
    write(package / 'package-manifest.json', json.dumps(manifest, indent=2))
    return package


def make_tree(root, version=VERSION):
    write(root / 'desktop/shengao/__init__.py', f"__version__ = '{version}'\n")
    write(root / 'backend/studio_backend/a.py', 'x = 1\n')
    write(root / 'scripts/tool.py', 'print(1)\n')
    write(root / 'docs/guide.md', '# guide\n')
    write(root / 'vendor/big/model.bin', b'\0' * 100)
    for name in ('README.md', 'meson.build', '.gitignore'): write(root / name, name)


def make_release(root, version=VERSION):
    """What prepare-desktop-release.py writes, built the same way."""
    release_module = load('check_release_helper', 'check-release.py')
    names = release_module.names(version); dist = root / 'dist'; dist.mkdir(exist_ok=True)
    package = root / 'build/desktop-dist/shengao-karaoke'
    with zipfile.ZipFile(dist / names['portable'], 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in package.rglob('*') if p.is_file()):
            archive.write(path, names['package'] + '/' + path.relative_to(package).as_posix())
    with zipfile.ZipFile(dist / names['source'], 'w', zipfile.ZIP_DEFLATED) as archive:
        for folder in release_module.SOURCE_FOLDERS:
            for path in release_module.tree(root / folder):
                archive.write(path, 'karaoke-studio/' + path.relative_to(root).as_posix())
        for name in release_module.SOURCE_FILES:
            archive.write(root / name, 'karaoke-studio/' + name)
        archive.writestr('karaoke-studio/SOURCE-NOTES.txt', 'notes\n')
    records = [{'file': names[k], 'size': (dist / names[k]).stat().st_size, 'sha256': sha((dist / names[k]).read_bytes())}
               for k in ('portable', 'source')]
    write(dist / names['sums'], ''.join(f"{r['sha256']}  {r['file']}\n" for r in records))
    write(root / 'build/desktop-release.json', json.dumps({'version': version, 'files': records}))
    return names


@pytest.fixture
def tree(tmp_path):
    make_tree(tmp_path); make_package(tmp_path)
    return tmp_path


# ---------------------------------------------------------------- check-release.py

def test_release_names_follow_the_version(release):
    assert release.names('0.32.0') == {'package': 'ShengaoKaraoke-0.32.0-final-win64',
                                       'portable': 'ShengaoKaraoke-0.32.0-final-win64.zip',
                                       'source': 'ShengaoKaraoke-0.32.0-source.zip', 'sums': 'SHA256SUMS-0.32.0.txt'}
    text = (ROOT / 'scripts/check-release.py').read_text(encoding='utf-8')
    assert '0.7.0' not in text and 'app_version' in text


def test_a_matching_release_passes_and_defaults_to_the_app_version(release, tree, capsys):
    make_release(tree)
    report = release.check(tree, VERSION)
    assert report['passed'], report
    assert set(report['archives']) == {'ShengaoKaraoke-0.32.0-final-win64.zip', 'ShengaoKaraoke-0.32.0-source.zip'}
    assert all(len(a['sha256']) == 64 and a['entries'] > 0 for a in report['archives'].values())
    assert release.main(['--root', str(tree)]) == 0
    saved = json.loads((tree / 'build/archive-check.json').read_text(encoding='utf-8'))
    assert saved['passed'] and saved['version'] == VERSION
    assert '全部核对通过' in capsys.readouterr().out


def problems(report, name):
    return ' '.join(next(c for c in report['checks'] if c['name'] == name)['problems'])


def rezip(path, change):
    """Rewrite a ZIP with one entry replaced (or removed when change returns None)."""
    with zipfile.ZipFile(path) as archive:
        entries = [(i.filename, archive.read(i)) for i in archive.infolist()]
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            data = change(name, data)
            if data is not None: archive.writestr(name, data)


def test_portable_content_must_match_the_accepted_manifest(release, tree):
    names = make_release(tree)
    rezip(tree / 'dist' / names['portable'],
          lambda n, d: b'tampered' if n.endswith('shengao-view.dll') else d)
    report = release.check(tree, VERSION)
    assert not report['passed'] and '内容和清单记录的不同' in problems(report, '便携包') and 'shengao-view.dll' in problems(report, '便携包')
    assert 'SHA256' in problems(report, 'SHA256 列表')      # the archive changed after its digest was listed


def test_portable_missing_required_file_and_wrong_version_are_reported(release, tree):
    names = make_release(tree)
    rezip(tree / 'dist' / names['portable'], lambda n, d: None if n.endswith('首次使用指南.md') else d)
    report = release.check(tree, VERSION)
    assert '缺少必需文件' in problems(report, '便携包') and '首次使用指南.md' in problems(report, '便携包')
    other = release.check(tree, '0.33.0')
    assert '找不到 ShengaoKaraoke-0.33.0-final-win64.zip' in problems(other, '便携包')


def test_portable_from_an_older_build_is_caught(release, tree):
    make_release(tree)
    make_package(tree, '0.31.0')          # package rebuilt after the ZIP was made
    report = release.check(tree, VERSION)
    assert '和验收过的运行包不同' in problems(report, '便携包')


def test_private_files_in_an_archive_fail(release, tree):
    names = make_release(tree)
    with zipfile.ZipFile(tree / 'dist' / names['source'], 'a') as archive:
        archive.writestr('karaoke-studio/backend/.env', 'KEY=1')
    report = release.check(tree, VERSION)
    assert '包含不该发布的文件' in problems(report, '源码包') and '.env' in problems(report, '源码包')


def test_source_zip_must_carry_current_sources(release, tree):
    make_release(tree)
    write(tree / 'scripts/tool.py', 'print(2)\n')            # changed after packing
    write(tree / 'docs/new.md', 'new\n')                     # added after packing
    (tree / 'docs/guide.md').unlink()                        # removed after packing
    report = release.check(tree, VERSION)
    text = problems(report, '源码包')
    assert '不是当前版本' in text and 'scripts/tool.py' in text
    assert '缺少当前源码里的文件' in text and 'docs/new.md' in text
    assert '已经没有的文件' in text and 'docs/guide.md' in text
    assert next(c for c in report['checks'] if c['name'] == '便携包')['passed']


def test_sums_must_list_exactly_both_archives(release, tree):
    names = make_release(tree)
    sums = tree / 'dist' / names['sums']
    sums.write_text(sums.read_text(encoding='utf-8').splitlines()[0] + '\n' + '0' * 64 + '  other.zip\n', encoding='utf-8')
    text = problems(release.check(tree, VERSION), 'SHA256 列表')
    assert '没有列出 ShengaoKaraoke-0.32.0-source.zip' in text and 'other.zip' in text
    sums.unlink()
    assert '找不到 SHA256SUMS-0.32.0.txt' in problems(release.check(tree, VERSION), 'SHA256 列表')


# ---------------------------------------------------------------- run-release-freeze.py

@pytest.mark.parametrize('version,expected', [('0.32.0', 'v032'), ('0.31.0', 'v031'), ('0.11.0', 'v011'),
                                              ('0.10.1', 'v0101'), ('1.0.0', 'v100')])
def test_acceptance_label_matches_earlier_releases(freeze, version, expected):
    assert freeze.label(version) == expected


EXPECTED = ['regression', 'build', 'dependencies', 'development', 'standalone-normal', 'standalone-dpi150',
            'timeline-normal', 'timeline-dpi150', 'window-checks', 'failure-drills', 'services', 'licenses',
            'prepare', 'archives', 'privacy']


def test_plan_runs_every_check_in_order_without_paid_calls(freeze, tree):
    evidence = tree / 'build/v032-evidence'
    steps = freeze.plan(tree, VERSION, evidence, python='py')
    assert [s.name for s in steps] == EXPECTED
    by = {s.name: s for s in steps}
    assert by['standalone-dpi150'].env['QT_SCALE_FACTOR'] == '1.5' and by['timeline-dpi150'].env['QT_SCALE_FACTOR'] == '1.5'
    assert all(by[n].env['QT_SCALE_FACTOR'] is None for n in EXPECTED if not n.endswith('dpi150'))
    assert by['prepare'].command[-2:] == ['--version', VERSION] and by['archives'].command[-2:] == ['--version', VERSION]
    assert by['privacy'].command[-2:] == [str(tree / 'dist/ShengaoKaraoke-0.32.0-final-win64.zip'), str(tree / 'dist/ShengaoKaraoke-0.32.0-source.zip')]
    assert '--full' in by['licenses'].command and '--package' in by['licenses'].command
    assert by['development'].env['QT_QPA_PLATFORM'] == 'offscreen' and 'tmp' in Path(by['development'].env['SHENGAO_HOME']).parts
    assert not any('--real' in s.command or '--yes' in s.command for s in steps)
    assert all(s.command[0] == 'py' for s in steps)


class Stub:
    """Plays every step: writes what the real script would, or fails where asked."""

    def __init__(self, root, fail=None, code=1, edit=None, report_passed=True):
        self.root = root; self.fail = fail; self.code = code; self.edit = edit
        self.report_passed = report_passed; self.calls = []

    def __call__(self, step, log, root):
        self.calls.append(step.name)
        log.parent.mkdir(parents=True, exist_ok=True); log.write_text(step.name + ' output\n', encoding='utf-8')
        if step.name == self.fail: return self.code
        if step.name == self.edit: write(root / 'scripts/tool.py', 'changed\n')
        evidence = root / 'build/v032-evidence'; package = root / 'build/desktop-dist/shengao-karaoke'
        if step.name == 'dependencies':
            write(root / 'build/desktop-dependencies.json', '{"passed": true}')
        elif step.name == 'development':
            write(evidence / 'development/report.json', json.dumps({'passed': self.report_passed, 'checks': [1, 2, 3]}))
        elif step.name.startswith('standalone'):
            out = root / 'tmp' / ('desktop-package-' + step.name)
            write(out / 'report.json', json.dumps({'passed': True, 'checks': [1] * 4}))
            write(out / 'timing-provenance-audit.json', '{}'); write(out / 'stdout.log', 'log')
            write(out / 'home/secret.bin', b'x')                       # not copied: only top-level reports
            manifest = sha((package / 'package-manifest.json').read_bytes())
            write(root / 'build/desktop-package-acceptance.json',
                  json.dumps({'passed': True, 'manifest_sha256': manifest, 'report': str(out / 'report.json'), 'checks': 4}))
        elif step.name.startswith('timeline'):
            out = Path(step.command[step.command.index('--output') + 1])
            write(out / 'report.json', json.dumps({'passed': True, 'cases': list(range(6))}))
            write(out / 'case-1.png', b'png'); write(out / 'synthetic.s16', b'pcm')
        elif step.name == 'prepare':
            make_release(root)
        elif step.name == 'archives':
            write(root / 'build/archive-check.json', '{"passed": true}')
        return 0


class Git:
    def __init__(self, status='', commit='abc123def456'):
        self.status = status; self.commit = commit

    def __call__(self, root, *args):
        return self.status if args[0] == 'status' else self.commit


def test_full_run_leaves_the_evidence_release_scripts_need(freeze, tree, capsys):
    stub = Stub(tree)
    assert freeze.freeze(tree, [], run=stub, git=Git(), windows=True) == 0
    assert stub.calls == EXPECTED
    evidence = tree / 'build/v032-evidence'
    audit = json.loads((evidence / 'desktop-final-audit-v032.json').read_text(encoding='utf-8'))
    assert (tree / 'build/desktop-final-audit-v032.json').read_text(encoding='utf-8') == (evidence / 'desktop-final-audit-v032.json').read_text(encoding='utf-8')
    assert audit['passed'] is True and audit['version'] == VERSION and audit['tag'] == 'v0.32.0' and audit['commit'] == 'abc123def456'
    assert [s['name'] for s in audit['steps']] == EXPECTED and all(s['passed'] for s in audit['steps'])
    assert audit['manifest_sha256'] == sha((tree / 'build/desktop-dist/shengao-karaoke/package-manifest.json').read_bytes())
    assert {r['file'] for r in audit['release']} == {'ShengaoKaraoke-0.32.0-final-win64.zip', 'ShengaoKaraoke-0.32.0-source.zip'}
    assert audit['sources'] and next(s for s in audit['steps'] if s['name'] == 'standalone-dpi150')['details']['checks'] == 4
    # exactly what package-public-evidence.py reads
    for name in ['README.txt', 'SHA256SUMS-0.32.0.txt', 'development/report.json', 'standalone-normal/report.json',
                 'standalone-dpi150/report.json', 'standalone-normal/timing-provenance-audit.json',
                 'timeline-full-pixels/report.json', 'timeline-full-pixels-dpi150/report.json', 'timeline-full-pixels/case-1.png']:
        assert (evidence / name).is_file(), name
    assert not (evidence / 'standalone-normal/home').exists() and not (evidence / 'timeline-full-pixels/synthetic.s16').exists()
    assert (evidence / 'SHA256SUMS-0.32.0.txt').read_bytes() == (tree / 'dist/SHA256SUMS-0.32.0.txt').read_bytes()
    assert all((evidence / s['log']).is_file() for s in audit['steps'])
    readme = (evidence / 'README.txt').read_text(encoding='utf-8')
    assert '0.32.0' in readme and 'abc123def456' in readme and f'全部 {len(EXPECTED)} 步通过' in readme
    out = capsys.readouterr().out
    assert '全部 15 步通过' in out and '还没有打标签、推送或发布' in out


def test_first_failure_stops_and_resume_continues_from_it(freeze, tree, capsys):
    first = Stub(tree, fail='standalone-dpi150', code=3)
    assert freeze.freeze(tree, [], run=first, git=Git(), windows=True) == 1
    assert first.calls == EXPECTED[:6]
    evidence = tree / 'build/v032-evidence'
    assert not (evidence / 'desktop-final-audit-v032.json').exists() and not (tree / 'build/desktop-final-audit-v032.json').exists()
    out = capsys.readouterr().out
    assert '第 6 步「独立包自检（150% 缩放）」没有通过：退出码 3' in out and 'standalone-dpi150.log' in out and '--resume' in out
    progress = json.loads((evidence / 'freeze-progress.json').read_text(encoding='utf-8'))
    assert [s['name'] for s in progress['steps']] == EXPECTED[:5]
    second = Stub(tree)
    assert freeze.freeze(tree, ['--resume'], run=second, git=Git(), windows=True) == 0
    assert second.calls == EXPECTED[5:]
    audit = json.loads((evidence / 'desktop-final-audit-v032.json').read_text(encoding='utf-8'))
    assert [s['name'] for s in audit['steps']] == EXPECTED
    assert '上次已通过，跳过' in capsys.readouterr().out


def test_resume_refuses_after_a_new_commit_or_changed_source(freeze, tree, capsys):
    assert freeze.freeze(tree, [], run=Stub(tree, fail='build'), git=Git(), windows=True) == 1
    later = Stub(tree)
    assert freeze.freeze(tree, ['--resume'], run=later, git=Git(commit='ffff0000'), windows=True) == 2
    write(tree / 'scripts/tool.py', 'edited\n')
    assert freeze.freeze(tree, ['--resume'], run=later, git=Git(), windows=True) == 2
    assert later.calls == [] and '不能接着跑' in capsys.readouterr().out


def test_a_report_that_did_not_pass_fails_its_step(freeze, tree, capsys):
    stub = Stub(tree, report_passed=False)
    assert freeze.freeze(tree, [], run=stub, git=Git(), windows=True) == 1
    assert stub.calls[-1] == 'development' and '自检报告没有通过' in capsys.readouterr().out


def test_source_change_during_the_run_voids_it(freeze, tree, capsys):
    stub = Stub(tree, edit='licenses')
    assert freeze.freeze(tree, [], run=stub, git=Git(), windows=True) == 1
    assert stub.calls == EXPECTED and not (tree / 'build/desktop-final-audit-v032.json').exists()
    assert '源码或提交发生了变化' in capsys.readouterr().out


@pytest.mark.parametrize('case', ['not-windows', 'dirty', 'released', 'frozen'])
def test_preconditions_stop_before_any_step(freeze, tree, case, capsys):
    git = Git(status=' M scripts/tool.py' if case == 'dirty' else '')
    if case == 'released': write(tree / 'dist/ShengaoKaraoke-0.32.0-source.zip', b'old')
    if case == 'frozen': write(tree / 'build/v032-evidence/desktop-final-audit-v032.json', '{"passed": true}')
    stub = Stub(tree)
    assert freeze.freeze(tree, [], run=stub, git=git, windows=case != 'not-windows') == 2
    assert stub.calls == []
    out = capsys.readouterr().out
    assert {'not-windows': 'Windows', 'dirty': '没提交', 'released': 'dist 里已有', 'frozen': '已经冻结过'}[case] in out


def test_fresh_run_clears_an_unfinished_attempt(freeze, tree):
    stale = write(tree / 'build/v032-evidence/development/report.json', json.dumps({'passed': False}))
    stub = Stub(tree)
    assert freeze.freeze(tree, [], run=stub, git=Git(), windows=True) == 0
    assert json.loads(stale.read_text(encoding='utf-8'))['passed'] is True


def test_list_only_prints_the_steps(freeze, tree, capsys):
    stub = Stub(tree)
    assert freeze.freeze(tree, ['--list'], run=stub, git=Git(status='dirty'), windows=False) == 0
    out = capsys.readouterr().out
    assert stub.calls == [] and '共 15 步' in out and '原版时间轴逐像素对照（150% 缩放）' in out


def test_steps_never_see_service_keys(freeze, tree, monkeypatch, tmp_path):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-test'); monkeypatch.setenv('QT_SCALE_FACTOR', '2')
    step = freeze.Step('probe', 'probe', [sys.executable, '-c',
                       'import os;print(os.environ.get("DEEPSEEK_API_KEY"), os.environ.get("QT_SCALE_FACTOR"))'], {'QT_SCALE_FACTOR': None})
    log = tmp_path / 'logs/probe.log'
    assert freeze.execute(step, log, tmp_path) == 0
    assert log.read_text(encoding='utf-8').split() == ['None', 'None']
