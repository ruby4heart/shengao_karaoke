"""Fast common checkpoints with the original JSON rejection/fallback semantics."""
import json
from studio_backend import model
try:import orjson
except ImportError:orjson=None

VERSION='3.13.0'
_calls={'fast':0,'standard':0}


def _context():
    state=model._SNAPSHOT_ACCELERATOR;encoder=orjson
    if encoder is None or encoder.__version__!=VERSION or state is None:return None
    guard=getattr(state[0],'json_tree',None)
    return (encoder,guard) if guard is not None else None


def available():return _context() is not None


def shareable(value):
    """Exact finite JSON trees have no user hooks and allow read-only sharing."""
    context=_context()
    return context is not None and context[1](value)


def dumps(value):
    context=_context()
    if context is not None and context[1](value):
        encoder=context[0]
        try:encoded=encoder.dumps(value).decode('utf-8')
        except encoder.JSONEncodeError:pass  # e.g. large integers or lone surrogates
        else:_calls['fast']+=1;return encoded
    _calls['standard']+=1
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def status():return {'available':available(),'version':orjson.__version__ if orjson is not None else None,'encoding_calls':dict(_calls)}
