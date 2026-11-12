"""Damaged files, full disks and failed helper processes: what is kept and what the person is told.

Toolkit independent. Nothing here deletes or rewrites a person's own file. A
damaged record the app owns is moved aside under a dated name (see
``preserve``) so it can still be inspected, and the caller starts clean. A
damaged task result is shown as unfinished, never as a usable result.
"""
import errno
import json
from pathlib import Path
from studio_backend.settings import preserve_damaged as preserve

DISK_FULL_ERRNO = {errno.ENOSPC} | ({errno.EDQUOT} if hasattr(errno, 'EDQUOT') else set())
DISK_FULL_WINERROR = {39, 112}      # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
BUSY_WINERROR = {32, 33}            # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION


def disk_full(error):
    return isinstance(error, OSError) and (error.errno in DISK_FULL_ERRNO or getattr(error, 'winerror', None) in DISK_FULL_WINERROR)


def reason(error):
    """One plain sentence for a file or format error."""
    if disk_full(error): return '磁盘空间不足，请清理出空间后重试'
    if isinstance(error, PermissionError) or getattr(error, 'winerror', None) in BUSY_WINERROR:
        return '没有写入权限，或文件正被其他程序占用'
    if isinstance(error, FileNotFoundError): return '文件或文件夹不存在，可能已被移动、改名或删除'
    if isinstance(error, IsADirectoryError): return '选中的是文件夹而不是文件'
    if isinstance(error, UnicodeDecodeError): return '文件不是有效的文本，可能已损坏'
    if isinstance(error, json.JSONDecodeError): return f'文件内容不完整或已损坏（第 {error.lineno} 行附近）'
    if isinstance(error, OSError): return '读写文件失败' + (f'（{error.strerror}）' if error.strerror else '')
    return str(error)


def read_task(folder):
    """(request, result) of one background task folder, or None without a request.

    A damaged request or result is reported as an unfinished task whose folder
    stays on disk; it is never offered as suggestions to apply.
    """
    folder = Path(folder)
    try: request = json.loads((folder/'request.json').read_text(encoding='utf-8'))
    except FileNotFoundError: return None
    except (OSError, ValueError) as error:
        return {'action': 'damaged'}, {'message': '任务记录已损坏（' + reason(error) + '）；任务目录保留：' + folder.name}
    if not isinstance(request, dict):
        return {'action': 'damaged'}, {'message': '任务记录已损坏；任务目录保留：' + folder.name}
    result = folder/'result.json'
    if not result.exists(): return request, {'message': '没有最终结果，请确认服务端状态后再重试'}
    try: value = json.loads(result.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        return request, {'message': '结果文件已损坏，未采用（' + reason(error) + '）；任务目录保留'}
    if not isinstance(value, dict): return request, {'message': '结果文件已损坏，未采用；任务目录保留'}
    return request, value


MEMORY_MARKERS = ('memoryerror', 'out of memory', 'cannot allocate memory', 'bad_alloc', 'defaultcpuallocator', 'not enough memory')
DISK_MARKERS = ('no space left', 'errno 28', 'winerror 112', 'winerror 39', 'disk full', 'not enough space on the disk')
MISSING_MARKERS = ('filenotfounderror', 'no such file', 'winerror 2]', 'winerror 3]', 'cannot find the file', 'cannot find the path')
# Windows exit codes of a process that crashed or was closed from outside.
CRASH_CODES = {0xC0000005: '内存访问错误', 0xC00000FD: '栈溢出', 0xC0000409: '运行库异常终止',
               0xC000013A: '被关闭', 0xC0000017: '内存不足', 0xE06D7363: '未处理的异常'}


def process_failure(kind, code, log=''):
    """Plain-language message for a local helper process that exited with an error.

    kind: 'alignment' or 'vocals' for the local models, 'audio' for the FFmpeg
    conversion that prepares their input.
    """
    title = {'alignment': '歌声对齐失败', 'vocals': '人声处理失败', 'audio': '声音准备失败'}.get(kind, '本地处理失败')
    who = '声音转换进程' if kind == 'audio' else '本地模型进程'
    text = log or ''; lower = text.lower(); unsigned = code & 0xFFFFFFFF if isinstance(code, int) else 0
    if any(x in lower for x in DISK_MARKERS): cause = '磁盘空间不足，请清理缓存所在的磁盘后重试'
    elif unsigned == 0xC0000017 or any(x in lower for x in MEMORY_MARKERS):
        cause = '本机内存不足，请关闭其他占用内存的程序，或减少一次处理的句数后重试'
    elif any(x in lower for x in MISSING_MARKERS):
        cause = ('找不到素材文件，请确认素材没有被移动或改名' if kind == 'audio'
                 else '找不到模型或输入文件，请确认运行包完整、素材没有被移动')
    elif unsigned in CRASH_CODES: cause = f'{who}意外退出（{CRASH_CODES[unsigned]}，代码 0x{unsigned:08X}）'
    elif isinstance(code, int) and code < 0: cause = f'{who}被系统终止（信号 {-code}）'
    else: cause = f'{who}异常结束（代码 {code}）'
    detail = text.strip()[-1200:]
    return (f'{title}：{cause}。原素材和工程没有改动，这次未完成的结果没有采用。'
            + ('\n详细记录：\n' + detail if detail else ''))
