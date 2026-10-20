import json
from pathlib import Path
import subprocess
import pytest


def test_packaged_worker_without_python_environment(tmp_path):
    root=Path(__file__).resolve().parents[2]
    executable=root/'build/worker-dist/studio-worker/studio-worker.exe'
    if not executable.exists():
        pytest.skip('Build the worker executable before packaging validation')
    output=tmp_path/'result.json'
    request={'action':'export','format':'json','output':str(tmp_path/'歌詞.json'),'lines':[
        {'id':'1','text':'歌','start':0,'end':1000,'units':[{'text':'歌','start':0,'end':1000,
         'kana':'うた','romaji':'uta'}],'kana':'うた','romaji':'uta','translation':'歌'}]}
    completed=subprocess.run([str(executable),'--request','-','--result',str(output),'--home',str(tmp_path/'home')],
        input=json.dumps(request,ensure_ascii=False).encode('utf-8'),capture_output=True,timeout=40)
    assert completed.returncode==0,completed.stderr.decode(errors='replace')
    result=json.loads(output.read_text(encoding='utf-8'))
    assert result['ok'],result
    assert json.loads((tmp_path/'歌詞.json').read_text(encoding='utf-8'))['lines'][0]['kana']=='うた'
