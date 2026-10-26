"""Load only the verified local accelerator; Python remains the fallback."""
from pathlib import Path
import hashlib,importlib.util,json,sys
from studio_backend import model
from .paths import RUNTIME,ROOT


def verify(runtime=RUNTIME,source=None):
    runtime=Path(runtime);binary=runtime/'_shengao_snapshot.pyd';manifest=runtime/'snapshot-native.json'
    if sys.implementation.name!='cpython' or sys.version_info[:2]!=(3,12) or sys.platform!='win32':raise ValueError('unsupported Python ABI')
    record=json.loads(manifest.read_text(encoding='utf-8'))
    if record.get('version')!=1 or record.get('module')!=binary.name or record.get('python_abi')!='cp312' or record.get('bits')!=64:raise ValueError('snapshot manifest ABI mismatch')
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=record.get('sha256'):raise ValueError('snapshot binary fingerprint mismatch')
    if source is not None and hashlib.sha256(Path(source).read_bytes()).hexdigest()!=record.get('source_sha256'):raise ValueError('snapshot source fingerprint mismatch')
    return binary,record


def enable():
    source=None if getattr(sys,'frozen',False) else ROOT/'desktop/native/snapshot.c'
    try:
        binary,record=verify(source=source)
        module=sys.modules.get('_shengao_snapshot')
        if module is None:
            spec=importlib.util.spec_from_file_location('_shengao_snapshot',binary);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            sys.modules['_shengao_snapshot']=module
        if module.source_sha256!=record['source_sha256'] or module.python_abi!=record['python_abi']:raise ValueError('loaded snapshot module fingerprint mismatch')
        model._set_snapshot_accelerator(module)
        return {'enabled':True,'source_sha256':record['source_sha256'],'sha256':record['sha256'],'python_abi':record['python_abi']}
    except (OSError,ValueError,ImportError,AttributeError) as error:
        model._set_snapshot_accelerator(None)
        return {'enabled':False,'reason':str(error)}
