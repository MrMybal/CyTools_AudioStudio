"""Build the application-owned English/French CyDoc manual (Node.js is build-only)."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,sys,tempfile
HERE=Path(__file__).resolve().parent
APP=HERE.parent
ROOT=APP.parent
OUTPUT=APP/'Documentation'

def load(path):return json.loads(path.read_text('utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def package(install):
 expected=load(HERE/'cydoc-source.json')
 archive=HERE/'vendor/cydoc-0.1.0.tgz'
 if sha(archive)!=expected['packageSha256']:raise RuntimeError('CyDoc archive digest mismatch')
 if install:
  npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
  if not npm:raise RuntimeError('Node.js 22+ and npm are required only for documentation generation')
  subprocess.run([npm,'ci','--no-audit','--no-fund'],cwd=HERE,check=True)
 result=HERE/'node_modules/cydoc'
 if not (result/'tools/cli.mjs').is_file():raise RuntimeError('Build tool missing; run this script with --install')
 return result
def validate_sources():
 # Keep stale French translations and future scaffolding out of every distribution.
 en={p.name:p for p in (HERE/'manual/en').glob('*.md')}
 fr={p.name:p for p in (HERE/'manual/fr').glob('*.md')}
 if en.keys()!=fr.keys():raise RuntimeError('English and French page sets differ')
 for name,original in en.items():
  first=original.read_text('utf-8');second=fr[name].read_text('utf-8')
  a=re.findall(r'\{#([\w-]+)\}',first);b=re.findall(r'\{#([\w-]+)\}',second)
  if a!=b:raise RuntimeError('Translation anchors differ: '+name)
  revision=re.search(r'^revision: (.+)$',first,re.M)
  source=re.search(r'^sourceRevision: (.+)$',second,re.M)
  if not revision or not source or revision[1]!=source[1]:raise RuntimeError('French translation is stale: '+name)
  content=first.split('\n---\n\n',1)
  if len(content)!=2 or hashlib.sha256(content[1].encode('utf-8')).hexdigest()[:16]!=revision[1]:raise RuntimeError('English revision must be refreshed: '+name)
  for text in (first,second):
   if re.search(r'Read this section in French|Read the complete original|English translation has not been supplied|⟦T[0-9a-f]+⟧|ZXQ\d{4}',text):raise RuntimeError('Unfinished document: '+name)
 if not en:raise RuntimeError('The manual is empty')
def generate(check=False,install=False):
 validate_sources();pkg=package(install);node=shutil.which('node')
 if not node:raise RuntimeError('Node.js 22+ is required only to build documentation')
 if int(subprocess.check_output([node,'--version'],text=True).strip().lstrip('v').split('.')[0])<22:raise RuntimeError('Node.js 22+ required')
 stage=APP/'.CyDocExport';previous=APP/'.CyDocExport.previous'
 if stage.exists() or previous.exists():raise RuntimeError('Inspect an unfinished documentation staging directory before retrying')
 config=load(HERE/'cydoc.config.json');config['out']='../.CyDocExport'
 temp=HERE/'cydoc.active.json';temp.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
 try:
  subprocess.run([node,str(pkg/'tools/cli.mjs'),'check' if check else 'build',str(temp)],cwd=HERE,check=True)
  manifest=load(stage/'DocData/manifest.json')
  if {l['code'] for l in manifest['locales']}!={'en','fr'}:raise RuntimeError('Both complete languages must be published')
  if any(p.get('kind')=='source' or p['id'].startswith(('source-','reference-licences-','migration-','translation-report')) for p in manifest['pages']):raise RuntimeError('Internal or implementation content in the human manual')
  migration=load(HERE/'routing.json')
  catalogue={'schemaVersion':2,'legacyPaths':migration['legacyPaths'],'aliases':manifest.get('aliases',{}),'pages':{p['id']:{'headings':[h['id'] for h in p.get('headings',[])],'locale':p['locale']} for p in manifest['pages']},'modules':config.get('modules',[])}
  (stage/'DocData/help-map.json').write_text(json.dumps(catalogue,ensure_ascii=False,indent=2),encoding='utf-8')
  # Host instructions are authored separately; never imported by the human reader.
  ai=HERE/'assistant.md'
  if ai.exists():
   sidecar=stage/'DocAI.md';sidecar.write_text(sidecar.read_text('utf-8')+'\n\n'+ai.read_text('utf-8'),encoding='utf-8')
  shutil.copy2(HERE/'CyDoc-MIT.txt',stage/'DocData/CyDoc-MIT.txt')
  if OUTPUT.is_symlink():raise RuntimeError('Refusing a symbolic documentation destination')
  if OUTPUT.exists() and not (OUTPUT/'Documentation.html').is_file():raise RuntimeError('Unrecognized documentation destination; inspect before replacing')
  if OUTPUT.exists():OUTPUT.rename(previous)
  try:stage.rename(OUTPUT)
  except BaseException:
   if previous.exists():previous.rename(OUTPUT)
   raise
  if previous.exists():
   assert previous.resolve().parent==APP.resolve() and previous.name=='.CyDocExport.previous'
   shutil.rmtree(previous)
  # Preserve existing local bookmarks without keeping a second reader or old data.
  legacy=APP/'help';legacy.mkdir(exist_ok=True)
  (legacy/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Documentation</title><script>location.replace("../Documentation/Documentation.html"+location.search+location.hash)</script><a href="../Documentation/Documentation.html">Open documentation / Ouvrir la documentation</a></html>\n',encoding='utf-8')
  return {'name':config['name'],'pages':len(manifest['pages']),'locales':['en','fr'],'modules':config.get('modules',[]),'entry':'app/Documentation/Documentation.html'}
 finally:
  temp.unlink(missing_ok=True)
  if stage.exists():
   assert stage.resolve().parent==APP.resolve() and stage.name=='.CyDocExport'
   shutil.rmtree(stage)
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--install',action='store_true');parser.add_argument('--check',action='store_true')
 args=parser.parse_args();print(json.dumps(generate(args.check,args.install)))
