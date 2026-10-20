"""Run upstream native tests with isolated, reproducible filesystem fixtures."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
build=ROOT/'build'/'baseline'
run=Path(tempfile.mkdtemp(prefix='native-tests-',dir=ROOT/'tmp'))
data=run/'data'
for folder in ('dir','dir_iterator','options','vfr/out','keyframe'):
    (data/folder).mkdir(parents=True,exist_ok=True)
for name in ('file','touch_mod_time','dir_iterator/1.a','dir_iterator/2.a','dir_iterator/1.b','dir_iterator/2.b'):
    (data/name).touch()
(data/'ten_bytes').write_bytes(b'1234567890')
(data/'mru_ok.json').write_text('{"Video":["Entry One","Entry Two"]}',encoding='utf-8')
(data/'mru_invalid.json').write_text('{"Video":[1,3]}',encoding='utf-8')
env=os.environ.copy()
env['AEGISUB_TEST_DATA_DIR']=str(ROOT/'vendor'/'aegisub'/'tests')
results=[]
for executable in ('gtest-main.exe','luajit-52.exe'):
    result=subprocess.run([str(build/'tests'/executable)],cwd=run,env=env,capture_output=True)
    log=ROOT/'build'/f'{executable}.test.log'
    log.write_bytes(result.stdout+result.stderr)
    results.append(result.returncode)
    print(executable,'PASS' if result.returncode==0 else 'FAIL','log:',log)
raise SystemExit(max(results))
