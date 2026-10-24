"""Startup errors must return safe IPC results rather than disappearing."""
import json
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.parametrize('payload',[b'',b'{"key":"secret-test-token-never-print",',b'\xff'])
def test_invalid_stdin_returns_safe_failure(tmp_path,payload):
    root=Path(__file__).resolve().parents[2]
    output=tmp_path/'result.json'
    completed=subprocess.run([sys.executable,str(root/'backend/worker_entry.py'),
                              '--request','-','--result',str(output),'--home',str(tmp_path/'home')],
                             input=payload,capture_output=True,timeout=20)
    assert completed.returncode==1
    result=json.loads(output.read_text(encoding='utf-8'))
    assert not result['ok'] and result['code']=='invalid_request'
    assert json.loads(Path(str(output)+'.progress.json').read_text(encoding='utf-8'))['phase']=='error'
    assert 'secret-test-token' not in output.read_text(encoding='utf-8')
    assert b'secret-test-token' not in completed.stdout+completed.stderr
    assert result['code_trace'] and all(set(v)=={'file','function','line'} for v in result['code_trace'])
    assert all(not Path(v['file']).is_absolute() and '/' not in v['file'] and '\\' not in v['file'] for v in result['code_trace'])
