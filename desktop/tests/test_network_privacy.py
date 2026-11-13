"""11.4: say what goes online before sending, and keep keys and private material out of shared files."""
import importlib.util
import itertools
import json
import zipfile
from pathlib import Path
import pytest
from PySide6.QtWidgets import QDialog
from shengao import network_notice as notice, network_dialog, privacy_check as check
from shengao.preferences import Preferences

ROOT = Path(__file__).resolve().parents[2]
LINES = [{'id': 'a', 'text': '夜空に', 'start': 1000, 'end': 3000}, {'id': 'b', 'text': '星が光る', 'start': 3200, 'end': 6200}]
MAI = {'mai': {'endpoint': 'https://studio-east.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe', 'has_key': True},
       'deepseek': {'model': 'deepseek-chat', 'has_key': True}}
PROVIDER = {'elevenlabs-stt:audio': 'elevenlabs', 'mai:audio': 'mai', 'elevenlabs-align:audio+text': 'elevenlabs', 'deepseek:text': 'deepseek'}


def request(action, **extra):
    return {'action': action, 'lines': LINES, 'media': 'D:/作品/新曲.mp4', 'language': 'ja', **extra}


# ---- what is said before sending ----

@pytest.mark.parametrize('value', [
    request('configure'), request('match'), request('segment'), request('export'), request('refine'),
    request('refine', use_llm=False), request('confirm_recognition'), request('chorus_reuse'), {'action': 'acoustic'},
    request('draft', draft_options={'source': 'offline', 'readings': 'dictionary', 'align': False, 'acoustic': True}),
    request('draft', draft_options={'source': 'reuse', 'readings': 'dictionary'}), None, 'transcribe', {}])
def test_local_work_is_never_interrupted(value, tmp_path):
    assert notice.describe(value) == [] and notice.keys(value if isinstance(value, dict) else {}) == []
    if isinstance(value, dict): assert notice.text(value, tmp_path) == '' and notice.summary(value) == ''


def test_worker_actions_that_reach_a_service_are_exactly_the_described_ones():
    # backend/studio_backend/worker.py: transcribe/transcribe_match upload audio, align uploads audio and
    # text, annotate and refine with use_llm send text to DeepSeek; match, segment and export stay local.
    online = {'transcribe', 'transcribe_match', 'align', 'annotate'}
    for action in ['transcribe', 'align', 'annotate', 'export', 'match', 'transcribe_match', 'segment', 'refine']:
        assert bool(notice.describe(request(action))) == (action in online), action
    assert notice.describe(request('refine', use_llm=True))


def test_transcription_names_service_host_audio_and_length():
    [item] = notice.describe(request('transcribe', provider='elevenlabs'), {}, 215000)
    assert item['id'] == 'elevenlabs-stt:audio' and item['host'] == 'api.elevenlabs.io' and item['kind'] == '音频'
    joined = '\n'.join(item['sends'])
    assert '「新曲.mp4」的整条音轨（约 3 分 35 秒）' in joined and 'FLAC' in joined and '视频画面不上传' in joined and '日语' in joined
    assert any('歌词' in x and '不发送' in x for x in item['keeps'])
    [same] = notice.describe(request('transcribe_match'))
    assert same['id'] == 'elevenlabs-stt:audio' and '约' not in same['sends'][0]


def test_microsoft_host_comes_from_the_saved_endpoint():
    [item] = notice.describe(request('transcribe_match', provider='mai'), MAI)
    assert item['id'] == 'mai:audio' and item['host'] == 'studio-east.cognitiveservices.azure.com'
    [empty] = notice.describe(request('transcribe', provider='mai'), {'mai': {'endpoint': ''}})
    assert '服务设置' in empty['host']


def test_selected_alignment_sends_only_the_selected_range_and_text():
    [item] = notice.describe(request('align', range_mode='selection'))
    assert item['id'] == 'elevenlabs-align:audio+text' and item['kind'] == '音频和文字'
    assert item['sends'][0].startswith('所选歌词时间范围内的一段音轨（约 5 秒）')
    assert '所选 2 句歌词的原文（共 7 字）' in item['sends'][1] and '不含假名' in item['sends'][1]
    [whole] = notice.describe(request('align'), {}, 61000)
    assert '整条音轨（约 1 分 01 秒）' in whole['sends'][0]


