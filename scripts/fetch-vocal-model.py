"""Fetch the fixed official Demucs checkpoint; never loads an arbitrary model."""
from pathlib import Path
import hashlib
import json
import urllib.request

root=Path(__file__).resolve().parents[1]
folder=root/'vendor'/'vocal-model';folder.mkdir(parents=True,exist_ok=True)
name='955717e8-8726e21a.th'
url='https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/'+name
target=folder/name
if not target.is_file():
    partial=target.with_suffix('.download')
    with urllib.request.urlopen(url,timeout=90) as response,partial.open('wb') as output:
        while data:=response.read(1024*1024):output.write(data)
    assert hashlib.sha256(partial.read_bytes()).hexdigest().startswith('8726e21a'),'Official checkpoint checksum mismatch'
    partial.replace(target)
digest=hashlib.sha256(target.read_bytes()).hexdigest()
assert digest.startswith('8726e21a')
(folder/'MODEL.json').write_text(json.dumps({'model':'htdemucs','checkpoint':name,'sha256':digest,'bytes':target.stat().st_size,'url':url,'source':'https://github.com/facebookresearch/demucs','license':'MIT'},indent=2),encoding='utf-8')
print(json.dumps({'path':str(target),'sha256':digest,'bytes':target.stat().st_size}))
