"""Fetch upstream OFL fonts; retain source URL, license and exact hashes."""
from pathlib import Path
import hashlib
import json
import urllib.request

root=Path(__file__).resolve().parents[1]/'desktop'/'assets'/'fonts'
root.mkdir(parents=True,exist_ok=True)
base='https://raw.githubusercontent.com/notofonts/noto-cjk/main/'
files={
 'NotoSansCJKjp-Regular.otf':'Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf',
 'NotoSerifCJKjp-Regular.otf':'Serif/OTF/Japanese/NotoSerifCJKjp-Regular.otf',
 'NotoSans-LICENSE.txt':'Sans/LICENSE',
 'NotoSerif-LICENSE.txt':'Serif/LICENSE',
}
sources=[]
for name,remote in files.items():
    path=root/name
    if not path.exists():
        with urllib.request.urlopen(base+remote,timeout=120) as response:
            data=response.read()
        if name.endswith('.otf') and data[:4]!=b'OTTO':
            raise ValueError('Upstream font is not an OpenType font')
        path.write_bytes(data)
    sources.append({'file':name,'url':base+remote,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
(root/'SOURCES.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
print(json.dumps(sources,indent=2))
