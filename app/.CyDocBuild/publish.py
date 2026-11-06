"""Stage only the generated reader for Pages; this command never publishes it."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,tempfile
HERE=Path(__file__).resolve().parent;APP=HERE.parent;ROOT=APP.parent
REQUIRED={'Documentation.html','DocAI.md','DocData/data.js','DocData/viewer.js','DocData/viewer.css','DocData/manifest.json','DocData/help-map.json','DocData/CyDoc-MIT.txt'}
SUFFIXES={'.html','.md','.js','.css','.json','.svg','.png','.jpg','.jpeg','.webp','.gif','.glb','.gltf','.bin','.mp4','.webm','.ogg','.wav','.txt','.ico','.woff','.woff2'}
def validate_export(source):
 entries=list(source.rglob('*'))
 for path in entries:
  if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):raise ValueError('Documentation must contain ordinary local files only')
 files={p.relative_to(source).as_posix():p for p in entries if p.is_file()}
 if not REQUIRED<=files.keys():raise ValueError('Incomplete CyDoc export: '+str(REQUIRED-files.keys()))
 for name,path in files.items():
  if path.suffix.lower() not in SUFFIXES or any(part.startswith('.') for part in Path(name).parts):raise ValueError('Unexpected reader file: '+name)
  if path.suffix.lower()=='.md' and name!='DocAI.md':raise ValueError('Authoring Markdown in the delivered reader')
 manifest=json.loads((source/'DocData/manifest.json').read_text('utf-8'))
 if manifest.get('defaultLocale')!='en' or {x['code'] for x in manifest['locales']}!={'en','fr'}:raise ValueError('Complete English and French manuals are required')
 if any(p.get('kind')=='source' for p in manifest['pages']):raise ValueError('Raw implementations cannot be published')
 html=(source/'Documentation.html').read_text('utf-8')
 for target in re.findall(r'(?:src|href)="([^"]+)"',html):
  if target.startswith(('#','data:')):continue
  if target not in files:raise ValueError('Missing local reader resource: '+target)
 return files,manifest
def stage(output):
 files,manifest=validate_export(APP/'Documentation');output=output.resolve()
 if output.parent!=ROOT.resolve() or output.name!='_site':raise ValueError('Pages output must be the application root / _site')
 if output.exists() and not (output/'.cydoc-pages-export').is_file():raise ValueError('Refusing to replace an unrecognized output')
 previous=ROOT/'_site.previous'
 if previous.exists():raise ValueError('Inspect the previous Pages staging directory first')
 staging=Path(tempfile.mkdtemp(prefix='_pages-stage-',dir=ROOT))
 try:
  for name,path in files.items():
   target=staging/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
   if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(path.read_bytes()).digest():raise ValueError('Reader copy mismatch')
  # Keep existing project Pages addresses while opening the same direct reader.
  shutil.copy2(staging/'Documentation.html',staging/'index.html')
  (staging/'.nojekyll').write_text('',encoding='utf-8')
  (staging/'.cydoc-pages-export').write_text(json.dumps({'name':manifest['name'],'schemaVersion':2}),encoding='utf-8')
  if output.exists():output.rename(previous)
  try:staging.rename(output)
  except BaseException:
   if previous.exists():previous.rename(output)
   raise
  if previous.exists():
   assert previous.resolve().parent==ROOT.resolve() and previous.name=='_site.previous';shutil.rmtree(previous)
  return {'files':len(files),'pages':len(manifest['pages']),'output':'_site'}
 finally:
  if staging.exists():
   assert staging.resolve().parent==ROOT.resolve() and staging.name.startswith('_pages-stage-');shutil.rmtree(staging)
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'_site');args=parser.parse_args();print(json.dumps(stage(args.output)))
