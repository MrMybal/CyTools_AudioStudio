"""Model catalogue and installation state, without any download (run from the app directory)."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from tests._fixtures import APP, ROOT
from cytools_core import CyToolError
from audiostudio import models

ID_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_.-]{0,127}$')


def fake_model(directory, files, **fields):
    entry = {'id': 'fake.model', 'backend': 'piper', 'family': 'voice', 'name': 'Fake', 'variant': '', 'directory': str(directory),
             'source': {'kind': 'huggingface', 'repository': 'x/y', 'revision': 'abc', 'url': 'https://example.invalid/model'},
             'files': files, 'downloadBytes': sum(int(f['size']) for f in files), 'license': {'name': 'Test', 'url': 'https://example.invalid/license', 'requiresAcceptance': False},
             'resources': {'ramBytes': 1024, 'vramBytes': None}}
    entry.update(fields)
    return entry


class CatalogueTests(unittest.TestCase):
    def test_catalogue_loads_declared_models_and_piper_voices(self):
        catalogue = models.catalog()
        declared = json.loads((APP / 'models' / 'catalog.json').read_text('utf-8-sig'))['models']
        voices = json.loads((APP / 'models' / 'piper-voices.json').read_text('utf-8-sig'))
        voices = voices.get('voices', voices)
        voice_count = sum(1 for v in voices.values() if isinstance(v, dict) and 'files' in v)
        self.assertGreaterEqual(len(declared), 8)           # 8 generation models plus the lyrics LLM helper
        self.assertEqual(len({m['id'] for m in declared}), len(declared))
        self.assertGreater(voice_count, 0)
        self.assertEqual({m['id'] for m in declared}, {k for k, m in catalogue.items() if m['backend'] != 'piper'})
        self.assertEqual(sum(1 for m in catalogue.values() if m['backend'] == 'piper'), voice_count)
        self.assertEqual(len(catalogue), len(declared) + voice_count)
        for model_id, model in catalogue.items():
            if model_id.isascii():                       # the non-ASCII voice key is covered by the known-bug test below
                self.assertRegex(model_id, ID_PATTERN)
            self.assertEqual(model['id'], model_id)
            self.assertTrue(model['files'], model_id)
            for entry in model['files']:
                self.assertIsInstance(entry['size'], int)
                self.assertTrue(entry['path'])
            self.assertIsInstance(model['downloadBytes'], int)
            self.assertFalse(Path(model['directory']).is_absolute(), model_id)
            self.assertEqual(models.directory(model), ROOT / model['directory'])
        self.assertIs(models.catalog(), catalogue)                     # cached until the files change
        self.assertTrue(catalogue['piper.fr_FR-siwis-medium']['default'])
        self.assertEqual(catalogue['piper.fr_FR-siwis-medium']['voiceKey'], 'fr_FR-siwis-medium')
        self.assertEqual(len(models.by_backend('qwen3tts')), 5)
        self.assertEqual(models.by_backend('nope'), [])
        with self.assertRaises(KeyError):
            models.get('no.such.model')

    def test_every_catalogue_id_matches_manifest_pattern_known_bug(self):
        """Known bug: the Piper voice key "pt_PT-tugão-medium" (upstream name, valid UTF-8 in piper-voices.json)
        gives the model id "piper.pt_PT-tugão-medium", which violates the manifest id pattern. Once that voice is
        installed, manifest_models('piper') lists it and a regenerated CyTool.json no longer validates."""
        offenders = [model_id for model_id in models.catalog() if not ID_PATTERN.match(model_id)]
        self.assertEqual(offenders, [])

    def test_status_of_missing_model_touches_nothing(self):
        candidates = [m for m in models.by_backend('piper') if not m.get('default') and not models.directory(m).exists()]
        self.assertTrue(candidates, 'every Piper voice is installed; nothing to test')
        model = candidates[0]
        with tempfile.TemporaryDirectory() as workdir, mock.patch.object(models, 'STATE_DIR', Path(workdir) / 'state'):
            info = models.status(model['id'])
        self.assertEqual(info['state'], 'NotInstalled')
        self.assertFalse(info['installed'])
        self.assertEqual(info['presentBytes'], 0)
        self.assertEqual(info['missing'], len(model['files']))
        self.assertEqual({p['reason'] for p in info['problems']}, {'missing'})
        self.assertEqual(info['directory'], str(models.directory(model)))
        self.assertEqual(info['downloadBytes'], model['downloadBytes'])
        self.assertFalse(models.directory(model).exists())               # status never creates folders
        with self.assertRaises(CyToolError) as ctx:
            with mock.patch.object(models, 'STATE_DIR', Path(workdir) / 'state'):
                models.require_installed(model['id'])
        self.assertEqual(ctx.exception.code, 'MissingModel')
        self.assertEqual(ctx.exception.details['state'], 'NotInstalled')
        self.assertFalse(models.directory(model).exists())

    def test_status_all_and_installed_default(self):
        listed = models.status_all(include_voices=False)
        ids = [m['id'] for m in listed]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('piper.fr_FR-siwis-medium', ids)
        self.assertTrue(all(m['backend'] != 'piper' or m['default'] or Path(m['directory']).exists() for m in listed))
        for item in listed:
            self.assertIn(item['state'], ('Installed', 'NotInstalled', 'Partial', 'Downloading', 'Verifying', 'Interrupted', 'Failed', 'AccessRequired', 'LicenseAcceptanceRequired', 'Cancelled'))
            self.assertEqual(item['installed'], item['state'] == 'Installed')
        piper_only = models.status_all('piper', include_voices=True)
        self.assertTrue(all(m['backend'] == 'piper' for m in piper_only))
        self.assertEqual(len(piper_only), len(models.by_backend('piper')))
        default = models.installed_default('piper')
        self.assertTrue(default is None or not models.missing_files(default))
        self.assertIsNone(models.installed_default('nope'))


class FileCheckTests(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.root = Path(self.workdir.name) / 'weights'
        self.root.mkdir()
        (self.root / 'a.bin').write_bytes(b'AAAA')
        (self.root / 'b.bin').write_bytes(b'BB')
        (self.root / 'd.bin').write_bytes(b'whatever')
        (self.root / 'e.bin').write_bytes(b'EEEE')
        (self.root / 'c.bin.part').write_bytes(b'CCC')
        self.files = [{'path': 'a.bin', 'size': 4, 'sha256': hashlib.sha256(b'AAAA').hexdigest()},
                      {'path': 'b.bin', 'size': 4},
                      {'path': 'c.bin', 'size': 10},
                      {'path': 'd.bin', 'size': 1, 'presenceOnly': True},
                      {'path': 'e.bin', 'size': 4, 'md5': hashlib.md5(b'XXXX').hexdigest()}]
        self.model = fake_model(self.root, self.files)

    def tearDown(self):
        self.workdir.cleanup()

    def test_missing_files_size_and_hash_checks(self):
        problems = {p['path']: p for p in models.missing_files(self.model)}
        self.assertEqual(set(problems), {'b.bin', 'c.bin'})
        self.assertEqual(problems['b.bin'], {'path': 'b.bin', 'reason': 'size', 'expected': 4, 'actual': 2})
        self.assertEqual(problems['c.bin']['reason'], 'missing')
        hashed = {p['path']: p['reason'] for p in models.missing_files(self.model, hash_check=True)}
        self.assertEqual(hashed, {'b.bin': 'size', 'c.bin': 'missing', 'e.bin': 'md5'})
        (self.root / 'a.bin').write_bytes(b'AAAB')
        hashed = {p['path']: p['reason'] for p in models.missing_files(self.model, hash_check=True)}
        self.assertEqual(hashed['a.bin'], 'sha256')
        self.assertNotIn('a.bin', {p['path'] for p in models.missing_files(self.model)})    # size-only check still passes
        self.assertEqual(models.present_bytes(self.model), 4 + 2 + 8 + 4 + 3)             # includes the .part file
        self.assertEqual(models.sha256(self.root / 'a.bin'), hashlib.sha256(b'AAAB').hexdigest())
        self.assertEqual(models.md5(self.root / 'e.bin'), hashlib.md5(b'EEEE').hexdigest())
        self.assertEqual(models.present_bytes(fake_model(self.root / 'nothing', self.files)), 0)

    def test_install_returns_installed_without_download_when_complete(self):
        (self.root / 'b.bin').write_bytes(b'BBBB')
        (self.root / 'c.bin').write_bytes(b'C' * 10)
        with mock.patch.object(models, 'get', return_value=self.model), mock.patch.object(models, 'STATE_DIR', Path(self.workdir.name) / 'state'):
            result = models.install('fake.model')
            self.assertEqual(result, {'modelId': 'fake.model', 'state': 'Installed', 'downloaded': 0})
            self.assertEqual(models.read_state('fake.model')['state'], 'Installed')
            info = models.status('fake.model')
            self.assertTrue(info['installed'])
            self.assertEqual(info['presentBytes'], 4 + 4 + 10 + 8 + 4 + 3)
            verified = models.verify('fake.model', hash_check=True)
            self.assertFalse(verified['ok'])                                   # e.bin md5 mismatch
            self.assertEqual([p['path'] for p in verified['problems']], ['e.bin'])
            self.assertEqual(models.read_state('fake.model')['state'], 'Partial')
            self.assertEqual(models.status('fake.model')['state'], 'Installed')    # every file present by size: Installed wins
            with self.assertRaises(CyToolError) as ctx:
                models.remove('fake.model')                                    # temp folder is outside data/models
            self.assertEqual(ctx.exception.code, 'AccessDenied')
            self.assertTrue(self.root.exists())

    def test_install_refuses_license_gated_model_without_acceptance(self):
        gated = fake_model(self.root, self.files, license={'name': 'Gated licence', 'url': 'https://example.invalid/licence', 'requiresAcceptance': True})
        with mock.patch.object(models, 'get', return_value=gated), mock.patch.object(models, 'STATE_DIR', Path(self.workdir.name) / 'state'):
            with self.assertRaises(CyToolError) as ctx:
                models.install('fake.model')
            self.assertEqual(ctx.exception.code, 'LicenseAcceptanceRequired')
            self.assertTrue(ctx.exception.recoverable)
            self.assertEqual(ctx.exception.details['licenseUrl'], 'https://example.invalid/licence')
            self.assertEqual(ctx.exception.details['modelId'], 'fake.model')
            state = models.read_state('fake.model')
            self.assertEqual(state['state'], 'LicenseAcceptanceRequired')
            info = models.status('fake.model')
            self.assertEqual(info['state'], 'LicenseAcceptanceRequired')
            self.assertFalse(info['installed'])
            self.assertEqual(info['license']['name'], 'Gated licence')
        self.assertFalse((self.root / 'c.bin').exists())                         # nothing was downloaded
        with mock.patch.object(models, 'get', return_value=fake_model(self.root, self.files, source={'repository': 'x/y', 'revision': 'r'})):
            self.assertEqual(models.file_url(models.get('x'), {'path': 'sub/w.bin'}), 'https://huggingface.co/x/y/resolve/r/sub/w.bin')
            self.assertEqual(models.file_url(models.get('x'), {'path': 'w.bin', 'url': 'https://direct/w'}), 'https://direct/w')
        self.assertEqual(models.file_url({'source': {'baseUrl': 'https://base/'}}, {'path': 'a', 'remotePath': 'r/a'}), 'https://base/r/a')

    def test_state_file_round_trip(self):
        with mock.patch.object(models, 'STATE_DIR', Path(self.workdir.name) / 'state'):
            self.assertEqual(models.read_state('fake.model'), {})
            models.write_state('fake.model', state='Downloading', progress={'doneBytes': 1})
            value = models.write_state('fake.model', message='m')
            self.assertEqual((value['state'], value['progress'], value['message']), ('Downloading', {'doneBytes': 1}, 'm'))
            self.assertIn('updatedAt', value)
            self.assertEqual(models.state_path('a:b/c').name, 'a_b_c.json')
            self.assertEqual([p.suffix for p in (Path(self.workdir.name) / 'state').iterdir()], ['.json'])   # no temp file left


class ManifestModelsTests(unittest.TestCase):
    def test_manifest_models_fields(self):
        for backend in ('audioldm', 'acestep', 'piper', 'qwen3tts', 'fishspeech'):
            entries = models.manifest_models(backend)
            self.assertTrue(entries, backend)
            for entry in entries:
                self.assertRegex(entry['id'], ID_PATTERN)
                for key in ('id', 'name', 'version', 'source', 'license', 'licenseUrl', 'location'):
                    self.assertIsInstance(entry[key], str, f'{backend}:{entry["id"]}.{key}')
                self.assertTrue(entry['version'])
                self.assertLessEqual(len(entry['version']), 12)
                self.assertEqual(entry['location'], 'Local')
                self.assertTrue(entry['runsLocally'])
                self.assertIsInstance(entry['installed'], bool)
                for key in ('downloadSize', 'installedSize'):
                    self.assertIsInstance(entry[key], int)
                    self.assertGreater(entry[key], 0)
                self.assertIsInstance(entry['resourceRequirements']['ramBytes'], int)
                if 'vramBytes' in entry['resourceRequirements']:
                    self.assertIsInstance(entry['resourceRequirements']['vramBytes']['auto'], int)
        self.assertEqual(len(models.manifest_models('qwen3tts')), 5)
        piper = models.manifest_models('piper')
        self.assertIn('piper.fr_FR-siwis-medium', [e['id'] for e in piper])
        self.assertLess(len(piper), len(models.by_backend('piper')))          # voices without a folder are not listed
        self.assertEqual(models.manifest_models('nope'), [])


if __name__ == '__main__':
    unittest.main()
