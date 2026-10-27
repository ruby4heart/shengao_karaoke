#define PY_SSIZE_T_CLEAN
#include <Python.h>

/* Stateless copies using owned references and CPython's recursion guard.
 * Uncommon values retain the caller's existing Python conversion semantics.
 * No borrowed pointer outlives a callback or an iterator result. */
#if PY_MAJOR_VERSION != 3 || PY_MINOR_VERSION != 12
#error Rebuild and audit snapshot support for this Python version first
#endif
#ifndef SG_SNAPSHOT_SOURCE_SHA256
#define SG_SNAPSHOT_SOURCE_SHA256 "unversioned"
#endif

static PyObject *copy_node(PyObject *value, PyObject *fields, PyObject *fallback, int tuples);

static PyObject *copy_mapping(PyObject *value, PyObject *fields, PyObject *fallback, int tuples) {
    PyObject *result=PyDict_New(), *view=NULL, *iterator=NULL, *pair=NULL;
    if (!result || !PyDict_Size(value)) return result;
    view=PyObject_CallMethod(value,"items",NULL);
    if (!view) goto fail;
    iterator=PyObject_GetIter(view);Py_DECREF(view);view=NULL;
    if (!iterator) goto fail;
    while ((pair=PyIter_Next(iterator))) {
        PyObject *key=copy_node(PyTuple_GET_ITEM(pair,0),fields,fallback,tuples);
        PyObject *item=key ? copy_node(PyTuple_GET_ITEM(pair,1),fields,fallback,tuples) : NULL;
        int ok=key && item && PyDict_SetItem(result,key,item)==0;
        Py_XDECREF(key);Py_XDECREF(item);Py_DECREF(pair);pair=NULL;
        if (!ok) goto fail;
    }
    if (PyErr_Occurred()) goto fail;
    Py_DECREF(iterator);return result;
fail:
    Py_XDECREF(pair);Py_XDECREF(iterator);Py_XDECREF(view);Py_XDECREF(result);return NULL;
}

static PyObject *copy_node(PyObject *value, PyObject *fields, PyObject *fallback, int tuples) {
    PyObject *result=NULL,*names=NULL;
    PyTypeObject *kind=Py_TYPE(value);
    if (kind==&PyUnicode_Type || kind==&PyLong_Type || kind==&PyFloat_Type || kind==&PyBool_Type || value==Py_None) return Py_NewRef(value);
    if (Py_EnterRecursiveCall(" while copying a karaoke snapshot")) return NULL;
    if (PyDict_CheckExact(value)) result=copy_mapping(value,fields,fallback,tuples);
    else if (PyList_CheckExact(value)) {
        PyObject *iterator=PyObject_GetIter(value),*item=NULL;
        result=iterator ? PyList_New(0) : NULL;
        if (result) {
            while ((item=PyIter_Next(iterator))) {
                PyObject *owned=copy_node(item,fields,fallback,tuples);Py_DECREF(item);
                int ok=owned && PyList_Append(result,owned)==0;Py_XDECREF(owned);
                if (!ok) {Py_CLEAR(result);break;}
            }
            if (PyErr_Occurred()) Py_CLEAR(result);
        }
        Py_XDECREF(iterator);
    }
    else if (tuples && PyTuple_CheckExact(value)) {
        Py_ssize_t count=PyTuple_GET_SIZE(value);result=PyTuple_New(count);
        if (result) for (Py_ssize_t i=0;i<count;i++) {
            PyObject *item=copy_node(PyTuple_GET_ITEM(value,i),fields,fallback,tuples);
            if (!item) {Py_CLEAR(result);break;}
            PyTuple_SET_ITEM(result,i,item);
        }
    }
    else {
        if (fields) names=PyDict_GetItemWithError(fields,(PyObject *)kind);
        if (!names && PyErr_Occurred()) goto done;
        if (names) {
            Py_INCREF(names);
            if (!PyTuple_CheckExact(names)) {PyErr_SetString(PyExc_TypeError,"model field names must be a tuple");Py_DECREF(names);goto done;}
            result=PyDict_New();
            if (result) for (Py_ssize_t i=0;i<PyTuple_GET_SIZE(names);i++) {
                PyObject *name=PyTuple_GET_ITEM(names,i);
                PyObject *raw=PyObject_GetAttr(value,name),*item=raw ? copy_node(raw,fields,fallback,tuples) : NULL;
                Py_XDECREF(raw);
                int ok=item && PyDict_SetItem(result,name,item)==0;Py_XDECREF(item);
                if (!ok) {Py_CLEAR(result);break;}
            }
            Py_DECREF(names);
        }
        else result=PyObject_CallOneArg(fallback,value);
    }
done:
    Py_LeaveRecursiveCall();return result;
}

