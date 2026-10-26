"""Verified local preview cache; delivery always keeps the original source."""
from array import array
from collections import deque
from contextlib import contextmanager
from decimal import Decimal,InvalidOperation
from pathlib import Path
import hashlib,json,os,queue,re,subprocess,tempfile,threading,time
from .paths import ffmpeg
from .project import file_stamp

VERSION='h264-pcm-preview-v1'
PROFILE={'max_width':1280,'max_height':720,'video':'h264_mf_cpu','bitrate':3000000,'audio':'pcm_s16le'}


def cancelled(cancel):
    if cancel is not None and cancel.is_set():raise ValueError('已取消轻量预览，原片与字幕保持。')


def digest(path,cancel=None):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data:=stream.read(2*1024*1024):cancelled(cancel);result.update(data)
    cancelled(cancel);return result.hexdigest()


def microseconds(value):
    try:return int((Decimal(value)*1000000).to_integral_value())
    except (InvalidOperation,ValueError,OverflowError) as error:raise ValueError('代理时间戳无效，原片保持。') from error


class TimingAudit:
    def __init__(self):
        self.pts=array('q');self.width=0;self.height=0;self.last_duration=0
        self.samples=0;self.rate=0;self.channels=0;self.audio_start=None;self.audio_end=None
        self.audio_packets=0

    def feed(self,line):
        if 'Parsed_showinfo_' in line and 'pts_time:' in line:
            match=re.search(r'\bn:\s*(\d+)\s+pts:.*?pts_time:([^\s]+).*?duration_time:([^\s]+).*?\bs:(\d+)x(\d+)',line)
            if not match:raise ValueError('无法完整核对视频帧时间，代理未采用。')
            if int(match[1])!=len(self.pts):raise ValueError('视频帧核对记录不连续，代理未采用。')
            pts=microseconds(match[2]);duration=microseconds(match[3]);width,height=int(match[4]),int(match[5])
            if self.pts and (pts<self.pts[-1] or (width,height)!=(self.width,self.height)):raise ValueError('视频时间倒序或中途改变尺寸，代理未采用。')
            self.pts.append(pts);self.last_duration=duration;self.width=width;self.height=height
        elif 'Parsed_ashowinfo_' in line and 'pts_time:' in line:
            match=re.search(r'\bn:(\d+)\s+pts:.*?pts_time:([^\s]+).*?channels:(\d+).*?rate:(\d+).*?nb_samples:(\d+)',line)
            if not match:raise ValueError('无法完整核对声音时间，代理未采用。')
            if int(match[1])!=self.audio_packets:raise ValueError('声音核对记录不连续，代理未采用。')
            self.audio_packets+=1;pts=microseconds(match[2]);channels,rate,samples=map(int,match.groups()[2:])
            if rate<=0 or channels<=0 or samples<=0:raise ValueError('声音样本资料无效，代理未采用。')
            if self.samples and (rate,channels)!=(self.rate,self.channels):raise ValueError('音轨中途改变采样率或声道，代理未采用。')
            if self.audio_start is None:self.audio_start=pts
            self.audio_end=pts+round(samples*1000000/rate);self.samples+=samples;self.rate=rate;self.channels=channels

    def summary(self):
        if not self.pts or not self.samples:raise ValueError('代理需要完整的视频和音频，当前素材保持。')
        return {'video_frames':len(self.pts),'video_start_us':self.pts[0],'video_last_us':self.pts[-1],
                'video_end_us':self.pts[-1]+self.last_duration,'frame_times_sha256':hashlib.sha256(self.pts.tobytes()).hexdigest(),
                'width':self.width,'height':self.height,'audio_samples':self.samples,'sample_rate':self.rate,
                'channels':self.channels,'audio_start_us':self.audio_start,'audio_end_us':self.audio_end}


