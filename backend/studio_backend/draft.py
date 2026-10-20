"""Resumable draft stages. Completed stages are immutable local checkpoints.

This coordinates existing operations; it does not turn character timestamps or
uniform mora splits into acoustic phoneme evidence.
"""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from contextlib import contextmanager

from .model import LyricLine
from .settings import Settings, atomic_json

STAGES = [('transcript', '准备转录'), ('matching', '按原歌词匹配'),
          ('readings', '生成读音建议'), ('alignment', '文字对齐'), ('preview', '准备审核')]
STATES = {'pending': '等待', 'running': '处理中', 'completed': '已完成',
          'skipped': '跳过', 'failed': '未完成', 'cancelled': '已取消', 'partial': '部分完成'}


def protected(line):
    return (line.locked or line.reviewed or any(u.locked or u.source == 'manual'
            or any(h.source == 'manual' for h in u.highlights) for u in line.units))


def options(request):
    value = request.get('draft_options', {})
    if not isinstance(value, dict): raise ValueError('初稿流程选项无效')
    source = value.get('source', 'offline')
    reading = value.get('readings', 'dictionary')
    provider = value.get('provider', 'elevenlabs')
    align = value.get('align', False)
    if source not in {'offline', 'reuse', 'cloud'} or reading not in {'dictionary', 'deepseek'}:
        raise ValueError('初稿流程选项无效')
    if provider not in {'elevenlabs', 'mai'} or type(align) is not bool:
        raise ValueError('初稿服务选项无效')
    acoustic=value.get('acoustic',False)
    if type(acoustic) is not bool:raise ValueError('歌声对齐选项无效')
    result={'source': source, 'readings': reading, 'provider': provider, 'align': align}
    # Preserve the exact dictionaries/signatures of legacy five-stage work.
    if acoustic:
        role=value.get('acoustic_audio','auto');fit=value.get('fit_range',True)
        if role not in {'auto','original','vocals'} or type(fit) is not bool:raise ValueError('歌声对齐选项无效')
        result.update(acoustic=True,acoustic_audio=role,fit_range=fit)
    return result

def stage_plan(opt,version=2):
    return STAGES[:4]+[('acoustic','歌声音节对齐')]+STAGES[4:] if version>=2 else STAGES


def checkpoint_path(root, workflow_id):
    if not isinstance(workflow_id, str) or not re.fullmatch('[a-f0-9]{32}', workflow_id):
        raise ValueError('初稿流程编号无效')
    return Settings(root).root / 'draft-workflows' / workflow_id / 'state.json'


def load(root, workflow_id):
    state = json.loads(checkpoint_path(root, workflow_id).read_text(encoding='utf-8'))
    if state.get('version') not in {1,2} or state.get('id') != workflow_id or not isinstance(state.get('stages'), list):
        raise ValueError('初稿检查点无效；没有自动重新提交请求')
    for stage in state['stages']:
        if stage['state'] in {'completed','partial'} or stage.get('result'):
            if stage.get('result_hash') != digest(stage.get('result')):
                raise ValueError('阶段检查点损坏；没有自动重新提交请求')
            if stage['key']=='transcript':
                for row in stage['result']['suggestions']:LyricLine.from_dict(row)
            else:verify_rows(stage['result']['suggestions'],state['request']['lines'])
    return state


def load_summary(root,workflow_id):
    return json.loads(checkpoint_path(root,workflow_id).with_name('status.json').read_text(encoding='utf-8'))


