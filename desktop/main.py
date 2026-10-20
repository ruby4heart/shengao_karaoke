"""Development and frozen entry point; worker mode never loads Qt."""
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'backend'),str(Path(__file__).resolve().parent)]

if __name__=='__main__':
    if '--worker' in sys.argv:
        sys.argv.remove('--worker')
        if '--owner-job' in sys.argv:
            index=sys.argv.index('--owner-job');name=sys.argv[index+1];del sys.argv[index:index+2]
            try:
                from shengao.process_tree import join_owner_job
                join_owner_job(name)
            except OSError:
                from studio_backend.settings import atomic_json
                result=Path(sys.argv[sys.argv.index('--result')+1]);atomic_json(result,{'ok':False,'message':'后台进程管理未就绪，尚未发送服务请求；请重启软件后重试。'})
                raise SystemExit(1)
        # Windowed PyInstaller programs set sys.stdin to None. QProcess still
        # supplies a real Windows pipe handle; reopen that pipe without a console.
        if sys.stdin is None and sys.platform=='win32':
            import ctypes,msvcrt,os,io
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.GetStdHandle.argtypes=[ctypes.c_ulong];kernel.GetStdHandle.restype=ctypes.c_void_p
            handle=kernel.GetStdHandle(ctypes.c_ulong(-10).value)
            if not handle or handle==ctypes.c_void_p(-1).value:raise SystemExit('Missing worker input pipe')
            fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
            sys.stdin=io.TextIOWrapper(os.fdopen(fd,'rb'),encoding='utf-8')
        from worker_entry import main
        raise SystemExit(main())
    elif '--self-test' in sys.argv:
        from shengao.self_test import main
        main()
    else:
        from shengao.app import main
        main()
