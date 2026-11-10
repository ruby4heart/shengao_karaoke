"""Paid requests that did not finish cleanly are never resubmitted automatically.

A record is written before a paid request leaves this computer. It is removed
when the result has been cached, or when the failure shows the service did not
process the request (not connected, upload cut short, request refused). A
timeout after the upload, a lost or unreadable response, or a worker that was
killed leaves the record behind, so sending the same request again needs an
explicit confirmation from the person, whichever task tries it next.
"""
import asyncio
import json
import re
import time
from contextlib import asynccontextmanager

from . import api
from .settings import Settings, atomic_json

SAFE = {'not_sent', 'unlikely', 'rejected'}
LABELS = {'transcribe': '音频识别', 'align': '文字对齐', 'refine': 'DeepSeek 读音复核', 'annotate': 'DeepSeek 注音和翻译'}
FIELDS = ('signature', 'action', 'provider', 'label', 'state', 'stage', 'billing', 'request_id', 'started', 'finished', 'cancelled')


class ResubmitRequired(ValueError):
    """The same paid request was interrupted before; ask before sending it again."""

    def __init__(self, record):
        self.record = {k: record[k] for k in FIELDS if record.get(k) not in (None, '')}
        stage = record.get('stage')
        where = f'在“{api.STAGES[stage][0]}”阶段' if stage in api.STAGES else '未确认是否已发出时'
        text = (f'同一{record.get("label") or "付费请求"}上次{where}中断，可能已经计费；已拦截自动重新提交。'
                '请先查看服务账户记录，确认需要时再手动重试。')
        if record.get('request_id'): text += f'服务请求编号：{record["request_id"]}。'
        super().__init__(text)
        # This attempt never left the computer.
        self.diagnostics = {'resubmit_blocked': True, 'previous_stage': stage or 'unknown'}


def folder(root):
    return Settings(root).root / 'paid-requests'


def signature(value):
    from .draft import digest
    return digest({'paid_request': 1, **value})


def pending(root, key):
    """The unresolved record for this request, or None. Unreadable means unknown."""
    path = folder(root) / f'{key}.json'
    try: record = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError: return None
    except (OSError, ValueError): return {'signature': key, 'state': 'unknown'}
    return record if isinstance(record, dict) else {'signature': key, 'state': 'unknown'}


@asynccontextmanager
async def guard(root, key, action, provider, diagnostics, confirmed=False):
    """Hold the request's lock while it runs and leave a record if it may be billed."""
    if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('付费请求编号无效；没有提交')
    from .draft import exclusive
    base = folder(root); path = base / f'{key}.json'; lock = base / f'{key}.lock'
    acquired = False
    try:
        with exclusive(lock, '同一付费请求正在另一个任务中进行，请等它结束；没有重复提交'):
            acquired = True
            previous = pending(root, key)
            if previous and confirmed is not True:
                raise ResubmitRequired(previous)
            record = {'version': 1, 'signature': key, 'action': action, 'provider': provider,
                      'label': LABELS.get(action, action), 'state': 'sent', 'started': time.time()}
            if previous: record['confirmed_after'] = previous.get('stage') or 'unknown'
            atomic_json(path, record)
            # A reused diagnostics dict must not carry the last request's phase.
            for name in ('phase', 'stage', 'billing', 'http_status', 'request_id'): diagnostics.pop(name, None)
            try:
                yield
            except BaseException as error:
                stage = api.classify(diagnostics); billing = api.STAGES[stage][2]
                if billing in SAFE: path.unlink(missing_ok=True)
                else:
                    record.update(state='unknown', stage=stage, billing=billing, finished=time.time(),
                                  cancelled=isinstance(error, asyncio.CancelledError))
                    if diagnostics.get('request_id'): record['request_id'] = str(diagnostics['request_id'])[:200]
                    atomic_json(path, record)
                raise
            path.unlink(missing_ok=True)
    finally:
        if acquired:
            try: lock.unlink(missing_ok=True)
            except OSError: pass
