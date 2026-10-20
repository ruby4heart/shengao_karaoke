"""Own the backend and all its descendants before sending its stdin request.

The backend waits for stdin, so assigning this private Windows job before
writing avoids a spawn/assignment race. Closing the GUI cannot orphan a model.
"""
import ctypes
import os
import uuid
import time
from ctypes import wintypes as w

class BasicLimits(ctypes.Structure):
    _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),('LimitFlags',w.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',w.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]

class IoCounters(ctypes.Structure):
    _fields_=[(name,ctypes.c_ulonglong) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]

class ExtendedLimits(ctypes.Structure):
    _fields_=[('BasicLimitInformation',BasicLimits),('IoInfo',IoCounters),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]

class BasicAccounting(ctypes.Structure):
    _fields_=[(name,ctypes.c_longlong) for name in ('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime')]+[(name,w.DWORD) for name in ('TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')]

class ProcessTree:
    def __init__(self):
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True);self.handle=None
        for name,args,result in [
            ('CreateJobObjectW',[ctypes.c_void_p,w.LPCWSTR],w.HANDLE),
            ('SetInformationJobObject',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD],w.BOOL),
            ('OpenProcess',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
            ('AssignProcessToJobObject',[w.HANDLE,w.HANDLE],w.BOOL),
            ('TerminateJobObject',[w.HANDLE,w.UINT],w.BOOL),
            ('QueryInformationJobObject',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p],w.BOOL),
            ('CloseHandle',[w.HANDLE],w.BOOL)]:
            fn=getattr(self.kernel,name);fn.argtypes=args;fn.restype=result
        self.name='Local\\ShengaoWorker-'+str(os.getpid())+'-'+uuid.uuid4().hex
        self.handle=self.kernel.CreateJobObjectW(None,self.name)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=ExtendedLimits();limits.BasicLimitInformation.LimitFlags=0x2000 # KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            error=ctypes.WinError(ctypes.get_last_error());self.close();raise error

    def assign(self,pid):
        process=self.kernel.OpenProcess(0x100|0x1,False,int(pid)) # SET_QUOTA | TERMINATE
        if not process:raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle,process):raise ctypes.WinError(ctypes.get_last_error())
        finally:self.kernel.CloseHandle(process)

    def terminate(self):
        if self.handle and not self.kernel.TerminateJobObject(self.handle,1):raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if getattr(self,'handle',None):self.kernel.CloseHandle(self.handle);self.handle=None

    def wait_empty(self,timeout=5):
        deadline=time.monotonic()+timeout
        while self.handle:
            info=BasicAccounting()
            if not self.kernel.QueryInformationJobObject(self.handle,1,ctypes.byref(info),ctypes.sizeof(info),None):raise ctypes.WinError(ctypes.get_last_error())
            if not info.ActiveProcesses:return
            if time.monotonic()>=deadline:raise TimeoutError('后台音频进程尚未退出')
            time.sleep(.01)

    def __del__(self):self.close()

def join_owner_job(name):
    """The real Python process joins before reading any service request.

    A Windows venv launcher can have created its interpreter before Qt emits
    started. Joining in the backend closes that launcher/assignment race.
    """
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    for fn,args,result in [('OpenJobObjectW',[w.DWORD,w.BOOL,w.LPCWSTR],w.HANDLE),('GetCurrentProcess',[],w.HANDLE),
        ('IsProcessInJob',[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)],w.BOOL),('AssignProcessToJobObject',[w.HANDLE,w.HANDLE],w.BOOL),('CloseHandle',[w.HANDLE],w.BOOL)]:
        method=getattr(kernel,fn);method.argtypes=args;method.restype=result
    handle=kernel.OpenJobObjectW(0x1|0x4,False,name)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        process=kernel.GetCurrentProcess();member=w.BOOL()
        if not kernel.IsProcessInJob(process,handle,ctypes.byref(member)):raise ctypes.WinError(ctypes.get_last_error())
        if not member and not kernel.AssignProcessToJobObject(handle,process):raise ctypes.WinError(ctypes.get_last_error())
    finally:kernel.CloseHandle(handle)
