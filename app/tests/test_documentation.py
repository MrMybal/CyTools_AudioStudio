"""Offline routing and delivered-reader checks; no model execution or network."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tested_help_docs',APP/'help_docs.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)


class DocumentationTests(unittest.TestCase):
    def test_local_route_and_french(self):
        uri=bridge.help_url('overview','fr','getting-started')
        self.assertTrue(uri.startswith('file:///'))
        self.assertTrue(uri.endswith('#/fr/overview/getting-started'))
        self.assertNotIn('\\',uri)

    def test_legacy_and_unknown_routes(self):
        self.assertIn('/guide-lisez-moi',bridge.help_url('LISEZ-MOI.md'))
        self.assertTrue(bridge.help_url('../unknown').endswith('/overview'))
        self.assertTrue(bridge.help_url('overview','unknown').endswith('#/en/overview'))

    def test_media_deep_link(self):
        self.assertTrue(bridge.help_url(media='image with spaces').endswith('?media=image%20with%20spaces'))

    def test_path_with_unicode_spaces_and_hash(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='CyDoc QA #é ') as directory:
            app=Path(directory);(app/'help').mkdir();(app/'help/index.html').write_text('',encoding='utf-8')
            with patch.object(bridge,'APP',app):
                url=bridge.help_url()
                self.assertIn('%20',url);self.assertIn('%23',url);self.assertIn('%C3%A9',url)

    def test_common_anchors_and_translations(self):
        data=json.loads((APP/'help/manifest.json').read_text('utf-8'))
        pages={(x['id'],x['locale']):x for x in data['pages']}
        for id in ('overview','operations'):
            en,fr=pages[(id,'en')],pages[(id,'fr')]
            self.assertEqual([x['id'] for x in en['headings']],[x['id'] for x in fr['headings']])
            self.assertEqual(en['revision'],fr['sourceRevision'])

    def test_browser_failure_is_reported(self):
        with patch.object(bridge.webbrowser,'open',return_value=False):
            self.assertFalse(bridge.open_help(locale='en'))
            self.assertIn('browser',bridge._last_error)

    def test_selected_operation(self):
        from types import SimpleNamespace
        operation=next(x for x in bridge.catalog()['pages'] if x.startswith('operation-'))
        bridge.set_context({'app':SimpleNamespace(page='Tools',tools=SimpleNamespace(selected=operation[len('operation-'):]))})
        self.assertEqual(bridge.contextual_page(),operation)

    def test_complete_reader(self):
        root=APP/'help'
        data=json.loads((root/'manifest.json').read_text('utf-8'))
        self.assertEqual(data['defaultLocale'],'en')
        self.assertEqual({x['code'] for x in data['locales']},{'en','fr'})
        self.assertTrue((root/'index.html').is_file())
        self.assertTrue((root/'viewer.js').is_file())
        self.assertTrue((root/'data.js').is_file())
        modules=bridge.catalog()['modules']
        self.assertEqual((root/'media-mesh.js').exists(),'mesh' in modules)
        for name in modules:self.assertTrue((root/('media-'+name+'.js')).is_file())


if __name__=='__main__':unittest.main()
