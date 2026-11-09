"""Find media files that moved since the project was saved.

Only file names and sizes near the project are inspected; nothing is decoded
or uploaded. A candidate with the same size and modification time is the same
file moved, so every stamp that named the old path is carried over and
existing transcripts stay usable. A candidate with the same name and size but
a different time is offered as the file, while recorded stamps stay as they
were so transcripts and caches are checked again.
"""
from dataclasses import dataclass
from pathlib import Path
import os

MEDIA_SUFFIXES={'.mp4','.mkv','.mov','.webm','.avi','.wav','.mp3','.flac','.m4a','.ogg'}
MAX_ENTRIES=4000


@dataclass
class Candidate:
    path:str
    same_file:bool       # size and modification time match the recorded stamp
    size_match:bool=True # same recorded size; False only when no size was recorded

    @property
    def automatic(self):
        """Safe to use without asking: the same file, or same name and size."""
        return self.same_file or self.size_match


def _norm(path):return os.path.normcase(os.path.abspath(str(path)))


def _search_roots(old_path,project_path):
    roots=[]
    if project_path:
        folder=Path(project_path).parent;roots+=[folder,folder.parent]
    old=Path(old_path)
    for parent in list(old.parents)[:3]:roots.append(parent)
    seen=set();result=[]
    for root in roots:
        key=_norm(root)
        if key not in seen and root.is_dir():seen.add(key);result.append(root)
    return result


def _walk(root,depth):
    """Breadth-first, bounded listing of files under root."""
    queue=[(root,0)];count=0
    while queue:
        folder,level=queue.pop(0)
        try:children=sorted(os.scandir(folder),key=lambda e:e.name)
        except OSError:continue
        for entry in children:
            count+=1
            if count>MAX_ENTRIES:return
            try:
                if entry.is_dir(follow_symlinks=False):
                    if level<depth and not entry.name.startswith('.') and not entry.name.endswith('.assets'):queue.append((Path(entry.path),level+1))
                elif entry.is_file():yield Path(entry.path),entry.stat()
            except OSError:continue


def locate(old_path,stamp=None,project_path=None,depth=2):
    """Candidates for a missing media file, best first. Empty when nothing fits."""
    if not old_path:return []
    old=Path(old_path)
    if old.is_file():return [Candidate(str(old),True)]
    stamp=stamp or {};size=stamp.get('size');modified=stamp.get('modified_ns')
    name=old.name.casefold();found={}
    for root in _search_roots(old_path,project_path):
        for path,stat in _walk(root,depth):
            if path.suffix.lower() not in MEDIA_SUFFIXES:continue
            same_name=path.name.casefold()==name;same_size=size is not None and stat.st_size==size
            same_time=same_size and modified is not None and stat.st_mtime_ns==modified
            # A renamed file is accepted only when its size and time both match.
            if not (same_name and (same_size or size is None) or same_time):continue
            key=_norm(path)
            if key not in found:found[key]=(Candidate(str(path.resolve()),bool(same_time),bool(same_size)),same_name)
    ranked=sorted(found.values(),key=lambda item:(not item[0].same_file,not item[1],item[0].path))
    return [candidate for candidate,_ in ranked]


def remap(value,old_path,new_path,same_file):
    """Replace every reference to the old media path inside a project dictionary.

    Stamps are carried over only when the new file is the same file moved.
    Returns the number of replaced references.
    """
    old_key=_norm(old_path);new_abs=str(Path(new_path).resolve());new_key=os.path.normcase(new_abs)
    count=0
    def walk(node):
        nonlocal count
        if isinstance(node,dict):
            if set(node)>={'path','size','modified_ns'} and isinstance(node.get('path'),str) and _norm(node['path'])==old_key:
                if same_file:node['path']=new_key;count+=1
                return
            for key,item in list(node.items()):
                if isinstance(item,str) and item and _looks_like(item,old_key):node[key]=new_abs;count+=1
                else:walk(item)
        elif isinstance(node,list):
            for index,item in enumerate(node):
                if isinstance(item,str) and item and _looks_like(item,old_key):node[index]=new_abs;count+=1
                else:walk(item)
    walk(value)
    return count


def _looks_like(text,old_key):
    if len(text)>4096 or ('/' not in text and '\\' not in text):return False
    try:return _norm(text)==old_key
    except (ValueError,OSError):return False


def missing_media(project):
    """(role, recorded path, stamp) for each recorded media file that is gone."""
    result=[];seen=set()
    if project.media and not Path(project.media).is_file():
        result.append((project.media_role,project.media,project.media_stamp));seen.add(_norm(project.media))
    for role,version in project.media_versions.items():
        if version.path and not Path(version.path).is_file() and _norm(version.path) not in seen:
            result.append((role,version.path,version.stamp));seen.add(_norm(version.path))
    return result
