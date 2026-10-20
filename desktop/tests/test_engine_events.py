import sys
import threading
import pytest
from shengao.vocal_audio import run

def test_stream_preserves_large_burst_and_final_events(tmp_path):
    script=tmp_path/'events.py';script.write_text("import json\nfor i in range(120):print(json.dumps({'stage':'event','index':i,'payload':'a'*16000}),flush=True)\n",encoding='utf-8')
    received=[];run([sys.executable,str(script)],threading.Event(),engine=True,event=received.append)
    assert [v['index'] for v in received]==list(range(120))
    assert all(len(v['payload'])==16000 for v in received)


def test_cancel_waits_for_real_interpreter_and_log_handle_release(tmp_path):
    script=tmp_path/'cancel.py'
    script.write_text("import sys,json,time,subprocess\nfrom shengao.process_tree import join_owner_job\njoin_owner_job(sys.argv[sys.argv.index('--owner-job')+1])\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)'],creationflags=subprocess.CREATE_NO_WINDOW)\nprint(json.dumps({'stage':'ready','child':p.pid}),flush=True)\ntime.sleep(90)\n",encoding='utf-8')
    cancel=threading.Event();received=[]
    def event(value):received.append(value);cancel.set()
    # Returning a normal cancellation also proves the temporary log was
    # removable after all worker descendants released their Windows handles.
    with pytest.raises(ValueError,match='取消'):
        run([sys.executable,str(script)],cancel,engine=True,event=event)
    assert len(received)==1 and received[0]['child']>0