def test_deepseek_says_text_only_with_context_and_skipped_lines():
    [item] = notice.describe(request('refine', use_llm=True, transcript=[{'text': 'よぞらに'}]), MAI)
    assert item['id'] == 'deepseek:text' and item['host'] == 'api.deepseek.com' and item['kind'] == '文字'
    assert 'deepseek-chat' in item['service']
    joined = '\n'.join(item['sends'] + item['keeps'])
    assert '2 句歌词原文（共 7 字）' in joined and '上一句和下一句' in joined and '转录文字（最多 4 段）' in joined
    assert '不发送任何音频' in joined and '人工确认的句子会跳过' in joined
    [plain] = notice.describe(request('refine', use_llm=True))
    assert not any('转录' in x for x in plain['sends']) and 'deepseek-flash' in plain['service']
    [annotate] = notice.describe(request('annotate'))
    assert len(annotate['sends']) == 1 and not any('跳过' in x for x in annotate['keeps'])


def test_draft_lists_each_service_in_the_order_it_runs():
    value = request('draft', draft_options={'source': 'cloud', 'provider': 'mai', 'readings': 'deepseek', 'align': True})
    found = notice.describe(value, MAI, 90000)
    assert [x['id'] for x in found] == ['mai:audio', 'deepseek:text', 'elevenlabs-align:audio+text']
    assert '最多 2 句' in found[1]['sends'][0] and any('转录' in x for x in found[1]['sends'])
    assert '全部 2 句' in found[2]['sends'][1] and '整条音轨' in found[2]['sends'][0]
    offline = notice.describe(request('draft', draft_options={'source': 'offline', 'readings': 'deepseek'}))
    assert [x['id'] for x in offline] == ['deepseek:text'] and not any('转录' in x for x in offline[0]['sends'])


@pytest.mark.parametrize('source,readings,provider,align', list(itertools.product(
    ['offline', 'reuse', 'cloud'], ['dictionary', 'deepseek'], ['elevenlabs', 'mai'], [False, True])))
def test_draft_services_match_the_paid_providers_the_workflow_records(source, readings, provider, align):
    # Same rule as studio_backend.draft.run: providers whose settings enter the workflow signature.
    expected = ({provider} if source == 'cloud' else set()) | ({'deepseek'} if readings == 'deepseek' else set()) | ({'elevenlabs'} if align else set())
    value = request('draft', draft_options={'source': source, 'readings': readings, 'provider': provider, 'align': align})
    assert {PROVIDER[x['id']] for x in notice.describe(value)} == expected


def test_explanation_lists_where_records_and_caches_are_kept(tmp_path):
    words = notice.text(request('align', range_mode='selection'), tmp_path)
    assert words.startswith('这次操作会联网') and 'api.elevenlabs.io（音频和文字）' in words
    assert str(tmp_path / 'desktop-tasks' / '<任务编号>') in words and str(tmp_path / 'cache') in words and str(tmp_path / 'paid-requests') in words
    assert '上传结束后删除' in words and '不再上传' in words and notice.KEY_NOTE in words
    assert 'readings' not in words and 'draft-workflows' not in words
    text_only = notice.text(request('refine', use_llm=True), tmp_path)
    assert str(tmp_path / 'readings') in text_only and str(tmp_path / 'cache') not in text_only and 'FLAC' not in text_only
    draft = notice.text(request('draft', draft_options={'source': 'cloud', 'readings': 'deepseek'}), tmp_path)
    assert str(tmp_path / 'draft-workflows') in draft and str(tmp_path / 'readings') in draft


