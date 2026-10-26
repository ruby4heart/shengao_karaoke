"""Build the optional CPython 3.12 snapshot accelerator with source provenance."""
from pathlib import Path
import hashlib,importlib.util,json,platform,shutil,sys,sysconfig
from setuptools import Extension,setup

root=Path(__file__).resolve().parents[1]


def main():
    if sys.implementation.name!='cpython' or sys.version_info[:2]!=(3,12) or sys.platform!='win32':
        raise SystemExit('Snapshot accelerator currently requires Windows CPython 3.12')
    source=root/'desktop/native/snapshot.c';fingerprint=hashlib.sha256(source.read_bytes()).hexdigest()
    output=root/'build/snapshot-native-lib'
    distribution=setup(name='shengao-snapshot',version='0.30.0',packages=[],
        ext_modules=[Extension('_shengao_snapshot',[str(source)],extra_compile_args=['/O2'],
            define_macros=[('SG_SNAPSHOT_SOURCE_SHA256','"'+fingerprint+'"')])],
        script_args=['build_ext','--force','--build-lib',str(output),'--build-temp',str(root/'build/snapshot-native-objects')])
    artifact=output/('_shengao_snapshot'+sysconfig.get_config_var('EXT_SUFFIX'))
    spec=importlib.util.spec_from_file_location('_shengao_snapshot',artifact);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.source_sha256==fingerprint and module.python_abi=='cp312'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==fingerprint,'Snapshot source changed during build'
    target=root/'build/desktop/_shengao_snapshot.pyd';target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(artifact,target)
    compiler=distribution.get_command_obj('build_ext').compiler
    record={'version':1,'module':target.name,'source_sha256':fingerprint,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'python_abi':module.python_abi,'python_version':platform.python_version(),'python_compiler':platform.python_compiler(),
        'native_compiler_type':getattr(compiler,'compiler_type',None),'native_compiler_executable':getattr(compiler,'cc',None),'bits':64 if sys.maxsize>2**32 else 32}
    (target.parent/'snapshot-native.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record))


if __name__=='__main__':main()
