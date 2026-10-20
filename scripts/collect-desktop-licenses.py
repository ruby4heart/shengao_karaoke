"""Collect installed package notices and official Qt/GNU license documents."""
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path
import hashlib
import html
import json
import re
import shutil
import urllib.parse
import urllib.request

root=Path(__file__).resolve().parents[1];target=root/'desktop'/'assets'/'licenses';target.mkdir(parents=True,exist_ok=True)
original=target/'Original-Audio';original.mkdir(exist_ok=True);original_records=[]
for relative in ['src/audio_display.cpp','libaegisub/audio/provider_convert.cpp']:
    path=root/'vendor/aegisub'/relative;text=path.read_text(encoding='utf-8');name=path.stem+'-NOTICE.txt'
    (original/name).write_text(text[:text.index('#include')],encoding='utf-8')
    original_records.append({'source':'vendor/aegisub/'+relative,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'notice':name})
path=root/'vendor/aegisub/subprojects/wxWidgets/docs/licence.txt';(original/'wxWidgets-LICENSE.txt').write_bytes(path.read_bytes())
original_records.append({'source':'vendor/aegisub/subprojects/wxWidgets/docs/licence.txt','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'notice':'wxWidgets-LICENSE.txt'})
(original/'SOURCES.json').write_text(json.dumps(original_records,indent=2),encoding='utf-8')
names=['PySide6','PySide6_Essentials','PySide6_Addons','shiboken6','numpy','fonttools','Pillow','Janome',
       'aiohttp','aiohappyeyeballs','aiosignal','attrs','frozenlist','multidict','propcache','yarl','idna',
       'RapidFuzz','packaging','PyInstaller','pyinstaller-hooks-contrib']
packages=[]
for name in names:
    dist=metadata.distribution(name);packages.append({'name':dist.metadata['Name'],'version':dist.version,
        'license':dist.metadata.get('License-Expression') or dist.metadata.get('License',''),
        'upstream':dist.metadata.get_all('Project-URL',[])})
    for entry in dist.files or []:
        text=str(entry);lower=text.lower()
        if ('license' in lower or 'copying' in lower or 'notice' in lower) and not text.endswith(('.py','.pyc','.pyd')):
            source=Path(dist.locate_file(entry))
            if not source.is_file():continue
            relative=Path(*[part for part in Path(text).parts if part not in ('..','.','')])
            destination=target/'python'/dist.metadata['Name']/relative
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)

records=[]
def fetch(url,dest):
    dest=target/dest;dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists():
        request=urllib.request.Request(url,headers={'User-Agent':'ShengaoStudio-SourceBuilder/0.8'})
        with urllib.request.urlopen(request,timeout=45) as response:data=response.read()
        dest.write_bytes(data)
    return {'file':str(dest.relative_to(target)).replace('\\','/'),'url':url,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}

for name,url in [('LGPL-3.0.txt','https://www.gnu.org/licenses/lgpl-3.0.txt'),('GPL-3.0.txt','https://www.gnu.org/licenses/gpl-3.0.txt'),('GPL-2.0.txt','https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt')]:
    records.append(fetch(url,'Qt/'+name))
index_url='https://doc.qt.io/qt-6/licenses-used-in-qt.html'
records.append(fetch(index_url,'Qt/third-party-index.html'))
index=(target/'Qt'/'third-party-index.html').read_text(encoding='utf-8')
modules={'Qt Core','Qt GUI','Qt Network','Qt Multimedia','Qt Image Formats','Qt SVG','Qt Widgets','Qt Test','Qt OpenGL','Qt OpenGL Widgets'}
tasks=[]
for match in re.finditer(r'<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|\Z)',index,re.S):
    heading=html.unescape(re.sub('<[^>]+>','',match[1])).strip()
    if heading not in modules:continue
    for href in re.findall(r'href="([^"]+)"',match[2]):
        if '-attribution-' in href:
            url=urllib.parse.urljoin(index_url,href);tasks.append((url,'Qt/attributions/'+Path(urllib.parse.urlparse(url).path).name))
with ThreadPoolExecutor(max_workers=6) as pool:
    for item in pool.map(lambda args:fetch(*args),tasks):records.append(item)
(target/'SOURCES.json').write_text(json.dumps({'packages':packages,'documents':records},ensure_ascii=False,indent=2),encoding='utf-8')
(target/'Qt'/'SOURCE-CODE.txt').write_text(
 'Qt / PySide / Shiboken 6.12.0 are dynamically linked and unmodified.\n'
 'Official corresponding source repositories:\nhttps://code.qt.io/cgit/qt/qtbase.git/?h=v6.12.0\n'
 'https://code.qt.io/cgit/qt/qtmultimedia.git/?h=v6.12.0\n'
 'https://code.qt.io/cgit/qt/qtimageformats.git/?h=v6.12.0\n'
 'https://code.qt.io/cgit/qt/qtsvg.git/?h=v6.12.0\n'
 'https://code.qt.io/cgit/pyside/pyside-setup.git/?h=v6.12.0\n'
 'https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/\n'
 'The application does not prohibit replacement of these dynamic libraries or debugging modifications to them.\n',encoding='utf-8')
print(json.dumps({'packages':len(packages),'documents':len(records),'license_files':sum(p.is_file() for p in target.rglob('*'))}))
