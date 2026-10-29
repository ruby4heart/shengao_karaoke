"""Non-secret local workspace preferences, separate from project/API settings."""
from pathlib import Path
import copy
import json
import os
import time
from studio_backend.settings import atomic_json

class Preferences:
    def __init__(self,home):
        self.path=Path(home)/'workspace.json';self.data={}
        try:
            value=json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(value,dict):self.data=value
        except (OSError,ValueError):pass

    def save(self):atomic_json(self.path,self.data)

    def set(self,name,value):
        self.data[name]=value
        try:self.save()
        except OSError:pass

    def set_many(self,changes):
        """Adopt related non-secret settings only after the file commits.

        Key profiles and their modes must not become active when a preference
        write fails. Both the caller's values and the old live state stay owned.
        Errors deliberately propagate to the settings dialog.
        """
        if type(changes) is not dict or any(not isinstance(key,str) for key in changes):
            raise ValueError('设置更新必须是具名字段')
        candidate=copy.deepcopy(self.data);candidate.update(copy.deepcopy(changes))
        atomic_json(self.path,candidate)
        self.data=candidate

    def recent(self):
        values=self.data.get('recent',[])
        if not isinstance(values,list):return []
        return [v for v in values if isinstance(v,dict) and isinstance(v.get('path'),str) and isinstance(v.get('title'),str)][:8]

    def remember(self,path,title):
        path=str(Path(path).resolve());identity=os.path.normcase(path)
        values=[v for v in self.recent() if os.path.normcase(v['path'])!=identity]
        self.set('recent',[{'path':path,'title':str(title),'opened':time.time()}]+values[:7])

    def forget(self,path):
        identity=os.path.normcase(str(Path(path).resolve()))
        self.set('recent',[v for v in self.recent() if os.path.normcase(v['path'])!=identity])