def compare_timing(source,proxy):
    a=source.summary();b=proxy.summary()
    if a['video_frames']!=b['video_frames']:raise ValueError('代理帧数与原片不同，未采用；请继续使用原片。')
    drift=max(max(abs(x-y) for x,y in zip(source.pts,proxy.pts)),abs(a['video_end_us']-b['video_end_us']))
    if drift>1000:raise ValueError(f'代理视频时间相差 {drift/1000:.3f}ms，未采用；原片保持。')
    if (a['width'],a['height'])!=(b['width'],b['height']) or b['width']>1280 or b['height']>720:raise ValueError('代理尺寸核对失败，原片保持。')
    if any(a[key]!=b[key] for key in ('audio_samples','sample_rate','channels')):raise ValueError('代理声音样本与原片不同，未采用。')
    audio_drift=max(abs(a[key]-b[key]) for key in ('audio_start_us','audio_end_us'))
    if audio_drift>2000:raise ValueError(f'代理声音时间相差 {audio_drift/1000:.3f}ms，未采用。')
    return {'source':a,'proxy':b,'max_video_drift_us':drift,'max_audio_edge_drift_us':audio_drift}


def run(command,cancel=None,progress=lambda value:None,audit=None,phase='processing'):
    """Drain both pipes while polling cancellation; never wait on a read."""
    cancelled(cancel);started=time.monotonic();events=queue.Queue();tail=deque(maxlen=24);stdout=[]
    process=subprocess.Popen([str(v) for v in command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    def read(name,stream):
        try:
            for line in iter(stream.readline,b''):events.put((name,line.decode('utf-8',errors='replace').rstrip()))
        finally:events.put((name,None))
    readers=[threading.Thread(target=read,args=(name,stream),daemon=True) for name,stream in [('out',process.stdout),('err',process.stderr)]]
    for reader in readers:reader.start()
    closed=set()
    try:
        while len(closed)<2:
            cancelled(cancel)
            try:name,line=events.get(timeout=.1)
            except queue.Empty:continue
            if line is None:closed.add(name);continue
            if name=='err':
                tail.append(line)
                if audit is not None:audit.feed(line)
            elif line.startswith('out_time_us='):
                try:value=max(0,int(line.split('=',1)[1]))
                except ValueError:continue
                progress({'phase':phase,'time_ms':round(value/1000),'elapsed':time.monotonic()-started})
            elif line.startswith('SHA256='):stdout.append(line)
        code=process.wait();cancelled(cancel)
        if code:raise ValueError('轻量预览处理失败，原片保持。\n'+'\n'.join(tail)[-2200:])
        return '\n'.join(stdout)
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=10)
        for reader in readers:reader.join(2)
        for stream in (process.stdout,process.stderr):stream.close()


def command(source,target):
    scale="scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,showinfo=checksum=0"
    return [ffmpeg(),'-hide_banner','-nostdin','-y','-copyts','-start_at_zero','-threads','2','-i',source,
        '-map','0:v:0','-map','0:a:0','-vf',scale,'-filter_threads','2',
        '-c:v','h264_mf','-hw_encoding','0','-b:v','3M','-pix_fmt','nv12','-bf','0','-g','48',
        '-enc_time_base:v','demux','-fps_mode:v','passthrough','-c:a','pcm_s16le',
        '-avoid_negative_ts','disabled','-map_metadata','-1','-map_chapters','-1','-progress','pipe:1','-nostats',target]


def scan(path,cancel,progress):
    audit=TimingAudit()
    run([ffmpeg(),'-hide_banner','-nostdin','-copyts','-start_at_zero','-threads','2','-i',path,
         '-map','0:v:0','-vf','showinfo=checksum=0','-an',
         '-fps_mode:v','passthrough','-progress','pipe:1','-nostats','-f','null','-'],cancel,progress,audit,'verify')
    if not audit.pts:raise ValueError('没有完整的视频核对记录，代理未采用。')
    return audit


def audio_digest(path,cancel=None,audit=None):
    # FFmpeg's per-filter stderr messages can interleave mid-line. Audit
    # audio separately from video so every numbered record is complete.
    text=run([ffmpeg(),'-hide_banner','-nostdin','-copyts','-start_at_zero','-threads','2','-i',path,
              '-map','0:a:0','-af','ashowinfo','-c:a','pcm_s16le','-f','hash','-hash','SHA256','-'],cancel,audit=audit)
    if not re.fullmatch(r'SHA256=[0-9a-f]{64}',text):raise ValueError('声音指纹核对未完成，代理未采用。')
    return text.split('=',1)[1]


@contextmanager
def cache_lock(folder):
    import msvcrt
    with (folder/'lock').open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as error:raise ValueError('另一个声稿窗口正在生成同一代理，请稍后复用。') from error
        try:yield
        finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def ready_record(value,source_hash,engine_hash):
    if not isinstance(value,dict) or value.get('version')!=VERSION or value.get('profile')!=PROFILE or value.get('source_sha256')!=source_hash or value.get('ffmpeg_sha256')!=engine_hash:raise ValueError('代理缓存版本或来源不同')
    if not isinstance(value.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',value['sha256']):raise ValueError('代理指纹无效')
    if value.get('file')!='preview-'+value['sha256']+'.mkv':raise ValueError('代理缓存路径无效')
    audit=value.get('verification')
    if not isinstance(audit,dict) or type(audit.get('max_video_drift_us')) is not int or not 0<=audit['max_video_drift_us']<=1000 or type(audit.get('max_audio_edge_drift_us')) is not int or not 0<=audit['max_audio_edge_drift_us']<=2000:raise ValueError('代理同步记录无效')
    if not isinstance(value.get('audio_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',value['audio_sha256']):raise ValueError('代理声音指纹无效')
    required={'video_frames','video_start_us','video_last_us','video_end_us','frame_times_sha256','width','height','audio_samples','sample_rate','channels','audio_start_us','audio_end_us'}
    summaries=[]
    for name in ('source','proxy'):
        record=audit.get(name)
        if not isinstance(record,dict) or set(record)!=required or any(type(record[k]) is not int for k in required-{'frame_times_sha256'}):raise ValueError('代理同步明细无效')
        if not isinstance(record['frame_times_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',record['frame_times_sha256']):raise ValueError('代理帧时间指纹无效')
        if any(record[k]<=0 for k in ('video_frames','width','height','audio_samples','sample_rate','channels')) or not record['video_start_us']<=record['video_last_us']<=record['video_end_us'] or record['audio_start_us']>=record['audio_end_us']:raise ValueError('代理同步范围无效')
        if record['width']>1280 or record['height']>720:raise ValueError('代理尺寸过大')
        summaries.append(record)
    a,b=summaries
    if any(a[k]!=b[k] for k in ('video_frames','audio_samples','sample_rate','channels','width','height')):raise ValueError('代理同步明细不一致')
    if any(abs(a[k]-b[k])>1000 for k in ('video_start_us','video_last_us','video_end_us')) or any(abs(a[k]-b[k])>2000 for k in ('audio_start_us','audio_end_us')):raise ValueError('代理同步边界不一致')


def prepare(source,cache,cancel=None,progress=lambda value:None):
    source=Path(source).resolve();stamp=file_stamp(source)
    if not stamp:raise ValueError('原片不存在，请重新定位素材；字幕保持。')
    started=time.monotonic();progress('正在核对原片与代理缓存…');source_hash=digest(source,cancel);engine_hash=digest(ffmpeg(),cancel)
    def stable():
        cancelled(cancel)
        if file_stamp(source)!=stamp or digest(source,cancel)!=source_hash:raise ValueError('原片内容在准备期间变化，代理未采用。')
    stable();signature=hashlib.sha256((VERSION+source_hash+engine_hash+json.dumps(PROFILE,sort_keys=True)).encode()).hexdigest()
    folder=Path(cache).resolve()/signature;folder.mkdir(parents=True,exist_ok=True)
    with cache_lock(folder):
        ready=folder/'ready.json'
        if ready.is_file():
            try:
                record=json.loads(ready.read_text(encoding='utf-8'));ready_record(record,source_hash,engine_hash);target=folder/record['file']
                if digest(target,cancel)==record['sha256']:
                    stable();return {**record,'path':str(target),'source_stamp':stamp,'source_path':str(source),'reused':True,'seconds':time.monotonic()-started}
            except (ValueError,OSError,KeyError,TypeError):cancelled(cancel)
        with tempfile.TemporaryDirectory(prefix='pending-',dir=folder) as temporary:
            target=Path(temporary)/'preview.mkv';source_audit=TimingAudit();progress('正在生成轻量预览，原片与时间轴保持…')
            run(command(source,target),cancel,progress,source_audit,'encode');stable()
            progress('正在逐帧核对代理时间与声音样本…');proxy_audit=scan(target,cancel,progress)
            source_audio=audio_digest(source,cancel,source_audit);proxy_audio=audio_digest(target,cancel,proxy_audit);verification=compare_timing(source_audit,proxy_audit)
            if source_audio!=proxy_audio:raise ValueError('代理解码声音与原片不同，尚未采用；请继续使用原片。')
            stable();fingerprint=digest(target,cancel);filename='preview-'+fingerprint+'.mkv'
            record={'version':VERSION,'profile':dict(PROFILE),'source_sha256':source_hash,'ffmpeg_sha256':engine_hash,
                    'file':filename,'sha256':fingerprint,'audio_sha256':source_audio,'verification':verification}
            ready_record(record,source_hash,engine_hash);cancelled(cancel);destination=folder/filename
            if not destination.is_file() or digest(destination,cancel)!=fingerprint:os.replace(target,destination)
            stable()
            from studio_backend.settings import atomic_json
            atomic_json(ready,record)
            return {**record,'path':str(destination),'source_stamp':stamp,'source_path':str(source),'reused':False,'seconds':time.monotonic()-started}


def prepare_mix(base,audition,cache,cancel=None,progress=lambda value:None):
    """Reuse the verified small video with the existing human audition audio."""
    audition=Path(audition).resolve();stamp=file_stamp(audition);base_path=Path(base['path']);base_stamp=file_stamp(base_path)
    if not stamp or digest(base_path,cancel)!=base['sha256']:raise ValueError('当前人声或轻量视频已变化，请重新准备；试听保持。')
    human_hash=digest(audition,cancel);engine_hash=digest(ffmpeg(),cancel)
    key=hashlib.sha256((VERSION+':vocal:'+base['sha256']+human_hash).encode()).hexdigest()
    folder=Path(cache).resolve()/key;folder.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    def stable():
        cancelled(cancel)
        if file_stamp(audition)!=stamp or file_stamp(base_path)!=base_stamp or digest(audition,cancel)!=human_hash or digest(base_path,cancel)!=base['sha256']:raise ValueError('准备期间人声或轻量视频变化，试听保持。')
    with cache_lock(folder):
        ready=folder/'ready.json'
        if ready.is_file():
            try:
                record=json.loads(ready.read_text(encoding='utf-8'));ready_record(record,key,engine_hash);target=folder/record['file']
                if digest(target,cancel)==record['sha256']:
                    stable();return {**record,'path':str(target),'source_path':str(audition),'source_stamp':stamp,'reused':True,'seconds':time.monotonic()-started}
            except (ValueError,OSError,KeyError,TypeError):cancelled(cancel)
        with tempfile.TemporaryDirectory(prefix='pending-',dir=folder) as temporary:
            target=Path(temporary)/'preview.mkv';progress('正在为人声试听准备轻量视频，保持当前试听与编辑…')
            run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-copyts','-start_at_zero',
                 '-i',base_path,'-i',audition,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','pcm_s16le',
                 '-avoid_negative_ts','disabled','-map_metadata','-1','-map_chapters','-1',target],cancel)
            source_audit=scan(base_path,cancel,progress);proxy_audit=scan(target,cancel,progress)
            source_audio=audio_digest(audition,cancel,source_audit);proxy_audio=audio_digest(target,cancel,proxy_audit)
            verification=compare_timing(source_audit,proxy_audit)
            if source_audio!=proxy_audio:raise ValueError('轻量人声试听与原人声不一致，尚未切换。')
            stable();fingerprint=digest(target,cancel);filename='preview-'+fingerprint+'.mkv'
            record={'version':VERSION,'profile':dict(PROFILE),'source_sha256':key,'ffmpeg_sha256':engine_hash,
                    'file':filename,'sha256':fingerprint,'audio_sha256':source_audio,'verification':verification,
                    'kind':'vocal_mix','proxy_sha256':base['sha256'],'audition_sha256':human_hash}
            ready_record(record,key,engine_hash);cancelled(cancel);destination=folder/filename
            if not destination.is_file() or digest(destination,cancel)!=fingerprint:os.replace(target,destination)
            stable()
            from studio_backend.settings import atomic_json
            atomic_json(ready,record)
            return {**record,'path':str(destination),'source_path':str(audition),'source_stamp':stamp,'reused':False,'seconds':time.monotonic()-started}
