"""One existing recalculate button explains old estimate protection when needed."""
from PySide6.QtWidgets import QDialog
from studio_backend.recalculation import inspect
from .project import file_stamp
from .recalculation_dialog import RecalculationDialog


def choose(window):
    if window.api.busy or window.source_job or window.analysis_job or window.local_job or window.pending:
        window.message('先处理当前任务或已有建议，再选择内部重算。');return False
    if not window.flush_edits() or not window.line:return False
    if window.line.locked:return window.align_acoustic()
    try:offered=window.line.reviewed or inspect(window.line)['released']
    except ValueError as error:window.message(str(error));return False
    if offered:return open_dialog(window)
    return window.align_acoustic()


def open_dialog(w,options=None):
    if w.api.busy or w.source_job or w.analysis_job or w.local_job or w.pending:
        w.message('先处理当前任务或已有建议，再选择内部重算。');return False
    if not w.flush_edits() or not w.line:return False
    context={'project':w.project.uid,'media':file_stamp(w.project.media)}
    if not context['media']:w.message('先添加可读取的音视频素材，再重算内部。');return False
    before=w.line.to_dict()
    try:dialog=RecalculationDialog(w.line,w.playback,w,options)
    except ValueError as error:w.message(str(error));return False
    accepted=dialog.exec()==QDialog.DialogCode.Accepted
    if w.project.uid!=context['project'] or file_stamp(w.project.media)!=context['media'] or not w.line or w.line.to_dict()!=before:
        w.message('工程、素材或本句已变化，没有开始重算，原内容保持。');return False
    if dialog.manual:
        w.set_stage(2);w.select_entire_line();w.message('当前时间与保护保持，可在本句直接手工校对。');return True
    if not accepted:w.message('已保留当前时间与保护，没有开始重算。');return False
    return w.align_acoustic(dialog.prepared)


def resume(w,request):
    if not w.flush_edits():return False
    if not isinstance(request,dict) or not isinstance(request.get('plan'),dict) or not isinstance(request.get('_studio_context'),dict):
        w.message('内部重算请求格式无效，原记录与工程保留。');return False
    context=request.get('_studio_context',{});prepared=request.get('plan',{});original=prepared.get('original',{})
    if not isinstance(original,dict) or not isinstance(prepared.get('recalculation'),dict):
        w.message('内部重算请求缺少原始行或选择，原内容保留。');return False
    index=next((i for i,line in enumerate(w.project.lines) if line.id==original.get('id')),None)
    if context.get('project')!=w.project.uid or context.get('media')!=file_stamp(w.project.media) or index is None or w.project.lines[index].to_dict()!=original:
        w.message('工程、素材或本句版本已变化，旧请求保留；请按当前内容重新选择重算。');return False
    w.current=index;w.set_stage(2);w.refresh();return open_dialog(w,prepared.get('recalculation',{}))
