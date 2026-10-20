from pathlib import Path
import os
import subprocess
import sys
import uuid
import json
from desktop_source_state import snapshot

root=Path(__file__).resolve().parents[1];before=snapshot(root)
env=os.environ.copy();env['PYTHONPATH']=str(root/'desktop')+os.pathsep+str(root/'backend');env['QT_QPA_PLATFORM']='offscreen'
env['PATH']=str(root/'dist'/'ShengaoKaraoke-0.7.0-final-win64')+os.pathsep+env['PATH']
base=(root/'tmp'/('desktop-pytest-'+uuid.uuid4().hex)).resolve()
assert base.is_relative_to((root/'tmp').resolve()) and not base.exists()
code=subprocess.call([sys.executable,'-m','pytest','desktop/tests','backend/tests','-q','--basetemp',str(base),*sys.argv[1:]],cwd=root,env=env)
record=root/'build'/'desktop-test-sources.json'
selected=any(a in {'-k','-m','--lf','--last-failed'} or a.startswith(('-k=','-m=')) or '::' in a for a in sys.argv[1:])
if code==0 and not selected and snapshot(root)==before:
    record.write_text(json.dumps({'sources':before,'arguments':sys.argv[1:]},indent=2),encoding='utf-8')
elif not selected:record.unlink(missing_ok=True)
raise SystemExit(code)
