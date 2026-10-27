"""A manifest digest alone must not certify changed or extra runtime files."""
import hashlib,json
from pathlib import Path
import pytest
from shengao.runtime_integrity import verify_runtime


def package(tmp_path):
    for name,data in [('program.exe',b'controlled executable'),('_internal/module.dll',b'controlled module')]:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    manifest={'application':'Shengao Independent Studio','version':'0.30.0','files':[
        {'path':p.relative_to(tmp_path).as_posix(),'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(tmp_path.rglob('*')) if p.is_file()]}
    (tmp_path/'package-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    return manifest


def test_every_file_and_manifest_are_verified_again_after_a_run(tmp_path):
    package(tmp_path);before=verify_runtime(tmp_path)
    assert before['verified_files']==2 and before['every_file_verified'] and before['no_unlisted_files']
    assert verify_runtime(tmp_path)==before
    path=tmp_path/'program.exe';data=path.read_bytes();path.write_bytes(b'X'+data[1:])
    with pytest.raises(ValueError,match='mismatch'):verify_runtime(tmp_path)


def test_missing_and_private_unlisted_outputs_cannot_certify_a_runtime(tmp_path):
    package(tmp_path);private=tmp_path/'private-project.sgproj';private.write_text('controlled private output')
    with pytest.raises(ValueError,match='unlisted'):verify_runtime(tmp_path)
    private.unlink();(tmp_path/'program.exe').unlink()
    with pytest.raises(ValueError,match='mismatch'):verify_runtime(tmp_path)


@pytest.mark.parametrize('change',['traversal','absolute','duplicate','size','sha','empty'])
def test_invalid_runtime_manifests_are_rejected_before_certification(tmp_path,change):
    value=package(tmp_path)
    if change=='traversal':value['files'][0]['path']='../outside-file'
    elif change=='absolute':value['files'][0]['path']='C:/outside-file'
    elif change=='duplicate':value['files'].append(dict(value['files'][0]))
    elif change=='size':value['files'][0]['size']=True
    elif change=='sha':value['files'][0]['sha256']='not-a-sha256'
    else:value['files']=[]
    (tmp_path/'package-manifest.json').write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError):verify_runtime(tmp_path)
