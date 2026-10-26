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
