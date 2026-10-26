import copy,json,os,shutil,subprocess,sys,threading,time
from pathlib import Path
import pytest
from shengao import proxy_video as proxy
from shengao.paths import ffmpeg
from shengao.project import file_stamp


@pytest.fixture(scope='module')
def prepared(video,tmp_path_factory):
    folder=tmp_path_factory.mktemp('verified-proxy');result=proxy.prepare(video,folder/'cache')
    return video,folder,result


def test_actual_video_keeps_every_frame_and_exact_decoded_audio(prepared):
    source,folder,result=prepared;a=result['verification'];p=Path(result['path'])
    assert p.is_file() and proxy.digest(p)==result['sha256'] and not result['reused']
    assert a['source']['video_frames']==a['proxy']['video_frames']==200
    assert a['max_video_drift_us']==0 and a['max_audio_edge_drift_us']<=2000
    assert a['source']['width']==640 and a['source']['height']==360
    assert result['audio_sha256']==proxy.audio_digest(source)==proxy.audio_digest(p)


def test_verified_cache_reuse_does_not_encode_again(prepared,monkeypatch):
    source,folder,first=prepared
    monkeypatch.setattr(proxy,'command',lambda *args:pytest.fail('A verified cache must not encode again'))
    again=proxy.prepare(source,folder/'cache')
    assert again['reused'] and again['path']==first['path'] and again['source_stamp']==file_stamp(source)


def test_same_path_same_size_and_mtime_changed_content_cannot_reuse_old_source(video,tmp_path):
    source=tmp_path/'素材.mp4';shutil.copy2(video,source);before=proxy.prepare(source,tmp_path/'cache');stamp=file_stamp(source);stat=source.stat()
    raw=source.read_bytes();assert b'Lavf' in raw;source.write_bytes(raw.replace(b'Lavf',b'Lawf',1));os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    assert file_stamp(source)==stamp
    after=proxy.prepare(source,tmp_path/'cache')
    assert not after['reused'] and before['source_sha256']!=after['source_sha256']


def test_corrupt_proxy_is_rebuilt_without_touching_source(video,tmp_path):
    before=proxy.digest(video);first=proxy.prepare(video,tmp_path/'cache');Path(first['path']).write_bytes(b'broken proxy')
    after=proxy.prepare(video,tmp_path/'cache')
    assert not after['reused'] and proxy.digest(after['path'])==after['sha256'] and proxy.digest(video)==before


def test_cancel_before_start_leaves_no_ready_cache(video,tmp_path):
    cancel=threading.Event();cancel.set()
    with pytest.raises(ValueError,match='已取消'):proxy.prepare(video,tmp_path/'cache',cancel)
    assert not list(tmp_path.rglob('ready.json'))


def test_cancel_after_encoding_progress_does_not_publish_partial_result(video,tmp_path):
    cancel=threading.Event()
    def progress(value):
        if isinstance(value,dict) and value['phase']=='encode':cancel.set()
    with pytest.raises(ValueError,match='已取消'):proxy.prepare(video,tmp_path/'cache',cancel,progress)
    assert not list(tmp_path.rglob('ready.json')) and not list(tmp_path.rglob('pending-*'))


def test_changed_source_while_verifying_is_not_published(video,tmp_path):
    source=tmp_path/'changing.mp4';shutil.copy2(video,source)
    def progress(value):
        if isinstance(value,str) and value.startswith('正在逐帧'):source.write_bytes(source.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='原片内容'):proxy.prepare(source,tmp_path/'cache',progress=progress)
    assert not list(tmp_path.rglob('ready.json')) and not list(tmp_path.rglob('pending-*'))


def test_variable_frame_times_and_original_audio_video_offset_are_preserved(tmp_path):
    source=tmp_path/'不等间隔与偏移.mkv'
    command=[ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y',
        '-f','lavfi','-i','testsrc2=s=1920x1080:r=30:d=1.2','-f','lavfi','-i','sine=frequency=720:sample_rate=48000:duration=1.5',
        '-filter_complex',"[0:v]select='not(mod(n,2))+not(mod(n,5))',settb=1/1000,setpts=PTS+125[v];[1:a]asetpts=PTS+0.065/TB[a]",
        '-map','[v]','-map','[a]','-c:v','h264_mf','-hw_encoding','0','-b:v','3M','-pix_fmt','nv12',
        '-enc_time_base:v','1:1000','-fps_mode:v','passthrough','-c:a','pcm_s16le','-avoid_negative_ts','disabled',str(source)]
    result=subprocess.run(command,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    prepared=proxy.prepare(source,tmp_path/'cache');verification=prepared['verification'];a=verification['source'];b=verification['proxy']
    assert 15<a['video_frames']<36 and a['video_start_us']-a['audio_start_us']>=50000
    assert a['video_start_us']==b['video_start_us'] and verification['max_video_drift_us']<=1000
    assert (b['width'],b['height'])==(1280,720) and verification['max_audio_edge_drift_us']<=2000


@pytest.mark.parametrize('field,value',[('file','../../original.mp4'),('version','old'),('sha256','bad'),('verification',{}),('profile',{}),('audio_sha256','bad')])
def test_invalid_cache_metadata_is_rejected(prepared,field,value):
    _,_,result=prepared;bad=copy.deepcopy(result);bad[field]=value
    with pytest.raises(ValueError):proxy.ready_record(bad,result['source_sha256'],result['ffmpeg_sha256'])


def test_missing_audio_stream_fails_without_creating_a_ready_cache(tmp_path):
    source=tmp_path/'静音无音轨.mp4';result=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i','color=s=128x128:r=25:d=0.2','-c:v','h264_mf','-hw_encoding','0',str(source)],capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0
    with pytest.raises(ValueError):proxy.prepare(source,tmp_path/'cache')
    assert not list(tmp_path.rglob('ready.json'))


def test_cancel_interrupts_a_silent_process_and_waits_for_it_to_exit(monkeypatch):
    cancel=threading.Event();processes=[];original=proxy.subprocess.Popen
    def capture(*args,**kwargs):
        p=original(*args,**kwargs);processes.append(p);return p
    monkeypatch.setattr(proxy.subprocess,'Popen',capture);began=time.monotonic()
    with pytest.raises(ValueError,match='已取消'):
        proxy.run([sys._base_executable,'-c',"import time;print('out_time_us=1',flush=True);time.sleep(60)"],cancel,lambda value:cancel.set())
    assert time.monotonic()-began<3 and processes and all(p.poll() is not None for p in processes)


def test_incomplete_numbered_audit_records_cannot_silently_skip_frames():
    audit=proxy.TimingAudit()
    with pytest.raises(ValueError,match='不连续'):audit.feed('[Parsed_showinfo_0] n: 1 pts: 40 pts_time:0.04 duration:40 duration_time:0.04 fmt:nv12 s:640x360')
    with pytest.raises(ValueError,match='不连续'):audit.feed('[Parsed_ashowinfo_0] n:1 pts:0 pts_time:0 fmt:s16 channels:2 rate:48000 nb_samples:960')
