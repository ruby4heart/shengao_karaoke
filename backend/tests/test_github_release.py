"""Published-tag 404 must not duplicate an existing GitHub draft release."""
from pathlib import Path
import runpy
import pytest

lookup=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/publish-github-release.py'))['find_release']

def test_published_release_needs_no_listing():
    calls=[];expected={'id':1,'tag_name':'v0.22.0','draft':False}
    def api(method,path):calls.append(path);return expected
    assert lookup(api,'v0.22.0') is expected and calls==['/releases/tags/v0.22.0']

def test_existing_draft_is_reused_after_tag_endpoint_404():
    expected={'id':2,'tag_name':'v0.22.0','draft':True};calls=[]
    def api(method,path):
        calls.append(path)
        return None if '/tags/' in path else [expected]
    assert lookup(api,'v0.22.0') is expected and len(calls)==2

def test_older_draft_is_found_on_later_page():
    expected={'id':4,'tag_name':'v0.22.0','draft':True}
    def api(method,path):
        if '/tags/' in path:return None
        return [{'tag_name':f'other{i}'} for i in range(100)] if path.endswith('page=1') else [expected]
    assert lookup(api,'v0.22.0') is expected

def test_absent_tag_allows_new_release():
    assert lookup(lambda method,path:None if '/tags/' in path else [],'v0.22.0') is None

def test_duplicate_drafts_and_failed_listing_never_create_release():
    for values in [[{'tag_name':'v0.22.0'},{'tag_name':'v0.22.0'}],None]:
        with pytest.raises(AssertionError):lookup(lambda method,path:None if '/tags/' in path else values,'v0.22.0')


def test_upload_stream_preserves_exact_bytes_and_bounded_chunks(tmp_path,capsys):
    """Exercise http.client's real file-body path, without opening a socket."""
    import hashlib
    transport=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/github_release_transport.py'))
    payload=bytes(range(256))*9001;path=tmp_path/'source.zip';path.write_bytes(payload)
    class Socket:
        def __init__(self):self.sent=[]
        def sendall(self,value):self.sent.append(bytes(value))
    connection=transport['LargeHTTPSConnection']('example.invalid');socket=Socket();connection.sock=socket
    with path.open('rb') as stream:
        reader=transport['ProgressReader'](stream,path)
        connection.request('POST','/assets',body=reader,headers={'Content-Length':str(len(payload))})
    body=socket.sent[1:]
    assert all(len(value)<=1024*1024 for value in body) and max(map(len,body))==1024*1024
    assert hashlib.sha256(b''.join(body)).digest()==hashlib.sha256(payload).digest() and reader.sent==len(payload)
    output=capsys.readouterr().out
    assert 'read_bytes' in output and 'remote verification follows' in output and 'Authorization' not in output
