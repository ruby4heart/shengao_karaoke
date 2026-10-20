"""Inspect all packaged PE imports/exports, including same-name DLL collisions."""
from pathlib import Path
import argparse
import json
import os
import pefile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--package',type=Path,default=ROOT/'build/desktop-dist/shengao-karaoke');args=parser.parse_args();package=args.package.resolve()
assert package.is_relative_to(ROOT)
system=Path(os.environ['WINDIR'])/'System32'
paths=[p for p in package.rglob('*') if p.suffix.lower() in {'.exe','.dll','.pyd'}]
names={}
for path in paths:names.setdefault(path.name.lower(),[]).append(path)
exports={};missing=[];binary_records=[]
def read(path):
    # QtGui exports more symbols than pefile's normal 8192-symbol safety cap.
    pe=pefile.PE(str(path),fast_load=True,max_symbol_exports=100000)
    pe.parse_data_directories(directories=[0,1,13])
    return pe
def symbols(path):
    key=str(path).casefold()
    if key not in exports:
        pe=read(path);values=getattr(getattr(pe,'DIRECTORY_ENTRY_EXPORT',None),'symbols',[])
        exports[key]=({s.name for s in values if s.name},{s.ordinal for s in values});pe.close()
    return exports[key]
main=read(package/'shengao-karaoke.exe');main.parse_data_directories(directories=[2]);common_controls_v6=False
for resource in getattr(main,'DIRECTORY_ENTRY_RESOURCE',()).entries:
    if resource.id==24:
        for name in resource.directory.entries:
            for language in name.directory.entries:
                value=language.data.struct;manifest=ET.fromstring(main.get_data(value.OffsetToData,value.Size))
                common_controls_v6=any(node.attrib.get('name')=='Microsoft.Windows.Common-Controls' and node.attrib.get('version')=='6.0.0.0' and node.attrib.get('publicKeyToken')=='6595b64144ccf1df' for node in manifest.iter())
main.close()
# The executable's activation context redirects common-controls v6 to WinSxS.
# System32/comctl32.dll is v5 and intentionally lacks LoadIconMetric (ordinal
# 380). Verify the actual v6 export rather than ignoring an unresolved symbol.
sxs=sorted((system.parent/'WinSxS').glob('amd64_microsoft.windows.common-controls_6595b64144ccf1df_6.*/comctl32.dll'),key=lambda p:tuple(int(x) for x in p.parent.name.split('_')[3].split('.')),reverse=True) if common_controls_v6 else []
for path in paths:
    pe=read(path);assert pe.FILE_HEADER.Machine==0x8664,path
    records=[]
    for item in list(getattr(pe,'DIRECTORY_ENTRY_IMPORT',[]))+list(getattr(pe,'DIRECTORY_ENTRY_DELAY_IMPORT',[])):
        name=item.dll.decode().lower()
        if name.startswith(('api-ms-','ext-ms-')):continue
        local=next((p for p in [path.parent/name,package/name,package/'_internal'/name] if p.is_file()),None)
        if local is None:local=next(iter(names.get(name,[])),None)
        dependency=local or (system/name if (system/name).is_file() else None)
        redirected=name=='comctl32.dll' and bool(sxs)
        if redirected:dependency=sxs[0];local=None
        if dependency is None:missing.append({'binary':path.relative_to(package).as_posix(),'dll':name});continue
        named,ordinals=symbols(dependency)
        for symbol in item.imports:
            if symbol.name is not None and symbol.name not in named:missing.append({'binary':path.relative_to(package).as_posix(),'dll':name,'symbol':symbol.name.decode(errors='replace')})
            elif symbol.name is None and symbol.ordinal not in ordinals:missing.append({'binary':path.relative_to(package).as_posix(),'dll':name,'ordinal':symbol.ordinal})
        records.append({'dll':name,'source':'Windows WinSxS common-controls v6' if redirected else 'package' if local else 'Windows System32'})
    binary_records.append({'path':path.relative_to(package).as_posix(),'dependencies':records});pe.close()
record={'passed':not missing,'binaries':len(paths),'missing':missing,'imports':binary_records}
(ROOT/'build/desktop-dependencies.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
assert not missing,missing[:20]
print(json.dumps({'passed':True,'binaries':len(paths),'report':str(ROOT/'build/desktop-dependencies.json')}))
