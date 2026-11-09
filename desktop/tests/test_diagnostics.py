"""The diagnostics report keeps failure clues and drops keys, lyrics and paths."""
import json
from pathlib import Path
from shengao import diagnostics
from studio_backend.settings import Settings, atomic_json


def _task(home,name,request,result,progress=None):
    folder=home/'desktop-tasks'/name;folder.mkdir(parents=True)
    atomic_json(folder/'request.json',request);atomic_json(folder/'result.json',result)
    if progress:atomic_json(folder/'result.json.progress.json',progress)
    return folder


def test_report_keeps_stage_and_request_id_but_no_private_data(tmp_path,monkeypatch,project):
    home=tmp_path/'Users'/'kanade'/'AppData'/'ShengaoKaraoke';home.mkdir(parents=True)
    monkeypatch.setenv('DEEPSEEK_API_KEY','dk-live-0123456789abcdef')
    monkeypatch.setenv('USERNAME','kanade');monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path/'Users'/'kanade'))
    media=tmp_path/'Users'/'kanade'/'Music'/'秘密の新曲デモ.wav';media.parent.mkdir(parents=True);media.write_bytes(b'0'*2048)
    atomic_json(home/'settings.json',{'deepseek':{'model':'deepseek-flash'},'mai':{'endpoint':'https://eastus.api.cognitive.microsoft.com/x','secret':'AAAA'}})
    lyric='誰にも言えない秘密の歌詞'
    _task(home,'a'*32,
          {'action':'transcribe','provider':'elevenlabs','media':str(media),'language':'ja',
           'lines':[{'id':'1','text':lyric,'start':0,'end':10,'units':[]}]},
          {'ok':False,'message':f'等待服务处理阶段失败：{lyric} 出错；key dk-live-0123456789abcdef；Authorization: Bearer abc.def.ghi；{media}；联系 someone@example.com',
           'exception':'ApiError','original_api_result':{'text':lyric},'transcript':[{'text':lyric}],
           'diagnostics':{'stage':'waiting','billing':'possibly_billed','phase':'waiting','request_id':'req-42',
                          'uploaded_bytes':2048,'upload_size':2048,'headers':{'xi-api-key':'never'},'transcribe':{'stage':'parsing','request_id':'req-43'}}},
          {'phase':'error','message':'等待服务处理阶段失败'})
    atomic_json(home/'desktop-renders'/'r.json',{'kind':'encode','state':'failed','title':'秘密の新曲','output':str(media),'message':f'写入 {home} 失败','encoder':'x264'})
    path=diagnostics.write(tmp_path/'报告.txt',home,project,Settings(home))
    text=path.read_text(encoding='utf-8-sig')
    for private in [lyric,'dk-live-0123456789abcdef','abc.def.ghi','秘密の新曲','someone@example.com','kanade',
                    str(home),'never',project.lines[0].text]:
        assert private not in text,private
    assert 'req-42' in text and 'req-43' in text and 'stage=waiting' in text and 'billing=possibly_billed' in text
    assert '已填写密钥' in text and 'eastus.api.cognitive.microsoft.com' in text and '/x' not in text.split('[结构化数据]')[0]
    data=json.loads(text.split('[结构化数据]\n',1)[1])
    task=data['tasks'][0]
    assert task['action']=='transcribe' and task['line_count']==1 and task['media']=={'extension':'.wav','size_mb':0.0}
    assert {d['part'] for d in task['diagnostics']}=={'请求','transcribe'}
    assert 'original_api_result' not in json.dumps(data) and 'transcript' not in task
    assert data['renders'][0]=={'kind':'encode','state':'failed','message':'写入 〔个人目录〕 失败','encoder':'x264'}
    assert data['project']['lines']==len(project.lines) and data['environment']['python']


def test_redactor_patterns_and_short_latin_fragments_survive():
    r=diagnostics.Redactor(texts=['to','歌う','love me tender'])
    out=r('Authorization: Bearer sk-abcdefghijklmnop api_key=xyz123 C:\\Users\\Mio\\Desktop\\a.ass /home/mio/x stop 歌う love me tender')
    assert 'sk-abcdefghijklmnop' not in out and 'xyz123' not in out and 'Mio' not in out and '/home/mio' not in out
    assert 'stop' in out and '歌う' not in out and 'love me tender' not in out


def test_empty_home_still_reports(tmp_path):
    text,data=diagnostics.report(tmp_path,None,Settings(tmp_path))
    assert data['tasks']==[] and data['renders']==[] and '未配置' in text
