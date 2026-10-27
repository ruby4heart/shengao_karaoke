"""Six fresh frozen processes: three empty app homes, then three reused homes.

Package hashes are audited and warm the OS file cache. No OS cache flush is
performed: 'cold' below means application state only, never a cold Windows boot.
"""
from pathlib import Path
import argparse,json,os,subprocess,sys,time,traceback

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'desktop'))
from shengao.runtime_integrity import verify_runtime


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scale',choices=('1','1.5'),default='1');args=parser.parse_args()
    package=args.package.resolve();exe=package/'shengao-karaoke.exe';out=args.output.resolve()
    if not exe.is_file():parser.error('Frozen executable does not exist')
    if out.is_relative_to(package):parser.error('output must be outside runtime')
    out.mkdir(parents=True,exist_ok=False)
    report={'completed':False,'passed':False,'scope':__doc__,'runs':[],
            'system_cache_flushed':False,'hash_audit_warms_files':True,'scale':args.scale,
            'computer_use':False,'paid_api_calls':0,'pending':['OS cold-cache and clean Windows certification']}
    try:
        before=verify_runtime(package);report['runtime_integrity_before']=before
        removed={'ELEVENLABS_API_KEY','MAI_SPEECH_KEY','DEEPSEEK_API_KEY','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH',
                 'QML_IMPORT_PATH','QML2_IMPORT_PATH','QT_QUICK_BACKEND','QSG_RHI_BACKEND',
                 'QT_FFMPEG_EXCLUDE_ENCODERS','QT_FFMPEG_DECODING_HW_DEVICE_TYPES','QT_FFMPEG_ENCODING_HW_DEVICE_TYPES'}
        env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON') and k not in removed}
        env['PATH']=str(package)+os.pathsep+str(Path(os.environ.get('WINDIR','C:/Windows'))/'System32')
        env['QT_SCALE_FACTOR']=args.scale
        last_home=None
        for kind,limit in [('empty-application-home',20000),('reused-application-home',10000)]:
            for index in range(3):
                run=out/(kind+'-'+str(index+1));home=out/('home-'+str(index+1)) if kind=='empty-application-home' else last_home
                if kind=='empty-application-home':assert not home.exists();last_home=home
                env['SHENGAO_HOME']=str(home)
                began=time.perf_counter()
                result=subprocess.run([str(exe),'--startup-readiness-test','--output',str(run),'--home',str(home),
                    '--launch-start',repr(began),'--cache-label',kind+'; audited OS files warm; no OS flush',
                    '--startup-limit-ms',str(limit)],env=env,cwd=out,capture_output=True,timeout=90,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                duration=(time.perf_counter()-began)*1000
                run.mkdir(parents=True,exist_ok=True);(run/'stdout.log').write_bytes(result.stdout);(run/'stderr.log').write_bytes(result.stderr)
                child=json.loads((run/'report.json').read_text(encoding='utf-8'))
                record={'kind':kind,'index':index+1,'exit_code':result.returncode,'process_wall_ms':duration,
                        'report':str(run/'report.json'),'window_ready_ms':child.get('window_ready_ms'),
                        'passed':bool(result.returncode==0 and child.get('completed') and child.get('passed') and child.get('frozen') and child.get('package_manifest_unchanged'))}
                report['runs'].append(record);print(json.dumps(record),flush=True)
        after=verify_runtime(package);report['runtime_integrity_after']=after
        report['runtime_unchanged']=before==after;report['completed']=True
        report['passed']=len(report['runs'])==6 and report['runtime_unchanged'] and all(row['passed'] for row in report['runs'])
    except Exception:report['error']=traceback.format_exc()
    finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
