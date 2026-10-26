"""Own-process Windows memory counters for repeatable performance reports."""
import ctypes,os
from ctypes import wintypes
_DLL=None
_API=None


class _Counters(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('page_faults',wintypes.DWORD),*[(name,ctypes.c_size_t) for name in ('peak_working_set','working_set','peak_paged_pool','paged_pool','peak_nonpaged_pool','nonpaged_pool','pagefile','peak_pagefile','private')]]


def sample():
    # Only the calling process is queried. No other process handles are opened.
    counters=_Counters();counters.cb=ctypes.sizeof(counters)
    global _DLL,_API
    if _API is None:
        _DLL=ctypes.WinDLL('psapi',use_last_error=True);_API=_DLL.GetProcessMemoryInfo
        _API.argtypes=[wintypes.HANDLE,ctypes.POINTER(_Counters),wintypes.DWORD];_API.restype=wintypes.BOOL
    if not _API(wintypes.HANDLE(-1),ctypes.byref(counters),counters.cb):raise ctypes.WinError(ctypes.get_last_error())
    return {'pid':os.getpid(),'working_set_bytes':counters.working_set,'peak_working_set_bytes':counters.peak_working_set,'private_bytes':counters.private,'peak_commit_bytes':counters.peak_pagefile,'page_faults':counters.page_faults}
