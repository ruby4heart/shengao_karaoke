from pathlib import Path
import hashlib

def state(root):
    root=Path(root)
    files=['desktop/vocal_engine.py','desktop/alignment_engine.py','desktop/audio_contract.py','desktop/shengao/__init__.py','desktop/shengao/process_tree.py','desktop/vocal-requirements.lock','scripts/build-vocal-engine.py','scripts/vocal_source_state.py']
    files += [p.relative_to(root).as_posix() for p in (root/'vendor/vocal-model').glob('*') if p.is_file()]
    files += ['scripts/python_tls_resources.py']
    files += [p.relative_to(root).as_posix() for p in (root/'vendor/python-tls').glob('*') if p.is_file()]
    files += [p.relative_to(root).as_posix() for folder in ('tifa','tifa-model') for p in (root/'vendor'/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sorted(files)}
