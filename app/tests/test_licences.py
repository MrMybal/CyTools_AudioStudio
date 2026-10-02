"""The SDK that is installed, its licence, the LICENCES folder and the SDK 0.10 scheduler contract (run from the app directory)."""
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tests._fixtures import APP
from cytools_core import load_manifest
from cytools_core.workers import worker_activity
from audiostudio.backends import registry as backends
from audiostudio.engines.workerhost import WorkerHost
import maintenance

sys.path.insert(0, str(APP / 'scripts'))
import build_licences  # noqa: E402

ROOT = APP.parent


class InstalledSdkTests(unittest.TestCase):
    def test_installed_sdk_is_the_pinned_mit_release(self):
        distribution = importlib.metadata.distribution('cytools-core')
        self.assertEqual(distribution.version, build_licences.SDK_VERSION)
        self.assertEqual(distribution.metadata.get('License-Expression'), 'MIT')

    def test_pins_agree(self):
        requirements = (APP / 'requirements.txt').read_text('utf-8')
        self.assertIn('cytools-core[mcp]==' + build_licences.SDK_VERSION, requirements)
        for path in (APP / 'requirements.txt', APP / 'README.md', ROOT / 'README.md'):
            self.assertIn(build_licences.SDK_REQUIREMENT, path.read_text('utf-8'), path.name)
        abi = json.loads((APP / 'release.json').read_text('utf-8'))['runtime_abi']
        self.assertIn('core' + build_licences.SDK_VERSION.replace('.', '') + '-', abi)


class LicencesFolderTests(unittest.TestCase):
    def test_folder_matches_the_installed_sdk(self):
        for path, text in build_licences.documents().items():
            self.assertTrue(path.is_file(), path)
            self.assertEqual(path.read_text('utf-8'), text, f'{path.name} is stale: run scripts/build_licences.py')

    def test_sdk_licence_is_the_full_unchanged_text(self):
        distribution = importlib.metadata.distribution('cytools-core')
        shipped = [entry for entry in distribution.files if entry.name == 'LICENSE' and '.dist-info' in str(entry)]
        self.assertEqual(len(shipped), 1)
        original = distribution.locate_file(shipped[0]).read_bytes().replace(b'\r\n', b'\n')
        for name in ('CyToolsCore-MIT.txt', 'LICENSE-CyToolsCore.txt'):
            self.assertEqual((ROOT / 'LICENCES' / name).read_bytes().replace(b'\r\n', b'\n'), original, name)
        self.assertIn(b'Copyright (c) 2026 Cyberalien', original)
        self.assertIn(b'Permission is hereby granted, free of charge', original)

    def test_product_keeps_its_own_licence(self):
        self.assertIn('GNU GENERAL PUBLIC LICENSE', (ROOT / 'LICENSE').read_text('utf-8')[:400])
        self.assertTrue(load_manifest(APP / 'CyTool.json')['license'].startswith('GPL-3.0-only'))
        entries = {entry['kind']: entry for entry in json.loads((APP / 'licenses.json').read_text('utf-8'))}
        self.assertEqual(entries['Application']['license'], 'GPL-3.0-only')
        self.assertEqual(entries['SDK']['license'], 'MIT')

    def test_sources_name_the_repositories_and_the_revision(self):
        sources = (ROOT / 'LICENCES' / 'SOURCES.txt').read_text('utf-8')
        for needle in (build_licences.SDK_REPOSITORY, build_licences.SDK_REVISION, build_licences.UNREAL_SDK_REPOSITORY,
                       build_licences.PRODUCT_REPOSITORY, 'UpdateExistingProducts.md', 'AgentGuide.md'):
            self.assertIn(needle, sources)

    def test_stale_folder_is_detected(self):
        """The check above can fail: a changed notice is reported."""
        with mock.patch.object(build_licences, 'notices_text', return_value='changed'):
            stale = [path.name for path, text in build_licences.documents().items() if path.read_text('utf-8') != text]
        self.assertEqual(stale, ['ThirdParty-Notices.txt'])

    def test_python_package_index_refuses_another_sdk(self):
        text, rows = build_licences.python_packages(sys.executable, Path(sys.prefix), 'runtime/python')
        core = next(row for row in rows if row['name'].lower().replace('_', '-') == 'cytools-core')
        self.assertEqual((core['version'], core['licence']), (build_licences.SDK_VERSION, 'MIT'))
        self.assertIn('runtime/python/' + core['texts'][0], text)
        with mock.patch.object(build_licences, 'SDK_VERSION', '0.9.0'), self.assertRaises(RuntimeError):
            build_licences.python_packages(sys.executable, Path(sys.prefix), 'runtime/python')