def latest(root, project_id):
    base = Settings(root).root / 'draft-workflows'
    paths = sorted(base.glob('*/state.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            status=load_summary(root,path.parent.name)
            if status.get('context',{}).get('project')!=project_id:continue
            state = load(root, path.parent.name)
            if state['request'].get('_studio_context', {}).get('project') == project_id:
                return state
        except (OSError, ValueError, KeyError):
            continue
    return None


def summary(state):
    return {'id': state['id'], 'status': state['status'], 'message': state.get('message', ''),
            'stages': [{**{k: s[k] for k in ('key', 'title', 'state', 'paid')},
                        **({'acoustic':s['result']['acoustic']} if s.get('result',{}).get('acoustic') else {})}
                       for s in state['stages']], 'lines': len(state['request']['lines']),
            'context': state['request'].get('_studio_context', {})}


def result(state):
    # Only completed, validated checkpoints contribute suggestions. A partly
    # returned reading batch is merged with the preceding complete draft.
    values = []; transcript = []; diagnostics = {};media_fingerprint='';acoustic=None;sequence=None
    for stage in state['stages']:
        if stage['state'] not in {'completed', 'partial'} and not stage.get('result',{}).get('partial'):
            continue
        data = stage.get('result', {})
        if stage['key'] == 'transcript':
            transcript = data.get('suggestions', [])
            media_fingerprint=data.get('media_fingerprint','')
        elif data.get('suggestions'):
            values = data['suggestions']
        if data.get('diagnostics'):
            diagnostics[stage['key']] = data['diagnostics']
        if stage['key']=='acoustic':acoustic=data.get('acoustic')
        if stage['key']=='matching':sequence=data.get('sequence_review')
    complete = state['status'] == 'completed'
    notice = ('初稿流程完成，请审核后采用。' if complete else '流程未全部完成；已完成的初稿可以先审核或继续。')
    notice += (f'歌声候选 {acoustic["aligned"]} 句，保留初稿待手工 {acoustic["needs_manual"]} 句，尚未处理 {acoustic["total"]-acoustic["processed"]} 句；读音和时间仍需确认。' if acoustic else '字符／词组对齐不是演唱音节识别，细音节仍可能均分估算，需试听。')
    return {'suggestions': copy.deepcopy(values), 'transcript': copy.deepcopy(transcript),
            'media_fingerprint':media_fingerprint,
            'diagnostics': diagnostics, 'review_required': True, 'partial': not complete,
            'message': notice + ('\n' + state.get('message', '') if not complete else ''),
            'workflow': summary(state),**({'acoustic':copy.deepcopy(acoustic)} if acoustic else {}),
            **({'sequence_review':copy.deepcopy(sequence)} if sequence else {})}


def saved_result(request, root):
    """Recover after cancellation/worker termination without restarting a call."""
    try:
        return result(load(root, request['workflow_id']))
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def mark_stopped(root,workflow_id):
    """Called only after the owning QProcess has authoritatively terminated."""
    path=checkpoint_path(root,workflow_id)
    with exclusive(path.parent/'.lock'):
        state=load(root,workflow_id)
        if state['status']!='running':return
        for stage in state['stages']:
            if stage['state']=='running':stage['state']='failed'
        complete=all(s['state'] in {'completed','skipped'} for s in state['stages'])
        state.update(status='completed' if complete else 'paused',updated=time.time(),
                     message='已完成阶段保留，等待审核。' if complete else '后台进程已经结束。已完成步骤保留；未返回的联网请求请检查服务记录后再决定是否重试。')
        atomic_json(path,state);atomic_json(path.with_name('status.json'),summary(state))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def inputs(request):
    # Persist only supported non-secret fields, never a settings/environment dump.
    lines = [LyricLine.from_dict(v) for v in request.get('lines', [])]
    if not lines:
        raise ValueError('请先粘贴原歌词；识别初稿的原文确认仍是单独步骤')
    if len({v.id for v in lines}) != len(lines) or any(protected(v) for v in lines):
        raise ValueError('自动初稿范围包含重复编号、锁定或人工校准内容，请调整范围')
    opt=options(request)
    transcript = [LyricLine.from_dict(v).to_dict() for v in request.get('transcript', [])] if opt['source']=='reuse' else []
    value = {k: copy.deepcopy(request[k]) for k in ('media', 'language', 'gap_ms', 'join_lines',
             '_studio_context', '_studio_checks', 'reading_confirmed_ids', 'transcript_stamp') if k in request}
    value.update(action='draft', draft_options=opt, lines=[v.to_dict() for v in lines],
                 transcript=transcript)
    if opt.get('acoustic'):value['vocal_track']=copy.deepcopy(request.get('vocal_track',{}))
    if value['draft_options']['source'] == 'reuse' and not transcript:
        raise ValueError('没有可复用的转录；请选择离线初稿或联网识别')
    return value


def verify_rows(rows, original):
    values = [LyricLine.from_dict(v) for v in rows]
    if [(v.id, v.text) for v in values] != [(v['id'], v['text']) for v in original]:
        raise ValueError('阶段结果改变了原歌词、编号或顺序，已停止流程')
    if any(v.reviewed or v.locked for v in values):
        raise ValueError('自动阶段不能将初稿标为人工确认或锁定')
    return values

def keep_readings(row,original,confirmed=False):
    """Matching may move text, but cannot discard human reading/group choices."""
    if not confirmed and not any(u.get('reading_source')=='manual' for u in original.get('units',[])):return row
    from .japanese import Group,retime_groups,word_groups,add_mora
    from .model import Unit
    value=LyricLine.from_dict(row);groups=[];cursor=0
    for u in original.get('units',[]):
        kana=u.get('kana','');latin=u.get('romaji','')
        if not kana and not confirmed:
            parts=word_groups(u['text']);kana=''.join(p.kana for p in parts);latin=''.join(p.romaji for p in parts)
        groups.append(Group(u['text'],cursor,cursor+len(u['text']),kana,latin));cursor+=len(u['text'])
    if groups:
        value.units=retime_groups(value,groups,preserve_readings=False)
        for u,old in zip(value.units,original['units']):u.reading_source=old.get('reading_source','')
    elif original.get('kana'):
        from .provenance import group_basis
        origin=group_basis(value.units,value.start,value.end,'confirmed_reading_group')
        value.units=[Unit(value.text,value.start,value.end,original['kana'],original.get('romaji',''),reading_source='confirmed',timing_origin=origin)]
    for u in value.units:add_mora(u)
    value.kana=original.get('kana','') if confirmed else ''.join(u.kana for u in value.units)
    value.romaji=original.get('romaji','') if confirmed else ' '.join(u.romaji for u in value.units if u.romaji)
    value.translation=original.get('translation','');value.validate();return value.to_dict()


@contextmanager
def exclusive(path):
    """OS lock is released even after a worker crash; no stale PID guessing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0: stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('这个初稿流程已在另一个进程运行，请等待原任务结束') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt': msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


async def run(request, root, report, operation):
    workflow_id = request.get('workflow_id') or uuid.uuid4().hex
    path = checkpoint_path(root, workflow_id)
    with exclusive(path.parent / '.lock'):
        return await _run({**request, 'workflow_id': workflow_id}, root, report, operation)


async def _run(request, root, report, operation):
    from .worker import fingerprint
    from .japanese import add_mora
    settings = Settings(root); supplied = inputs(request); opt = supplied['draft_options']
    media = Path(supplied.get('media', ''))
    needs_media = opt['source'] in {'cloud','reuse'} or opt['align'] or opt.get('acoustic')
    if needs_media and not media.is_file():
        raise ValueError('转录或音节对齐前，请先添加有效音视频')
    media_hash = await asyncio.to_thread(fingerprint, media) if media.is_file() else ''
    if opt['source']=='reuse':
        stat=media.stat()
        current_stamp={'path':os.path.normcase(str(media.resolve())),'size':stat.st_size,'modified_ns':stat.st_mtime_ns}
        if supplied.get('transcript_stamp')!=current_stamp:
            raise ValueError('已有转录没有对应当前素材版本，请切回原素材或重新识别')
    providers = ({opt['provider']} if opt['source'] == 'cloud' else set())
    if opt['readings'] == 'deepseek': providers.add('deepseek')
    if opt['align']: providers.add('elevenlabs')
    config = settings.read()
    config = {p: {k: config.get(p, {}).get(k, '') for k in ('endpoint', 'model')} for p in sorted(providers)}
    signature = digest({'input': supplied, 'media': media_hash, 'services': config})
    workflow_id = request.get('workflow_id') or uuid.uuid4().hex
    path = checkpoint_path(root, workflow_id)
    if path.exists():
        state = load(root, workflow_id)
        if state.get('signature') != signature or digest(state.get('request')) != digest(supplied):
            raise ValueError('素材、流程输入或服务配置已变化；原检查点保留，请建立新流程')
        if [s.get('key') for s in state['stages']] != [key for key, _ in stage_plan(opt,state['version'])]:
            raise ValueError('阶段检查点损坏；没有自动重新提交请求')
        for stage in state['stages']:
            if stage.get('state') not in STATES:
                raise ValueError('阶段检查点状态无效；没有自动重新提交请求')
            if stage['state'] == 'completed':
                if stage.get('result_hash') != digest(stage.get('result')):
                    raise ValueError('已完成阶段的检查点损坏；没有自动重新提交请求')
                if stage['key'] != 'transcript': verify_rows(stage['result']['suggestions'], supplied['lines'])
    else:
        if request.get('resume'):
            raise ValueError('找不到原流程检查点；没有自动重新提交请求')
        titles={'transcript':{'cloud':'联网识别音轨','reuse':'复用已有转录','offline':'离线初稿（不转录）'}[opt['source']],
                'matching':'按原歌词分词' if opt['source']=='offline' else '按原歌词匹配',
                'readings':'DeepSeek 读音建议' if opt['readings']=='deepseek' else '本地读音建议',
                'alignment':'ElevenLabs 文字对齐' if opt['align'] else '文字对齐（未选择）'}
        state = {'version': 2, 'id': workflow_id, 'signature': signature, 'request': supplied,
                 'created': time.time(), 'status': 'pending', 'message': '', 'stages': [
                     {'key': key, 'title': titles.get(key,title), 'state': 'pending', 'paid':
                      key == 'transcript' and opt['source'] == 'cloud' or
                      key == 'readings' and opt['readings'] == 'deepseek' and
                      any(v['id'] not in supplied.get('reading_confirmed_ids', []) for v in supplied['lines']) or
                      key == 'alignment' and opt['align']} for key, title in stage_plan(opt)]}
        atomic_json(path, state)
        atomic_json(path.with_name('status.json'),summary(state))

    def save(message='', status=None):
        state['message'] = message
        if status: state['status'] = status
        state['updated'] = time.time(); atomic_json(path, state)
        atomic_json(path.with_name('status.json'),summary(state))

    async def verify_media():
        if media_hash and (not media.is_file() or await asyncio.to_thread(fingerprint, media) != media_hash):
            raise ValueError('素材在流程期间被替换；结果保留在检查点，没有继续提交')

    if opt.get('acoustic') and any(s['key']=='acoustic' and s['state'] not in {'completed','skipped'} for s in state['stages']):
        from .singing_stage import preflight
        try:await preflight(supplied,media_hash)
        except ValueError as error:
            save(str(error),'paused');return result(state)

    values = copy.deepcopy(supplied['lines']); transcript = copy.deepcopy(supplied['transcript'])
    for number, stage in enumerate(state['stages'], 1):
        key = stage['key']; previous = stage['state']
        if previous in {'completed', 'skipped'}:
            if key == 'transcript': transcript = stage.get('result', {}).get('suggestions', [])
            elif previous == 'completed': values = copy.deepcopy(stage['result']['suggestions'])
            report('draft_cached', f'{number}/{len(state["stages"])} {stage["title"]}：复用已完成阶段')
            continue
        if stage['paid'] and previous in {'running', 'failed', 'cancelled', 'partial'} and request.get('retry_stage') != key:
            save('该联网阶段上次未完整返回。请先检查服务记录，再选择是否手动重试；已完成阶段不会重复运行。', 'paused')
            return result(state)
        skip = key == 'alignment' and not opt['align']
        skip = skip or key=='acoustic' and not opt.get('acoustic')
        skip = skip or key=='transcript' and opt['source']=='offline'
        skip = skip or key=='readings' and all(v['id'] in supplied.get('reading_confirmed_ids',[]) for v in values)
        if skip:
            stage['state'] = 'skipped'; save(); continue
        # Check every required key before the first new submission, so a missing
        # later-stage setting does not waste an earlier paid transcription.
        remaining = [s for s in state['stages'] if s['state'] not in {'completed', 'skipped'}]
        required = set()
        for item in remaining:
            if item['key'] == 'transcript' and item['paid']: required.add(opt['provider'])
            elif item['key'] == 'readings' and item['paid']: required.add('deepseek')
            elif item['key'] == 'alignment' and item['paid']: required.add('elevenlabs')
        missing = [p for p in sorted(required) if not settings.key(p)]
        if missing:
            save('请先在服务设置填写 ' + '、'.join(missing) + ' 密钥，然后继续；尚未提交本阶段。', 'paused')
            return result(state)
        stage['state'] = 'running'; save(status='running')
        report('draft_stage', f'{number}/{len(state["stages"])} {stage["title"]}：' + ('联网处理，未完成请求不会自动重试' if stage['paid'] else '本机处理'))
        try:
            await verify_media()
            base = {'media': supplied.get('media', ''), 'language': supplied.get('language', 'ja'),
                    'gap_ms': supplied.get('gap_ms', 0), 'join_lines': supplied.get('join_lines', False)}
            if key == 'transcript':
                if opt['source'] == 'cloud':
                    data = await operation({**base, 'action': 'transcribe', 'provider': opt['provider'], 'lines': []}, root, report)
                    transcript = data['suggestions']
                else:
                    data = {'suggestions': transcript, 'local': True}
                for row in data['suggestions']: LyricLine.from_dict(row)
            elif key == 'matching':
                data = await operation({**base, 'action': 'segment' if opt['source'] == 'offline' else 'match',
                                        'mode': 'mora', 'lines': values, 'transcript': transcript}, root, report)
                if opt.get('acoustic') and opt['source']=='offline':
                    originals={v['id']:v for v in supplied['lines']}
                    for row in data['suggestions']:
                        old=originals[row['id']].get('match',{})
                        if old.get('status') in {'unmatched','uncertain'}:row['match']=copy.deepcopy(old)
            elif key == 'readings':
                confirmed = set(supplied.get('reading_confirmed_ids', []))
                candidates = [v for v in values if v['id'] not in confirmed]
                data = await operation({**base, 'gap_ms': 0, 'action': 'refine', 'lines': candidates,
                                        'transcript': transcript, 'context': values, 'use_llm': opt['readings'] == 'deepseek',
                                        'preserve_legacy': True, 'preserve_manual': True, 'transcript_verified': bool(media_hash)}, root, report) if candidates else {'suggestions': [], 'local': True}
                updates = {v['id']: v for v in data['suggestions']}
                for old in values:
                    if old.get('translation') and old['id'] in updates:
                        updates[old['id']]['translation'] = old['translation']
                data['suggestions'] = [updates.get(v['id'], v) for v in values]
            elif key == 'alignment':
                data = await operation({**base, 'action': 'align', 'range_mode': 'full', 'lines': values}, root, report)
                by_id = {v['id']: v for v in values}
                for row in data['suggestions']:
                    old = by_id[row['id']]
                    row['match'] = copy.deepcopy(old.get('match', {}))
                    row['reading_review'] = copy.deepcopy(old.get('reading_review', {}))
            elif key=='acoustic':
                from .singing_stage import run as sing
                def checkpoint(data):
                    verify_rows(data['suggestions'],supplied['lines'])
                    stage['result']=data;stage['result_hash']=digest(data);save()
                data=await sing(values,{**supplied,'workflow_id':workflow_id},root,report,checkpoint,stage.get('result',{}).get('acoustic_checkpoint'))
            else:
                rows = verify_rows(values, supplied['lines'])
                for row, original in zip(rows, supplied['lines']):
                    for unit in row.units:
                        if not unit.highlights: add_mora(unit)
                    if original.get('display_start') is not None:
                        row.display_start = min(original['display_start'], row.start)
                    if original.get('display_end') is not None:
                        row.display_end = max(original['display_end'], row.end)
                    row.validate()
                data = {'suggestions': [v.to_dict() for v in rows], 'local': True}
            await verify_media()
            if key in {'matching','alignment'}:
                confirmed=set(supplied.get('reading_confirmed_ids',[]));originals={v['id']:v for v in supplied['lines']}
                data['suggestions']=[keep_readings(v,originals[v['id']],v['id'] in confirmed) for v in data['suggestions']]
            if key != 'transcript':
                verify_rows(data['suggestions'], supplied['lines']); values = copy.deepcopy(data['suggestions'])
            stage['result'] = data; stage['result_hash'] = digest(data)
            stage['state'] = 'partial' if data.get('partial') else 'completed'
            save()
            if stage['state'] == 'partial':
                save(data.get('message', '该阶段仅完成一部分；结果已保留'), 'paused'); return result(state)
        except asyncio.CancelledError:
            stage['state'] = 'cancelled'; save('本地已取消；已提交的云端请求可能仍在处理，检查后手动决定是否重试。' if stage['paid'] else '本地已取消，已完成部分保留，可继续未完成部分。', 'paused')
            raise
        except Exception as error:
            from .api import ApiError
            stage['state'] = 'failed'
            if isinstance(error, ApiError): stage['diagnostics'] = error.diagnostics
            # Do not persist arbitrary library exception text, headers or keys.
            message = str(error) if isinstance(error, ValueError) else '该阶段处理失败，请检查文件、配置或返回结构'
            save(message, 'paused'); report('draft_paused', message); return result(state)
    save('各阶段完成，等待人工审核。', 'completed')
    return result(state)
