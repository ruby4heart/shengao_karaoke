"""Per-user configuration; API secrets are Windows-DPAPI encrypted at rest."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
import time


def default_home():
    return Path(os.getenv('SHENGAO_HOME', str(Path(os.getenv('APPDATA', Path.home())) / 'ShengaoKaraoke')))


def atomic_json(path, value, *, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.stem + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            if compact:stream.write(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False))
            else:json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows antivirus/indexers and short-lived JSON readers can hold the
        # destination without FILE_SHARE_DELETE. Retry only the local atomic
        # rename, never the operation (or any billable request) that produced it.
        for attempt in range(8):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 7: raise
                time.sleep(min(.01 * 2**attempt, .08))
    finally:
        Path(temp).unlink(missing_ok=True)


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(value, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('当前版本仅支持 Windows DPAPI 密钥存储')
    buf = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    fn = getattr(ctypes.WinDLL('crypt32', use_last_error=True), 'CryptUnprotectData' if decrypt else 'CryptProtectData')
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(result.data)


class Settings:
    def __init__(self, root=None):
        self.root = Path(root) if root else default_home()
        self.path = self.root / 'settings.json'

    def read(self):
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding='utf-8'))

    def public(self):
        data = self.read()
        return {name: {**{k: v for k,v in value.items() if k != 'secret'}, 'has_key': bool(value.get('secret'))}
                for name,value in data.items()}

    def key(self, provider):
        data = self.read().get(provider, {})
        if data.get('secret'):
            return crypt(base64.b64decode(data['secret']), True).decode('utf-8')
        environment = {'elevenlabs':'ELEVENLABS_API_KEY', 'mai':'MAI_SPEECH_KEY', 'deepseek':'DEEPSEEK_API_KEY'}
        return os.getenv(environment.get(provider, ''), '').strip()

    def save(self, provider, key='', **options):
        if provider not in {'elevenlabs', 'mai', 'deepseek'}:
            raise ValueError('不支持的服务')
        data = self.read()
        config = data.setdefault(provider, {})
        if key:
            if len(key) > 1024 or any(c.isspace() for c in key):
                raise ValueError('密钥格式无效')
            config['secret'] = base64.b64encode(crypt(key.encode('utf-8'))).decode('ascii')
        for name in ('endpoint','model','ffmpeg'):
            if name in options:
                config[name] = options[name]
        atomic_json(self.path, data)

    def forget(self, provider):
        data = self.read()
        data.get(provider, {}).pop('secret', None)
        atomic_json(self.path, data)
