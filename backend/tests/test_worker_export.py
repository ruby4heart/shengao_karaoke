import asyncio
import json
import os
from pathlib import Path
import subprocess
import pytest
from studio_backend.model import LyricLine,Unit
from studio_backend.export import export_ass,read_embedded_project,export_file
from studio_backend.settings import Settings
from studio_backend.worker import execute


def sample():
    return LyricLine('sample','今日も歌う',500,3000,[Unit('今日',500,1500,'きょう','kyou'),
           Unit('も',1500,1900,'も','mo'),Unit('歌う',1900,3000,'うたう','utau')],
           'きょうもうたう','kyou mo utau','今天也要歌唱')


def test_resolved_ass_has_ruby_and_no_unresolved_pipes(tmp_path):
    text=export_ass([sample()])
    active=[line for line in text.splitlines() if line.startswith('Dialogue:')]
    assert any(',Ruby,' in line and 'きょう' in line for line in active)
    assert not any('|!' in line for line in active)
    assert any('\\kf100' in line for line in active)
    data=read_embedded_project(text)
    assert LyricLine.from_dict(data['lines'][0]).units[0].kana=='きょう'
    path=tmp_path/'日语.ass'
    export_file([sample()],{'format':'ass','output':str(path)})
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')


@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI')
def test_secrets_are_encrypted_and_provider_scoped(tmp_path):
    settings=Settings(tmp_path)
    settings.save('elevenlabs','secret-one')
    settings.save('deepseek','secret-two',model='deepseek-flash')
    assert settings.key('elevenlabs')=='secret-one'
    assert settings.key('deepseek')=='secret-two'
    assert 'secret-one' not in settings.path.read_text()
    assert 'secret-two' not in json.dumps(settings.public())
    settings.forget('deepseek')
    assert not settings.key('deepseek')
    assert settings.key('elevenlabs')=='secret-one'


def test_worker_export_without_cloud_key(tmp_path):
    result=tmp_path/'result.json'
    asyncio.run(execute({'action':'export','format':'json','output':str(tmp_path/'工程.json'),
                         'lines':[sample().to_dict()]},tmp_path/'home',result))
    assert json.loads(result.read_text(encoding='utf-8'))['ok']
    assert json.loads((tmp_path/'工程.json').read_text(encoding='utf-8'))['lines'][0]['translation']=='今天也要歌唱'


def test_worker_cancel_does_not_publish_success(tmp_path,monkeypatch):
    from studio_backend import worker
    async def slow(*args):
        await asyncio.sleep(100)
    monkeypatch.setattr(worker,'operation',slow)
    result=tmp_path/'result.json'
    Path(str(result)+'.cancel').touch()
    asyncio.run(execute({},tmp_path,result))
    data=json.loads(result.read_text(encoding='utf-8'))
    assert data['cancelled'] and not data['ok']


def test_real_ass_renderer_accepts_karaoke_and_ruby(tmp_path):
    from studio_backend.media import ffmpeg_executable
    source=tmp_path/'lyrics.ass'
    source.write_text(export_ass([sample()]),encoding='utf-8-sig')
    output=tmp_path/'frame.png'
    # Work relative to the subtitle file to avoid Windows colon escaping in filters.
    result=subprocess.run([ffmpeg_executable(),'-hide_banner','-loglevel','error','-f','lavfi','-i',
        'color=c=0x163c30:s=1920x1080:d=3','-vf','ass=lyrics.ass','-ss','1.5','-frames:v','1',str(output)],
        cwd=tmp_path,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    from PIL import Image
    image=Image.open(output).convert('RGB')
    # Actual rendered subtitle pixels must appear in the expected lyric/ruby region.
    assert image.crop((500,760,1420,1020)).getextrema()!=image.crop((0,0,400,200)).getextrema()
