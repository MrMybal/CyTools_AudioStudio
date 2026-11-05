"""Build this application's offline CyDoc manual. Node >=22 is build-only."""
from pathlib import Path
from urllib.parse import unquote
import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import base64

HERE = Path(__file__).resolve().parent
APP = HERE.parent
ROOT = APP.parent


def load(path):
    return json.loads(path.read_text('utf-8-sig'))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def slug(text):
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub('[^a-z0-9]+', '-', text.lower()).strip('-') or 'section'


def page_id(name):
    return 'guide-' + slug(str(Path(name).with_suffix('')).replace('\\', '/'))


def headings(text):
    result = {}; used = {}; fenced = False
    for line in text.splitlines():
        if re.match(r'^\s*(`{3,}|~{3,})', line):
            fenced = not fenced
        m = re.match(r'^#{1,6}\s+(.+?)\s*#*$', line) if not fenced else None
        if m:
            title = m[1]; explicit = re.search(r'\{#([\w-]+)\}$', title)
            key = explicit[1] if explicit else slug(re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', title))
            n = used.get(key, 0); used[key] = n + 1
            key = key + ('-' + str(n) if n else '')
            result[key] = title
    return result


def language(text, filename):
    if 'LISEZ' in filename.upper() or filename.lower().endswith('.fr.md'): return 'fr'
    sample = re.sub(r'```[\s\S]*?```', '', text[:10000]).lower()
    fr = len(re.findall(r'\b(?:les|des|une|dans|pour|avec|utiliser|fichier|est|pas|du|ne)\b', sample))
    en = len(re.findall(r'\b(?:the|with|from|this|that|file|and|is|not|use|for)\b', sample))
    return 'fr' if fr > en else 'en'


class Manual:
    def __init__(self, work, spec):
        self.work, self.spec = work, spec
        self.assets = work / 'assets'; self.assets.mkdir(parents=True)
        logo=APP/'assets/branding/logo.png'
        if logo.is_file():
            icon='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><image width="128" height="128" href="data:image/png;base64,'+base64.b64encode(logo.read_bytes()).decode()+'"/></svg>'
        else:icon='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#326aa0"/><text x="32" y="41" text-anchor="middle" fill="white" font-family="sans-serif" font-size="30">Cy</text></svg>'
        write(self.assets/'favicon.svg',icon)
        self.docs = {}; self.issues = []; self.modules = set(); self.extra = {}; self.inventory = []
        self.routes = {}; self.originals = {}
        for name in spec['documents']:
            p = ROOT / name
            if not p.is_file():
                self.issues.append({'source': name, 'reason': 'Source document no longer exists'}); continue
            text = p.read_text('utf-8-sig'); lang = language(text, name)
            self.docs[name.lower()] = (name, page_id(name), lang, text, headings(text))
            self.originals[name] = digest(text.encode('utf-8'))

    def page(self, id, locale, title, section, body, order=100, translated=None):
        meta = {'id': id, 'title': title.replace('\n', ' ').replace('"', ''), 'description': title.replace('\n', ' '), 'section': section, 'order': order, 'revision': digest(body.encode())[:16]}
        if translated: meta['sourceRevision'] = translated
        text = '---\n' + '\n'.join(f'{k}: {v}' for k, v in meta.items()) + '\n---\n\n' + body + '\n'
        write(self.work / 'manual' / locale / (id + '.md'), text)
        self.routes.setdefault(id, {})[locale] = list(headings(body))
        return meta['revision']

    def local(self, name, href):
        raw = unquote(href.split('#', 1)[0].split('?', 1)[0]).replace('\\', '/')
        if raw.startswith(('http:', 'https:', 'mailto:', 'doc:', '#/')): return None
        if not raw: return ROOT / name
        if re.match(r'^[A-Za-z]:', raw) or raw.startswith('/'): return None
        path = (ROOT / name).parent / raw
        path = path.resolve()
        return path if path.is_relative_to(ROOT.resolve()) else None

    def asset(self, path, source):
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 20 * 1024**2:
            self.issues.append({'source': source, 'target': path.name, 'reason': 'Missing or oversized local media; not copied'}); return None
        ext = path.suffix.lower(); data = path.read_bytes()
        filename = digest(data)[:16] + '-' + slug(path.stem) + ext
        shutil.copyfile(path, self.assets / filename)
        return 'assets/' + filename

    def attachment(self, path, source):
        name = path.relative_to(ROOT).as_posix()
        if not path.is_file() or path.stat().st_size > 1_000_000 or any(x.lower() in ('runtime', 'data', '.git', '.env', 'settings') for x in path.relative_to(ROOT).parts): return None
        try: text = path.read_text('utf-8-sig')
        except (UnicodeError, OSError): return None
        id = 'reference-' + slug(name)
        suffix = path.suffix.lower(); lang = {'.py':'python','.json':'json','.cpp':'cpp','.h':'cpp','.hpp':'cpp','.sh':'bash','.js':'javascript','.ts':'typescript'}.get(suffix, 'text')
        fence = '`' * max(3, 1 + max((len(x) for x in re.findall('`+', text)), default=0))
        self.extra[id] = (name, f'Original distributed file: `{name}`.\n\n{fence}{lang}\n{text}\n{fence}')
        return id

    def convert(self, name, id, lang, text):
        def change(match):
            image, label, href = match[1], match[2], match[3].strip('<>')
            if href.startswith(('http://','https://','mailto:')):
                if image:
                    self.issues.append({'source': name, 'target': href, 'reason': 'Remote image requires a locally licensed copy'})
                    return label + ' (external image: ' + href + ')'
                return match[0]
            p = self.local(name, href)
            if p is None: return match[0]
            if image:
                target = self.asset(p, name)
                if target:
                    self.modules.add('image')
                    return '\n```image\n' + json.dumps({'id':'image-'+digest((name+href).encode())[:12],'src':target,'alt':label,'controls':'minimal'},ensure_ascii=False) + '\n```\n'
                return label + ' (image unavailable in this edition)'
            key = p.relative_to(ROOT).as_posix().lower()
            if key == 'app/help/index.html':return f'[{label}](doc:overview)'
            if key in ('licences','licences/') or p.name.upper()=='LICENSE' and not p.exists():
                return f'[{label}](doc:licenses)'
            anchor = unquote(href.partition('#')[2]); record = self.docs.get(key)
            if record:
                dest_name, dest_id, dest_lang, _, anchors = record
                if anchor and anchor not in anchors:
                    self.issues.append({'source':name,'target':href,'reason':'Legacy section missing; linked to page instead'})
                    anchor = ''
                url = f'#/{dest_lang}/{dest_id}' + ('/'+anchor if anchor else '')
                return f'[{label}]({url})'
            if href.startswith('#'):
                if anchor in headings(text): return f'[{label}](doc:{id}#{anchor})'
                self.issues.append({'source':name,'target':href,'reason':'Legacy anchor missing'})
                return label
            attachment = self.attachment(p, name)
            if attachment: return f'[{label}](doc:{attachment})'
            self.issues.append({'source':name,'target':href,'reason':'Legacy target absent or not distributable'})
            return f'{label} (`{href}` — reference unavailable in this edition)'
        # Keep examples byte-for-byte inside code fences; convert only prose links.
        lines = []; chunk = []; fenced = False
        def flush():
            if chunk:
                prose = '\n'.join(chunk)
                prose = re.sub(r'<img\b[^>]*src="([^"]+)"[^>]*>', lambda m: '!['+(re.search(r'alt="([^"]*)"',m[0])[1] if re.search(r'alt="([^"]*)"',m[0]) else 'Application image')+']('+m[1]+')', prose)
                prose = re.sub(r'</?p(?:\s[^>]*)?>', '', prose)
                prose = re.sub(r'(!?)\[([^\]]*)\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)', change, prose)
                lines.extend(prose.splitlines());chunk.clear()
        for line in text.splitlines():
            if re.match(r'^\s*(`{3,}|~{3,})', line):
                flush();fenced=not fenced;lines.append(line)
            elif fenced: lines.append(line)
            else: chunk.append(line)
        flush()
        return '\n'.join(lines)

    def build(self):
        for name,id,lang,text,anchors in self.docs.values():
            title = next(iter(anchors.values()), Path(name).stem)
            section = 'SDK reference' if name.startswith('app/Docs/') else 'Application guides'
            banner = ''
            if name.startswith('app/Docs/') and Path(name).name not in self.spec['productGuides']:
                banner = '> SDK reference retained from the application sources. Its SDK version may differ from this application; the current operation reference is generated from CyTool.json.\n\n'
            body = banner + self.convert(name,id,lang,text)
            self.page(id, lang, title, section, body)
            if lang == 'fr':
                self.page(id,'en',title,section,f'This original document is available in French. An English translation has not been supplied.\n\n[Read the complete original](#/fr/{id}).\n\n'+'\n\n'.join(f'## {title} {{#{anchor}}}\n\n[Read this section in French](#/fr/{id}/{anchor}).' for anchor,title in anchors.items()))
            self.inventory.append({'source':name,'id':id,'locale':lang,'sha256':self.originals[name]})
        manifest = load(APP/'CyTool.json')
        # Actual schemas are the public operation reference; descriptions are never inferred.
        for locale in ('en','fr'):
            fr=locale=='fr';links=[]
            for operation in manifest.get('operations',[]):
                oid=operation['id'];id='operation-'+slug(oid);links.append(f'- [{oid}](doc:{id})')
                body = str(operation.get('description') or '') + '\n\n## '+('Contrat' if fr else 'Contract')+' {#contract}\n\n```json\n'+json.dumps(operation,ensure_ascii=False,indent=2)+'\n```\n'
                body += '\n## '+('Utilisation' if fr else 'Usage')+' {#usage}\n\n```bash\npython app/tool.py describe-operation '+oid+'\n```\n'
                self.page(id,locale,oid,'Operations',body,200)
            body=('Ces contrats sont générés à partir du manifeste livré. Ils décrivent les paramètres, sorties, permissions et backends déclarés ; ils ne prouvent pas que les poids ou moteurs sont installés.' if fr else 'These contracts come from the shipped manifest. They describe declared inputs, outputs, permissions and backends; they do not prove that models or engines are installed.')+'\n\n## Operations {#operations}\n\n'+'\n'.join(links)
            self.page('operations',locale,'Référence des opérations' if fr else 'Operation reference','Reference',body,20)
        # Source extraction and lexical indexing: only the distributed public entry point.
        source=APP/'tool.py';target=self.work/'sources/tool.py';target.parent.mkdir(parents=True)
        write(target,source.read_text('utf-8-sig'))
        symbols=[]
        tree=ast.parse(source.read_text('utf-8-sig'))
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and not node.name.startswith('_'):
                signature='class '+node.name if isinstance(node,ast.ClassDef) else node.name+'('+ast.unparse(node.args)+')'
                symbols.append({'key':node.name,'name':node.name,'language':'python','kind':'class' if isinstance(node,ast.ClassDef) else 'function','signature':signature,'description':ast.get_docstring(node) or 'Public definition from the distributed tool.py.','source':{'file':'sources/tool.py','line':node.lineno}})
        write(self.work/'api.json',json.dumps({'symbols':symbols},ensure_ascii=False,indent=2))
        notices=[]
        license_files=([ROOT/'LICENSE'] if (ROOT/'LICENSE').is_file() else [])+sorted((ROOT/'LICENCES').glob('*'),key=lambda path:path.name.casefold())
        for path in license_files:
            id=self.attachment(path,'licenses')
            if id:notices.append(f'- [{path.name}](doc:{id})')
        self.page('licenses','en','Licenses','Reference','Full original license texts from this distribution. Model weights and separately downloaded engines retain their own terms.\n\n'+'\n'.join(notices),25)
        for id,(name,body) in self.extra.items():self.page(id,'en',name,'File references',body,250)
        # A tested, local fixture illustrates the mesh viewer without downloading weights.
        demo=HERE/'assets/studio-knot-demo.glb'
        if demo.is_file():
            shutil.copy2(demo,self.assets/demo.name);self.modules.add('mesh')
            for locale in ('en','fr'):
                body=('Objet procédural de démonstration, pas une reconstruction IA. Faites glisser pour tourner et utilisez la molette pour zoomer. Les contrôles restent dans la fenêtre.' if locale=='fr' else 'Procedural demonstration object, not an AI reconstruction. Drag to orbit and use the wheel to zoom. Enlargement stays inside this window.')+'\n\n```mesh\n'+json.dumps({'id':'studio-demo','src':'assets/'+demo.name,'title':'Studio demo','controls':'minimal'})+'\n```\n'
                self.page('mesh-preview',locale,'Aperçu 3D' if locale=='fr' else '3D preview','Guides',body,15)
        # Bilingual orientation has shared explicit anchors. Existing prose remains intact.
        for locale in ('en','fr'):
            fr=locale=='fr';guide='guide-lisez-moi' if fr else ('guide-readme' if 'readme.md' in self.docs else 'guide-app-readme')
            if not fr and self.docs.get('app/readme.md',('', '', ''))[2]=='fr' and 'readme.md' not in self.docs:guide='guide-app-readme'
            intro = ('Documentation locale de ' if fr else 'Local documentation for ')+self.spec['name']+'.\n\n'
            body=intro+'## '+('Démarrer' if fr else 'Getting started')+' {#getting-started}\n\n'+f'[{"Guide de l’application" if fr else "Application guide"}](doc:{guide}) · [Operations](doc:operations)\n\n'
            body+='## '+('Aide contextuelle' if fr else 'Contextual help')+' {#contextual-help}\n\n'+('F1 ouvre l’aide du panneau ou de l’opération active. Options propose le manuel et son index. La lecture ne nécessite ni Node.js, ni serveur, ni connexion Internet.' if fr else 'F1 opens help for the active workspace or operation. Options provides the manual and its index. Reading needs no Node.js, server or Internet connection.')+'\n\n'
            body+='## '+('Guides existants' if fr else 'Existing guides')+' {#guides}\n\n'+'\n'.join(f'- [{Path(x[0]).as_posix()}](doc:{x[1]})' for x in self.docs.values())+'\n\n'
            if demo.is_file():body+='[3D preview](doc:mesh-preview?media=studio-demo)\n\n'
            body+='## '+('Langues et limites' if fr else 'Languages and limits')+' {#languages-and-limits}\n\n'+('Anglais par défaut ; français conservé. Une page anglaise absente pour un original français indique clairement le lien vers cet original. Les autres traductions manquantes utilisent le repli anglais. Le rapport des traductions montre les révisions manquantes ou périmées.' if fr else 'English is the default; French originals are retained. An untranslated French guide has an English orientation page linking to its original. Other missing translations fall back to English. Translation status tracks missing or stale revisions.')+'\n\n[Translation status](doc:translation-report) · [Migration notes](doc:migration-notes)\n'
            self.page('overview',locale,self.spec['name'],'Guides',body,0)
        for locale in ('en',):
            body='## Scope {#scope}\n\nMigrated from the existing application documents. Original Markdown remains the authoring source and GitHub-compatible reference. Agent instructions, caches, private data and unrelated third-party developer guides are not end-user help.\n\n## Modules {#modules}\n\n'+(', '.join(sorted(self.modules)) or 'Core reader only')+'. Only media used by this manual is bundled. The mesh reader and Three.js are absent unless a local mesh example is included.\n\n## Source documentation {#source-documentation}\n\nPython AST public definitions are imported using CyDoc’s neutral API format. CyDoc provides a lexical index of the distributed tool.py, not a semantic Python compiler.\n\n## Existing documentation gaps {#gaps}\n\n'
            body+='\n'.join('- `'+str(x['source'])+'`: '+str(x['reason'])+' — `'+str(x.get('target',''))+'`' for x in self.issues) or 'No unresolved imported references.'
            self.page('migration-notes',locale,'Migration notes','Maintenance',body,280)
        # Explicitly generated bilingual pages share anchors and track the English revision.
        for id in ['overview','operations','mesh-preview']+['operation-'+slug(o['id']) for o in manifest.get('operations',[])]:
            en=self.work/'manual/en'/f'{id}.md';fr=self.work/'manual/fr'/f'{id}.md'
            if en.exists() and fr.exists():
                rev=re.search(r'^revision: (.+)$',en.read_text('utf-8'),re.M)[1]
                write(fr,fr.read_text('utf-8').replace('\n---\n','\nsourceRevision: '+rev+'\n---\n',1))
        config={'name':self.spec['name'],'version':manifest['version'],'defaultLocale':'en','locales':[{'code':'en','label':'English'},{'code':'fr','label':'Français'}],'homePage':'overview','content':'manual','assets':'assets','out':'export','modules':sorted(self.modules),'sources':['sources'],'sourceIndex':{'enabled':True,'includeDirs':['sources']},'apiImports':[{'format':'cydoc','prefix':'python','path':'api.json'}],'translationReport':True,'aliases':{'home':'overview','README':'overview','readme':'overview','help':'overview','user-guide':'guide-lisez-moi','api':'operations'}}
        # Alias ids are lower-case public addresses; legacy paths use help-map.json instead.
        config['aliases'].pop('README')
        write(self.work/'cydoc.config.json',json.dumps(config,ensure_ascii=False,indent=2))
        return config


def installed_package(install):
    runtime=ROOT/'runtime/documentation-build'
    package=runtime/'node_modules/cydoc'
    expected=load(HERE/'cydoc-source.json')
    if digest((HERE/'vendor/cydoc-0.1.0.tgz').read_bytes())!=expected['packageSha256']:raise RuntimeError('CyDoc package digest mismatch')
    if install:
        runtime.mkdir(parents=True,exist_ok=True)
        for name in ('package.json','package-lock.json'):shutil.copy2(HERE/name,runtime/name)
        (runtime/'vendor').mkdir(exist_ok=True);shutil.copy2(HERE/'vendor/cydoc-0.1.0.tgz',runtime/'vendor/cydoc-0.1.0.tgz')
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        if not npm:raise RuntimeError('Node.js >=22 and npm are required only to regenerate documentation')
        subprocess.run([npm,'ci','--no-audit','--no-fund'],cwd=runtime,check=True)
    if not (package/'tools/cli.mjs').is_file():raise RuntimeError('Build dependency missing. Run this script with --install once.')
    return package


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true',help='Install pinned build-only dependencies under runtime/')
    parser.add_argument('--cydoc-root',type=Path,help='Use an already built CyDoc checkout/package')
    parser.add_argument('--check',action='store_true',help='Regenerate and validate using the CyDoc check command')
    args=parser.parse_args();spec=load(HERE/'sources.json')
    package=args.cydoc_root.resolve() if args.cydoc_root else installed_package(args.install)
    node=shutil.which('node');
    if not node:raise RuntimeError('Node.js >=22 is required only to regenerate documentation')
    major=int(subprocess.check_output([node,'--version'],text=True).strip().lstrip('v').split('.')[0])
    if major<22:raise RuntimeError('Node.js 22 or later required')
    work=Path(tempfile.mkdtemp(prefix='cydoc-',dir=HERE))
    try:
        manual=Manual(work,spec)
        for locale in ('en','fr'):(work/'manual'/locale).mkdir(parents=True)
        config=manual.build()
        subprocess.run([node,str(package/'tools/cli.mjs'),'check' if args.check else 'build',str(work/'cydoc.config.json')],check=True)
        export=work/'export'
        # Runtime paths never include this temporary source directory.
        manifest=load(export/'manifest.json')
        legacy={x['source']:x['id'] for x in manual.inventory}
        write(export/'help-map.json',json.dumps({'schemaVersion':1,'legacyPaths':legacy,'pages':{p['id']:{'headings':[h['id'] for h in p.get('headings',[])],'locale':p['locale']} for p in manifest['pages']},'modules':config['modules']},ensure_ascii=False,indent=2))
        write(export/'migration-report.json',json.dumps({'schemaVersion':1,'documents':manual.inventory,'issues':manual.issues,'modules':config['modules'],'sourceIndex':['app/tool.py'],'platforms':{'Windows':'See validation report','Linux':'Not executed','macOS':'Not executed'}},ensure_ascii=False,indent=2))
        shutil.copy2(HERE/'CyDoc-MIT.txt',export/'CyDoc-MIT.txt')
        # CyDoc's exporter keeps its own classic-script provider and reader unchanged.
        destination=APP/'help';previous=APP/'help.previous'
        if previous.exists():raise RuntimeError('Previous documentation replacement incomplete: inspect help.previous')
        if destination.exists():destination.rename(previous)
        try:export.rename(destination)
        except BaseException:
            if previous.exists():previous.rename(destination)
            raise
        if previous.exists():
            assert previous.resolve().parent==APP.resolve() and previous.name=='help.previous'
            shutil.rmtree(previous)
        write(HERE/'cydoc.config.json',json.dumps({k:v for k,v in config.items() if k not in ('sources','apiImports','sourceIndex')},ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'name':spec['name'],'pages':len(manifest['pages']),'documents':len(manual.inventory),'issues':len(manual.issues),'modules':config['modules']}))
    finally:
        assert work.resolve().parent==HERE.resolve() and work.name.startswith('cydoc-')
        shutil.rmtree(work)


if __name__=='__main__':main()
