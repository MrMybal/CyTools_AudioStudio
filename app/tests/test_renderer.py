"""Editor graph: inserts, master bus, automation lanes, tail mixdown, side-chain, sessions, undo."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tests._fixtures import tone, cydaw_available, CYDAW_PLUGIN
from audiostudio.editor.document import Document
from audiostudio.editor.automation import AutomationLane
from audiostudio.editor.renderer import Renderer
from audiostudio.workflow import model as workflow_model

RATE = 48000


def node(effect, **params):
    return workflow_model.new_node('effect', effect=effect, params=params)


def render_blocks(document, frames, size=1024, renderer=None):
    renderer = renderer or Renderer(document)
    return np.concatenate([renderer.render(start, min(size, frames - start)) for start in range(0, frames, size)], axis=1), renderer


class AutomationLaneTests(unittest.TestCase):
    def test_points_interpolation_and_editing(self):
        lane = AutomationLane('gain_db')
        self.assertEqual(lane.value_at(3.0, default=-6.0), -6.0)
        lane.add_point(1.0, 0.0)
        lane.add_point(3.0, -20.0)
        lane.add_point(2.0, -10.0)
        self.assertEqual([p[0] for p in lane.points], [1.0, 2.0, 3.0])
        self.assertAlmostEqual(lane.value_at(0.0), 0.0)          # constant before the first point
        self.assertAlmostEqual(lane.value_at(2.5), -15.0)
        self.assertAlmostEqual(lane.value_at(9.0), -20.0)
        self.assertTrue(np.allclose(lane.values([1.0, 1.5, 2.0]), [0.0, -5.0, -10.0]))
        index = lane.add_point(2.0, -12.0)                        # same time replaces
        self.assertEqual((index, len(lane)), (1, 3))
        lane.move_point(1, 5.0, -1.0)                             # cannot cross the next point
        self.assertLess(lane.points[1][0], 3.0)
        self.assertEqual(lane.nearest(3.0, 1e-5), 2)
        self.assertIsNone(lane.nearest(7.0, 0.1))
        lane.write(3.0, -30.0, window=0.05)
        self.assertEqual(lane.points[-1], [3.0, -30.0])
        lane.remove_point(0)
        self.assertEqual(len(lane), 1)                            # write() replaced the two points near 3.0
        restored = AutomationLane.from_dict(lane.to_dict())
        self.assertEqual(restored.points, lane.points)
        self.assertEqual(restored.key, 'gain_db')
        lane.shift(2.0, 1.0)
        self.assertEqual(lane.points[-1][0], 4.0)
        lane.clear()
        self.assertFalse(lane.active)


class InsertTests(unittest.TestCase):
    def setUp(self):
        self.doc = Document(RATE)
        self.track = self.doc.add_track(tone(1.0, RATE, 2, 440.0, amplitude=0.5), 'a')

    def test_add_move_remove_inserts_with_undo(self):
        doc, track = self.doc, self.track
        gain = doc.add_insert(track, node('gain', gain_db=-6.0))
        lowpass = doc.add_insert(track, node('lowpass', cutoff_hz=200.0))
        self.assertEqual([n['effect'] for n in track.inserts], ['gain', 'lowpass'])
        self.assertTrue(doc.move_insert(track, lowpass['id'], -1))
        self.assertEqual([n['effect'] for n in track.inserts], ['lowpass', 'gain'])
        self.assertFalse(doc.move_insert(track, lowpass['id'], -1))
        doc.automation_add(track, gain['id'] + '.gain_db', 0.5, -12.0)
        self.assertTrue(doc.remove_insert(track, gain['id']))
        self.assertEqual([n['effect'] for n in track.inserts], ['lowpass'])
        self.assertNotIn(gain['id'] + '.gain_db', track.automation)
        self.assertEqual(doc.undo(), 'Remove insert')
        self.assertEqual([n['effect'] for n in track.inserts], ['lowpass', 'gain'])
        self.assertIn(gain['id'] + '.gain_db', track.automation)
        with self.assertRaises(workflow_model.WorkflowError):
            doc.add_insert(track, {'kind': 'effect', 'effect': 'nope'})

    def test_track_insert_changes_the_mix_and_static_gain_matches(self):
        doc, track = self.doc, self.track
        dry = doc.mixdown(tail={'enabled': False})
        doc.add_insert(track, node('gain', gain_db=-20.0))
        wet = doc.mixdown(tail={'enabled': False})
        self.assertEqual(wet.shape, dry.shape)
        self.assertTrue(np.allclose(wet, dry * 10 ** (-20 / 20), atol=1e-4))
        track.inserts[0]['enabled'] = False
        self.assertTrue(np.allclose(doc.mixdown(tail={'enabled': False}), dry, atol=1e-6))
        track.inserts[0]['enabled'] = True
        track.inserts[0]['mix'] = 0.5
        half = doc.mixdown(tail={'enabled': False})
        self.assertTrue(np.allclose(half, dry * (0.5 + 0.5 * 0.1), atol=1e-4))

    def test_master_chain_and_gain(self):
        doc = self.doc
        dry = doc.mixdown(tail={'enabled': False})
        doc.master.gain_db = -6.0
        self.assertTrue(np.allclose(doc.mixdown(tail={'enabled': False}), dry * 10 ** (-6 / 20), atol=1e-4))
        doc.master.gain_db = 0.0
        doc.add_insert(doc.master, node('mute'))
        self.assertTrue(np.allclose(doc.mixdown(tail={'enabled': False}), 0.0))
        doc.undo()
        self.assertEqual(doc.master.inserts, [])
        doc.master.mute = True
        self.assertTrue(np.allclose(doc.mixdown(tail={'enabled': False}), 0.0))

    def test_realtime_renderer_keeps_state_and_reports_meters(self):
        doc, track = self.doc, self.track
        comp = doc.add_insert(track, node('compressor', threshold_db=-30.0, ratio=10.0, attack_ms=1.0, release_ms=50.0))
        live, renderer = render_blocks(doc, doc.frames)
        offline = doc.mixdown(tail={'enabled': False})
        self.assertTrue(np.allclose(live, offline, atol=1e-4))
        self.assertLess(renderer.meters(comp['id'])['gain_reduction_db'], -10.0)
        tap = renderer.tap(comp['id'])
        self.assertGreater(tap.in_peak[0], tap.out_peak[0])
        recent = tap.recent('output', 512)
        self.assertEqual(recent.shape, (2, 512))
        self.assertGreater(renderer.track_peaks[track.id][0], 0.0)
        self.assertGreater(renderer.master_peak[0], 0.0)
        # parameter change without rebuilding the processor
        processor = renderer.processor(comp['id'])
        comp['params']['ratio'] = 2.0
        renderer.render(0, 1024)
        self.assertIs(renderer.processor(comp['id']), processor)
        self.assertEqual(processor.params['ratio'], 2.0)
        # changing the effect rebuilds it
        comp['effect'] = 'gain'
        comp['params'] = {'gain_db': 0.0}
        renderer.render(0, 1024)
        self.assertIsNot(renderer.processor(comp['id']), processor)
        renderer.prune()
        doc.remove_insert(track, comp['id'])
        renderer.prune()
        self.assertNotIn(comp['id'], renderer.processors)

    def test_offline_effect_in_a_chain_is_bypassed_with_a_message(self):
        doc, track = self.doc, self.track
        bad = doc.add_insert(track, node('normalize'))
        renderer = Renderer(doc)
        renderer.render(0, 1024)
        self.assertIn(bad['id'], renderer.errors)

    def test_side_chain_from_another_track(self):
        doc = self.doc
        pad = doc.tracks[0]
        pad.audio = np.full((2, RATE), 0.5, np.float32)
        pad.invalidate()
        key = doc.add_track(np.concatenate([np.zeros((2, RATE // 2), np.float32), np.full((2, RATE // 2), 0.9, np.float32)], axis=1), 'key')
        key.mute = True
        doc.add_insert(pad, {**node('compressor', threshold_db=-40.0, ratio=20.0, attack_ms=1.0, release_ms=30.0, sidechain_input=True), 'sidechain': key.id})
        out = doc.mixdown(tail={'enabled': False})
        self.assertGreater(float(np.abs(out[0, 1000:20000]).max()), 0.45)
        self.assertLess(float(np.abs(out[0, 30000:]).max()), 0.05)


class AutomationDocumentTests(unittest.TestCase):
    def test_volume_pan_and_insert_parameter_automation(self):
        doc = Document(RATE)
        track = doc.add_track(np.full((1, RATE), 0.5, np.float32), 'a')
        doc.automation_add(track, 'gain_db', 0.0, 0.0)
        doc.automation_add(track, 'gain_db', 1.0, -40.0)
        out = doc.mixdown(tail={'enabled': False})
        self.assertAlmostEqual(float(out[0, 10]), 0.5, places=2)
        self.assertAlmostEqual(float(out[0, RATE // 2]), 0.5 * 10 ** (-20 / 20), places=2)
        self.assertLess(float(out[0, -10]), 0.01)
        doc.automation_clear(track, 'gain_db')
        doc.automation_add(track, 'pan', 0.0, -1.0)
        doc.automation_add(track, 'pan', 1.0, 1.0)
        out = doc.mixdown(tail={'enabled': False})
        self.assertGreater(float(out[0, 100]), float(out[1, 100]))
        self.assertLess(float(out[0, -100]), float(out[1, -100]))
        doc.automation_clear(track, 'pan')
        gain = doc.add_insert(track, node('gain', gain_db=0.0))
        key = gain['id'] + '.gain_db'
        doc.automation_add(track, key, 0.0, 0.0)
        doc.automation_add(track, key, 1.0, -40.0)
        out = doc.mixdown(tail={'enabled': False})
        self.assertGreater(float(out[0, 1000]), float(out[0, -1000]) * 10.0)
        self.assertEqual(gain['params']['gain_db'], 0.0)                 # the static value is untouched
        lo, hi, current, kind = doc.automation_range(track, key)
        self.assertEqual((lo, hi, kind), (-60.0, 24.0, 'float'))
        keys = dict(doc.automatable_keys(track))
        self.assertIn(key, keys)
        self.assertIn('pan', keys)
        self.assertNotIn('pan', dict(doc.automatable_keys(doc.master)))

    def test_mute_lane_and_write(self):
        doc = Document(RATE)
        track = doc.add_track(np.full((1, RATE), 0.5, np.float32), 'a')
        doc.automation_add(track, 'mute', 0.0, 0.0)
        doc.automation_add(track, 'mute', 0.5, 1.0)
        out = doc.mixdown(tail={'enabled': False})
        self.assertGreater(float(out[0, 1000]), 0.4)
        self.assertEqual(float(out[0, -1000]), 0.0)
        doc.automation_write(track, 'gain_db', 0.25, -3.0)
        doc.automation_write(track, 'gain_db', 0.26, -4.0)
        self.assertEqual(len(track.automation['gain_db']), 1)
        self.assertEqual(track.automation['gain_db'].points[0][1], -4.0)
        self.assertTrue(doc.automation_remove(track, 'gain_db', 0))
        self.assertNotIn('gain_db', track.automation)

    def test_split_copies_chain_and_lanes(self):
        doc = Document(RATE)
        track = doc.add_track(tone(1.0, RATE, 2, 440.0), 'a')
        gain = doc.add_insert(track, node('gain', gain_db=-3.0))
        doc.automation_add(track, gain['id'] + '.gain_db', 0.2, -6.0)
        doc.cursor = 0.5
        self.assertTrue(doc.split())
        right = doc.tracks[1]
        self.assertEqual(right.inserts[0]['effect'], 'gain')
        self.assertNotEqual(right.inserts[0]['id'], gain['id'])
        self.assertIn(right.inserts[0]['id'] + '.gain_db', right.automation)


class TailAndSessionTests(unittest.TestCase):
    def test_mixdown_extends_for_the_reverb_tail(self):
        doc = Document(RATE)
        audio = np.zeros((2, RATE // 2), np.float32)
        audio[:, :200] = 0.8
        track = doc.add_track(audio, 'click')
        doc.add_insert(track, node('ir_reverb', type='hall', decay_seconds=1.5, mix=0.6))
        self.assertTrue(doc.has_stateful_inserts())
        out = doc.mixdown()
        self.assertGreater(out.shape[1], doc.frames + RATE // 4)
        self.assertLess(out.shape[1], doc.frames + int(RATE * doc.tail['max_seconds']) + 8192)
        self.assertGreater(float(np.abs(out[:, doc.frames:doc.frames + 4800]).max()), 10 ** (-60 / 20))
        short = doc.mixdown(tail={'enabled': True, 'threshold_db': -60.0, 'max_seconds': 0.2, 'hold_seconds': 0.0})
        self.assertLessEqual(short.shape[1], doc.frames + int(0.2 * RATE) + 4096)
        self.assertEqual(doc.mixdown(tail={'enabled': False}).shape[1], doc.frames)

    def test_session_round_trip_keeps_inserts_automation_master(self):
        doc = Document(RATE)
        track = doc.add_track(tone(0.5, RATE, 2, 330.0), 'a')
        comp = doc.add_insert(track, node('compressor', threshold_db=-24.0))
        doc.add_insert(doc.master, node('parametric_eq', b1_gain=3.0))
        doc.master.gain_db = -2.0
        doc.automation_add(track, comp['id'] + '.threshold_db', 0.1, -40.0)
        doc.automation_add(doc.master, 'gain_db', 0.3, -12.0)
        track.automation_view = 'gain_db'
        doc.tail['max_seconds'] = 3.0
        expected = doc.mixdown()
        with tempfile.TemporaryDirectory() as folder:
            doc.save_session(folder)
            index = (Path(folder) / 'session.json').read_text('utf-8')
            self.assertIn('"schemaVersion": 2', index)
            loaded = Document.load_session(folder)
        self.assertEqual([n['effect'] for n in loaded.tracks[0].inserts], ['compressor'])
        self.assertEqual(loaded.tracks[0].inserts[0]['params']['threshold_db'], -24.0)
        self.assertEqual([n['effect'] for n in loaded.master.inserts], ['parametric_eq'])
        self.assertEqual(loaded.master.gain_db, -2.0)
        self.assertEqual(loaded.master.automation['gain_db'].points, [[0.3, -12.0]])
        self.assertEqual(loaded.tracks[0].automation_view, 'gain_db')
        self.assertEqual(loaded.tail['max_seconds'], 3.0)
        got = loaded.mixdown()
        self.assertEqual(got.shape, expected.shape)
        self.assertTrue(np.allclose(got, expected, atol=1e-4))

    def test_legacy_session_without_master_loads(self):
        doc = Document(RATE)
        doc.add_track(tone(0.2, RATE, 1, 220.0), 'a')
        with tempfile.TemporaryDirectory() as folder:
            doc.save_session(folder)
            path = Path(folder) / 'session.json'
            import json
            index = json.loads(path.read_text('utf-8'))
            index['schemaVersion'] = 1
            index.pop('master')
            index.pop('tail')
            for item in index['tracks']:
                item.pop('inserts')
                item.pop('automation')
            path.write_text(json.dumps(index), 'utf-8')
            loaded = Document.load_session(folder)
        self.assertEqual(loaded.master.inserts, [])
        self.assertEqual(loaded.tracks[0].inserts, [])
        self.assertEqual(loaded.tail['threshold_db'], -60.0)


@unittest.skipUnless(cydaw_available(), 'CyDAW Test Gain.vst3 is not built on this machine')
class VST3InsertTests(unittest.TestCase):
    def test_vst3_insert_renders_in_process_and_keeps_state(self):
        doc = Document(RATE)
        track = doc.add_track(np.full((2, RATE // 4), 0.25, np.float32), 'a')
        # gain_x is normalised 0..1 in this plugin (0.5 = unity).
        vst = doc.add_insert(track, workflow_model.new_node('vst3', plugin=str(CYDAW_PLUGIN), pluginName='', params={'gain_x': 1.0}))
        out, renderer = render_blocks(doc, doc.frames)
        self.assertNotIn(vst['id'], renderer.errors)
        loud = float(out[0, 5000])
        vst['params']['gain_x'] = 0.25
        out2, _ = render_blocks(doc, doc.frames, renderer=renderer)
        quiet = float(out2[0, 5000])
        self.assertGreater(loud, quiet * 2.0)
        processor = renderer.processor(vst['id'])
        captured = processor.capture()
        self.assertIn('state', captured)
        self.assertAlmostEqual(float(captured['params']['gain_x']), 0.25, places=3)


if __name__ == '__main__':
    unittest.main()
