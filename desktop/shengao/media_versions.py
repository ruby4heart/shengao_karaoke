"""Named media files share one subtitle document and its absolute timestamps."""
from dataclasses import dataclass, field
from pathlib import Path

ROLES={'original':'原唱版','instrumental':'伴奏版'}

@dataclass
class MediaVersion:
    path:str
    duration:int=0
    stamp:dict=field(default_factory=dict)

    def validate(self):
        if not isinstance(self.path,str) or not self.path:raise ValueError('视频版本路径无效')
        if type(self.duration) is not int or self.duration<0:raise ValueError('视频版本时长无效')
        if not isinstance(self.stamp,dict):raise ValueError('视频版本文件标识无效')

def switch_warnings(project,metadata):
    duration=int(metadata['duration']);warnings=[]
    if project.duration and abs(duration-project.duration)>300:
        direction='长' if duration>project.duration else '短'
        warnings.append(f'新源比当前源{direction} {abs(duration-project.duration)/1000:.3f} 秒。')
    last=max((max(line.end,line.display_end or 0) for line in project.lines),default=0)
    if last>duration:warnings.append(f'字幕最晚到 {last/1000:.3f} 秒，新源只有 {duration/1000:.3f} 秒，片尾可能看不全。')
    return warnings

def apply_media_version(project,role,path,metadata,stamp):
    if role not in ROLES:raise ValueError('视频版本类型无效')
    if project.media:
        project.media_versions[project.media_role]=MediaVersion(project.media,project.duration,project.media_stamp.copy())
    project.media_role=role;project.media=str(Path(path).resolve())
    project.duration=int(metadata['duration']);project.width=int(metadata['width']);project.height=int(metadata['height']);project.fps=float(metadata['fps']);project.has_video=bool(metadata['has_video'])
    project.media_stamp=stamp.copy();project.media_versions[role]=MediaVersion(project.media,project.duration,stamp.copy())
    # Existing transcript remains tied to its original file stamp. It may be
    # reused when that source returns, never relabelled as accompaniment speech.

