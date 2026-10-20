"""Preserve the already-built standalone FFmpeg runtime with provenance."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
root=Path(__file__).resolve().parents[1]
source=root/'dist'/'ShengaoKaraoke-0.7.0-final-win64';target=root/'vendor'/'desktop-runtime';target.mkdir(parents=True,exist_ok=True)
files=[source/'ffmpeg.exe',*source.glob('*.dll')]
for path in files:shutil.copy2(path,target/path.name)
shutil.copytree(source/'licenses',target/'licenses',dirs_exist_ok=True)
version=subprocess.run([str(target/'ffmpeg.exe'),'-version'],capture_output=True,check=True).stdout.decode(errors='replace')
data={'source':'Existing user-authorized FFmpeg build; full corresponding source in vendor/aegisub/subprojects/ffmpeg',
      'version':version,'files':[{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in target.glob('*') if p.is_file()]}
(target/'SOURCES.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
print(json.dumps({'runtime':str(target),'files':len(files)}))
