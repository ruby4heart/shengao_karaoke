"""Prepare a test-only view library with freshly extracted original methods.

The drawing bodies have recorded SHA256 parity with the user-provided pristine
3.5.0 source. The scene adapter is shared; PCM rendering remains independently
checked by shengao-reference.dll. This is not a reference for every user gesture.
"""
from pathlib import Path
import subprocess
import sys
import json

root=Path(__file__).resolve().parents[1];dest=root/'build'/'desktop-reference'
subprocess.run([sys.executable,str(root/'scripts'/'extract-timeline-view.py'),'--output',str(dest/'original-timeline')],check=True)
expected=json.loads((root/'desktop/native/aegisub/UPSTREAM-TIMELINE-AUDIT.json').read_text())
actual=json.loads((dest/'original-timeline/TIMELINE-SOURCES.json').read_text())
assert expected['classes_sha256']==actual['classes_sha256'] and expected['methods']==actual['methods'], 'Drawing bodies differ from audited pristine Aegisub 3.5.0'
source=(root/'desktop'/'native'/'timeline_view.cpp').read_text(encoding='utf-8')
source=source.replace('#include SG_TIMELINE_METHODS','#include "original-timeline/timeline_view.inc"')
(dest/'reference_view.cpp').write_text(source,encoding='utf-8')
command=(root/'scripts'/'build-desktop-view.cmd').read_text(encoding='utf-8')
command=command.replace('desktop\\native\\timeline_view.cpp','/I desktop\\native build\\desktop-reference\\reference_view.cpp')
command=command.replace('build\\desktop\\timeline_view.obj','build\\desktop-reference\\timeline_view.obj').replace('build\\desktop\\shengao-view','build\\desktop-reference\\shengao-view-reference')
# The generated command lives one directory deeper than scripts/.
command=command.replace('cd /d "%~dp0.."','cd /d "%~dp0..\\.."')
(dest/'build-view-reference.cmd').write_text(command,encoding='utf-8')
print(dest/'build-view-reference.cmd')
