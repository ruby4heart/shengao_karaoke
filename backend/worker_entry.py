"""Keep startup failures inside the JSON IPC contract, without logging secrets."""
import json
import os
from pathlib import Path
import sys
import tempfile


def startup_failure(error):
    # Imports and request decoding can fail before worker.execute() exists.
    # Report the exception type, never its text (which could contain a key).
    args=sys.argv[1:]
    if '--result' not in args or args.index('--result')+1>=len(args):
        return
    path=Path(args[args.index('--result')+1])
    invalid=isinstance(error,(json.JSONDecodeError,UnicodeDecodeError))
    message=('传入后台的任务数据不完整或格式无效，请更新主程序后重试。' if invalid else
             '后台启动失败，请使用完整的软件包；错误类型：'+type(error).__name__)
    def write(target,value):
        target.parent.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix=target.stem+'.',suffix='.tmp',dir=target.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(value,stream,ensure_ascii=False)
            os.replace(temp,target)
        finally:
            Path(temp).unlink(missing_ok=True)
    write(path,{'ok':False,'code':'invalid_request' if invalid else 'startup_failed',
                'message':message,'exception':type(error).__name__})
    write(Path(str(path)+'.progress.json'),{'phase':'error','message':message})


def main():
    try:
        from studio_backend.worker import main as run
        run()
    except Exception as error:
        startup_failure(error)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
