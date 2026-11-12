"""Release licence inventory (ToDo 11.6): every third-party part has a source, licence and fixed
fingerprint, the inventory agrees with the fingerprints the code enforces, and nothing claims the
product may be used commercially while the TIFA weights (CC BY-NC-SA 4.0) are bundled.

Large vendor files exist only in the full source ZIP, so file checks run on synthetic trees here;
scripts/check-licenses.py --full / --package does the real check on Windows."""
from pathlib import Path
import copy, hashlib, importlib.util, json, os, stat, sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def lic():
    spec = importlib.util.spec_from_file_location('check_licenses', ROOT / 'scripts' / 'check-licenses.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def manifest(lic):
    return lic.load()


def component(manifest, name):
    return next(c for c in manifest['components'] if c['id'] == name)


def tiny_manifest(files):
    """A one-component inventory whose files are (in, path, bytes, text)."""
    return {'schema': 1, 'product_statement': '整体只供非商业使用，不宣称可商用。', 'components': [{
        'id': 'demo', 'name': 'Demo', 'version': '1', 'license': 'MIT', 'use': 'test', 'upstream': ['https://example.invalid/'],
        'files': [{'path': p, 'in': where, 'role': 'license' if p.endswith('LICENSE') else 'artifact',
                   'sha256': hashlib.sha256(data).hexdigest(), **({'text': True} if text else {})}
                  for where, p, data, text in files]}]}


def put(base, path, data):
    target = Path(base) / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)


# --- the inventory itself -------------------------------------------------------------------------

def test_inventory_is_complete_and_well_formed(lic, manifest):
    assert lic.check_manifest(manifest) == []
    ids = {c['id'] for c in manifest['components']}
    assert {'shengao', 'aegisub', 'fonts', 'ffmpeg', 'demucs', 'tifa-code', 'tifa-model'} <= ids
    for c in manifest['components']:
        assert c['upstream'] and all(u.startswith('https://') for u in c['upstream'])
        assert any(f['role'] == 'license' for f in c['files']) or c.get('license_file_note'), c['id']


def test_inventory_version_follows_the_app():
    sys.path.insert(0, str(ROOT / 'desktop'))
    try:
        from shengao import __version__
    finally:
        sys.path.remove(str(ROOT / 'desktop'))
    data = json.loads((ROOT / 'desktop/assets/licenses/THIRD-PARTY-INVENTORY.json').read_text(encoding='utf-8'))
    assert data['app_version'] == __version__


def test_singing_model_is_the_only_noncommercial_part_and_says_so(manifest):
    model = component(manifest, 'tifa-model')
    assert model['noncommercial'] is True and model['license'] == 'CC-BY-NC-SA-4.0'
    assert '非商业' in model['restriction'] and '不宣称可商用' in model['restriction']
    assert [c['id'] for c in manifest['components'] if c.get('noncommercial')] == ['tifa-model']
    assert '非商业' in manifest['product_statement'] and '不宣称可商用' in manifest['product_statement']
    assert any(f['path'].endswith('CC-BY-NC-SA-4.0.html') and f['role'] == 'license' for f in model['files'])


def test_core_artifacts_are_fingerprinted_in_source_and_package(manifest):
    expected = {
        'ffmpeg': '967f4567a6879493237dbe7171dfa838c5b0e869dbb86db3bd8701edfca49f9c',
        'demucs': '8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4',
        'tifa-model': '8d9bf896da1827f36bf135f80c7ab1fc4f3c1d48f328818b8402c9527c0f014b',
    }
    for name, sha in expected.items():
        places = {f['in'] for f in component(manifest, name)['files'] if f['sha256'] == sha}
        assert places == {'source', 'package'}, name
    assert component(manifest, 'ffmpeg')['license'].startswith('LGPL')
    assert component(manifest, 'ffmpeg')['binary_license_check'] == 'ffmpeg'


def test_manifest_problems_are_reported(lic, manifest):
    broken = copy.deepcopy(manifest)
    component(broken, 'tifa-model').pop('noncommercial')
    component(broken, 'fonts')['upstream'] = ['http://example.invalid/']
    component(broken, 'demucs')['files'][0]['sha256'] = 'abc'
    component(broken, 'qt')['files'][0]['path'] = '../outside.txt'
    broken['components'] = [c for c in broken['components'] if c['id'] != 'aegisub']
    problems = '\n'.join(lic.check_manifest(broken))
    for words in ('TIFA 模型权重没有标为非商业', '许可含非商业条款', 'fonts：来源地址必须是 https', '64 位 SHA256', '必须是相对路径', '缺少必需组件：aegisub'):
        assert words in problems


# --- agreement with the code ---------------------------------------------------------------------

def test_inventory_matches_every_fingerprint_the_code_enforces(lic, manifest):
    pins = lic.code_pins(ROOT)
    assert len(pins) >= 15  # TIFA ×4, Demucs, orjson ×2, TLS, TBB, fonts ×4, Original-Audio sources
    assert pins['vendor/tifa-model/model.pt'] == '8d9bf896da1827f36bf135f80c7ab1fc4f3c1d48f328818b8402c9527c0f014b'
    assert 'vendor/tbb-runtime/tbb-2023.2.0-py3-none-win_amd64.whl' in pins
    assert lic.check_pins(manifest, ROOT) == []


