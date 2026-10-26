from pathlib import Path
import hashlib,json,urllib.request,zipfile
from json_runtime_sources import VERSION,FILES,verify

root=Path(__file__).resolve().parents[1];folder=root/'vendor/orjson';folder.mkdir(parents=True,exist_ok=True)
for name,(url,digest) in FILES.items():
    target=folder/name
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
        data=urllib.request.urlopen(url,timeout=30).read()
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Downloaded orjson fingerprint mismatch')
        target.write_bytes(data)
licenses=folder/'licenses';licenses.mkdir(exist_ok=True)
with zipfile.ZipFile(folder/next(name for name in FILES if name.endswith('.whl'))) as archive:
    for name in archive.namelist():
        if '.dist-info/licenses/' in name and not name.endswith('/'):(licenses/Path(name).name).write_bytes(archive.read(name))
        elif name.endswith('.dist-info/METADATA'):(folder/'METADATA.txt').write_bytes(archive.read(name))
(folder/'SOURCES.json').write_text(json.dumps({'package':'orjson','version':VERSION,'metadata_url':'https://pypi.org/pypi/orjson/3.13.0/json',
    'project_url':'https://github.com/ijl/orjson','files':{name:{'url':url,'sha256':digest} for name,(url,digest) in FILES.items()}},indent=2),encoding='utf-8')
verify(root,installed=False)
print(json.dumps({'version':VERSION,'files':len(FILES),'licenses':[p.name for p in licenses.iterdir()]}))
