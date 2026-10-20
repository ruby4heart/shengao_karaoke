"""Desktop-only local audio bridge; cancellation awaits actual thread cleanup."""
import asyncio
from pathlib import Path
import threading

def runtime():
    try:
        from shengao import acoustic_batch
    except ImportError as error:raise ValueError('缺少桌面歌声引擎，请使用完整的声稿运行包。') from error
    return acoustic_batch

async def preflight(request,source_hash):
    opt=request['draft_options'];module=runtime()
    await asyncio.to_thread(module.preflight,request['media'],request.get('vocal_track',{}),opt['acoustic_audio'],source_hash)

async def run(rows,request,root,report,checkpoint,completed):
    module=runtime();opt=request['draft_options'];cancel=threading.Event()
    task_dir=getattr(report,'task_dir',None)
    from .settings import Settings
    work=Path(task_dir)/'acoustic-work' if task_dir else Settings(root).root/'draft-workflows'/request['workflow_id']/'acoustic-work'
    task=asyncio.create_task(asyncio.to_thread(module.generate,rows,request['media'],request.get('vocal_track',{}),root,cancel,
        lambda message:report('acoustic',message),checkpoint,opt['fit_range'],opt['acoustic_audio'],completed,work))
    try:return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        try:await task
        except Exception:pass
        raise
