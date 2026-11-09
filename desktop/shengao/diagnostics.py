"""A diagnostics report the person can send without leaking keys or lyrics.

Everything comes from whitelists: only named, non-private fields of task
records are copied, and every string still passes through redaction of API
keys, the person's home folder and user name, and the task's own lyrics.
Requests, transcripts, suggestions and raw service responses are never read
into the report.
"""
from pathlib import Path
import json
import os
import platform
import re
import sys
import time

REDACTED='〔已隐去〕'
LYRIC='〔歌词已隐去〕'
_DIAGNOSTIC_KEYS=('stage','billing','phase','http_status','request_id','error_code','exception',
                  'elapsed_ms','uploaded_bytes','upload_size','response_bytes','response_saved')
_REQUEST_KEYS=('action','provider','language','range_mode','mode','force','use_llm','gap_ms','backend')
_RENDER_KEYS=('kind','state','created','message','encoder','quality','size','width','height','duration','code','elapsed_ms')
_SECRET_PATTERNS=[
    (re.compile(r'(?i)\b(bearer)\s+[^\s"\',;]+'),r'\1 '+REDACTED),
    (re.compile(r'(?i)((?:xi-api-key|ocp-apim-subscription-key|authorization|api[_-]?key|access[_-]?token|secret|password)["\']?\s*[:=]\s*["\']?)[^\s"\',;]+'),r'\1'+REDACTED),
    (re.compile(r'\bsk[-_][A-Za-z0-9_\-]{12,}'),REDACTED),
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'),'〔邮箱已隐去〕'),
    (re.compile(r'(?i)([a-z]:[\\/](?:users|documents and settings)[\\/])[^\\/\s"\']+'),r'\1〔用户〕'),
    (re.compile(r'(/(?:home|Users)/)[^/\s"\']+'),r'\1〔用户〕'),
]