static PyObject *snapshot(PyObject *self,PyObject *args) {
    PyObject *value,*fields,*fallback;
    if (!PyArg_ParseTuple(args,"OO!O:snapshot",&value,&PyDict_Type,&fields,&fallback)) return NULL;
    if (!PyCallable_Check(fallback)) {PyErr_SetString(PyExc_TypeError,"fallback must be callable");return NULL;}
    return copy_node(value,fields,fallback,1);
}

static PyObject *detach(PyObject *self,PyObject *args) {
    PyObject *value,*fallback;
    if (!PyArg_ParseTuple(args,"OO:detach",&value,&fallback)) return NULL;
    if (!PyCallable_Check(fallback)) {PyErr_SetString(PyExc_TypeError,"fallback must be callable");return NULL;}
    return copy_node(value,NULL,fallback,0);
}

/* A fast encoder may have broader type support and different NaN semantics.
 * Admit only finite, exact JSON built-ins; all other data keeps stdlib rules.
 * This traversal allocates no containers and calls no user-defined methods. */
static int plain_json(PyObject *value) {
    PyTypeObject *kind=Py_TYPE(value);int result=1;
    if (kind==&PyUnicode_Type || kind==&PyLong_Type || kind==&PyBool_Type || value==Py_None) return 1;
    if (kind==&PyFloat_Type) return Py_IS_FINITE(PyFloat_AS_DOUBLE(value));
    if (!(PyDict_CheckExact(value)||PyList_CheckExact(value)||PyTuple_CheckExact(value))) return 0;
    if (Py_EnterRecursiveCall(" while checking recovery data")) return -1;
    if (PyDict_CheckExact(value)) {
        Py_ssize_t position=0;PyObject *key,*item;
        while (PyDict_Next(value,&position,&key,&item)) {
            if (!PyUnicode_CheckExact(key)) {result=0;break;}
            result=plain_json(item);if (result!=1) break;
        }
    }
    else {
        Py_ssize_t count=PyList_CheckExact(value)?PyList_GET_SIZE(value):PyTuple_GET_SIZE(value);
        for (Py_ssize_t i=0;i<count;i++) {
            PyObject *item=PyList_CheckExact(value)?PyList_GET_ITEM(value,i):PyTuple_GET_ITEM(value,i);
            result=plain_json(item);if (result!=1) break;
        }
    }
    Py_LeaveRecursiveCall();return result;
}

static PyObject *json_tree(PyObject *self,PyObject *value) {
    int result=plain_json(value);
    if (result<0) {
        if (!PyErr_ExceptionMatches(PyExc_RecursionError)) return NULL;
        PyErr_Clear();Py_RETURN_FALSE;
    }
    return PyBool_FromLong(result);
}

/* Certify the unchanged provenance schema for exact built-ins only. Any
 * unsupported/invalid record returns false and keeps the Python validator's
 * original errors and hook order. No record is cached by identity/revision. */
typedef struct {
    PyObject *fields,*kinds,*providers,*changes,*keys,*zero,*one;
} OriginContext;
#define ORIGIN_CAPSULE "shengao.origin-context-v1"

