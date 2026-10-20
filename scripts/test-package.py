"""Run the staged package with no development PATH, Python, user keys or UI."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import argparse
import shutil

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--package',type=Path,default=ROOT/'dist/ShengaoKaraoke-0.7.0-final-win64')
PACKAGE=parser.parse_args().package.resolve()
RUN=Path(tempfile.mkdtemp(prefix='package-test-',dir=ROOT/'tmp'))
ENV={key:value for key,value in os.environ.items() if key not in
     {'PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','ELEVENLABS_API_KEY','MAI_SPEECH_KEY','DEEPSEEK_API_KEY'}}
ENV['PATH']=str(Path(os.environ['WINDIR'])/'System32')
ENV['TEMP']=str(RUN);ENV['TMP']=str(RUN)
flags=subprocess.CREATE_NO_WINDOW


def run(command,**options):
    result=subprocess.run([str(part) for part in command],env=ENV,capture_output=True,timeout=60,
                          creationflags=flags,**options)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    return result


def worker(request):
    result=RUN/'result.json'
    run([PACKAGE/'studio-worker.exe','--request','-','--result',result,'--home',RUN/'home'],
        input=json.dumps(request,ensure_ascii=False).encode('utf-8'))
    value=json.loads(result.read_text(encoding='utf-8'))
    assert value['ok'],value
    return value


manifest=json.loads((PACKAGE/'package-manifest.json').read_text(encoding='utf-8'))
assert any('rapidfuzz' in str(path).lower() for path in (PACKAGE/'licenses/python').rglob('*'))
matched=worker({'action':'match','lines':[{'id':'target','text':'今日も、歌う','start':0,'end':5000,'units':[]}],
                'transcript':[{'id':'asr','text':'今日も歌う','start':1000,'end':3000,'units':[{'text':'今日も歌う','start':1000,'end':3000,'source':'word'}]}]})
assert matched['match_summary']['matched']==1 and matched['suggestions'][0]['text']=='今日も、歌う'
assert all(unit['source']=='estimated' for unit in matched['suggestions'][0]['units'])
assert any('janome' in str(path).lower() for path in (PACKAGE/'licenses/python').rglob('*'))
janome_license=next(path for path in (PACKAGE/'licenses/python').iterdir() if path.name.lower()=='janome')
assert (janome_license/'LICENSE.txt').is_file() and (janome_license/'NOTICE.txt').is_file()
original='今日 も、歌う！'
segmented=worker({'action':'segment','mode':'mora','lines':[{'id':'original','text':original,'start':1000,'end':6000,'units':[]}]})
line=segmented['suggestions'][0]
assert line['text']==original and ''.join(u['text'] for u in line['units'])==original
assert [p['kana'] for p in line['units'][0]['highlights']]==['きょ','う']
reading_line={'id':'reading','text':'明日も','start':1000,'end':3000,'reviewed':True,
              'units':[{'text':'明日','start':1000,'end':2000,'kana':'あした','source':'matched','reading_source':'dictionary'},
                       {'text':'も','start':2050,'end':3000,'kana':'も','source':'matched'}]}
refined=worker({'action':'refine','use_llm':False,'lines':[reading_line],
                'transcript':[{'id':'asr','text':'あす','start':1000,'end':2000,'units':[]}]})
revised=refined['suggestions'][0]
assert refined['local'] and refined['transcript_used'] and revised['text']=='明日も'
assert revised['units'][0]['kana']=='あす' and revised['units'][0]['end']==2000 and revised['units'][1]['start']==2050
assert revised['reading_review']['requires_review'] and revised['units'][0]['source']=='manual'
phonetic=worker({'action':'match','lines':[{'id':'original','text':original,'start':0,'end':5000,'units':[]}],
    'transcript':[{'id':'asr','text':'きょう も うたう','start':1000,'end':3000,'units':[]}]})
assert phonetic['suggestions'][0]['text']==original and phonetic['suggestions'][0]['match']['method']=='reading'
for index,payload in enumerate((b'',b'{"key":"package-secret-do-not-log",',b'\xff')):
    failure=RUN/f'bootstrap-{index}.json'
    completed=subprocess.run([str(PACKAGE/'studio-worker.exe'),'--request','-','--result',str(failure),'--home',str(RUN/'home')],input=payload,env=ENV,capture_output=True,timeout=30,creationflags=flags)
    assert completed.returncode==1
    problem=json.loads(failure.read_text(encoding='utf-8'))
    assert not problem['ok'] and problem['code']=='invalid_request'
    assert 'package-secret' not in failure.read_text(encoding='utf-8')
    assert b'package-secret' not in completed.stdout+completed.stderr
for name,digest in manifest['files_sha256'].items():
    assert hashlib.sha256((PACKAGE/name).read_bytes()).hexdigest()==digest,name
worker({'action':'configure','provider':'elevenlabs','key':'package-test-only-not-a-real-key'})
assert worker({'action':'settings'})['settings']['elevenlabs']['has_key']
assert 'package-test-only-not-a-real-key' not in (RUN/'home/settings.json').read_text()
project=json.loads((PACKAGE/'demo/tutorial.json').read_text(encoding='utf-8'))
for kind in ('ass','json','srt','txt'):
    worker({'action':'export','format':kind,'output':str(RUN/('字幕.'+kind)),
            'lines':project['lines'],'api_history':[{'test':'roundtrip'}]})
assert json.loads((RUN/'字幕.json').read_text(encoding='utf-8'))['api_history']==[{'test':'roundtrip'}]
shutil.copyfile(PACKAGE/'demo/demo.wav',RUN/'日本語の音声.wav')
run([PACKAGE/'ffmpeg.exe','-hide_banner','-loglevel','error','-nostdin','-i',RUN/'日本語の音声.wav',
     '-ac','1','-ar','16000','-c:a','flac',RUN/'提取音轨.flac'])
assert (RUN/'提取音轨.flac').stat().st_size>100
run([PACKAGE/'ffmpeg.exe','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=black:s=1920x1080:d=3',
     '-vf','ass=字幕.ass','-ss','1.5','-frames:v','1',RUN/'frame.png'],cwd=RUN)
from PIL import Image
frame=Image.open(RUN/'frame.png').convert('RGB')
assert frame.crop((500,760,1420,1020)).getbbox()
installed=RUN/'安装测试'
run([Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile',
     '-ExecutionPolicy','Bypass','-File',PACKAGE/'install.ps1','-Destination',installed,'-NoShortcuts'])
assert (installed/'shengao-karaoke.exe').read_bytes()==(PACKAGE/'shengao-karaoke.exe').read_bytes()
print('PASS: package hashes, isolated worker, encrypted configuration, four exports, bundled FFmpeg render/extract, isolated install')
print('Evidence:',RUN)
