"""Publish a verified local release; keep failed uploads as a resumable draft.

Uses an explicitly supplied GITHUB_TOKEN or the configured Git credential helper.
Never prints or persists credentials. Push the source commit and version tag first.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
REPO='ruby4heart/shengao_karaoke'


def git(*args):
    env={**os.environ,'GCM_INTERACTIVE':'never','GIT_TERMINAL_PROMPT':'0'}
    return subprocess.check_output(['git',*args],cwd=ROOT,env=env,text=True,stderr=subprocess.PIPE).strip()


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',required=True);p.add_argument('--notes-file',type=Path,required=True)
    p.add_argument('--evidence-tag',required=True,help='Local acceptance label, e.g. v021')
    args=p.parse_args();version=args.version
    assert re.fullmatch(r'\d+\.\d+\.\d+',version),'Expected a final semantic version'
    tag='v'+version;short=args.evidence_tag
    assert re.fullmatch(r'v\d+',short),'Invalid acceptance label'
    audit_path=ROOT/'build'/('desktop-final-audit-'+short+'.json')
    audit=json.loads(audit_path.read_text(encoding='utf-8'))
    assert audit['passed'] and audit['version']==version
    from desktop_source_state import snapshot
    assert snapshot(ROOT)==json.loads((ROOT/'build/desktop-build-sources.json').read_text())
    assert snapshot(ROOT)==json.loads((ROOT/'build/desktop-test-sources.json').read_text())['sources']
    assert not git('status','--porcelain'),'Commit source and documentation before publishing'
    head=git('rev-parse','HEAD');assert git('rev-parse',tag+'^{commit}')==head
    remote=git('ls-remote','https://github.com/'+REPO+'.git','refs/tags/'+tag,'refs/tags/'+tag+'^{}')
    assert any(row.split()[0]==head for row in remote.splitlines()),'Push the matching version tag first'
    sums=ROOT/'dist'/('SHA256SUMS-'+version+'.txt');assets=[]
    expected={f'ShengaoKaraoke-{version}-final-win64.zip',f'ShengaoKaraoke-{version}-source.zip'}
    for row in sums.read_text(encoding='utf-8').splitlines():
        digest,name=row.split();assert name in expected and re.fullmatch(r'[0-9a-f]{64}',digest)
        path=ROOT/'dist'/name;assert path.is_file() and sha(path)==digest
        assets.append((path,digest));expected.remove(name)
    assert not expected
    evidence=ROOT/'dist'/f'ShengaoKaraoke-{version}-evidence.zip'
    assert evidence.is_file(),'Create the public evidence archive first'
    assets.extend([(sums,sha(sums)),(evidence,sha(evidence))])
    token=os.environ.get('GITHUB_TOKEN')
    if not token:
        env={**os.environ,'GCM_INTERACTIVE':'never','GIT_TERMINAL_PROMPT':'0'}
        result=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,env=env,timeout=30)
        values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        token=values.get('password')
    assert token,'No existing GitHub login; configure Git credentials or GITHUB_TOKEN'
    headers={'Authorization':'Bearer '+token,'User-Agent':'Shengao-release','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    def api(method,path,payload=None):
        url='https://api.github.com/repos/'+REPO+path
        request=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers={**headers,'Content-Type':'application/json'},method=method)
        try:
            with urllib.request.urlopen(request,timeout=90) as response:return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code==404 and method=='GET':return None
            raise RuntimeError(f'GitHub {method} {path}: HTTP {error.code}') from None
    release=api('GET','/releases/tags/'+tag)
    if not release:
        release=api('POST','/releases',{'tag_name':tag,'target_commitish':head,'name':'声稿 '+version,
            'body':args.notes_file.read_text(encoding='utf-8'),'draft':True,'prerelease':version.startswith('0.'),'make_latest':'false'})
    assert release['tag_name']==tag
    uploaded=[]
    for path,digest in assets:
        existing=next((item for item in release['assets'] if item['name']==path.name),None)
        if existing is None:
            assert release['draft'],'Never change an already published release'
            url=release['upload_url'].split('{',1)[0]+'?'+urllib.parse.urlencode({'name':path.name})
            assert urllib.parse.urlsplit(url).hostname=='uploads.github.com'
            print('Uploading '+path.name,flush=True)
            with path.open('rb') as stream:
                request=urllib.request.Request(url,data=stream,headers={**headers,'Content-Type':'application/octet-stream','Content-Length':str(path.stat().st_size)},method='POST')
                with urllib.request.urlopen(request,timeout=600) as response:existing=json.load(response)
        assert existing['state']=='uploaded' and existing['size']==path.stat().st_size,path.name
        assert existing.get('digest')=='sha256:'+digest,'Remote SHA256 mismatch or unavailable: '+path.name
        uploaded.append({'name':path.name,'size':existing['size'],'sha256':digest,'url':existing['browser_download_url']})
        print('Verified '+path.name,flush=True)
    if release['draft']:release=api('PATCH','/releases/'+str(release['id']),{'draft':False})
    assert not release['draft']
    report={'passed':True,'version':version,'repository':REPO,'commit':head,'tag':tag,'url':release['html_url'],'assets':uploaded}
    (ROOT/'build'/('github-release-'+version+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr)
        raise SystemExit(1)
