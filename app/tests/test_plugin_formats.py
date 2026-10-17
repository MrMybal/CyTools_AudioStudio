"""Real native worker tests; synthetic JSFX, optional external CLAP/LV2 fixtures."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from audiostudio.vst import host
from audiostudio.plugins.native import NativePlugin, worker_executable
from audiostudio.plugins import scripts
from audiostudio.workflow import engine, model
from audiostudio.editor.document import Document
from audiostudio.editor.renderer import Renderer
from tests._fixtures import APP

SOURCE = """desc:AudioStudio Test Gain
slider1:1<0,1,0.001>Gain
@sample
spl0 *= slider1; spl1 *= slider1;
"""


def native_available():
    try:
        return worker_executable().is_file()
    except RuntimeError:
        return False


class DiscoveryTests(unittest.TestCase):
    def test_formats_bundles_and_extensionless_jsfx(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'One.clap').write_bytes(b'not loaded during discovery')
            (root / 'Two.lv2').mkdir()
            (root / 'Two.lv2' / 'manifest.ttl').write_text('fixture')
            (root / 'Three.vst3').mkdir()
            (root / 'Four.jsfx').write_text(SOURCE)
            (root / 'Five').write_text(SOURCE)
            (root / 'ignore').write_text('not a plugin')
            self.assertEqual({p.name for p in host.find_bundles([root, root])}, {'One.clap', 'Two.lv2', 'Three.vst3', 'Four.jsfx', 'Five'})
            self.assertEqual(host.plugin_format(root / 'Five'), 'jsfx')
            before = host.cache_key(root / 'Two.lv2')
            (root / 'Two.lv2' / 'manifest.ttl').write_text('changed fixture')
            self.assertNotEqual(before, host.cache_key(root / 'Two.lv2'))

    def test_new_document_kinds_and_legacy_vst3_survive_roundtrip(self):
        nodes = [model.new_node(k, plugin='fixture.' + k, params={'p0': .25}, state='') for k in host.PLUGIN_KINDS]
        result = model.loads(model.dumps(model.new_workflow('Formats', nodes=nodes)))
        self.assertEqual([n['kind'] for n in result['nodes']], list(host.PLUGIN_KINDS))


@unittest.skipUnless(native_available(), 'Build app/scripts/build_plugin_host.py first')
class NativeJsfxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='audiostudio-test-jsfx-')
        self.folder = Path(self.temp.name)
        self.script = self.folder / 'Gain.jsfx'
        self.script.write_text(SOURCE, 'utf-8')
        self.audio = np.full((2, 4097), .1, np.float32)

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_bad_binary_is_isolated_and_successful_script_is_cached(self):
        from workers.dsp_worker import scan
        reporter = mock.Mock()
        (self.folder / 'Broken.clap').write_bytes(b'not a native plugin')
        request = {'directories':[str(self.folder)], 'cache_dir':str(self.folder / 'catalogue')}
        first = scan(request, reporter)
        self.assertEqual(len(first['failures']), 1)
        self.assertEqual(len([p for p in first['plugins'] if p.get('state') == 'ok']), 1)
        second = scan(request, reporter)
        self.assertEqual(len(second['plugins']), 2)
        self.assertEqual(len(second['failures']), 1)
        self.assertTrue(host.read_cache(self.folder / 'catalogue')['plugins'])

    def test_audio_parameters_state_samplerate_and_isolated_instances(self):
        a, b = host.load(self.script), host.load(self.script)
        try:
            host.apply_settings(a, {'p0': .25})
            saved = host.capture(a)
            self.assertTrue(saved['state'])
            for rate in (48000, 44100):
                np.testing.assert_allclose(host.process(a, self.audio, rate), self.audio * .25, atol=1e-7)
                np.testing.assert_allclose(host.process(b, self.audio, rate), self.audio, atol=1e-7)
            host.apply_settings(a, {'p0': .8})
            host.apply_settings(a, None, saved['state'])
            np.testing.assert_allclose(host.process(a, self.audio, 44100), self.audio * .25, atol=1e-7)
        finally:
            a.close()
            b.close()

    def test_renderer_automation_and_session_roundtrip(self):
        doc = Document(48000)
        track = doc.add_track(self.audio)
        node = doc.add_insert(track, model.new_node('jsfx', plugin=str(self.script), params={'p0': .25}))
        doc.automation_add(track, node['id'] + '.p0', 0, .5)
        renderer = Renderer(doc)
        try:
            np.testing.assert_allclose(renderer.render(0, 512), self.audio[:, :512] * .5, atol=1e-7)
            self.assertFalse(renderer.errors)
            saved = doc.save_session(self.folder / 'session')
            loaded = Document.load_session(saved)
            self.assertEqual(loaded.tracks[0].inserts[0]['kind'], 'jsfx')
        finally:
            renderer.forget(node['id'])
        self.assertFalse(renderer.plugins)

    def test_workflow_instances_and_tail(self):
        source = """desc:Test echo