static void origin_free(OriginContext *c) {
    if (!c) return;
    Py_XDECREF(c->fields);Py_XDECREF(c->kinds);Py_XDECREF(c->providers);
    Py_XDECREF(c->changes);Py_XDECREF(c->keys);Py_XDECREF(c->zero);Py_XDECREF(c->one);
    PyMem_Free(c);
}
static void origin_destroy(PyObject *capsule) {
    OriginContext *c=PyCapsule_GetPointer(capsule,ORIGIN_CAPSULE);
    if (!c) {PyErr_Clear();return;}
    origin_free(c);
}
static int plain_choices(PyObject *set) {
    if (!PyFrozenSet_CheckExact(set)) return 0;
    PyObject *iterator=PyObject_GetIter(set),*value;int ok=1;
    if (!iterator) return 0;
    while ((value=PyIter_Next(iterator))) {
        ok=PyUnicode_CheckExact(value);Py_DECREF(value);
        if (!ok) break;
    }
    if (PyErr_Occurred()) ok=0;
    Py_DECREF(iterator);return ok;
}
static PyObject *origin_context(PyObject *self,PyObject *args) {
    PyObject *fields,*kinds,*providers,*changes;
    if (!PyArg_ParseTuple(args,"OOOO:origin_context",&fields,&kinds,&providers,&changes)) return NULL;
    if (!plain_choices(fields)||!plain_choices(kinds)||!plain_choices(providers)||
        !PyTuple_CheckExact(changes)||PyTuple_GET_SIZE(changes)!=2) goto invalid;
    OriginContext *c=PyMem_Calloc(1,sizeof(OriginContext));
    if (!c) return PyErr_NoMemory();
    c->fields=Py_NewRef(fields);c->kinds=Py_NewRef(kinds);c->providers=Py_NewRef(providers);c->changes=Py_NewRef(changes);
    c->keys=Py_BuildValue("(sssssssss)","version","kind","provider","method","reference","current","reading","parent_kinds","operations");
    c->zero=PyLong_FromLong(0);c->one=PyLong_FromLong(1);
    if (!c->keys||!c->zero||!c->one) {origin_free(c);return NULL;}
    int valid=PySet_Size(fields)==9;
    for (Py_ssize_t i=0;valid && i<9;i++) valid=PySet_Contains(fields,PyTuple_GET_ITEM(c->keys,i))==1;
    for (Py_ssize_t i=0;valid && i<2;i++) {
        PyObject *pair=PyTuple_GET_ITEM(changes,i);
        valid=PyTuple_CheckExact(pair)&&PyTuple_GET_SIZE(pair)==2;
        if (valid) valid=PyUnicode_CheckExact(PyTuple_GET_ITEM(pair,0))&&plain_choices(PyTuple_GET_ITEM(pair,1));
        if (valid) valid=PyObject_RichCompareBool(PyTuple_GET_ITEM(pair,0),PyTuple_GET_ITEM(c->keys,7+i),Py_EQ)==1;
    }
    if (!valid||PyErr_Occurred()) {origin_free(c);goto invalid;}
    PyObject *capsule=PyCapsule_New(c,ORIGIN_CAPSULE,origin_destroy);
    if (!capsule) origin_free(c);
    return capsule;
invalid:
    if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError,"unsupported provenance schema contract");
    return NULL;
}

