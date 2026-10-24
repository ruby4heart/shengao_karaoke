"""Export a small public proof set without private projects, caches or MV frames."""
from pathlib import Path
import argparse
import json
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--version',required=True);p.add_argument('--tag',required=True);args=p.parse_args()
assert re.fullmatch(r'\d+\.\d+\.\d+',args.version) and re.fullmatch(r'v\d+',args.tag)
base=ROOT/'build'/(args.tag+'-evidence');audit=base/('desktop-final-audit-'+args.tag+'.json')
value=json.loads(audit.read_text(encoding='utf-8'));assert value['passed'] and value['version']==args.version
target=ROOT/'dist'/f'ShengaoKaraoke-{args.version}-evidence.zip';assert not target.exists(),'Keep prior public archives'
files=[audit,base/'README.txt',base/('SHA256SUMS-'+args.version+'.txt')]
for label in ['development','standalone-normal','standalone-dpi150']:
    folder=base/label
    for name in ['report.json','acoustic-human-reference.json','staged-acoustic-reference.json','timing-provenance-audit.json','sound-gap-audit.json','sequence-match-audit.json','chorus-reuse-audit.json','color-state-audit.json','guided-alignment-audit.json','vocal-ab-state.json','native-slot-audit.json']:
        path=folder/name
        if path.is_file():files.append(path)
for label in ['timeline-full-pixels','timeline-full-pixels-dpi150']:
    folder=base/label;files.append(folder/'report.json');files.extend(folder.glob('*.png'))
formal=base/'formal-song/report.json'
if formal.is_file():files.append(formal)
gaps=base/'formal-song/sound-gap-report.json'
if gaps.is_file():files.append(gaps)
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for path in files:archive.write(path,path.relative_to(base).as_posix())
    archive.writestr('PUBLIC-NOTES.txt','Public verification subset. No private project, task cache, user MV frame or original media. Full local acceptance remains in build/'+args.tag+'-evidence. Public PJS reference attribution and licenses are in the source distribution.\n')
with zipfile.ZipFile(target) as archive:assert archive.testzip() is None
print(json.dumps({'archive':str(target),'evidence_files':len(files)},ensure_ascii=False))