@init
prev0=0;prev1=0;
@sample
v0=spl0;v1=spl1;
spl0+=prev0*0.999;spl1+=prev1*0.999;
prev0=spl0;prev1=spl1;
"""
        self.script.write_text(source)
        workflow = model.new_workflow('Tail', nodes=[model.new_node('jsfx', plugin=str(self.script))], tail={'max_seconds': .05})
        impulse = np.zeros((2, 8), np.float32)
        impulse[:, -1] = .5
        result = engine.render(impulse, 48000, workflow)
        self.assertGreater(result.audio.shape[1], impulse.shape[1])
        self.assertGreater(result.tail_seconds, 0)
        self.assertLess(result.audio.shape[1], 3000)

    def test_compile_failure_preserves_script_and_imports(self):
        (self.folder / 'math.jsfx-inc').write_text('@init\nfunction scale(x) (x * 0.5);')
        valid = 'desc:Imports\nimport math.jsfx-inc\n@sample\nspl0=scale(spl0);spl1=scale(spl1);\n'
        self.assertTrue(scripts.validate_source(valid, self.folder)['valid'])
        with mock.patch.object(scripts, 'SCRIPT_DIRECTORY', self.folder):
            scripts.save_source('Saved', SOURCE)
            before = (self.folder / 'Saved.jsfx').read_bytes()
            with self.assertRaises(RuntimeError):
                scripts.save_source('Saved', 'desc:Broken\n@sample\nthis is ( broken ???', True)
            self.assertEqual(before, (self.folder / 'Saved.jsfx').read_bytes())
        self.assertFalse(list(self.folder.glob('.audiostudio-*')))

    def test_native_editor_can_open_and_close_without_touching_app(self):
        plugin = host.load(self.script)
        try:
            plugin._command(5)
            plugin._command(1)
            self.assertEqual(plugin._get(6, 'H'), 1)
            plugin._command(6)
            plugin._command(1)
            self.assertEqual(plugin._get(6, 'H'), 0)
        finally:
            plugin.close()

    def test_worker_crash_is_reported_and_other_instance_survives(self):
        a, b = host.load(self.script), host.load(self.script)
        try:
            a._process.kill()
            a._process.wait(timeout=3)
            with self.assertRaises(RuntimeError):
                host.process(a, self.audio, 48000, reset=False)
            np.testing.assert_allclose(host.process(b, self.audio, 48000), self.audio, atol=1e-7)
        finally:
            a.close()
            b.close()


@unittest.skipUnless(native_available(), 'Build native worker first')
class ExternalFormatTests(unittest.TestCase):
    def check_format(self, variable, kind):
        path = os.environ.get(variable)
        if not path:
            self.skipTest('Set ' + variable + ' to the native CyCrossGain test export')
        info = host.describe(path)
        self.assertEqual(info['format'], kind.upper())
        plugin = host.load(path)
        audio = np.full((2, 4097), .1, np.float32)
        try:
            plugin._command(5)
            plugin._command(1)
            self.assertEqual(plugin._get(6, 'H'), 1)
            plugin._command(6)
            plugin._command(1)
            if 'p1' in plugin.parameters:
                host.apply_settings(plugin, {'p1': 1.0})
            # CyCrossGain has the native -120 .. +24 dB range and starts at -18 dB.
            np.testing.assert_allclose(host.process(plugin, audio, 48000)[:, -256:], audio[:, -256:] * 10 ** (-18/20), atol=1e-6)
            host.apply_settings(plugin, {'p0': 114/144})
            state = host.capture(plugin)
            np.testing.assert_allclose(host.process(plugin, audio, 48000)[:, -256:], audio[:, -256:] * 10 ** (-6/20), atol=1e-6)
            host.apply_settings(plugin, {'p0': 102/144})
            host.apply_settings(plugin, None, state['state'])
            np.testing.assert_allclose(host.process(plugin, audio, 48000)[:, -256:], audio[:, -256:] * 10 ** (-6/20), atol=1e-6)
            workflow = model.new_workflow('External', nodes=[model.new_node(kind, plugin=path, params={'p0': 114/144, **({'p1': 0.0} if kind == 'clap' else {})})], tail={'enabled':False})
            np.testing.assert_allclose(engine.render(audio, 48000, workflow).audio[:, -256:], audio[:, -256:] * 10 ** (-6/20), atol=1e-6)
        finally:
            plugin.close()

    def test_clap(self):
        self.check_format('AUDIOSTUDIO_TEST_CLAP', 'clap')

    def test_lv2(self):
        self.check_format('AUDIOSTUDIO_TEST_LV2', 'lv2')
