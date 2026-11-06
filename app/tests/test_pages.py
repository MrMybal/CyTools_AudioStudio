"""The public artifact contains the generated reader and its local resources only."""
from pathlib import Path
import importlib.util,tempfile,unittest
APP=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pages_publisher',APP/'.CyDocBuild/publish.py');publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
class PagesExport(unittest.TestCase):
 def test_complete_reader_is_the_only_source(self):
  files,manifest=publisher.validate_export(APP/'Documentation');self.assertTrue(manifest['pages']);self.assertIn('DocAI.md',files)
  self.assertTrue(all(not name.startswith(('data/','runtime/','.git/','.CyDocBuild/')) for name in files))
 def test_missing_reader_is_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   with self.assertRaises(ValueError):publisher.validate_export(Path(folder))
 def test_application_directory_cannot_be_overwritten(self):
  with self.assertRaises(ValueError):publisher.stage(APP)
if __name__=='__main__':unittest.main()
