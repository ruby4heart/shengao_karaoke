import importlib.metadata as metadata
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from vocal_build_environment import validate_environment


def test_old_demucs_only_environment_fails_before_packaging_alignment_engine(tmp_path):
    lock=tmp_path/'engine.lock';lock.write_text('torch==2.8.0+cpu\ng2pflow==0.3.1\nlibrosa==1.0.0\n',encoding='utf-8')
    def old_environment(name):
        if name=='torch':return '2.8.0+cpu'
        raise metadata.PackageNotFoundError(name)
    with pytest.raises(ValueError,match='g2pflow') as caught:validate_environment(lock,old_environment)
    assert 'librosa' in str(caught.value) and '构建未开始' in str(caught.value)


def test_gpu_or_different_cpu_versions_do_not_silently_match_fixed_engine(tmp_path):
    lock=tmp_path/'engine.lock';lock.write_text('torch==2.8.0+cpu\n',encoding='utf-8')
    with pytest.raises(ValueError,match='2.8.0\\+cpu'):validate_environment(lock,lambda name:'2.8.0+cu128')


def test_unpinned_or_duplicate_environment_manifest_is_rejected(tmp_path):
    lock=tmp_path/'engine.lock';lock.write_text('torch>=2.8\n',encoding='utf-8')
    with pytest.raises(ValueError,match='未固定'):validate_environment(lock)
    lock.write_text('lazy_loader==0.6\nlazy-loader==0.6\n',encoding='utf-8')
    with pytest.raises(ValueError,match='重复'):validate_environment(lock)


def test_exact_environment_records_all_pins_and_lock_fingerprint(tmp_path):
    lock=tmp_path/'engine.lock';lock.write_text('torch==2.8.0+cpu\ng2pflow==0.3.1\n',encoding='utf-8')
    versions={'torch':'2.8.0+cpu','g2pflow':'0.3.1'};value=validate_environment(lock,versions.__getitem__)
    assert value['passed'] and value['distributions']==versions and len(value['requirements_sha256'])==64
