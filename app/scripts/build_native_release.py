"""Build a Windows release from committed product sources and the tested base dependencies.

Run with the product's private Python: app/scripts/build_native_release.py.
Models, GPU engines, user data and developer environments are never copied.
"""
import argparse,hashlib,io,json,os,re,shutil,subprocess,sys,tarfile,urllib.request,zipfile
from pathlib import Path
try:
 from packaging.requirements import Requirement
 from packaging.utils import canonicalize_name
except ImportError:
 from pip._vendor.packaging.requirements import Requirement
 from pip._vendor.packaging.utils import canonicalize_name
APP=Path(__file__).resolve().parents[1];ROOT=APP.parent;NAME=ROOT.name
SKIP={'.CyDocBuild','.CyDocExport','.CyDocExport.previous','node_modules','__pycache__','.pytest_cache','.git'}
PYTHONS={
 '3.11':('https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip','009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b'),
 '3.12':('https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip','4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3')}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while b:=f.read(1024*1024):h.update(b)
 return h.hexdigest()
def run(args,**kw):return subprocess.run([str(x) for x in args],check=True,**kw)
def git(*args):return subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'-C',str(ROOT),*args])
def included(name):
 parts=Path(name).parts
 if Path(name).name in {'AGENTS.md','CyToolsGuide.md'} or name in {'app/Docs/AgentGuide.md','app/Docs/AgentPrompt.md'}:return False
 return not any(x in SKIP for x in parts) and not name.startswith(('.github/','website/')) and Path(name).suffix not in {'.pyc','.pyo','.obj','.pdb','.log','.tmp','.bak'} and '.env' not in parts

