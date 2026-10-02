"""Workflow documents (model) and the render engine (run from the app directory)."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tests._fixtures import tone, write_wav, CYDAW_PLUGIN, cydaw_available, rms_db
from audiostudio import audio_io
from audiostudio.workflow import model, engine

RATE = 48000


def effect(effect_id, params=None, **fields):
    return {'kind': 'effect', 'effect': effect_id, 'params': params or {}, **fields}


class WorkflowModelTests(unittest.TestCase):
    def test_new_workflow_normalizes(self):
        document = model.new_workflow('Test', nodes=[effect('highpass', {'cutoff_hz': 120}), {'kind': 'model', 'model': 'denoise.x', 'mix': 5}])
        self.assertEqual(document['format'], model.FORMAT)
        self.assertEqual(document['schemaVersion'], model.SCHEMA_VERSION)
        self.assertEqual(document['name'], 'Test')
        self.assertEqual(document['tail'], model.normalize_tail(None))
        self.assertEqual(len(document['nodes']), 2)
        first = document['nodes'][0]
        self.assertEqual(first['params'], {'cutoff_hz': 120.0})
        self.assertTrue(first['enabled'])
        self.assertEqual(first['mix'], 1.0)
        self.assertTrue(first['id'])
        self.assertEqual(document['nodes'][1]['mix'], 1.0)  # clamped
        self.assertEqual(model.validate(document)['nodes'], model.validate(model.validate(document))['nodes'])
        node = model.new_node('effect', effect='gain', params={'gain_db': -3})
        self.assertEqual(node['params'], {'gain_db': -3.0})
        self.assertEqual(len(node['id']), 8)

    def test_validate_rejects(self):
        base = model.new_workflow('Base')
        cases = {
            'unknown effect': {**base, 'nodes': [effect('does_not_exist')]},
            'bad kind': {**base, 'nodes': [{'kind': 'plugin', 'plugin': 'x'}]},
            'duplicate ids': {**base, 'nodes': [effect('gain', id='n1'), effect('gain', id='n1')]},
            'wrong format': {**base, 'format': 'something-else'},
            'wrong version': {**base, 'schemaVersion': 2},
            'too many nodes': {**base, 'nodes': [effect('gain') for _ in range(model.MAX_NODES + 1)]},
            'nodes not a list': {**base, 'nodes': {'a': 1}},
            'not an object': [],
            'vst3 without plugin': {**base, 'nodes': [{'kind': 'vst3'}]},
            'vst3 state not text': {**base, 'nodes': [{'kind': 'vst3', 'plugin': 'x.vst3', 'state': 12}]},
            'model bad id': {**base, 'nodes': [{'kind': 'model', 'model': 'Bad Id!'}]},
            'node not an object': {**base, 'nodes': ['gain']},
            'mix not a number': {**base, 'nodes': [effect('gain', mix='loud')]},
        }
        for label, document in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(model.WorkflowError):
                    model.validate(document)
        self.assertEqual(len(model.validate({**base, 'nodes': [effect('gain') for _ in range(model.MAX_NODES)]})['nodes']), model.MAX_NODES)

    def test_save_load_loads_and_dumps(self):
        document = model.new_workflow('Chain', nodes=[effect('delay', {'delay_seconds': 0.2}), {'kind': 'vst3', 'plugin': 'C:/x/Plugin.vst3', 'params': {'gain': 0.5, 'nested': {'a': 1}}, 'state': 'AAAA'}])
        with tempfile.TemporaryDirectory() as workdir:
            path = model.save(Path(workdir) / 'sub' / 'chain.json', document)
            self.assertTrue(path.is_file())
            self.assertEqual([p.name for p in path.parent.iterdir()], ['chain.json'])  # no temp file left
            loaded = model.load(path)
            self.assertEqual(loaded['name'], 'Chain')
            self.assertEqual(loaded['nodes'][0]['params']['delay_seconds'], 0.2)
            self.assertEqual(loaded['nodes'][1]['params'], {'gain': 0.5})   # non-scalar dropped
            self.assertEqual(loaded['nodes'][1]['state'], 'AAAA')
            self.assertEqual(loaded['nodes'][1]['pluginName'], '')
            self.assertEqual(model.loads(model.dumps(loaded))['nodes'], loaded['nodes'])
            with self.assertRaises(model.WorkflowError):
                model.loads('{not json')
            with self.assertRaises(model.WorkflowError):
                model.loads('{"format": "x"}')
            big = Path(workdir) / 'big.json'
            big.write_text(' ' * (8 * 1024 * 1024 + 1) + '{}', encoding='utf-8')
            with self.assertRaises(model.WorkflowError):
                model.load(big)
            (Path(workdir) / 'broken.json').write_text('[]', encoding='utf-8')
            entries = model.list_workflows(workdir)
            names = {e['name']: e for e in entries}
            self.assertIn('broken', names)
            self.assertIn('error', names['broken'])
            self.assertEqual(model.list_workflows(Path(workdir) / 'nope'), [])
            listed = model.list_workflows(path.parent)
            self.assertEqual(listed[0]['name'], 'Chain')
            self.assertEqual(listed[0]['nodes'], 2)

    def test_summary_and_safe_name(self):
        document = model.new_workflow('S', nodes=[effect('highpass'), {'kind': 'vst3', 'plugin': 'C:/x/Tool.vst3'}, {'kind': 'vst3', 'plugin': 'C:/x/Y.vst3', 'pluginName': 'Named'},
                                                  {'kind': 'model', 'model': 'denoise.deep'}, effect('gain', enabled=False)])
        self.assertEqual(model.summary(document), 'highpass > vst3:Tool > vst3:Named > model:denoise.deep')
        self.assertEqual(model.summary(model.new_workflow('E')), '(empty)')
        self.assertEqual(model.safe_name('  My/Chain: v2 ?.. '), 'My_Chain_ v2')
        self.assertEqual(model.safe_name('a/b\\c'), 'a_b_c')
        self.assertEqual(model.safe_name('***'), 'workflow')
        self.assertEqual(len(model.safe_name('x' * 200)), 80)


class RenderEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audio = tone(0.5, RATE, 2)

    def test_chain_of_stateful_and_stateless_nodes(self):
        workflow = model.new_workflow('Chain', nodes=[effect('gain', {'gain_db': -12.0}), effect('normalize', {'target_db': -1.0}), effect('invert')],
                                      tail={'max_seconds': 1.0})
        steps = []
        result = engine.render(self.audio, RATE, workflow, progress=lambda fraction, text: steps.append((fraction, text)))
        self.assertEqual(result.samplerate, RATE)
        self.assertEqual(result.audio.dtype, np.float32)
        self.assertEqual(result.original_frames, self.audio.shape[1])
        self.assertEqual(result.audio.shape, self.audio.shape)          # silent extension trimmed away
        self.assertEqual(result.tail_seconds, 0.0)
        self.assertAlmostEqual(float(np.abs(result.audio).max()), 10 ** (-1 / 20), delta=0.02)
        expected = -self.audio * (10 ** (-1 / 20) / float(np.abs(self.audio).max()))
        self.assertTrue(np.allclose(result.audio, expected, atol=1e-3))
        self.assertEqual([n['label'] for n in result.nodes], ['gain', 'normalize', 'invert'])
        self.assertEqual(steps[-1], (1.0, 'done'))
        self.assertEqual(len(steps), 4)
        # A filter's ring-down after the input ends is a real (short) tail, kept by the extension.
        ringing = engine.render(self.audio, RATE, model.new_workflow('HP', nodes=[effect('highpass', {'cutoff_hz': 40.0})], tail={'max_seconds': 1.0}))
        self.assertGreaterEqual(ringing.audio.shape[1], self.audio.shape[1])
        self.assertLess(ringing.tail_seconds, 0.1)
        report = result.report()
        for key in ('samplerate', 'frames', 'channels', 'originalFrames', 'durationSeconds', 'tailSeconds', 'nodes', 'renderSeconds'):
            self.assertIn(key, report)
        json.dumps(report)

    def test_tail_extension_measured(self):
        workflow = model.new_workflow('Delay', nodes=[effect('delay', {'delay_seconds': 0.25, 'feedback': 0.5, 'mix': 0.5})], tail={'max_seconds': 4.0, 'threshold_db': -60.0})
        result = engine.render(self.audio, RATE, workflow)
        self.assertGreater(result.tail_seconds, 0.25)
        self.assertGreater(result.audio.shape[1], self.audio.shape[1])
        self.assertLess(result.audio.shape[1], self.audio.shape[1] + 4 * RATE)
        self.assertAlmostEqual(result.report()['durationSeconds'], result.audio.shape[1] / RATE)
        disabled = engine.render(self.audio, RATE, model.new_workflow('D', nodes=[effect('delay')], tail={'enabled': False}))
        self.assertEqual(disabled.audio.shape, self.audio.shape)
        self.assertEqual(disabled.tail_seconds, 0.0)

    def test_disabled_node_is_skipped(self):
        workflow = model.new_workflow('Skip', nodes=[effect('silence', enabled=False), effect('gain', {'gain_db': 0.0})])
        result = engine.render(self.audio, RATE, workflow)
        self.assertTrue(np.allclose(result.audio, self.audio, atol=1e-6))
        self.assertEqual([n['label'] for n in result.nodes], ['gain'])

    def test_mix_zero_leaves_audio_unchanged(self):
        workflow = model.new_workflow('Dry', nodes=[effect('gain', {'gain_db': -60.0}, mix=0.0), effect('silence', mix=0.0)])
        result = engine.render(self.audio, RATE, workflow)
        self.assertEqual(result.audio.shape, self.audio.shape)
        self.assertTrue(np.allclose(result.audio, self.audio, atol=1e-6))
        half = engine.render(self.audio, RATE, model.new_workflow('Half', nodes=[effect('silence', mix=0.5)]))
        self.assertTrue(np.allclose(half.audio, self.audio * 0.5, atol=1e-6))

    def test_resample_node_changes_samplerate(self):
        workflow = model.new_workflow('Rate', nodes=[effect('resample', {'target_rate': 24000}), effect('delay', {'delay_seconds': 0.1, 'feedback': 0.0, 'mix': 0.5})], tail={'max_seconds': 1.0})
        result = engine.render(self.audio, RATE, workflow)
        self.assertEqual(result.samplerate, 24000)
        self.assertEqual(result.original_frames, self.audio.shape[1] // 2)
        self.assertGreaterEqual(result.audio.shape[1], self.audio.shape[1] // 2)
        stretched = engine.render(self.audio, RATE, model.new_workflow('Stretch', nodes=[effect('time_stretch', {'stretch_factor': 2.0})]))
        self.assertAlmostEqual(stretched.audio.shape[1] / self.audio.shape[1], 0.5, delta=0.05)
        self.assertEqual(stretched.samplerate, RATE)

    def test_model_node_needs_runner(self):
        workflow = model.new_workflow('Model', nodes=[{'kind': 'model', 'model': 'denoise.fake'}])
        with self.assertRaises(engine.UnsupportedNode):
            engine.render(self.audio, RATE, workflow)
        seen = []

        def runner(node, audio, rate, progress):
            seen.append((node['model'], rate))
            progress(0.5, 'half')
            return audio_io.resample(audio * 0.5, rate, 24000), 24000
        result = engine.render(self.audio, RATE, workflow, model_runner=runner)
        self.assertEqual(seen, [('denoise.fake', RATE)])
        self.assertEqual(result.samplerate, 24000)
        self.assertEqual(result.original_frames, self.audio.shape[1] // 2)
        self.assertAlmostEqual(rms_db(result.audio) - rms_db(self.audio), -6.02, delta=0.3)

    def test_cancellation(self):
        calls = {'n': 0}

        def cancel():
            calls['n'] += 1
            return calls['n'] >= 2
        workflow = model.new_workflow('Cancel', nodes=[effect('gain'), effect('gain'), effect('gain')])
        with self.assertRaises(engine.RenderCancelled):
            engine.render(self.audio, RATE, workflow, cancel=cancel)
        self.assertEqual(calls['n'], 2)
        with self.assertRaises(engine.RenderCancelled):
            engine.render(self.audio, RATE, model.new_workflow('Empty'), cancel=lambda: True)

    @unittest.skipUnless(cydaw_available(), 'CyDAW Test Gain.vst3 is not built on this machine')
    def test_vst3_node_processes_audio(self):
        cache = engine.PluginCache()
        levels = {}
        for gain in (1.0, 0.25):
            workflow = model.new_workflow('VST', nodes=[{'kind': 'vst3', 'plugin': str(CYDAW_PLUGIN), 'params': {'gain_x': gain}}], tail={'max_seconds': 0.5})
            result = engine.render(self.audio, RATE, workflow, plugin_cache=cache)
            self.assertEqual(result.audio.shape, self.audio.shape)
            self.assertTrue(np.isfinite(result.audio).all())
            self.assertEqual(result.nodes[0]['kind'], 'vst3')
            levels[gain] = rms_db(result.audio)
        self.assertAlmostEqual(levels[1.0], rms_db(self.audio), delta=0.1)
        self.assertAlmostEqual(levels[1.0] - levels[0.25], 20 * np.log10(4), delta=0.5)
        self.assertEqual(len(cache.plugins), 1)     # one instance reused across renders
        # The bundle folder and the inner DLL resolve to the same cache entry.
        from audiostudio.vst import host
        self.assertEqual(host.bundle_path(host.loadable_path(CYDAW_PLUGIN)), CYDAW_PLUGIN)
        cache.get(host.loadable_path(CYDAW_PLUGIN))
        self.assertEqual(len(cache.plugins), 1)

    def test_render_file_writes_a_file(self):
        with tempfile.TemporaryDirectory() as workdir:
            source = write_wav(Path(workdir) / 'in.wav', self.audio, RATE)
            workflow = model.new_workflow('File', nodes=[effect('delay', {'delay_seconds': 0.2, 'feedback': 0.4, 'mix': 0.5})], tail={'max_seconds': 2.0})
            result, written = engine.render_file(source, Path(workdir) / 'out.flac', workflow, fmt='flac', subtype='PCM_16')
            self.assertTrue(written.is_file())
            info = audio_io.probe(written)
            self.assertEqual(info.format, 'FLAC')
            self.assertEqual(info.frames, result.audio.shape[1])
            self.assertGreater(info.duration, 0.5)
            self.assertGreater(result.tail_seconds, 0.0)



class ProcessorNodeTests(unittest.TestCase):
    def test_block_processors_render_in_workflows_with_a_tail(self):
        from audiostudio.workflow import engine
        audio = np.zeros((2, 9600), np.float32)                             # 0.2 s: the 1 s reverb must ring past the end
        audio[:, :200] = 0.8
        document = model.new_workflow('chain', nodes=[model.new_node('effect', effect='compressor', params={'threshold_db': -10.0}),
                                                      model.new_node('effect', effect='ir_reverb', params={'decay_seconds': 1.0, 'mix': 0.5})],
                                       tail={'enabled': True, 'threshold_db': -60.0, 'max_seconds': 5.0, 'hold_seconds': 0.1})
        result = engine.render(audio, 48000, document)
        self.assertGreater(result.audio.shape[1], audio.shape[1])          # the reverb tail was kept
        self.assertGreater(result.tail_seconds, 0.1)
        self.assertEqual([n['kind'] for n in result.nodes], ['effect', 'effect'])

if __name__ == '__main__':
    unittest.main()
