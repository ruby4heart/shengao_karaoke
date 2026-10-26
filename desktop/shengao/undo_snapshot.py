"""Private, structurally shared snapshots; restoration returns independent data.

Complete documents are retained. Unchanged lyric records and document fields
share only private copies between steps, never mutable controller objects.
There is no binary/file import API and no change to project persistence.
"""
from collections.abc import Mapping
import copy,io,pickle

_MISSING=object()

class _BuiltinFingerprint(pickle.Pickler):
    # CPython's exact built-ins use the C implementation. All custom classes,
    # including scalar/container subclasses, are rejected before __reduce__ or
    # custom state hooks. Their opaque state must never be interned by equality.
    def reducer_override(self,value):raise TypeError('opaque snapshot value')


def _fingerprint(value):
    stream=io.BytesIO()
    try:_BuiltinFingerprint(stream,protocol=5).dump(value)
    except (TypeError,pickle.PicklingError,RecursionError):return None
    return stream.getvalue()


def _owned(value,previous):
    # These bytes are only strict in-process equality keys, never restored or
    # imported. Restore always deep-copies the owned document. Unlike Python ==,
    # the key distinguishes bool/int, signed zero, tuple/list and shared graphs.
    fingerprint=_fingerprint(value)
    if fingerprint is not None and previous is not _MISSING and previous[1]==fingerprint:return previous
    return copy.deepcopy(value),fingerprint


def _row_key(row,index):
    return row['id'] if isinstance(row,dict) and isinstance(row.get('id'),str) else index


class SnapshotStore:
    def __init__(self):self._rows={};self._fields={}

    def _capture(self,data):
        if not isinstance(data,dict):raise TypeError('撤销快照须为工程字典')
        result={};rows={};fields={}
        for name,value in data.items():
            if name=='lines' and type(value) is list:
                owned=[]
                for index,row in enumerate(value):
                    key=_row_key(row,index);previous=self._rows.get(key,_MISSING)
                    entry=_owned(row,previous);rows[_row_key(entry[0],index)]=entry;owned.append(entry[0])
                result[name]=owned
            else:
                previous=self._fields.get(name,_MISSING)
                entry=_owned(value,previous)
                key=copy.deepcopy(name);fields[key]=entry;result[key]=entry[0]
        self._rows=rows;self._fields=fields;return result,rows,fields

    def capture(self,data):return UndoSnapshot(data,_store=self)

    def adopt(self,snapshot):
        if not isinstance(snapshot,UndoSnapshot):return
        self._rows=snapshot._rows;self._fields=snapshot._fields


class UndoSnapshot(Mapping):
    __slots__=('_data','_rows','_fields')

    def __init__(self,data,*,_store=None):self._data,self._rows,self._fields=(_store if _store is not None else SnapshotStore())._capture(data)

    def restore(self):return copy.deepcopy(self._data)
    def __getitem__(self,key):return copy.deepcopy(self._data[key])
    def __iter__(self):return iter(self._data)
    def __len__(self):return len(self._data)
    def __eq__(self,other):
        if isinstance(other,UndoSnapshot):return self._data==other._data
        if isinstance(other,Mapping):return self._data==other
        return NotImplemented


def restore(value):
    """Old in-memory dict steps remain readable during the transition."""
    return value.restore() if isinstance(value,UndoSnapshot) else value


def controller_view(value):
    """Only for Project.from_dict, whose input-isolation contract is tested."""
    return value._data if isinstance(value,UndoSnapshot) else value