def test_summary_and_remembered_choices():
    value = request('draft', draft_options={'source': 'cloud', 'readings': 'deepseek', 'align': True})
    assert notice.summary(value) == '联网发送到 ElevenLabs 转录（音频）、DeepSeek（歌词文字）、ElevenLabs 对齐（音频和歌词文字）；'
    assert notice.keys(value) == ['deepseek:text', 'elevenlabs-align:audio+text', 'elevenlabs-stt:audio']
    assert notice.pending(value, ['deepseek:text', 7, None]) == ['elevenlabs-align:audio+text', 'elevenlabs-stt:audio']
    assert notice.pending(value, 'deepseek:text') == notice.keys(value) and notice.remembered({'a': 1}) == set()


# ---- asking before sending ----

class Dialog:
    shown = []; answer = QDialog.DialogCode.Accepted; tick = False

    def __init__(self, parent, text):
        Dialog.shown.append(text)
        self.remember = type('Box', (), {'isChecked': lambda box: Dialog.tick})()

    def exec(self): return Dialog.answer


class Window:
    def __init__(self, home, duration=0):
        self.home = home; self.preferences = Preferences(home); self.project = type('P', (), {'duration': duration})()


@pytest.fixture
def dialog():
    Dialog.shown = []; Dialog.answer = QDialog.DialogCode.Accepted; Dialog.tick = False
    return Dialog


def test_local_request_needs_no_question(tmp_path, dialog):
    assert network_dialog.confirm(Window(tmp_path), request('segment'), dialog) and dialog.shown == []


def test_declining_sends_nothing_and_remembers_nothing(tmp_path, dialog):
    dialog.answer = QDialog.DialogCode.Rejected; window = Window(tmp_path, 125000)
    assert network_dialog.confirm(window, request('transcribe'), dialog) is False
    assert '「新曲.mp4」的整条音轨（约 2 分 05 秒）' in dialog.shown[0] and str(tmp_path / 'cache') in dialog.shown[0]
    assert network_dialog.PREFERENCE not in window.preferences.data


def test_do_not_ask_again_is_kept_per_kind_of_sending(tmp_path, dialog):
    window = Window(tmp_path); dialog.tick = True
    assert network_dialog.confirm(window, request('transcribe'), dialog) and len(dialog.shown) == 1
    assert Preferences(tmp_path).data[network_dialog.PREFERENCE] == ['elevenlabs-stt:audio']
    assert network_dialog.confirm(window, request('transcribe_match'), dialog) and len(dialog.shown) == 1
    # A request that adds another service asks again, then keeps both.
    draft = request('draft', draft_options={'source': 'cloud', 'readings': 'deepseek'})
    assert network_dialog.confirm(window, draft, dialog) and len(dialog.shown) == 2
    assert window.preferences.data[network_dialog.PREFERENCE] == ['deepseek:text', 'elevenlabs-stt:audio']
    assert network_dialog.remembered_count(window.preferences) == 2
    # Microsoft is a different service and is asked about separately.
    assert network_dialog.confirm(window, request('transcribe', provider='mai'), dialog) and len(dialog.shown) == 3


def test_accepting_without_ticking_asks_next_time(tmp_path, dialog):
    window = Window(tmp_path)
    assert network_dialog.confirm(window, request('annotate'), dialog) and network_dialog.confirm(window, request('annotate'), dialog)
    assert len(dialog.shown) == 2 and network_dialog.remembered_count(window.preferences) == 0


def test_saved_endpoint_host_is_shown(tmp_path, dialog):
    (tmp_path / 'settings.json').write_text(json.dumps({'mai': {'endpoint': MAI['mai']['endpoint']}}), encoding='utf-8')
    network_dialog.confirm(Window(tmp_path), request('transcribe', provider='mai'), dialog)
    assert 'studio-east.cognitiveservices.azure.com' in dialog.shown[0]


class Job:
    """ApiJob.start called on a stand-in: the question comes before any folder or process."""
    busy = False

    def __init__(self, home, answer):
        self.home = home; self.asked = []; self.answer = answer

    def confirm(self, value):
        self.asked.append(value); return self.answer


class Stop(Exception):
    pass


def test_job_start_asks_first_and_writes_nothing_when_declined(tmp_path):
    from shengao.api_jobs import ApiJob
    job = Job(tmp_path, False)
    assert ApiJob.start(job, request('transcribe')) is False
    assert job.asked and not (tmp_path / 'desktop-tasks').exists()


