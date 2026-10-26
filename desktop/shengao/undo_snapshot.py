"""Compressed, process-local undo data. Never loaded from project files.

The constructor only accepts an owned dictionary captured by the controller.
There is deliberately no bytes/file import API. Pickle preserves tuple and
other Python metadata semantics; unsupported objects keep a detached fallback.
"""
from collections.abc import Mapping
import copy,pickle,zlib


class UndoSnapshot(Mapping):
    __slots__=('_payload','_fallback')

    def __init__(self,data):
        if not isinstance(data,dict):raise TypeError('撤销快照须为工程字典')
        self._payload=None;self._fallback=None
        try:self._payload=zlib.compress(pickle.dumps(data,protocol=5),1)
        except (pickle.PickleError,TypeError,AttributeError):self._fallback=copy.deepcopy(data)

    def restore(self):
        # _payload is produced only by this object in this process. Imported
        # sgproj/ASS and recovery files continue to use their JSON readers.
        return pickle.loads(zlib.decompress(self._payload)) if self._payload is not None else copy.deepcopy(self._fallback)

    @property
    def compressed_bytes(self):return len(self._payload) if self._payload is not None else None

    def __getitem__(self,key):return self.restore()[key]
    def __iter__(self):return iter(self.restore())
    def __len__(self):return len(self.restore())
    def __eq__(self,other):
        if isinstance(other,UndoSnapshot):
            if self._payload is not None and self._payload==other._payload:return True
            return self.restore()==other.restore()
        if isinstance(other,Mapping):return self.restore()==other
        return NotImplemented


def restore(value):
    """Old in-memory dict steps remain readable during the transition."""
    return value.restore() if isinstance(value,UndoSnapshot) else value
