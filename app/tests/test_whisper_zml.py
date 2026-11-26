"""Whisper ZML worker routing, placement and errors without model weights."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

import psutil

from cytools_core import CyToolError

from audiostudio.engines import registry
from audiostudio.engines.workerhost import WorkerHost
from tests._fixtures import APP


LAUNCHER = """
import json
import os
import sys
import time
from pathlib import Path

args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
assert Path(args['--audio']).is_file()
assert Path(args['--workspace']).parent == Path(os.environ['TEST_JOB_WORKSPACE'])
assert args['--profile'] == 'large_v3_turbo'
assert args['--language'] == 'auto'
device = args['--backend']
if device == 'cpu':
    assert args['--expected-device'] == 'cpu:0'
elif args['--expected-device'] == 'Test GPU':
    assert device == 'cuda'
print('fixture diagnostics', file=sys.stderr)
if os.environ.get('TEST_WAIT_FOR_CANCELLATION'):
    (Path(os.environ['TEST_JOB_WORKSPACE']) / 'launcher.pid').write_text(str(os.getpid()))
    time.sleep(60)
if os.environ.get('TEST_WRONG_PLATFORM'):
    device = 'cpu'
print(json.dumps({'text': 'Bonjour.', 'segments': [{'start': 0, 'end': 0.1, 'text': 'Bonjour.'}],
                  'language': 'fr', 'duration': 0.1, 'complete': True,
                  'placement': {'backend': device, 'pjrt': 'iree_cuda' if device == 'cuda' else 'cpu',
                                'device': 'Test GPU' if device == 'cuda' else 'cpu:0', 'shards': 1}}))
"""


class WhisperZmlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.logs = root / 'worker.log'
        self.workspace = root / 'job'
        self.workspace.mkdir()
        audio = root / 'speech.wav'
        with wave.open(str(audio), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(bytes(3200))
        launcher = root / 'fake_transcribe.py'
        launcher.write_text(LAUNCHER, encoding='utf-8')
        probe = root / 'whisper_probe.exe'
        probe.touch()
        weights = root / 'weights'
        weights.mkdir()
        for part in ('encoder', 'decoder'):
            (weights / f'{part}.safetensors').touch()
        self.config = root / 'runtime.json'
        self.config.write_text(json.dumps({'launcher': str(launcher), 'probe': str(probe), 'weights': str(weights),
                                           'expected_cuda_device': 'Test GPU'}), encoding='utf-8')
        self.params = {'input': str(audio), 'model_dir': str(root), 'workspace': str(self.workspace)}

    def host(self, *, configured=True, wrong_platform=False, wait_for_cancellation=False):
        env = registry.base_environment()
        env['TEST_JOB_WORKSPACE'] = str(self.workspace)
        env.pop('CYTOOLS_WHISPER_ZML_CONFIG', None)
        if configured:
            env['CYTOOLS_WHISPER_ZML_CONFIG'] = str(self.config)
        if wrong_platform:
            env['TEST_WRONG_PLATFORM'] = '1'
        if wait_for_cancellation:
            env['TEST_WAIT_FOR_CANCELLATION'] = '1'
        host = WorkerHost('whisper', [sys.executable, '-B', APP / 'workers/whisper_worker.py'],
                          cwd=APP, env=env, log_path=self.logs, idle_seconds=0)
        self.addCleanup(host.stop)
        return host

    def test_auto_and_explicit_devices_preserve_language_and_segments(self):
        host = self.host()
        for runtime, device, platform in [('auto', 'cpu', 'cpu'), ('zml', 'cuda', 'iree_cuda')]:
            with self.subTest(runtime=runtime, device=device):
                report = host.request('transcribe', {**self.params, 'runtime': runtime, 'device': device})
                self.assertEqual(report['runtime'], 'zml')
                self.assertEqual(report['language'], 'fr')
                self.assertEqual(report['durationSeconds'], 0.1)
                self.assertEqual(report['segments'], [{'start': 0, 'end': 0.1, 'text': 'Bonjour.'}])
                self.assertEqual(report['placement']['pjrt'], platform)
                self.assertEqual(list(self.workspace.iterdir()), [])

    def test_explicit_zml_requires_config(self):
        with self.assertRaises(CyToolError) as error:
            self.host(configured=False).request('transcribe', {**self.params, 'runtime': 'zml', 'device': 'cpu'})
        self.assertEqual(error.exception.code, 'MissingDependency')

    def test_cuda_rejects_a_cpu_result(self):
        with self.assertRaises(CyToolError) as error:
            self.host(wrong_platform=True).request('transcribe', {**self.params, 'runtime': 'zml', 'device': 'cuda'})
        self.assertEqual(error.exception.code, 'InferenceFailed')
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_cancellation_stops_the_launcher(self):
        marker = self.workspace / 'launcher.pid'
        host = self.host(wait_for_cancellation=True)
        with self.assertRaises(CyToolError) as error:
            host.request('transcribe', {**self.params, 'runtime': 'zml', 'device': 'cpu'},
                         cancelled=lambda: marker.is_file() and bool(marker.stat().st_size), timeout=30)
        self.assertEqual(error.exception.code, 'Cancelled')
        self.assertFalse(psutil.pid_exists(int(marker.read_text(encoding='ascii'))))


if __name__ == '__main__':
    unittest.main()
