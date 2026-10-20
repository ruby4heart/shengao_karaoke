"""Build the offline worker, including Janome's mmap dictionary source files."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir',
    '--name','studio-worker','--distpath','build/worker-dist','--workpath','build/worker-build',
    '--specpath','build','--paths','backend','--collect-all','janome','backend/worker_entry.py'],cwd=ROOT,check=True)
