"""Verify native editor services on synthetic fixtures, without desktop control."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
sys.stdout.reconfigure(encoding='utf-8')

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--package',type=Path,default=ROOT/'dist/ShengaoKaraoke-0.7.0-final-win64')
parser.add_argument('--native',type=Path,help='Optional incremental-build executable; final release uses the packaged binary')
args=parser.parse_args();PACKAGE=args.package.resolve();NATIVE=(args.native or PACKAGE/'shengao-karaoke.exe').resolve()
RUN=Path(tempfile.mkdtemp(prefix='native-integration-日语-',dir=ROOT/'tmp'))
(RUN/'.studio-test-fixture').touch()
env={key:value for key,value in os.environ.items() if key not in
     {'PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','ELEVENLABS_API_KEY','MAI_SPEECH_KEY','DEEPSEEK_API_KEY'}}
env['PATH']=str(Path(os.environ['WINDIR'])/'System32')
env['TEMP']=str(RUN);env['TMP']=str(RUN)

def run(command,**options):
    result=subprocess.run([str(p) for p in command],env=env,capture_output=True,timeout=90,
                          creationflags=subprocess.CREATE_NO_WINDOW,**options)
    if result.returncode:
        raise RuntimeError(f'{command[0]} exited {result.returncode}: {result.stderr.decode(errors="replace")}')
    return result

project=json.loads((PACKAGE/'demo/tutorial.json').read_text(encoding='utf-8'))
first=project['lines'][0]['units'][0]
first['highlights']=[{'kana':'きょ','start':1000,'end':1800,'source':'manual'},
                     {'kana':'う','start':1800,'end':3000,'source':'manual'}]
(RUN/'project.json').write_text(json.dumps(project,ensure_ascii=False),encoding='utf-8')
(RUN/'import.lrc').write_text('[offset:100]\n[00:01.00]今日\n[00:04.00]歌う\n',encoding='utf-8-sig')
(RUN/'invalid.lrc').write_text('[00:90]invalid\n',encoding='utf-8-sig')
(RUN/'config.json').write_text(json.dumps({
    'App':{'Language':'en_US','First Start':False,'Maximized':False,
           'Auto':{'Load Linked Files':0,'Save':True,'Save Every Seconds':1}},
    'Video':{'Open Audio':True,'Untagged Matrix Warning':False,'HDR Video Warning':False,
             'PlayRes Mismatch':0,'No YCbCr Matrix in Script':0,'No LayoutRes in Script':0},
    'Audio':{'Auto':{'Commit':False}}}),encoding='utf-8')
run([PACKAGE/'ffmpeg.exe','-hide_banner','-loglevel','error','-f','lavfi',
     '-i','color=c=0x163c30:s=1280x720:r=25:d=8','-i',PACKAGE/'demo/demo.wav',
     '-c:v','mpeg4','-c:a','aac','-shortest',RUN/'test-video.mp4'])
result_path=RUN/'worker-result.json'
run([PACKAGE/'studio-worker.exe','--request','-','--result',result_path,'--home',RUN/'worker-home'],
    input=json.dumps({'action':'export','format':'ass','resolved':True,'lines':project['lines'],
                      'output':str(RUN/'resolved.ass')},ensure_ascii=False).encode())
assert json.loads(result_path.read_text(encoding='utf-8'))['ok']
print('Fixture:',RUN,flush=True)
run([NATIVE,'--studio-self-test',RUN])
report=json.loads((RUN/'native-report.json').read_text(encoding='utf-8'))
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
assert report['ok'],report
from PIL import Image
frame=Image.open(RUN/'preview-2000.png')
assert frame.size==(1280,720)
print('PASS: actual native import, timing, review, save/reopen, playback and subtitle rendering')