class UpdaterLicencesTests(unittest.TestCase):
    def test_application_update_refreshes_licences_and_keeps_the_previous_ones(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'LICENCES').mkdir()
            (root / 'LICENCES' / 'SOURCES.txt').write_text('old', 'utf-8')
            (root / 'LICENCES' / 'PythonPackages.txt').write_text('runtime index', 'utf-8')
            staged = root / 'stage' / 'LICENCES'
            staged.mkdir(parents=True)
            (staged / 'SOURCES.txt').write_text('new', 'utf-8')
            (staged / 'CyToolsCore-MIT.txt').write_text('mit', 'utf-8')
            (staged / 'PythonPackages.txt').write_text('must not replace the runtime index', 'utf-8')
            with mock.patch.object(maintenance, 'ROOT', root):
                maintenance.sync_licences(staged, keep=root / 'backup.LICENCES')
                maintenance.sync_licences(root / 'absent')                       # a release without the folder changes nothing
            self.assertEqual((root / 'LICENCES' / 'SOURCES.txt').read_text('utf-8'), 'new')
            self.assertEqual((root / 'LICENCES' / 'CyToolsCore-MIT.txt').read_text('utf-8'), 'mit')
            self.assertEqual((root / 'LICENCES' / 'PythonPackages.txt').read_text('utf-8'), 'runtime index')
            self.assertEqual((root / 'backup.LICENCES' / 'SOURCES.txt').read_text('utf-8'), 'old')


class SchedulerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.operations = {op['id']: op for op in load_manifest(APP / 'CyTool.json')['operations']}

    def groups(self, operation_id):
        return set(self.operations[operation_id].get('exclusiveGroups', []))

    def test_every_gpu_operation_shares_the_gpu_group(self):
        gpu_backends = {b.id for b in backends.BACKENDS.values() if b.engine == 'torch'}
        self.assertTrue(gpu_backends)
        for op in self.operations.values():
            if gpu_backends & set(op.get('supportedBackends', [])):
                self.assertIn('gpu', self.groups(op['id']), op['id'])
                self.assertIn('engine_torch', self.groups(op['id']), op['id'])

    def test_engine_maintenance_excludes_every_engine_operation(self):
        for op in self.operations.values():
            engines_used = {backends.BACKENDS[b].engine for b in op.get('supportedBackends', [])} - {''}
            for engine in engines_used:
                self.assertTrue(self.groups(op['id']) & self.groups('install_engine'), op['id'])
                self.assertIn('engine_' + engine, self.groups('install_engine'))
        for maintenance_op in ('release_workers', 'diagnose_backend'):
            self.assertLessEqual({'gpu', 'engine_torch', 'engine_piper'}, self.groups(maintenance_op))
        self.assertTrue(self.groups('remove_model') & self.groups('generate_music'))
        self.assertTrue(self.groups('remove_model') & self.groups('voice_piper'))

    def test_editing_and_listing_stay_unconstrained(self):
        for operation_id in ('process_audio', 'batch_session', 'render_session', 'convert_audio', 'list_effects', 'list_models', 'engine_status'):
            self.assertEqual(self.groups(operation_id), set(), operation_id)

    def test_runtime_status_can_observe_the_worker_hosts(self):
        """GetRuntimeStatus counts a worker through process / state: the host must never be 'unknown'."""
        host = WorkerHost('probe', [sys.executable, '-c', 'import time; time.sleep(30)'])
        self.assertIs(worker_activity(host), False)                      # never started
        for state, expected in (('Busy', True), ('Idle', True), ('Stopped', False), ('Failed', False)):
            host.state = state
            self.assertIs(worker_activity(host), expected, state)


if __name__ == '__main__':
    unittest.main()
