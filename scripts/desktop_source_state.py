"""Source/runtime inventory shared by build, tests and release gates."""
from pathlib import Path
import hashlib
import ast

def app_version(root):
    tree=ast.parse((Path(root)/'desktop/shengao/__init__.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in node.targets):return ast.literal_eval(node.value)
    raise ValueError('Missing desktop application version')

def snapshot(root):
    root=Path(root)
    paths=[p for folder in ['desktop','backend/studio_backend','backend/tests','scripts'] for p in (root/folder).rglob('*') if p.is_file() and not {'__pycache__','.pytest_cache'}&set(p.parts)]
    paths.extend(p for p in (root/'backend').glob('*.py'))
    paths += [root/'meson.build']
    paths += list((root/'build'/'desktop').glob('shengao-*.dll'))
    paths += list((root/'vendor'/'vocal-model').glob('*'))
    paths += [p for folder in ('tifa','tifa-model') for p in (root/'vendor'/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    paths += [p for p in (root/'vendor/tbb-runtime').glob('*') if p.is_file()]
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