static int origin_pair(PyObject *value,PyObject *zero) {
    if (!value||!PyList_CheckExact(value)||PyList_GET_SIZE(value)!=2) return 0;
    PyObject *a=PyList_GET_ITEM(value,0),*b=PyList_GET_ITEM(value,1);
    if (!PyLong_CheckExact(a)||!PyLong_CheckExact(b)) return 0;
    return PyObject_RichCompareBool(zero,a,Py_LE)==1 && PyObject_RichCompareBool(a,b,Py_LE)==1;
}
static int certify_origin(OriginContext *c,PyObject *value) {
    if (!PyDict_CheckExact(value)) return 0;
    if (!PyDict_Size(value)) return 1;
    Py_ssize_t pos=0;PyObject *key,*item;
    while (PyDict_Next(value,&pos,&key,&item))
        if (!PyUnicode_CheckExact(key)||PySet_Contains(c->fields,key)!=1) return 0;
    PyObject *version=PyDict_GetItemWithError(value,PyTuple_GET_ITEM(c->keys,0));
    if (!version||!PyLong_CheckExact(version)||PyObject_RichCompareBool(version,c->one,Py_EQ)!=1) return 0;
    for (Py_ssize_t i=1;i<=2;i++) {
        item=PyDict_GetItemWithError(value,PyTuple_GET_ITEM(c->keys,i));
        if (!item||!PyUnicode_CheckExact(item)||PySet_Contains(i==1?c->kinds:c->providers,item)!=1) return 0;
    }
    item=PyDict_GetItemWithError(value,PyTuple_GET_ITEM(c->keys,3));
    if (!item||!PyUnicode_CheckExact(item)||PyUnicode_GET_LENGTH(item)>80) return 0;
    for (Py_ssize_t i=4;i<=5;i++)
        if (!origin_pair(PyDict_GetItemWithError(value,PyTuple_GET_ITEM(c->keys,i)),c->zero)) return 0;
    item=PyDict_GetItemWithError(value,PyTuple_GET_ITEM(c->keys,6));
    if (item&&(!PyUnicode_CheckExact(item)||PyUnicode_GET_LENGTH(item)>20000)) return 0;
    for (Py_ssize_t i=0;i<2;i++) {
        PyObject *pair=PyTuple_GET_ITEM(c->changes,i),*choices=PyTuple_GET_ITEM(pair,1);
        item=PyDict_GetItemWithError(value,PyTuple_GET_ITEM(pair,0));
        if (!item) continue;
        if (!PyList_CheckExact(item)||PyList_GET_SIZE(item)>PySet_Size(choices)) return 0;
        for (Py_ssize_t a=0;a<PyList_GET_SIZE(item);a++) {
            PyObject *entry=PyList_GET_ITEM(item,a);
            if (!PyUnicode_CheckExact(entry)||PySet_Contains(choices,entry)!=1) return 0;
            for (Py_ssize_t b=0;b<a;b++)
                if (PyObject_RichCompareBool(entry,PyList_GET_ITEM(item,b),Py_EQ)!=0) return 0;
        }
    }
    return 1;
}
static PyObject *origin_valid(PyObject *self,PyObject *args) {
    PyObject *capsule,*value;
    if (!PyArg_ParseTuple(args,"OO:origin_valid",&capsule,&value)) return NULL;
    OriginContext *c=PyCapsule_GetPointer(capsule,ORIGIN_CAPSULE);
    if (!c) return NULL;
    int result=certify_origin(c,value);
    if (PyErr_Occurred()) return NULL;
    return PyBool_FromLong(result);
}

/* Collect exactly the legacy [line, *units, *highlights] order before testing
 * any value's truth. Strong references keep that list stable even when an
 * uncommon __bool__ changes one of the copied containers. */