def test_job_start_sets_notice_and_skips_the_question_for_confirmed_resends(tmp_path, monkeypatch):
    from shengao import api_jobs
    monkeypatch.setattr(api_jobs, 'uuid', type('U', (), {'uuid4': staticmethod(lambda: (_ for _ in ()).throw(Stop()))}))
    job = Job(tmp_path, True)
    with pytest.raises(Stop): api_jobs.ApiJob.start(job, request('align', range_mode='selection'))
    assert job.asked and job.notice == '联网发送到 ElevenLabs 对齐（音频和歌词文字）；'
    job = Job(tmp_path, False)
    with pytest.raises(Stop): api_jobs.ApiJob.start(job, {**request('transcribe'), 'confirm_resubmit': True})
    assert job.asked == []
    job = Job(tmp_path, False); job.confirm = None
    with pytest.raises(Stop): api_jobs.ApiJob.start(job, request('segment'))
    assert job.notice == ''


class Studio:
    """Enough of the main window for start_api, settings and the workflow entries."""
    def __init__(self, project, home, started):
        self.project = project; self.home = home; self.line = 0; self.pending = None; self.source_job = None
        self.messages = []; self.preferences = Preferences(home); self.snapshots = {}
        self.continuous_timing = type('C', (), {'isChecked': lambda box: False})()
        self.api = type('A', (), {'busy': False, 'notice': '联网发送到 DeepSeek（歌词文字）；', 'requests': [],
                                  'start': lambda api, value: (api.requests.append(value), started)[1]})()

    def flush_edits(self): return True
    def message(self, text): self.messages.append(text)


def test_cancelled_question_says_nothing_was_sent(project, tmp_path):
    from shengao.app import StudioWindow
    window = Studio(project, tmp_path, False)
    StudioWindow.start_api(window, 'refine', use_llm=True)
    assert window.messages[-1] == '已取消，没有发送任何内容。' and window.api.requests[0]['use_llm'] is True
    window = Studio(project, tmp_path, True)
    StudioWindow.start_api(window, 'refine', use_llm=True)
    assert window.messages[-1].startswith('任务已开始；联网发送到 DeepSeek（歌词文字）；结果会先进入审核。')
    # Test doubles that return nothing are treated as started.
    window = Studio(project, tmp_path, None)
    StudioWindow.start_api(window, 'refine', use_llm=True)
    assert window.messages[-1].startswith('任务已开始')


def test_cancelled_draft_keeps_its_checkpoint(project, tmp_path):
    from shengao.draft_workflow import DraftWorkflow
    window = Studio(project, tmp_path, False)
    DraftWorkflow.submit_draft(window, {'action': 'draft', 'lines': LINES})
    assert window.messages == ['已取消，没有发送任何内容；初稿流程的检查点保留。']
    window = Studio(project, tmp_path, True)
    DraftWorkflow.submit_draft(window, {'action': 'draft', 'lines': LINES})
    assert window.messages == ['初稿流程已开始；联网发送到 DeepSeek（歌词文字）；每步完成会保存，结果先审核。']


def test_settings_restores_the_questions(monkeypatch, project, tmp_path):
    from shengao import app
    seen = {}

    class Settings:
        def __init__(self, parent, settings, remembered):
            seen['remembered'] = remembered
            self.ask_again = type('B', (), {'isChecked': lambda box: True})() if remembered else None

        def exec(self): return QDialog.DialogCode.Accepted
        def request(self): return {'action': 'configure', 'provider': 'deepseek', 'key': '', 'forget': False}

    monkeypatch.setattr(app, 'SettingsDialog', Settings)
    window = Studio(project, tmp_path, True)
    window.preferences.set(network_dialog.PREFERENCE, ['deepseek:text', 'mai:audio'])
    app.StudioWindow.settings(window)
    assert seen['remembered'] == 2 and window.preferences.data[network_dialog.PREFERENCE] == []
    assert window.api.requests[-1]['action'] == 'configure'
    app.StudioWindow.settings(window)
    assert seen['remembered'] == 0


# ---- privacy check ----

