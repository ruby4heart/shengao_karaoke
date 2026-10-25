"""Refuse an incomplete or different numerical environment before PyInstaller."""
import hashlib
import importlib.metadata as metadata
import re
from pathlib import Path


def validate_environment(requirements,version=metadata.version):
    requirements=Path(requirements);pins={};seen=set();errors=[];installed={}
    for number,line in enumerate(requirements.read_text(encoding='utf-8').splitlines(),1):
        line=line.split('#',1)[0].strip()
        if not line:continue
        match=re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;]+)',line)
        if match is None:raise ValueError(f'本地引擎依赖第 {number} 行未固定为 name==version；构建未开始')
        name,expected=match.groups();key=re.sub(r'[-_.]+','-',name).lower()
        if key in seen:raise ValueError('本地引擎依赖重复：'+name)
        seen.add(key);pins[name]=expected
    if not pins:raise ValueError('本地引擎依赖清单为空，构建未开始')
    for name,expected in pins.items():
        try:actual=version(name)
        except metadata.PackageNotFoundError:actual=None
        installed[name]=actual
        if actual!=expected:errors.append(f'{name}: 需要 {expected}，当前 {actual or "未安装"}')
    if errors:raise ValueError('当前 Python 环境不满足本地引擎锁定依赖，构建未开始。请按 docs/DESKTOP-BUILD.md 使用 .venv-align：\n'+'\n'.join(errors))
    return {'passed':True,'requirements_sha256':hashlib.sha256(requirements.read_bytes()).hexdigest(),'distributions':installed}
