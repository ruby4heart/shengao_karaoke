"""Ask before sending again a paid request that may already have been billed.

The backend refuses to resend an interrupted paid request on its own. This
offers the person one explicit way to send it again, only while the project,
media and selected lines are still exactly what the request was made for.
"""
from PySide6.QtWidgets import QMessageBox

from studio_backend.api import STAGES
from .project import file_stamp


def blocked(job):
    """The interrupted request the last failure refused to resend, if any."""
    record=(getattr(job,'failure',None) or {}).get('resubmit_required')
    return record if isinstance(record,dict) else None


def stale_reason(window):
    """Why the old request no longer fits the open project, or ''."""
    request=window.api.request;context=request.get('_studio_context') or {}
    if window.api.busy:return '已有后台任务正在执行'
    if window.pending and window.pending.get('result',{}).get('suggestions'):return '还有建议等待审核'
    if context and (context.get('project')!=window.project.uid or context.get('media')!=file_stamp(window.project.media)):return '工程或素材已经变化'
    current={line.id:line.to_dict() for line in window.project.lines}
    if any(current.get(key)!=value for key,value in (getattr(window,'snapshots',None) or {}).items()):return '所选歌词已经修改'
    return ''


def question(record):
    label=record.get('label') or '付费请求';stage=record.get('stage')
    where=f'在“{STAGES[stage][0]}”阶段中断' if stage in STAGES else '中断时无法确认是否已经发出'
    text=(f'{label}上次{where}，服务可能已经处理并计费。\n\n'
          '请先到服务账户查看用量或请求记录'+(f'（请求编号：{record["request_id"]}）' if record.get('request_id') else '')+'。'
          '确认上次没有成功、仍要再提交一次时，选择“是”。\n\n选择“否”不会发送任何内容。')
    return text


def offer_resubmit(window):
    """After the person confirms, send the same request once more; True if sent."""
    record=blocked(window.api)
    if not record:return False
    reason=stale_reason(window)
    if reason:window.message(f'{reason}，没有重新提交；需要时请重新发起这项操作，仍会先询问是否重新提交。');return False
    answer=QMessageBox.question(window,'可能已计费的请求',question(record),
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
    if answer!=QMessageBox.StandardButton.Yes:
        window.message('没有重新提交。上次的请求记录保留，下次发起同一请求仍会先询问。');return False
    window.api.start({**window.api.request,'confirm_resubmit':True})
    window.message('已按你的确认重新提交一次；结果仍会先进入审核。');return True
