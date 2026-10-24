"""Retain the build Python's certificate policy in frozen applications."""
from pathlib import Path
import hashlib

NAME='codex-rejected-cas.pem'
SHA256='c916ce1b14ed8ca69e9b5c9fab22799a900dd610d6d4ec9b1347f4fd48e53718'


def pyinstaller_arguments(root,ssl_source=None):
    if ssl_source is None:
        import ssl
        ssl_source=ssl.__file__
    source=Path(ssl_source)
    # Stock CPython has no reference to this sidecar and needs no extra data.
    if NAME not in source.read_text(encoding='utf-8'):return []
    bundled=Path(root)/'vendor/python-tls'/NAME
    for path in (source.with_name(NAME),bundled):
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=SHA256:
            raise ValueError('Python TLS policy data is missing or changed; verify the build runtime and vendor/python-tls before packaging')
    return ['--add-data',str(bundled)+';.']
