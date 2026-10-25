"""Personal entries stay in the chosen local application home, outside projects."""
import copy,json,hashlib
from pathlib import Path
from studio_backend.reading_dictionary import validate,merge
from studio_backend.settings import atomic_json


class DictionaryStore:
    def __init__(self,home):
        self.path=Path(home)/'reading-dictionary.json';self.cached_stamp=None;self.cached={};self.previous=None;self.saved_digest=None

    def read(self):
        if not self.path.exists():return {}
        stamp=(self.path.stat().st_size,self.path.stat().st_mtime_ns)
        if self.cached_stamp==stamp:return copy.deepcopy(self.cached)
        try:document=json.loads(self.path.read_text(encoding='utf-8-sig'));validate(document)
        except (OSError,UnicodeError,ValueError) as error:raise ValueError('个人读音词典无法读取，原文件已保留：'+str(self.path)) from error
        self.cached_stamp=stamp;self.cached=copy.deepcopy(document);return document

    def save(self,document):
        validate(document);before=self.read();atomic_json(self.path,document)
        self.previous=copy.deepcopy(before);self.saved_digest=hashlib.sha256(self.path.read_bytes()).hexdigest();self.cached_stamp=None

    def undo_save(self):
        if self.previous is None:raise ValueError('没有可撤销的个人词典保存。')
        if not self.path.is_file() or hashlib.sha256(self.path.read_bytes()).hexdigest()!=self.saved_digest:raise ValueError('个人词典已被别处修改，未用旧记录覆盖。')
        atomic_json(self.path,self.previous);self.previous=None;self.saved_digest=None;self.cached_stamp=None

    def import_file(self,path):
        try:value=json.loads(Path(path).read_text(encoding='utf-8-sig'));validate(value)
        except (OSError,UnicodeError,ValueError) as error:raise ValueError('导入文件不是受支持的读音词典；现有词典保持。') from error
        return merge(self.read(),value)

    def export_file(self,path):atomic_json(Path(path),self.read())

    def digest(self):return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.is_file() else None