def test_a_changed_code_pin_is_caught(lic, manifest):
    changed = copy.deepcopy(manifest)
    for f in component(changed, 'demucs')['files']:
        if f['path'] == 'vendor/vocal-model/955717e8-8726e21a.th': f['sha256'] = '0' * 64
    component(changed, 'orjson')['files'] = [f for f in component(changed, 'orjson')['files'] if not f['path'].endswith('.tar.gz')]
    problems = '\n'.join(lic.check_pins(changed, ROOT))
    assert 'vendor/vocal-model/955717e8-8726e21a.th：清单指纹与代码里固定的不一致' in problems
    assert '代码固定了 vendor/orjson/orjson-3.13.0.tar.gz，但清单里没有' in problems


def test_local_files_in_this_repository_match(lic, manifest):
    rows = lic.check_files(manifest, ROOT, 'source', required=False)
    assert not [r for r in rows if r[2] == '失败']
    passed = {r[1] for r in rows if r[2] == '通过'}
    assert {'desktop/assets/fonts/NotoSansCJKjp-Regular.otf', 'desktop/assets/alignment-demo/pjs056_song.wav',
            'desktop/assets/licenses/Qt/LGPL-3.0.txt', 'vendor/python-tls/codex-rejected-cas.pem'} <= passed
    skipped = {r[1] for r in rows if r[2] == '跳过'}
    assert all(p.startswith('vendor/') for p in skipped)


def test_the_repository_passes_the_source_check(lic):
    lines = []
    report = lic.run(ROOT, show=lines.append)
    assert report['counts']['失败'] == 0, '\n'.join(lines)
    assert report['mode'] == 'source'


# --- file fingerprints ---------------------------------------------------------------------------

def test_full_and_package_checks_on_a_synthetic_tree(lic, tmp_path):
    files = [('source', 'vendor/model.bin', b'\x00weights\r\n', False), ('source', 'vendor/LICENSE', b'MIT\r\nline\r\n', True),
             ('package', 'engine/model.bin', b'\x00weights\r\n', False), ('package', 'licenses/LICENSE', b'MIT\r\nline\r\n', True)]
    data = tiny_manifest(files)
    for where, path, content, _ in files: put(tmp_path / where, path, content)
    assert {r[2] for r in lic.check_files(data, tmp_path / 'source', 'source', True)} == {'通过'}
    assert {r[2] for r in lic.check_files(data, tmp_path / 'package', 'package', True)} == {'通过'}
    # Git on Windows may turn LF into CRLF (or back) for text; binaries must stay byte-exact
    put(tmp_path / 'source', 'vendor/LICENSE', b'MIT\nline\n')
    put(tmp_path / 'source', 'vendor/model.bin', b'\x00weights\n')
    rows = {r[1]: r for r in lic.check_files(data, tmp_path / 'source', 'source', True)}
    assert rows['vendor/LICENSE'][2] == '通过'
    assert rows['vendor/model.bin'][2] == '失败' and '指纹不符' in rows['vendor/model.bin'][3]
    # missing files: skipped for a plain checkout, failed for --full and packages
    (tmp_path / 'package' / 'engine' / 'model.bin').unlink()
    (tmp_path / 'source' / 'vendor' / 'model.bin').unlink()
    assert [r[2] for r in lic.check_files(data, tmp_path / 'source', 'source', False) if r[1] == 'vendor/model.bin'] == ['跳过']
    assert [r[2] for r in lic.check_files(data, tmp_path / 'source', 'source', True) if r[1] == 'vendor/model.bin'] == ['失败']
    assert [r[3] for r in lic.check_files(data, tmp_path / 'package', 'package', True) if r[2] == '失败'] == ['缺少文件']


def test_text_tolerance_does_not_accept_other_content(lic):
    original = b'line one\r\nline two\r\n'
    sha = hashlib.sha256(original).hexdigest()
    assert lic.matches(b'line one\nline two\n', sha, text=True)
    assert not lic.matches(b'line one\nline two\n', sha, text=False)
    assert not lic.matches(b'line one\nline 2\n', sha, text=True)
    lf_sha = hashlib.sha256(b'a\nb\n').hexdigest()
    assert lic.matches(b'a\r\nb\r\n', lf_sha, text=True)