class Redactor:
    def __init__(self,secrets=(),private_paths=(),texts=()):
        self.secrets=sorted({s for s in secrets if isinstance(s,str) and len(s)>=6},key=len,reverse=True)
        paths=set()
        for path in private_paths:
            if path:
                text=str(path);paths.update({text,text.replace('\\','/'),text.replace('/','\\')})
        self.paths=sorted((p for p in paths if len(p)>3),key=len,reverse=True)
        # Short Latin fragments ('to', 'ai') would blank unrelated words.
        self.texts=sorted({t.strip() for t in texts if isinstance(t,str) and len(t.strip())>=(4 if t.strip().isascii() else 2)},key=len,reverse=True)
        user=os.getenv('USERNAME') or os.getenv('USER') or ''
        self.user=user if len(user)>=3 else ''

    def __call__(self,value):
        if isinstance(value,dict):return {k:self(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [self(v) for v in value]
        if not isinstance(value,str):return value
        for secret in self.secrets:value=value.replace(secret,REDACTED)
        for path in self.paths:value=value.replace(path,'〔个人目录〕')
        for text in self.texts:value=value.replace(text,LYRIC)
        for pattern,replacement in _SECRET_PATTERNS:value=pattern.sub(replacement,value)
        if self.user:value=re.sub(r'(?<![A-Za-z0-9])'+re.escape(self.user)+r'(?![A-Za-z0-9])','〔用户〕',value,flags=re.I)
        return value[:2000]


def _read(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return None


def _diagnostics(value,found=None,label=''):
    """Every nested ``diagnostics`` dict, reduced to the whitelisted keys."""
    found=[] if found is None else found
    if isinstance(value,dict):
        for key,item in value.items():
            if key=='diagnostics' and isinstance(item,dict):
                flat={k:item[k] for k in _DIAGNOSTIC_KEYS if k in item and isinstance(item[k],(str,int,float,bool))}
                if flat:found.append({'part':label or '请求',**flat})
                for name,nested in item.items():
                    if isinstance(nested,dict):_diagnostics({'diagnostics':nested},found,name)
            elif isinstance(item,(dict,list)):_diagnostics(item,found,label)
    elif isinstance(value,list):
        for item in value:_diagnostics(item,found,label)
    return found


def _media(path):
    if not path:return None
    path=Path(str(path))
    info={'extension':path.suffix.lower()}
    try:info['size_mb']=round(path.stat().st_size/1048576,2)
    except OSError:info['present']=False
    return info


def _lyrics(request):
    texts=[]
    for key in ('lines','transcript','context'):
        for line in request.get(key,[]) if isinstance(request.get(key),list) else []:
            if isinstance(line,dict):
                texts.append(line.get('text',''));texts.extend(u.get('text','') for u in line.get('units',[]) if isinstance(u,dict) and len(u.get('text',''))>=2)
                texts.extend(line.get(k,'') for k in ('translation','kana','romaji'))
    return texts


def tasks(home,limit=20):
    """Recent background tasks, newest first, with private fields left out."""
    root=Path(home)/'desktop-tasks';result=[]
    folders=sorted((f for f in root.iterdir() if f.is_dir()),key=lambda f:f.stat().st_mtime,reverse=True)[:limit] if root.is_dir() else []
    for folder in folders:
        request=_read(folder/'request.json') or {}
        outcome=_read(folder/'result.json');progress=_read(folder/'result.json.progress.json') or {}
        entry={'task':folder.name[:12],'modified':time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(folder.stat().st_mtime))}
        entry.update({k:request[k] for k in _REQUEST_KEYS if k in request and isinstance(request[k],(str,int,float,bool))})
        if isinstance(request.get('draft_options'),dict):entry['draft_options']={k:v for k,v in request['draft_options'].items() if isinstance(v,(str,int,float,bool))}
        if isinstance(request.get('lines'),list):entry['line_count']=len(request['lines'])
        if request.get('media'):entry['media']=_media(request['media'])
        if outcome is None:entry['result']='没有最终结果'
        else:
            entry['ok']=bool(outcome.get('ok'));entry['cancelled']=bool(outcome.get('cancelled'))
            for key in ('message','exception','code','cached','partial'):
                if key in outcome and isinstance(outcome[key],(str,int,float,bool)):entry[key]=outcome[key]
            if isinstance(outcome.get('code_trace'),list):entry['code_trace']=[{k:v.get(k) for k in ('file','function','line')} for v in outcome['code_trace'][:20] if isinstance(v,dict)]
            entry['diagnostics']=_diagnostics(outcome)
        if progress:entry['last_progress']={k:progress.get(k) for k in ('phase','message') if isinstance(progress.get(k),str)}
        entry['_lyrics']=_lyrics(request)
        result.append(entry)
    return result


def renders(home,limit=10):
    root=Path(home)/'desktop-renders'
    files=sorted(root.glob('*.json'),key=lambda f:f.stat().st_mtime,reverse=True)[:limit] if root.is_dir() else []
    result=[]
    for file in files:
        value=_read(file)
        if isinstance(value,dict):result.append({k:value[k] for k in _RENDER_KEYS if k in value and isinstance(value[k],(str,int,float,bool))})
    return result


def environment():
    info={'app_version':'','python':platform.python_version(),'os':platform.platform(),'machine':platform.machine(),
          'frozen':bool(getattr(sys,'frozen',False))}
    try:
        from . import __version__;info['app_version']=__version__
    except ImportError:pass
    try:
        import PySide6;info['qt']=PySide6.__version__
    except ImportError:pass
    return info


def services(settings):
    """Which services are set up; never the keys themselves."""
    try:public=settings.public()
    except (OSError,ValueError):return {}
    return {name:{'has_key':bool(value.get('has_key')),**({'model':value['model']} if isinstance(value.get('model'),str) else {}),
                  **({'endpoint_host':re.sub(r'^https?://([^/]+).*$',r'\1',value['endpoint'])} if isinstance(value.get('endpoint'),str) and value['endpoint'] else {})}
            for name,value in public.items() if isinstance(value,dict)}


def secrets(settings):
    values=[]
    for provider in ('elevenlabs','mai','deepseek'):
        try:values.append(settings.key(provider))
        except Exception:pass  # DPAPI unavailable or damaged: patterns still apply
    return values


def report(home,project=None,settings=None,extra_secrets=()):
    """The full report as (text, data). Text is what the person saves."""
    home=Path(home)
    if settings is None:
        from studio_backend.settings import Settings
        settings=Settings(home)
    recent=tasks(home)
    lyrics=[t for entry in recent for t in entry.pop('_lyrics')]
    if project is not None:
        for line in project.lines:lyrics.extend([line.text,line.translation,line.kana,line.romaji]+[u.text for u in line.units if len(u.text)>=2])
    data={'generated':time.strftime('%Y-%m-%d %H:%M:%S'),'environment':environment(),'services':services(settings),
          'project':None,'tasks':recent,'renders':renders(home)}
    if project is not None:
        data['project']={'lines':len(project.lines),'units':sum(len(l.units) for l in project.lines),'duration_ms':project.duration,
                         'media':_media(project.media),'media_role':getattr(project,'media_role',''),
                         'media_versions':len(getattr(project,'media_versions',{}) or {}),
                         'ass_compatibility_mode':bool(project.source_ass_active)}
    redact=Redactor([*secrets(settings),*extra_secrets],[home,Path.home(),os.getenv('APPDATA',''),os.getenv('LOCALAPPDATA','')],lyrics)
    data=redact(data)
    rows=['声稿诊断报告','本报告不含 API 密钥、歌词、识别原文或素材文件名；个人目录与用户名已替换。发送前仍可自行检查。','',
          f"生成时间：{data['generated']}",'',"[运行环境]"]
    rows+=[f'{k}：{v}' for k,v in data['environment'].items()]
    rows+=['',"[服务配置]"]+([f"{k}：{'已填写密钥' if v['has_key'] else '未填写密钥'}"+(f"，模型 {v['model']}" if v.get('model') else '')+(f"，主机 {v['endpoint_host']}" if v.get('endpoint_host') else '') for k,v in data['services'].items()] or ['未配置'])
    if data['project']:rows+=['',"[当前作品]"]+[f'{k}：{v}' for k,v in data['project'].items()]
    rows+=['',f"[最近后台任务 {len(data['tasks'])} 个]"]
    for entry in data['tasks']:
        state='成功' if entry.get('ok') else '已取消' if entry.get('cancelled') else '失败' if 'ok' in entry else entry.get('result','')
        rows.append(f"- {entry['modified']} {entry.get('action','未知操作')}{' · '+entry['provider'] if entry.get('provider') else ''} · {state}")
        if entry.get('message'):rows.append('  说明：'+entry['message'])
        for item in entry.get('diagnostics',[]):
            rows.append('  阶段：'+'，'.join(f'{k}={v}' for k,v in item.items()))
    rows+=['',f"[最近视频压制 {len(data['renders'])} 个]"]+[f"- {', '.join(f'{k}={v}' for k,v in r.items())}" for r in data['renders']]
    rows+=['','[结构化数据]',json.dumps(data,ensure_ascii=False,indent=1)]
    return '\n'.join(rows)+'\n',data


def write(path,home,project=None,settings=None):
    text,_=report(home,project,settings)
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(text,encoding='utf-8-sig');os.replace(temporary,path)
    return path
