"""Bounded streaming with progress; credentials remain in urllib headers."""
import http.client
import urllib.request
import time
import json


class LargeHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self,*args,**kwargs):
        kwargs.setdefault('blocksize',1024*1024)
        super().__init__(*args,**kwargs)


class UploadHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self,request):
        return self.do_open(LargeHTTPSConnection,request,context=self._context)


def install():
    urllib.request.install_opener(urllib.request.build_opener(UploadHTTPSHandler()))


class ProgressReader:
    def __init__(self,stream,path):
        self.stream=stream;self.name=path.name;self.size=path.stat().st_size
        self.sent=0;self.last=0.;self.started=time.monotonic()
    def read(self,size=-1):
        value=self.stream.read(size);self.sent+=len(value);now=time.monotonic()
        if now-self.last>=10 or not value:
            self.last=now
            print(json.dumps({'upload':self.name,'read_bytes':self.sent,'total_bytes':self.size,
                'elapsed_seconds':round(now-self.started,1),'meaning':'read for streaming; remote verification follows'}),flush=True)
        return value