ELEVEN = 'sk_' + '5e' * 24
DEEP = 'sk-' + '9a0b' * 8
# Made-up home folders and key headers are assembled at run time so this file itself passes the scan.
U = 'Us' + 'ers'
PRIVATE = '-----BEGIN RSA ' + 'PRIVATE KEY-----'


def fake(text):
    return text.replace('<U>', U)


def test_key_patterns_are_found_but_never_repeated():
    data = (f'a = "{ELEVEN}"\nb={DEEP}\nAuthorization: Bearer {"x" * 30}\nxi-api-key: {"k" * 24}\n'
            f'ghp_{"A" * 36}\nAKIA{"B" * 16}\n{PRIVATE}\n').encode()
    found = check.secrets_in(data, 'f.py')
    assert [x['where'] for x in found] == ['f.py:1', 'f.py:2', 'f.py:3', 'f.py:4', 'f.py:5', 'f.py:6', 'f.py:7']
    assert not any(ELEVEN in x['what'] or DEEP in x['what'] for x in found)
    assert check.secrets_in(b'xsk_' + b'5e' * 24 + b' sk-short dk-live-0123', 'f') == []
    [saved] = check.secrets_in(b'..my-own-key-123..', 'r.json', [('DeepSeek', 'my-own-key-123')])
    assert 'DeepSeek' in saved['what'] and 'my-own-key-123' not in saved['what']


def test_personal_paths_are_found_with_placeholders_and_redaction_fixtures_allowed():
    def names(data, where='f', own=((), '')):
        data = fake(data.decode('utf-8')).encode('utf-8') if isinstance(data, bytes) else data
        return [x['what'] for x in check.paths_in(data, where, own)]
    assert names(b'C:\\<U>\\Alice\\Music\\a.wav') == ['含个人目录路径（用户名 Alice）']
    assert names(b'"c:\\\\<U>\\\\bob\\\\x"') == ['含个人目录路径（用户名 bob）']
    assert names(b'D:/<U>/kanade/x') == ['含个人目录路径（用户名 kanade）'] and names(b' /ho' + b'me/mio/x') == ['含个人目录路径（用户名 mio）']
    for fine in [b'C:\\Users\\Public\\x', b'C:\\Users\\<\xe7\x94\xa8\xe6\x88\xb7\xe5\x90\x8d>\\x', b'%APPDATA%\\ShengaoKaraoke',
                 b'tmp/final/home/draft-workflows/x', b'abc:\\users\\joe', b'/Users/']:
        assert names(fine) == [], fine
    assert names(b'C:\\<U>\\Mio\\x', 'desktop/tests/test_diagnostics.py') == []
    assert names(b'E:\\Work\\x', own=([b'E:\\Work'], '')) == ['含本机个人目录路径']
    assert names(b'x\\Users\\kanade2', own=((), 'kanade2')) == ['含本机用户名路径']
    # Split by whose folder it is: release archives fail only this computer's.
    mine = fake('C:\\<U>\\Kanade2\\venv\\x').encode()
    assert [[x['what'] for x in part] for part in check.personal_paths(mine, 'f', ((), 'kanade2'))] == [['含本机用户名路径'], []]
    other = fake('C:\\<U>\\Alice\\x').encode()
    assert [[x['what'] for x in part] for part in check.personal_paths(other, 'f', ((), 'kanade2'))] == [[], ['含个人目录路径（用户名 Alice）']]


@pytest.mark.parametrize('name,kind', [
    ('songs/my.sgproj', '声稿工程文件'), ('home/workspace.json', '工作区设置'), ('settings.json', '服务设置'), ('.env', '环境变量文件'),
    ('.env.local', '环境变量文件'), ('x/desktop-tasks/ab/request.json', '个人数据目录 desktop-tasks'),
    ('paid-requests/a.json', '个人数据目录 paid-requests'), ('readings/a.json', '个人数据目录 readings'),
    ('desktop/shengao/app.py', ''), ('docs/readings.md', ''), ('vendor/python-tls/codex-rejected-cas.pem', '')])
def test_private_file_names(name, kind):
    assert check.private_name(name) == kind


