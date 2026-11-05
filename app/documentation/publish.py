"""Stage the complete CyDoc reader, and only that reader, for GitHub Pages."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import tempfile

APP=Path(__file__).resolve().parents[1]
ROOT=APP.parent
REQUIRED={'index.html','data.js','viewer.js','viewer.css','manifest.json','CyDoc-MIT.txt'}
SUFFIXES={'.html','.js','.css','.json','.svg','.png','.jpg','.jpeg','.webp','.gif','.glb','.gltf','.bin','.mp4','.webm','.ogg','.wav','.txt','.ico','.woff','.woff2'}


def validate_export(source):
    files={p.relative_to(source).as_posix():p for p in source.rglob('*') if p.is_file()}
    if not REQUIRED<=files.keys():raise ValueError('Incomplete CyDoc export: '+str(REQUIRED-files.keys()))
    for name,path in files.items():
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):raise ValueError('Documentation must not contain links: '+name)
        if path.suffix.lower() not in SUFFIXES or any(part.startswith('.') for part in Path(name).parts):raise ValueError('Unexpected reader file: '+name)
    manifest=json.loads((source/'manifest.json').read_text('utf-8'))
    if manifest.get('schemaVersion')!=1 or not manifest.get('pages'):raise ValueError('Invalid documentation manifest')
    html=(source/'index.html').read_text('utf-8')
    for target in re.findall(r'(?:src|href)="([^"]+)"',html):
        if target.startswith(('#','data:')):continue
        if target not in files:raise ValueError('Missing local reader resource: '+target)
    modules=json.loads((source/'help-map.json').read_text('utf-8'))['modules']
    for module in modules:
        if 'media-'+module+'.js' not in files:raise ValueError('Missing module: '+module)
    if ('mesh' in modules)!=('media-mesh.js' in files):raise ValueError('Mesh module selection mismatch')
    return files,manifest


def stage(output):
    source=APP/'help'
    files,manifest=validate_export(source)
    # This is a fixed generated output, never a selectable application data directory.
    output=output.resolve()
    if output.parent!=ROOT.resolve() or output.name!='_site':raise ValueError('Pages output must be the application root / _site')
    marker='.cydoc-pages-export'
    if output.exists() and not (output/marker).is_file():raise ValueError('Refusing to replace an unrecognized output directory')
    previous=ROOT/'_site.previous'
    if previous.exists():raise ValueError('Inspect the previous Pages staging directory before continuing')
    staging=Path(tempfile.mkdtemp(prefix='_pages-stage-',dir=ROOT))
    try:
        for name,path in files.items():
            target=staging/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(path.read_bytes()).digest():raise ValueError('Copy mismatch: '+name)
        (staging/'.nojekyll').write_text('',encoding='utf-8')
        (staging/marker).write_text(json.dumps({'name':manifest['name'],'schemaVersion':1}),encoding='utf-8')
        if output.exists():output.rename(previous)
        try:staging.rename(output)
        except BaseException:
            if previous.exists():previous.rename(output)
            raise
        if previous.exists():
            assert previous.resolve().parent==ROOT.resolve() and previous.name=='_site.previous'
            shutil.rmtree(previous)
        return {'name':manifest['name'],'files':len(files),'pages':len(manifest['pages']),'output':'_site'}
    finally:
        if staging.exists():
            assert staging.resolve().parent==ROOT.resolve() and staging.name.startswith('_pages-stage-')
            shutil.rmtree(staging)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'_site')
    args=parser.parse_args()
    print(json.dumps(stage(args.output)))