def test_package_must_carry_the_inventory_and_explanation(lic, manifest, tmp_path):
    status, detail = lic.check_package_notices(manifest, tmp_path)
    assert status == '失败' and 'THIRD-PARTY-INVENTORY.json' in detail and 'THIRD-PARTY-LICENSES.md' in detail
    put(tmp_path, 'licenses/THIRD-PARTY-LICENSES.md', (ROOT / 'docs/THIRD-PARTY-LICENSES.md').read_bytes())
    old = copy.deepcopy(manifest); old['app_version'] = '0.30.0'
    put(tmp_path, 'licenses/Independent-Qt/THIRD-PARTY-INVENTORY.json', json.dumps(old).encode())
    assert lic.check_package_notices(manifest, tmp_path) == ('失败', '随包清单与源码里的不同（运行包可能是旧版本构建的）')
    put(tmp_path, 'licenses/Independent-Qt/THIRD-PARTY-INVENTORY.json', (ROOT / 'desktop/assets/licenses/THIRD-PARTY-INVENTORY.json').read_bytes())
    assert lic.check_package_notices(manifest, tmp_path) == ('通过', '')


def test_build_puts_inventory_and_explanation_into_the_package():
    build = (ROOT / 'scripts/build-desktop.py').read_text(encoding='utf-8')
    assert "root/'desktop'/'assets'/'licenses',package/'licenses'/'Independent-Qt'" in build
    assert "root/'docs'/'THIRD-PARTY-LICENSES.md',package/'licenses'/'THIRD-PARTY-LICENSES.md'" in build


# --- wording -------------------------------------------------------------------------------------

@pytest.mark.parametrize('text', [
    '本软件可商用。', '正式版支持商业用途', 'Free for commercial use.', '获得商业授权后发布成品',
])
def test_commercial_claims_are_flagged(lic, text):
    assert lic.commercial_claims(text)


@pytest.mark.parametrize('text', [
    'TIFA 权重限非商业用途。', '“正式版”不代表商用授权。', 'Not for commercial use.',
    '更多语种与商业可用模型均不作为本次 1.0 的前提。', 'CC BY-NC-SA 4.0 (NonCommercial)', 'non-commercial only',
])
def test_restrictions_are_not_flagged(lic, text):
    assert lic.commercial_claims(text) == []


def test_documents_state_the_restriction_and_make_no_claim(lic, tmp_path):
    assert lic.check_wording(ROOT) == []
    for name in lic.NOTICE_FILES:
        put(tmp_path, name, '说明：模型限非商业用途。\n'.encode())
    assert lic.check_wording(tmp_path) == []
    put(tmp_path, 'docs/THIRD-PARTY-LICENSES.md', '本软件可以商用。\n'.encode())
    put(tmp_path, 'desktop/shengao/about.py', "TEXT='Ready for commercial use'\n".encode())
    problems = '\n'.join(lic.check_wording(tmp_path))
    assert 'docs/THIRD-PARTY-LICENSES.md 没有写明' in problems
    assert 'docs/THIRD-PARTY-LICENSES.md：疑似宣称可商用' in problems
    assert 'desktop/shengao/about.py：疑似宣称可商用' in problems


def test_explanation_lists_every_component(manifest):
    text = (ROOT / 'docs/THIRD-PARTY-LICENSES.md').read_text(encoding='utf-8')
    for c in manifest['components']:
        assert c['name'] in text and c['license'] in text, c['id']
    assert 'check-licenses.py --full' in text and 'check-licenses.py --package' in text


# --- FFmpeg build licence ------------------------------------------------------------------------

def fake_ffmpeg(folder, banner):
    """A stand-in executable that prints `banner` for -L."""
    script = Path(folder) / 'fake_ffmpeg.py'
    script.write_text(f'import sys\nsys.stdout.write({banner!r})\n', encoding='utf-8')
    if os.name == 'nt':
        launcher = Path(folder) / 'ffmpeg.bat'
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding='utf-8')
    else:
        launcher = Path(folder) / 'ffmpeg'
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding='utf-8')
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    return launcher


# The texts FFmpeg's show_license prints for each configuration (fftools/opt_common.c), line breaks included
LGPL = ('ffmpeg is free software; you can redistribute it and/or\nmodify it under the terms of the GNU Lesser General Public\n'
        'License as published by the Free Software Foundation; either\nversion 2.1 of the License, or (at your option) any later version.\n')
GPL = ('ffmpeg is free software; you can redistribute it and/or modify\nit under the terms of the GNU General Public License as published by\n'
       'the Free Software Foundation; either version 2 of the License, or\n(at your option) any later version.\n')
NONFREE = 'This version of ffmpeg has nonfree parts compiled in.\nTherefore it is not legally redistributable.\n'


@pytest.mark.parametrize('banner,expected', [(LGPL, '通过'), (GPL, '失败'), (NONFREE, '失败'), ('ffmpeg version n8\n', '跳过')])
def test_ffmpeg_build_licence_is_read_from_the_binary(lic, tmp_path, banner, expected):
    status, detail = lic.check_ffmpeg(fake_ffmpeg(tmp_path, banner))
    assert status == expected, detail


def test_ffmpeg_that_cannot_run_is_skipped_not_failed(lic, tmp_path):
    assert lic.check_ffmpeg(tmp_path / 'ffmpeg.exe')[0] == '跳过'
    broken = tmp_path / 'ffmpeg.exe'; broken.write_bytes(b'MZ not really a program')
    assert lic.check_ffmpeg(broken)[0] == '跳过'
