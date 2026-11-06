"""Checks of authored bilingual content, delivered assets and native help routes."""
from pathlib import Path
import importlib.util,json,re,tempfile,unittest
from unittest.mock import patch
APP=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tested_help_docs',APP/'help_docs.py');bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
spec=importlib.util.spec_from_file_location('documentation_builder',APP/'.CyDocBuild/build.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
def manifest():return json.loads((APP/'Documentation/DocData/manifest.json').read_text('utf-8'))
class DocumentationTests(unittest.TestCase):
 def test_local_route_and_french(self):
  url=bridge.help_url('overview','fr','getting-started');self.assertTrue(url.startswith('file:///'));self.assertIn('/Documentation/Documentation.html#',url);self.assertTrue(url.endswith('#/fr/overview/getting-started'))
 def test_legacy_and_unknown_routes(self):
  self.assertIn('/guide-lisez-moi',bridge.help_url('LISEZ-MOI.md'));self.assertTrue(bridge.help_url('../unknown').endswith('/overview'));self.assertTrue(bridge.help_url('overview','unknown').endswith('#/en/overview'))
 def test_media_deep_link(self):self.assertTrue(bridge.help_url(media='image with spaces').endswith('?media=image%20with%20spaces'))
 def test_path_with_unicode_spaces_and_hash(self):
  with tempfile.TemporaryDirectory(prefix='CyDoc QA #é ') as folder:
   app=Path(folder);(app/'Documentation').mkdir();(app/'Documentation/Documentation.html').write_text('',encoding='utf-8')
   with patch.object(bridge,'APP',app):
    url=bridge.help_url();self.assertIn('%20',url);self.assertIn('%23',url);self.assertIn('%C3%A9',url)
 def test_all_pages_have_both_languages_and_matching_anchors(self):
  data=manifest();en={p['id']:p for p in data['pages'] if p['locale']=='en'};fr={p['id']:p for p in data['pages'] if p['locale']=='fr'};self.assertEqual(en.keys(),fr.keys())
  for id,p in en.items():
   self.assertEqual([h['id'] for h in p['headings']],[h['id'] for h in fr[id]['headings']],id)
   self.assertTrue(p['text'].strip());self.assertTrue(fr[id]['text'].strip())
   if fr[id].get('sourceRevision'):self.assertEqual(p['revision'],fr[id]['sourceRevision'],id)
 def test_no_placeholder_or_internal_reader_pages(self):
  for p in manifest()['pages']:
   self.assertNotEqual(p.get('kind'),'source');self.assertFalse(p['id'].startswith(('source-','migration-','translation-report','reference-licences-')))
   self.assertNotRegex(p['text'],r'Read this section in French|Read the complete original|translation has not been supplied|ZXQ\d{4}|⟦T[0-9a-f]+⟧')
 def test_navigation_has_real_parent_pages(self):
  data=manifest();pages={(p['id'],p['locale']) for p in data['pages']};children=0
  for p in data['pages']:
   if p.get('parent'):children+=1;self.assertIn((p['parent'],p['locale']),pages)
  self.assertGreater(children,5)
 def test_reader_and_ai_sidecar_are_separate(self):
  root=APP/'Documentation';self.assertTrue((root/'DocAI.md').is_file());self.assertTrue((root/'Documentation.html').is_file())
  self.assertFalse(any(p['id'].lower()=='docai' for p in manifest()['pages']))
  html=(root/'Documentation.html').read_text('utf-8');self.assertIn('DocData/',html);self.assertNotIn('<iframe',html)
  for p in root.rglob('*'):
   self.assertNotIn('node_modules',p.parts);self.assertNotIn('.CyDocBuild',p.parts)
 def test_selected_modules_only(self):
  root=APP/'Documentation/DocData';modules=bridge.catalog()['modules']
  for name in ['image','video','mesh','gallery','graph','gif']:self.assertEqual((root/('media-'+name+'.js')).exists(),name in modules)
  if 'gallery' in modules:self.assertIn('image',modules)
 def test_authored_sources_are_complete(self):builder.validate_sources()
 def test_no_copied_english_prose_in_french(self):
  for original in (APP/'.CyDocBuild/manual/en').glob('*.md'):
   translated=APP/'.CyDocBuild/manual/fr'/original.name
   def prose(path):
    text=path.read_text('utf-8').split('\n---\n\n',1)[-1]
    text=re.sub(r'```[\s\S]*?```|`[^`]+`|https?://[^\s)]+','',text)
    return {p.strip() for p in text.split('\n\n') if len(re.findall(r'\b(?:the|with|from|this|that|your|without|these|allows|and|for)\b',p,re.I))>=3}
   self.assertFalse(prose(original)&prose(translated),original.name)
 def test_stale_translation_is_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   work=Path(folder);(work/'manual/en').mkdir(parents=True);(work/'manual/fr').mkdir(parents=True)
   (work/'manual/en/a.md').write_text('revision: 2\n## Open {#open}\nText',encoding='utf-8');(work/'manual/fr/a.md').write_text('sourceRevision: 1\n## Ouvrir {#open}\nTexte',encoding='utf-8')
   with patch.object(builder,'HERE',work):
    with self.assertRaises(RuntimeError):builder.validate_sources()
 def test_browser_failure_is_reported(self):
  with patch.object(bridge.webbrowser,'open',return_value=False):self.assertFalse(bridge.open_help(locale='en'));self.assertIn('browser',bridge._last_error)
 def test_legacy_alias_routes_are_supported(self):
  aliases=bridge.catalog()['aliases']
  if aliases:
   alias=next(iter(aliases));self.assertIn('/'+alias,bridge.help_url(alias))
if __name__=='__main__':unittest.main()
