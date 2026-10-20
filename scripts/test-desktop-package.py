"""Isolated executable acceptance; PATH deliberately excludes Python and Aegisub."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import uuid

root=Path(__file__).resolve().parents[1];package=root/'build'/'desktop-dist'/'shengao-karaoke'
out=root/'tmp'/('desktop-package-'+uuid.uuid4().hex);out.mkdir(parents=True)
env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME','ELEVENLABS_API_KEY','MAI_SPEECH_KEY','DEEPSEEK_API_KEY'}}
env['PATH']=str(package)+os.pathsep+str(Path(os.environ.get('WINDIR','C:/Windows'))/'System32')
env['QT_QPA_PLATFORM']='offscreen';env['SHENGAO_HOME']=str(out/'home')
manifest=json.loads((package/'package-manifest.json').read_text(encoding='utf-8'))
for value in manifest['files']:
    path=package/value['path'];assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==value['sha256'],value['path']
assert not any('aegisub.exe' in v['path'].lower() for v in manifest['files'])
assert (package/'shengao-view.dll').is_file(), 'Original offscreen timeline drawing module is required'
result=subprocess.run([str(package/'shengao-karaoke.exe'),'--self-test','--output',str(out)],env=env,cwd=out,capture_output=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
(out/'stdout.log').write_bytes(result.stdout);(out/'stderr.log').write_bytes(result.stderr)
assert result.returncode==0,('Executable self-test failed',result.returncode,out)
report=json.loads((out/'report.json').read_text(encoding='utf-8'));assert report['passed'],out
manifest_hash=hashlib.sha256((package/'package-manifest.json').read_bytes()).hexdigest()
(root/'build'/'desktop-package-acceptance.json').write_text(json.dumps({'passed':True,'manifest_sha256':manifest_hash,'report':str(out/'report.json'),'checks':len(report['checks'])},indent=2),encoding='utf-8')
print(json.dumps({'ok':True,'files':len(manifest['files']),'checks':len(report['checks']),'output':str(out)}))
