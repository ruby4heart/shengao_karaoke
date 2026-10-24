import json
import os
from pathlib import Path
import subprocess
import pytest


def test_packaged_worker_without_python_environment(tmp_path):
    root=Path(__file__).resolve().parents[2]
    # The shipped desktop executable owns the real headless IPC route. Keep
    # the legacy CLI fallback for backend-only developer checkouts.
    executable=root/'build/desktop-dist/shengao-karaoke/shengao-karaoke.exe'
    mode=['--worker']
    if not executable.exists():executable=root/'build/worker-dist/studio-worker/studio-worker.exe';mode=[]
    if not executable.exists():
        pytest.skip('Build the desktop package or standalone worker before packaging validation')
    output=tmp_path/'result.json'
    request={'action':'export','format':'json','output':str(tmp_path/'歌詞.json'),'lines':[
        {'id':'1','text':'歌','start':0,'end':1000,'units':[{'text':'歌','start':0,'end':1000,
         'kana':'うた','romaji':'uta'}],'kana':'うた','romaji':'uta','translation':'歌'}]}
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME','ELEVENLABS_API_KEY','MAI_SPEECH_KEY','DEEPSEEK_API_KEY'}}
    env['PATH']=str(executable.parent)+os.pathsep+str(Path(os.environ.get('WINDIR','C:/Windows'))/'System32')
    completed=subprocess.run([str(executable),*mode,'--request','-','--result',str(output),'--home',str(tmp_path/'home')],
        input=json.dumps(request,ensure_ascii=False).encode('utf-8'),capture_output=True,timeout=40,env=env,cwd=tmp_path,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    assert completed.returncode==0,completed.stderr.decode(errors='replace')
    result=json.loads(output.read_text(encoding='utf-8'))
    assert result['ok'],result
    assert json.loads((tmp_path/'歌詞.json').read_text(encoding='utf-8'))['lines'][0]['kana']=='うた'