def test_repository_in_this_checkout_is_clean():
    section = check.check_repository(ROOT)
    assert section['problems'] == [], section['problems'][:5]
    assert set(check.PUBLIC_MEDIA) <= set(check.tracked(ROOT)[0])


def test_repository_check_reports_each_kind_of_leak(tmp_path):
    (tmp_path / 'demo').mkdir(); (tmp_path / 'demo' / 'demo.wav').write_bytes(b'RIFF')
    (tmp_path / 'my song.sgproj').write_text('{}', encoding='utf-8')
    (tmp_path / 'desktop-tasks' / 'a').mkdir(parents=True); (tmp_path / 'desktop-tasks' / 'a' / 'request.json').write_text('{}')
    (tmp_path / 'private.mp3').write_bytes(b'ID3')
    (tmp_path / 'code.py').write_text(f'KEY="{DEEP}"\npath=r"C:\\{U}\\Alice\\a.wav"\n', encoding='utf-8')
    (tmp_path / '.venv').mkdir(); (tmp_path / '.venv' / 'x.py').write_text(DEEP)
    section = check.check_repository(tmp_path, own=((), ''))
    assert '没有 Git 记录' in section['checked']
    found = sorted((x['where'], x['what']) for x in section['problems'])
    assert found == [('code.py:1', '疑似DeepSeek 式密钥（sk-9…）'), ('code.py:2', '含个人目录路径（用户名 Alice）'),
                     ('desktop-tasks/a/request.json', '不应进入仓库的个人数据目录 desktop-tasks'),
                     ('my song.sgproj', '不应进入仓库的声稿工程文件'), ('private.mp3', '未登记来源的音视频或字幕文件')]


def test_release_archives_are_checked_inside(tmp_path):
    good = tmp_path / 'good.zip'
    with zipfile.ZipFile(good, 'w') as bundle:
        bundle.write(ROOT / 'demo' / 'demo.wav', 'ShengaoKaraoke/assets/demo.wav'); bundle.writestr('ShengaoKaraoke/readme.txt', '说明')
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as bundle:
        bundle.writestr('app/config.txt', f'token={ELEVEN}'); bundle.writestr('app/workspace.json', '{}')
        bundle.writestr('app/song.wav', b'RIFF0000'); bundle.writestr('app/log.txt', fake('C:\\<U>\\Builder\\src\\x.py'))
        bundle.writestr('app/built.json', fake('{"python": "C:\\\\<U>\\\\kanade2\\\\venv"}'))
        bundle.writestr('app/notes.txt', 'E:\\Home\\kanade2\\cache')
        bundle.writestr('src/vendor/aegisub/tests/sample.ass', '[Script Info]')
    (tmp_path / 'broken.zip').write_bytes(b'not a zip')
    section = check.check_archives([good], ROOT)
    assert section['problems'] == [] and section['warnings'] == [] and '文件 2 个' in section['checked']
    section = check.check_archives([bad, tmp_path / 'broken.zip'], ROOT, own=([b'E:\\Home\\kanade2'], 'kanade2'))
    whats = {x['where']: x['what'] for x in section['problems']}
    assert whats['bad.zip!app/config.txt:1'].startswith('疑似ElevenLabs 式密钥') and '工作区设置' in whats['bad.zip!app/workspace.json']
    assert whats['bad.zip!app/built.json:1'] == '含本机用户名路径' and whats['bad.zip!app/notes.txt:1'] == '含本机个人目录路径'
    assert '无法读取' in whats[str(tmp_path / 'broken.zip')] and not any('log.txt' in x for x in whats)
    assert '别人的目录路径 1 处（1 个文件' in section['checked'] and '上游源码自带的测试音视频或字幕 1 个' in section['checked']
    assert [x['where'] for x in section['warnings']] == ['bad.zip!app/song.wav']
    assert check.check_archives([], ROOT)['checked'] == '没有找到发行包，跳过'


