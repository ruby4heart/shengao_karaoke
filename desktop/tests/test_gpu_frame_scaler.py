"""Actual native GPU pixels in an owned hidden process, separate from qapp."""
import json,os,subprocess,sys
from pathlib import Path
import pytest


@pytest.mark.parametrize('scale',['1','1.5'])
def test_native_gpu_scaling_geometry_zoom_pts_and_cpu_fallback(tmp_path,scale):
    root=Path(__file__).resolve().parents[2]
    env={key:value for key,value in os.environ.items() if key not in ('PYTHONPATH','PYTHONHOME','QT_QUICK_BACKEND','QSG_RHI_BACKEND','ELEVENLABS_API_KEY','MAI_SPEECH_KEY','DEEPSEEK_API_KEY')}
    env['QT_QPA_PLATFORM']='windows';env['QT_SCALE_FACTOR']=scale
    result=subprocess.run([sys.executable,str(root/'desktop/main.py'),'--gpu-preview-test','--output',str(tmp_path/'native-gpu')],cwd=root,env=env,capture_output=True,timeout=90)
    assert result.returncode==0,result.stderr.decode(errors='replace')[-5000:]
    report=json.loads((tmp_path/'native-gpu/report.json').read_text(encoding='utf-8'))
    assert report['passed'] and len(report['checks'])==31 and all(check['passed'] for check in report['checks'])
