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
