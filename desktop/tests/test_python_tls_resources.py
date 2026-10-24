"""The frozen worker must retain the TLS data required by its Python runtime."""
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('python_tls_resources_test',ROOT/'scripts/python_tls_resources.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def runtime(tmp_path):
    source=tmp_path/'python/ssl.py';source.parent.mkdir()
    source.write_text('policy="'+module.NAME+'"',encoding='utf-8')
    data=(ROOT/'vendor/python-tls'/module.NAME).read_bytes()
    source.with_name(module.NAME).write_bytes(data)
    root=tmp_path/'project';bundled=root/'vendor/python-tls'/module.NAME
    bundled.parent.mkdir(parents=True);bundled.write_bytes(data)
    return source,root,bundled


def test_patched_runtime_adds_verified_public_data(tmp_path):
    source,root,bundled=runtime(tmp_path)
    assert module.pyinstaller_arguments(root,source)==['--add-data',str(bundled)+';.']


def test_stock_runtime_needs_no_sidecar(tmp_path):
    source=tmp_path/'ssl.py';source.write_text('class SSLContext: pass',encoding='utf-8')
    assert module.pyinstaller_arguments(tmp_path,source)==[]


@pytest.mark.parametrize('change',['missing_runtime','changed_runtime','changed_bundle'])
def test_missing_or_changed_security_data_rejected(tmp_path,change):
    source,root,bundled=runtime(tmp_path)
    if change=='missing_runtime':source.with_name(module.NAME).unlink()
    elif change=='changed_runtime':source.with_name(module.NAME).write_bytes(b'changed')
    else:bundled.write_bytes(b'changed')
    with pytest.raises(ValueError,match='missing or changed'):module.pyinstaller_arguments(root,source)
