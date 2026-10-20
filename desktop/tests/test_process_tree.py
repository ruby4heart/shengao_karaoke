import json
import subprocess
import sys
import time
from pathlib import Path
from shengao.process_tree import ProcessTree

def test_closing_owned_job_terminates_backend_and_its_descendant(tmp_path):
    script=tmp_path/'backend.py';marker=tmp_path/'child.json'
    script.write_text("import sys,subprocess,json,time,os\nfrom pathlib import Path\nfrom shengao.process_tree import join_owner_job\njoin_owner_job(sys.argv[2])\nPath(sys.argv[1]+'.ready').write_text(str(os.getpid()))\nsys.stdin.buffer.read(1)\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)'],creationflags=subprocess.CREATE_NO_WINDOW)\nPath(sys.argv[1]).write_text(json.dumps({'child':p.pid}))\ntime.sleep(90)\n",encoding='utf-8')
    job=ProcessTree();child=None
    process=subprocess.Popen([sys.executable,str(script),str(marker),job.name],stdin=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        end=time.monotonic()+10
        while not Path(str(marker)+'.ready').exists() and time.monotonic()<end:time.sleep(.02)
        assert Path(str(marker)+'.ready').is_file()
        # Deliberately assign the launcher only after its real interpreter has
        # started, reproducing the Windows venv race rather than hiding it.
        job.assign(process.pid);process.stdin.write(b'1');process.stdin.flush()
        end=time.monotonic()+10
        while not marker.exists() and time.monotonic()<end:time.sleep(.02)
        assert marker.is_file();pid=json.loads(marker.read_text())['child']
        import ctypes
        from ctypes import wintypes as w
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
        kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];kernel.WaitForSingleObject.restype=w.DWORD
        kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
        child=kernel.OpenProcess(0x100000,False,pid);assert child
        job.close();process.wait(timeout=5)
        assert kernel.WaitForSingleObject(child,5000)==0
    finally:
        job.close()
        if process.poll() is None:process.kill();process.wait()
        if child:kernel.CloseHandle(child)
