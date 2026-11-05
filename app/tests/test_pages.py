"""Checks for the Pages export boundary; no network or application runtime."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
import hashlib
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pages_publisher',APP/'documentation/publish.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
spec=importlib.util.spec_from_file_location('documentation_builder',APP/'documentation/build.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


class PagesExport(unittest.TestCase):
    def test_complete_local_reader_is_the_only_source(self):
        files,manifest=publisher.validate_export(APP/'help')
        self.assertTrue(manifest['pages'])
        self.assertTrue(all(not name.startswith(('data/','runtime/','.git/')) for name in files))
        self.assertIn('assets/favicon.svg',files)

    def test_source_newlines_and_hashes_are_portable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app=root/'app';app.mkdir()
            (root/'README.md').write_bytes(b'# Example\r\n\r\nA guide.\r\n')
            (app/'tool.py').write_bytes(b'\xef\xbb\xbfdef example():\r\n    return 1\r\n')
            (app/'CyTool.json').write_text('{"version":"1.0.0","operations":[]}',encoding='utf-8')
            work=root/'work';work.mkdir()
            with patch.object(builder,'ROOT',root),patch.object(builder,'APP',app),patch.object(builder,'HERE',app/'documentation'):
                manual=builder.Manual(work,{'name':'Example','documents':['README.md'],'productGuides':[]})
                manual.build()
            self.assertEqual(manual.originals['README.md'],hashlib.sha256(b'# Example\n\nA guide.\n').hexdigest())
            self.assertEqual((work/'sources/tool.py').read_bytes(),b'def example():\n    return 1\n')

    def test_missing_reader_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):publisher.validate_export(Path(root))

    def test_application_directory_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):publisher.stage(APP)


if __name__=='__main__':unittest.main()
