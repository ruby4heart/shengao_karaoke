"""Privacy check: no API keys or private user material in Git, release assets, diagnostics or local records.

  .venv-desktop\\Scripts\\python.exe scripts\\check-privacy.py
  .venv-desktop\\Scripts\\python.exe scripts\\check-privacy.py --archives dist\\ShengaoKaraoke-1.0.0-final-win64.zip
  .venv-desktop\\Scripts\\python.exe scripts\\check-privacy.py --no-home

Reads only. Keys saved on this computer are compared byte for byte and never
printed; findings show at most the first four characters of anything that
looks like a key. Without --archives every dist\\*.zip is checked. The local
data folder (default %APPDATA%\\ShengaoKaraoke, or SHENGAO_HOME) supplies the
saved keys and is itself checked for keys; --no-home skips both.

Exit code 0 when nothing was found, 1 otherwise. Items marked "?" (media in a
release that is not one of the published demo files) need a look but do not
fail the check.
"""
from pathlib import Path
import argparse,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'desktop'))
from shengao import privacy_check


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--archives',nargs='*',type=Path,help='要检查的发行包（默认 dist 下所有 zip）')
    parser.add_argument('--home',type=Path,help='本机数据目录（默认与程序相同）')
    parser.add_argument('--no-home',action='store_true',help='不读取本机数据目录和已保存的密钥')
    args=parser.parse_args(argv)
    try:sys.stdout.reconfigure(errors='replace')
    except (AttributeError,ValueError):pass
    home=None
    if not args.no_home:
        from studio_backend.settings import default_home
        home=args.home or default_home()
    report=privacy_check.run(ROOT,home,args.archives)
    print(privacy_check.text(report))
    return 1 if report['problems'] else 0


if __name__=='__main__':sys.exit(main())