static PyObject *clean_lyric(PyObject *self,PyObject *args) {
    PyObject *value,*keys,*units=NULL,*nodes=NULL,*iterator=NULL,*unit=NULL;
    if (!PyArg_ParseTuple(args,"OO!:clean_lyric",&value,&PyTuple_Type,&keys)) return NULL;
    if (PyTuple_GET_SIZE(keys)!=3) {PyErr_SetString(PyExc_TypeError,"three legacy keys are required");return NULL;}
    for (Py_ssize_t i=0;i<3;i++) if (!PyUnicode_CheckExact(PyTuple_GET_ITEM(keys,i))) {
        PyErr_SetString(PyExc_TypeError,"legacy keys must be plain strings");return NULL;
    }
    if (!PyDict_CheckExact(value)) Py_RETURN_FALSE;
    PyObject *raw_units=PyDict_GetItemString(value,"units");
    if (!raw_units) {if (PyErr_Occurred()) return NULL;Py_RETURN_FALSE;}
    if (!(PyList_CheckExact(raw_units)||PyTuple_CheckExact(raw_units))) Py_RETURN_FALSE;
    units=Py_NewRef(raw_units);
    nodes=PyList_New(0);
    if (!nodes || PyList_Append(nodes,value)<0) goto error;
    iterator=PyObject_GetIter(units);
    if (!iterator) goto error;
    while ((unit=PyIter_Next(iterator))) {
        int exact=PyDict_CheckExact(unit),ok=exact && PyList_Append(nodes,unit)==0;
        Py_DECREF(unit);unit=NULL;
        if (!exact) goto fallback;
        if (!ok) goto error;
    }
    if (PyErr_Occurred()) goto error;
    Py_CLEAR(iterator);Py_CLEAR(units);
    Py_ssize_t unit_count=PyList_GET_SIZE(nodes);
    for (Py_ssize_t i=1;i<unit_count;i++) {
        PyObject *highlights=PyDict_GetItemString(PyList_GET_ITEM(nodes,i),"highlights");
        if (!highlights) {if (PyErr_Occurred()) goto error;goto fallback;}
        if (!(PyList_CheckExact(highlights)||PyTuple_CheckExact(highlights))) goto fallback;
        Py_INCREF(highlights);iterator=PyObject_GetIter(highlights);Py_DECREF(highlights);
        if (!iterator) goto error;
        while ((unit=PyIter_Next(iterator))) {
            int exact=PyDict_CheckExact(unit),ok=exact && PyList_Append(nodes,unit)==0;
            Py_DECREF(unit);unit=NULL;
            if (!exact) goto fallback;
            if (!ok) goto error;
        }
        if (PyErr_Occurred()) goto error;
        Py_CLEAR(iterator);
    }
    for (Py_ssize_t i=0;i<PyList_GET_SIZE(nodes);i++) {
        PyObject *node=PyList_GET_ITEM(nodes,i);
        for (Py_ssize_t k=0;k<3;k++) {
            PyObject *key=PyTuple_GET_ITEM(keys,k),*item=PyDict_GetItemWithError(node,key);
            if (!item) {if (PyErr_Occurred()) goto error;continue;}
            Py_INCREF(item);int truth=PyObject_IsTrue(item);Py_DECREF(item);
            if (truth<0) goto error;
            if (!truth && PyDict_DelItem(node,key)<0) {
                if (k==0 && PyErr_ExceptionMatches(PyExc_KeyError)) PyErr_Clear();
                else goto error;
            }
        }
    }
    Py_DECREF(nodes);Py_RETURN_TRUE;
fallback:
    Py_XDECREF(units);Py_XDECREF(iterator);Py_XDECREF(nodes);Py_RETURN_FALSE;
error:
    Py_XDECREF(units);Py_XDECREF(unit);Py_XDECREF(iterator);Py_XDECREF(nodes);return NULL;
}

static PyMethodDef methods[]={
    {"snapshot",snapshot,METH_VARARGS,"Copy known models with the canonical field order."},
    {"detach",detach,METH_VARARGS,"Copy plain containers, delegating uncommon values."},
    {"clean_lyric",clean_lyric,METH_VARARGS,"Apply legacy omission only to the original lyric nodes."},
    {"json_tree",json_tree,METH_O,"Admit only finite plain JSON data, without executing hooks."},
    {"origin_context",origin_context,METH_VARARGS,"Prepare an immutable provenance schema contract."},
    {"origin_valid",origin_valid,METH_VARARGS,"Certify exact built-ins; unsupported records keep Python validation."},
    {NULL,NULL,0,NULL}
};
static struct PyModuleDef definition={PyModuleDef_HEAD_INIT,"_shengao_snapshot",NULL,-1,methods};
PyMODINIT_FUNC PyInit__shengao_snapshot(void) {
    PyObject *module=PyModule_Create(&definition);
    if (!module) return NULL;
    if (PyModule_AddStringConstant(module,"source_sha256",SG_SNAPSHOT_SOURCE_SHA256)<0 ||
        PyModule_AddStringConstant(module,"python_abi","cp312")<0) {Py_DECREF(module);return NULL;}
    return module;
}