def test_third_party_build_and_example_paths_do_not_fail_a_release(tmp_path):
    """The first 0.32.0 freeze failed on 772 such paths: example output in the
    upstream threadpoolctl wheel's metadata (its author's home folder), compiled
    DLLs (their build machine's Administrator folder) and the standard library.
    None is the person's; none can be changed."""
    archive = tmp_path / 'ShengaoKaraoke-0.32.0-final-win64.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('x/vocal-engine/licenses/threadpoolctl/METADATA.txt',
                        '"filepath": "/ho' + 'me/ogrisel/miniconda3/envs/tmp/lib/libmkl_rt.so",\n')
        bundle.writestr('x/vocal-engine/_internal/libcrypto-3-x64.dll',
                        fake('\0OPENSSLDIR: "C:\\<U>\\Administrator\\ssl"\0C:\\<U>\\ADMINI~1\\AppData\\Local\\Temp\\b\0').encode())
    section = check.check_archives([archive], ROOT, own=([b'C:\\' + U.encode() + b'\\kanade2'], 'kanade2'))
    assert section['problems'] == [] and '别人的目录路径 3 处（2 个文件' in section['checked']


def test_diagnostics_report_hides_made_up_private_data():
    section = check.check_diagnostics()
    assert section['problems'] == [] and '虚构' in section['checked']


def test_diagnostics_check_notices_a_leak(monkeypatch):
    from shengao import diagnostics
    monkeypatch.setattr(diagnostics, 'report', lambda home, project, settings: ('誰にも言えない秘密の歌詞 req-privacy', {}))
    assert [x['what'] for x in check.check_diagnostics()['problems']] == ['泄露了歌词']


def test_local_records_and_recent_projects_hold_no_saved_key(tmp_path):
    home = tmp_path / 'home'; key = 'local-deepseek-key-0001'
    (home / 'desktop-tasks' / 'a').mkdir(parents=True)
    (home / 'desktop-tasks' / 'a' / 'request.json').write_text(json.dumps({'lines': [{'text': '歌詞'}], 'media': fake('C:/<U>/me/a.wav')}))
    (home / 'desktop-tasks' / 'b').mkdir(); (home / 'desktop-tasks' / 'b' / 'result.json').write_text(f'{{"message": "{key}"}}')
    (home / 'vocal-cache').mkdir(); (home / 'vocal-cache' / 'x.json').write_text(key)
    project = tmp_path / 'song.sgproj'; project.write_text(json.dumps({'note': DEEP}))
    (home / 'workspace.json').write_text(json.dumps({'recent': [{'path': str(project), 'title': 't'}, {'path': str(tmp_path / 'gone.sgproj')}, 'x']}))
    section = check.check_home(home, [('DeepSeek', key)])
    assert sorted(x['where'] for x in section['problems']) == [str(Path('desktop-tasks/b/result.json')) + ':1', '工程 song.sgproj:1']
    assert '最近打开的工程 1 个' in section['checked']
    assert check.check_home(tmp_path / 'none')['problems'] == []


def test_report_text_names_saved_keys_without_showing_them(tmp_path, monkeypatch):
    key = 'sk-' + 'c0de' * 8
    monkeypatch.setattr(check, 'saved_keys', lambda home: [('DeepSeek', key)])
    home = tmp_path / 'home'; (home / 'desktop-tasks' / 'a').mkdir(parents=True)
    (home / 'desktop-tasks' / 'a' / 'result.json').write_text(key)
    archive = tmp_path / 'r.zip'
    with zipfile.ZipFile(archive, 'w') as bundle: bundle.writestr('x.txt', 'ok')
    report = check.run(ROOT, home, [archive])
    words = check.text(report)
    assert key not in words and 'DeepSeek（逐字比对，报告中不显示）' in words and '【本机记录与工程】发现 2 处问题' in words
    assert report['problems'] == 2 and '【Git 仓库】通过' in words and '【诊断报告】通过' in words


def test_privacy_script_passes_on_this_checkout(capsys):
    spec = importlib.util.spec_from_file_location('check_privacy', ROOT / 'scripts' / 'check-privacy.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.main(['--no-home', '--archives']) == 0
    out = capsys.readouterr().out
    assert '【Git 仓库】通过' in out and '合计：问题 0 处' in out and '本机记录与工程' not in out
