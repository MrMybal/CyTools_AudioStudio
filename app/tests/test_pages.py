"""Checks for the Pages export boundary; no network or application runtime."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

APP=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pages_publisher',APP/'documentation/publish.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)


class PagesExport(unittest.TestCase):
    def test_complete_local_reader_is_the_only_source(self):
        files,manifest=publisher.validate_export(APP/'help')
        self.assertTrue(manifest['pages'])
        self.assertTrue(all(not name.startswith(('data/','runtime/','.git/')) for name in files))
        self.assertIn('assets/favicon.svg',files)

    def test_missing_reader_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):publisher.validate_export(Path(root))

    def test_application_directory_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):publisher.stage(APP)


if __name__=='__main__':unittest.main()
