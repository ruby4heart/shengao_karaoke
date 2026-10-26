"""Official fixed orjson artifacts, including redistributable source/licenses."""
from pathlib import Path
import hashlib,json,importlib.metadata,zipfile

VERSION='3.13.0'
FILES={
    'orjson-3.13.0-cp312-cp312-win_amd64.whl':('https://files.pythonhosted.org/packages/58/9d/a1ca7321eeafd7d72e174cdc388cc96301f41516d863e7b1f64f0a1735be/orjson-3.13.0-cp312-cp312-win_amd64.whl','b571236d8393edcd3236e07423f762bfcf571f852aad667a3bce9e7b755e0790'),
    'orjson-3.13.0.tar.gz':('https://files.pythonhosted.org/packages/f2/72/380b97dc45bd162d23afe5194721ef678d9eac7cfaa549fe2873f7f0a518/orjson-3.13.0.tar.gz','d1de5eb04485110c5da4c657e49168995d55e076b1ce60f1a042e254f4186c4f'),
}


def verify(root,installed=True):
    folder=Path(root)/'vendor/orjson'
    for name,(url,digest) in FILES.items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:raise ValueError('orjson artifact fingerprint mismatch: '+name)
    provenance=json.loads((folder/'SOURCES.json').read_text(encoding='utf-8'))
    if provenance.get('version')!=VERSION or provenance.get('files')!={name:{'url':url,'sha256':digest} for name,(url,digest) in FILES.items()}:raise ValueError('orjson source provenance mismatch')
    with zipfile.ZipFile(folder/next(name for name in FILES if name.endswith('.whl'))) as archive:
        for name in archive.namelist():
            if '.dist-info/licenses/' in name and not name.endswith('/'):
                if (folder/'licenses'/Path(name).name).read_bytes()!=archive.read(name):raise ValueError('orjson license differs from wheel')
            elif name.endswith('.dist-info/METADATA'):
                if (folder/'METADATA.txt').read_bytes()!=archive.read(name):raise ValueError('orjson metadata differs from wheel')
    if installed:
        distribution=importlib.metadata.distribution('orjson')
        if distribution.version!=VERSION:raise ValueError('orjson installed version mismatch')
        package=Path(distribution.locate_file('orjson')).resolve()
        with zipfile.ZipFile(folder/next(name for name in FILES if name.endswith('.whl'))) as archive:
            for name in archive.namelist():
                if not name.startswith('orjson/') or name.endswith('/'):continue
                path=Path(distribution.locate_file(name)).resolve()
                if not path.is_relative_to(package) or hashlib.sha256(path.read_bytes()).digest()!=hashlib.sha256(archive.read(name)).digest():raise ValueError('orjson installed file differs from wheel: '+name)
    return {'version':VERSION,'artifacts':{name:digest for name,(url,digest) in FILES.items()},'installed_checked':installed}