def dependencies(python):
 code='''import importlib.metadata as m,json,sys,sysconfig
from pathlib import Path
site=Path(sysconfig.get_paths()['purelib']).resolve()
rows=[]
for d in m.distributions():
 rows.append({'name':d.metadata['Name'],'version':d.version,'requires':d.requires or [],'license':d.metadata.get('License-Expression') or d.metadata.get('License') or 'See included notices','files':[str(d.locate_file(f).resolve()) for f in d.files or []]})
print(json.dumps({'python':'.'.join(map(str,sys.version_info[:2])),'site':str(site),'distributions':rows}))'''
 raw=json.loads(subprocess.check_output([str(python),'-c',code],cwd=ROOT,text=True,encoding='utf-8'))
 installed={canonicalize_name(d['name']):d for d in raw['distributions']}
 context={'python_version':raw['python'],'python_full_version':raw['python']+'.0','sys_platform':'win32','platform_system':'Windows','platform_machine':'AMD64','extra':''}
 roots=[]
 req=APP/'requirements.txt'
 for line in req.read_text('utf-8').splitlines():
  line=line.split(' #',1)[0].strip()
  if not line or line.startswith(('#','-')):continue
  r=Requirement(line)
  if not r.marker or r.marker.evaluate(context):roots.append(canonicalize_name(r.name))
 # These are application imports formerly supplied accidentally by the Python MCP extra.
 if NAME=='CyTools_AIChat':roots+=['httpx']
 selected={};pending=roots[:]
 while pending:
  key=pending.pop()
  if key in selected or key in {'pytest','mcp'}:continue
  if key not in installed:
   if NAME=='CyTools_Subtitle' and key=='torch':continue # explicit on-demand runtime_components.py
   raise RuntimeError('Base dependency not installed: '+key)
  d=installed[key];selected[key]=d
  for requirement in d['requires']:
   r=Requirement(requirement)
   if not r.marker or r.marker.evaluate(context):pending.append(canonicalize_name(r.name))
 if selected['cytools-core']['version']!='0.11.0':raise RuntimeError('Native Core 0.11.0 required')
 return raw,selected

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--python',type=Path,default=ROOT/'runtime/python/Scripts/python.exe');parser.add_argument('--output',type=Path);parser.add_argument('--allow-dirty',action='store_true');args=parser.parse_args()
 if os.name!='nt':raise SystemExit('This builder validates Windows x64 only')
 if not args.allow_dirty and git('status','--porcelain').strip():raise RuntimeError('Commit and verify the source tree before building')
 version=json.loads((APP/'CyTool.json').read_text('utf-8'))['version'];commit=git('rev-parse','HEAD').decode().strip()
 out=args.output or ROOT/'runtime/build/native-release'/version;out.mkdir(parents=True,exist_ok=True)
 stage=out/(NAME+'-stage')
 if stage.exists():raise RuntimeError('Stage exists; inspect it or choose another output folder')
 stage.mkdir()
 # Only repository-owned files from the selected commit enter the product.
 with tarfile.open(fileobj=io.BytesIO(git('archive','--format=tar','HEAD'))) as archive:
  for member in archive.getmembers():
   if not member.isfile() or not included(member.name):continue
   if not (member.name.startswith(('app/','LICENCES/')) or member.name in {'LICENSE','README.md','README.fr.md','VERSION.md','VERSION.fr.md','LISEZ-MOI.md',NAME+'.sh'}):continue
   target=stage/member.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.extractfile(member).read())
 launcher=ROOT/(NAME+'.exe')
 if not launcher.is_file():raise RuntimeError('Compile app/launcher.cpp before packaging')
 shutil.copy2(launcher,stage/launcher.name)
 runtime=stage/'runtime';scripts=runtime/'python/Scripts';scripts.mkdir(parents=True)
 raw,selected=dependencies(args.python)
 url,digest=PYTHONS[raw['python']];cache=ROOT/'runtime/downloads/native-release';cache.mkdir(parents=True,exist_ok=True);source=cache/url.rsplit('/',1)[-1]
 if not source.is_file():
  with urllib.request.urlopen(url,timeout=60) as res,source.open('wb') as dst:shutil.copyfileobj(res,dst)
 if sha(source)!=digest:raise RuntimeError('Official Python digest mismatch')
 with zipfile.ZipFile(source) as archive:
  for m in archive.infolist():
   if m.is_dir():continue
   target=(scripts/m.filename).resolve()
   if not target.is_relative_to(scripts.resolve()):raise RuntimeError('Unsafe Python archive')
   target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(m))
 pth=next(scripts.glob('python*._pth'));pth.write_text(pth.stem+'.zip\n.\n../Lib/site-packages\n../../../app\nimport site\n',encoding='ascii')
 site=runtime/'python/Lib/site-packages';site.mkdir(parents=True)
 (scripts/'sitecustomize.py').write_text('import site, sys\nfrom pathlib import Path\nsys.dont_write_bytecode = True\nsite.addsitedir(str(Path(__file__).resolve().parent.parent / \'Lib/site-packages\'))\n',encoding='utf-8')
 oldsite=Path(raw['site']);notices=[]
 for key,d in sorted(selected.items()):
  notices.append({'name':d['name'],'version':d['version'],'license':d['license']})
  for name in d['files']:
   f=Path(name)
   if not f.is_file() or not f.is_relative_to(oldsite):continue
   relative=f.relative_to(oldsite)
   if any(part in SKIP for part in relative.parts) or f.suffix in {'.pyc','.pyo'} or f.name=='direct_url.json' or relative.parts[0]=='bin':continue
   target=site/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
 # Metadata paths and generated console entry points are not portable payload.
 if not (site/'cytools_core/native/cytools_communication.dll').is_file():raise RuntimeError('Native Core library missing')
 notices_path=stage/'LICENCES/PythonPackages-native.json';notices_path.write_text(json.dumps(notices,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 # The bootstrap belongs to the product, not the build machine.
 bootstrap=APP/('scripts/bootstrap.py' if NAME=='CyTools_Storyboard' else 'bootstrap.py')
 if bootstrap.exists():shutil.copy2(bootstrap,runtime/'bootstrap.py')
 for source in [ROOT/'runtime/uv',ROOT/'runtime/natives'] if NAME=='CyTools_MeshStudio' else []:
  if source.exists():
   for f in source.rglob('*'):
    if f.is_file() and included(f.relative_to(ROOT).as_posix()):
     target=stage/f.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
 # Native communication uses the Microsoft C++ runtime; ship its permitted CRT DLLs.
 crt_roots=sorted(Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Redist/MSVC').glob('*/x64/Microsoft.VC143.CRT'))
 crt=next((p for p in reversed(crt_roots) if (p/'msvcp140.dll').is_file()),None)
 if crt is None:raise RuntimeError('Install the MSVC x64 redistributable build components')
 for name in ['msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','vcruntime140.dll','vcruntime140_1.dll']:
  shutil.copy2(crt/name,scripts/name)
 (stage/'LICENCES/MSVC-Runtime-Notice.txt').write_text('Microsoft Visual C++ Runtime (x64). Copyright Microsoft Corporation.\nRedistributable CRT DLLs from the Visual Studio build tools.\nhttps://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files\n',encoding='utf-8')
 if NAME=='CyTools_AudioStudio':
  worker=APP/'native/bin/Windows-AMD64/AudioStudioPluginWorker.exe'
  if not worker.is_file():raise RuntimeError('Build the AudioStudio native plugin worker first')
  target=stage/worker.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(worker,target)
 if NAME=='CyTools_MeshStudio':
  # Reuse the source builder's exact URL/hash verification for bundled native dependencies.
  import importlib.util
  spec=importlib.util.spec_from_file_location('mesh_release_parts',APP/'scripts/build_release.py')
  parts=importlib.util.module_from_spec(spec);spec.loader.exec_module(parts)
  uv=parts.fetch(next(p for p in parts.PARTS if p['id']=='uv'))
  with zipfile.ZipFile(uv) as z:
   matches=[m for m in z.namelist() if Path(m).name=='uv.exe'];assert len(matches)==1
   target=runtime/'uv/uv.exe';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(matches[0]))
 (runtime/'portable.json').write_text(json.dumps({'version':version,'commit':commit,'core':'0.11.0','cymcp':'0.7.1','python':raw['python'],'pythonSource':url,'pythonSha256':digest},indent=2)+'\n',encoding='utf-8')
 check='import cytools_core;from cytools_core.transports._native import library;assert cytools_core.__version__=="0.11.0";print(library().cytools_native_info().decode())'
 run([scripts/'python.exe','-c',check],cwd=stage,env={**os.environ,'PYTHONPATH':'','PYTHONNOUSERSITE':'1','PATH':str(scripts)})
 app_name=f'{NAME}-{version}-app.zip' if NAME in {'CyTools_AIChat','CyTools_MeshStudio'} else 'cytools-app.zip'
 assets=[]
 for dest,filter_app,prefix in [(out/app_name,True,''),(out/f'{NAME}-{version}-windows-x64.zip',False,NAME+'/')]:
  with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
   for f in sorted(stage.rglob('*')):
    if not f.is_file():continue
    rel=f.relative_to(stage).as_posix()
    if filter_app and not rel.startswith(('app/','LICENCES/')) and rel!='LICENSE':continue
    if not included(rel):continue
    z.write(f,prefix+rel)
  assets.append(dest)
 exe=out/launcher.name;shutil.copy2(launcher,exe);assets.append(exe)
 for f in assets:(out/(f.name+'.sha256')).write_text(sha(f)+'  '+f.name+'\n',encoding='ascii')
 (out/'SHA256SUMS.txt').write_text(''.join(sha(f)+'  '+f.name+'\n' for f in assets),encoding='ascii')
 print(json.dumps({'name':NAME,'version':version,'commit':commit,'stage':str(stage),'assets':[{'path':str(f),'bytes':f.stat().st_size,'sha256':sha(f)} for f in assets]},indent=2),flush=True)
if __name__=='__main__':main()
