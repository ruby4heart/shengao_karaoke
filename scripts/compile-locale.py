"""Compile the bundled gettext catalogs without an external gettext install."""
import ast
import gettext
from pathlib import Path
import re
import struct
import sys


def compile_catalog(source,destination):
    messages={}
    item={};active=None;fuzzy=False
    def flush():
        nonlocal item,active,fuzzy
        if 'msgid' in item and not fuzzy:
            key=item['msgid']
            if 'msgctxt' in item:
                key=item['msgctxt']+'\x04'+key
            if 'msgid_plural' in item:
                key+='\0'+item['msgid_plural']
                value='\0'.join(item[k] for k in sorted(item) if k.startswith('msgstr['))
            else:
                value=item.get('msgstr','')
            if value:
                messages[key.encode('utf-8')]=value.encode('utf-8')
        item={};active=None;fuzzy=False
    for raw in Path(source).read_text(encoding='utf-8-sig').splitlines()+['']:
        value=raw.strip()
        if not value:
            flush()
        elif value.startswith('#,'):
            fuzzy='fuzzy' in value
        elif value.startswith('#'):
            continue
        elif value.startswith('"'):
            if active is None:
                raise ValueError('Orphan gettext continuation')
            item[active]+=ast.literal_eval(value)
        else:
            match=re.fullmatch(r'(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+(".*")',value)
            if not match:
                raise ValueError('Invalid gettext directive: '+value)
            active=match[1];item[active]=ast.literal_eval(match[2])
    keys=sorted(messages);ids=b'';strings=b'';originals=[];translations=[]
    base=28+len(keys)*16
    for key in keys:
        originals.extend((len(key),base+len(ids)));ids+=key+b'\0'
    for key in keys:
        translated=messages[key]
        translations.extend((len(translated),base+len(ids)+len(strings)));strings+=translated+b'\0'
    header=struct.pack('<7I',0x950412de,0,len(keys),28,28+len(keys)*8,0,0)
    output=Path(destination);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(header+struct.pack('<'+'I'*(len(keys)*4),*(originals+translations))+ids+strings)
    with output.open('rb') as stream:
        catalog=gettext.GNUTranslations(stream)
    return len(catalog._catalog)


if __name__=='__main__':
    print(compile_catalog(sys.argv[1],sys.argv[2]),'messages compiled')
