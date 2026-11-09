import os
import shutil

from shengao import media_locate
from shengao.media_versions import MediaVersion
from shengao.project import Project,file_stamp


def make(path,size=64):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'\0'*size);return path


def recorded(path):
    stamp=file_stamp(path)
    return Project(media=str(path),media_stamp=stamp,media_versions={'original':MediaVersion(str(path),1000,dict(stamp))},
                   transcript_stamp=dict(stamp),duration=1000)


def test_moved_file_is_found_and_every_stamp_follows(tmp_path):
    old=make(tmp_path/'old'/'素材.mp4');project=recorded(old)
    new=tmp_path/'work'/'video'/'素材.mp4';new.parent.mkdir(parents=True);shutil.move(old,new)
    found=media_locate.locate(project.media,project.media_stamp,tmp_path/'work'/'song.sgproj')
    assert [c.path for c in found]==[str(new.resolve())] and found[0].same_file
    data=project.to_dict()
    assert media_locate.remap(data,project.media,found[0].path,True)>=4
    moved=Project.from_dict(data)
    assert moved.media==str(new.resolve()) and moved.media_versions['original'].path==str(new.resolve())
    assert moved.media_stamp==file_stamp(new)==moved.transcript_stamp==moved.media_versions['original'].stamp


def test_renamed_file_needs_matching_size_and_time(tmp_path):
    old=make(tmp_path/'song'/'take1.mp4',77);project=recorded(old)
    renamed=old.with_name('final.mp4');os.replace(old,renamed)
    make(tmp_path/'song'/'other.mp4',77)  # same size, different time
    os.utime(tmp_path/'song'/'other.mp4',ns=(1,1))
    found=media_locate.locate(project.media,project.media_stamp,tmp_path/'song'/'p.sgproj')
    assert [c.path for c in found]==[str(renamed.resolve())] and found[0].same_file


def test_copied_file_keeps_old_stamps_for_recheck(tmp_path):
    old=make(tmp_path/'a'/'mv.mp4',90);project=recorded(old)
    copy=make(tmp_path/'b'/'mv.mp4',90);os.utime(copy,ns=(5,5));old.unlink()
    found=media_locate.locate(project.media,project.media_stamp,tmp_path/'b'/'p.sgproj')
    assert found and not found[0].same_file
    data=project.to_dict();media_locate.remap(data,project.media,found[0].path,False)
    moved=Project.from_dict(data)
    assert moved.media==str(copy.resolve()) and moved.transcript_stamp==project.transcript_stamp


def test_unrelated_files_are_not_offered(tmp_path):
    old=make(tmp_path/'x'/'song.mp4',30);project=recorded(old);old.unlink()
    make(tmp_path/'x'/'song.mp4.txt',30);make(tmp_path/'x'/'song.mp4.part',30);make(tmp_path/'x'/'other.mp4',31)
    assert media_locate.locate(project.media,project.media_stamp,tmp_path/'x'/'p.sgproj')==[]
    assert media_locate.missing_media(project)==[('original',project.media,project.media_stamp)]


def test_name_only_match_is_not_automatic(tmp_path):
    project=Project(media=str(tmp_path/'gone'/'song.wav'))
    make(tmp_path/'p'/'song.wav',12)
    found=media_locate.locate(project.media,{},tmp_path/'p'/'x.sgproj')
    assert len(found)==1 and not found[0].automatic
    stamped=media_locate.locate(project.media,{'size':12,'modified_ns':1},tmp_path/'p'/'x.sgproj')
    assert stamped[0].automatic and not stamped[0].same_file
