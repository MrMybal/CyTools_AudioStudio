"""Validate the real built Pages artifact; no model or application dependencies."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,unquote
import json,hashlib,re,unittest
ROOT=Path(__file__).resolve().parents[1];SITE=ROOT/'_site';HERE=ROOT/'website'

class Document(HTMLParser):
    def __init__(self):super().__init__();self.elements=[]
    def handle_starttag(self,tag,attrs):self.elements.append((tag,dict(attrs)))

class Showcase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(SITE/'index.html').read_text('utf-8');cls.dom=Document();cls.dom.feed(cls.source)
        cls.content=json.loads((HERE/'content.json').read_text('utf-8'))
        cls.copy=json.loads(re.search(r'<script type="application/json" id="site-copy">(.*?)</script>',cls.source,re.S).group(1))
    def test_every_visible_copy_has_both_languages(self):
        for key,value in self.copy.items():
            if key=='product':continue
            self.assertEqual(set(value),{'en','fr'},key)
            self.assertTrue(all(isinstance(v,str) and v.strip() for v in value.values()),key)
        for _,attrs in self.dom.elements:
            for name in ['data-copy','data-copy-alt','data-copy-label','data-caption']:
                if name in attrs:self.assertIn(attrs[name],self.copy)
    def test_all_local_resources_and_anchors_resolve(self):
        ids=[attrs['id'] for _,attrs in self.dom.elements if 'id' in attrs]
        self.assertEqual(len(ids),len(set(ids)))
        manifest=json.loads((SITE/'DocData/manifest.json').read_text('utf-8'))
        pages={p['id'] for p in manifest['pages']}
        for tag,attrs in self.dom.elements:
            for key in ['src','href','data-image']:
                target=attrs.get(key,'');url=urlsplit(target)
                if not target or url.scheme:continue
                if url.path:
                    file=(SITE/unquote(url.path)).resolve();self.assertTrue(file.is_relative_to(SITE.resolve()));self.assertTrue(file.is_file(),target)
                elif url.fragment:self.assertIn(url.fragment,ids,target)
            if 'data-doc' in attrs:self.assertIn(attrs['data-doc'],pages)
    def test_embedded_reader_is_byte_identical(self):
        for path in (ROOT/'app/Documentation').rglob('*'):
            if path.is_file():self.assertEqual(path.read_bytes(),(SITE/path.relative_to(ROOT/'app/Documentation')).read_bytes(),str(path.name))
    def test_content_fingerprints_match_sources(self):
        for name in ['site.css','site.js']:
            data=(HERE/'src'/name).read_bytes();fingerprint=hashlib.sha256(data).hexdigest()[:12]
            target='assets/showcase/'+name.replace('.','.'+fingerprint+'.',1)
            self.assertIn(target,self.source);self.assertEqual((SITE/target).read_bytes(),data)
    def test_publication_boundary(self):
        self.assertTrue((SITE/'.nojekyll').is_file())
        for path in SITE.rglob('*'):
            if not path.is_file():continue
            name=path.relative_to(SITE).as_posix()
            self.assertFalse(name.startswith(('data/','runtime/','.git/','.CyDocBuild/','website/')),name)
            self.assertNotIn(path.suffix.lower(),{'.py','.ps1','.exe','.dll','.sqlite','.gguf','.safetensors'})
    def test_chapter_and_lightbox_semantics(self):
        self.assertIn('<html lang="en">',self.source);self.assertIn('id="image-viewer"',self.source)
        self.assertIn('aria-pressed="true"',self.source);self.assertIn('data-language="fr"',self.source)
        self.assertNotIn('Read this section in French',self.source)

if __name__=='__main__':unittest.main(verbosity=2)
