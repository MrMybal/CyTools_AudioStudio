"""Headless session scripting: actions, describe, slot batch (fixtures only)."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tests._fixtures import tone, write_wav
from audiostudio.editor.document import Document
from audiostudio.editor import batch
from audiostudio.workflow import model as workflow_model

RATE = 48000


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.voice = root / 'voice.wav'
        self.other = root / 'other.wav'
        write_wav(self.voice, tone(0.5, RATE, 1, 330.0, amplitude=0.4))
        write_wav(self.other, tone(0.25, RATE, 2, 220.0, amplitude=0.3))
        self.doc = Document(RATE)
        self.bed = self.doc.add_track(tone(2.0, RATE, 2, 110.0, amplitude=0.2), 'Bed')
        self.doc.add_insert(self.bed, workflow_model.new_node('effect', effect='gain', params={'gain_db': -6.0}))
        self.doc.automation_add(self.bed, 'gain_db', 0.0, 0.0)

    def tearDown(self):
        self.folder.cleanup()

    def test_add_replace_set_remove(self):
        doc = self.doc
        reports = batch.apply_actions(doc, [
            {'action': 'add_track', 'file': str(self.voice), 'name': 'Voice', 'offset_seconds': 0.5, 'gain_db': -3.0, 'pan': 0.5, 'inserts_from': 'Bed'},
            {'action': 'set_track', 'track': 'Voice', 'mute': False, 'offset_seconds': 1.0},
            {'action': 'set_inserts', 'target': 'Voice', 'nodes': [workflow_model.new_node('effect', effect='compressor')]},
            {'action': 'set_master', 'gain_db': -2.0},
            {'action': 'set_tail', 'max_seconds': 2.0},
        ])
        self.assertEqual([r['action'] for r in reports], ['add_track', 'set_track', 'set_inserts', 'set_master', 'set_tail'])
        voice = batch.find_track(doc, 'Voice')
        self.assertEqual(voice.offset, RATE)
        self.assertEqual(voice.gain_db, -3.0)
        self.assertEqual([n['effect'] for n in voice.inserts], ['compressor'])
        self.assertIn('gain_db', voice.automation)                    # copied from Bed by inserts_from
        self.assertEqual(doc.master.gain_db, -2.0)
        self.assertEqual(doc.tail['max_seconds'], 2.0)
        batch.apply_actions(doc, [{'action': 'replace_audio', 'track': voice.id, 'file': str(self.other), 'offset_seconds': 0.0}])
        self.assertEqual(voice.channels, 2)
        self.assertEqual(voice.frames, RATE // 4)
        self.assertEqual(voice.offset, 0)
        self.assertEqual([n['effect'] for n in voice.inserts], ['compressor'])
        batch.apply_actions(doc, [{'action': 'clear_automation', 'target': 'Bed'}, {'action': 'remove_track', 'track': 'Voice'}])
        self.assertEqual([t.name for t in doc.tracks], ['Bed'])
        self.assertEqual(self.bed.automation, {})
        description = batch.describe(doc)
        self.assertEqual(description['tracks'][0]['inserts'], ['gain'])
        self.assertEqual(description['master']['gain_db'], -2.0)

    def test_errors(self):
        with self.assertRaises(batch.BatchError) as ctx:
            batch.apply_actions(self.doc, [{'action': 'remove_track', 'track': 'nope'}])
        self.assertEqual(ctx.exception.code, 'MissingInput')
        with self.assertRaises(batch.BatchError):
            batch.apply_actions(self.doc, [{'action': 'add_track', 'file': 'missing.wav'}])
        with self.assertRaises(batch.BatchError):
            batch.apply_actions(self.doc, [{'action': 'teleport'}])
        with self.assertRaises(batch.BatchError):
            batch.apply_actions(self.doc, ['not a dict'])
        with self.assertRaises(batch.BatchError):
            batch.load_or_new(str(Path(self.folder.name) / 'absent'))
        self.assertEqual(batch.load_or_new(None, 44100).samplerate, 44100)

    def test_workflow_name_loader(self):
        chain = workflow_model.new_workflow('chain', nodes=[workflow_model.new_node('effect', effect='lowpass'), workflow_model.new_node('model', model='x')])
        loader = lambda name: chain if name == 'chain' else (_ for _ in ()).throw(KeyError(name))
        batch.apply_actions(self.doc, [{'action': 'set_inserts', 'target': 'master', 'workflow_name': 'chain'}], loader)
        self.assertEqual([n['effect'] for n in self.doc.master.inserts], ['lowpass'])     # model nodes are skipped
        with self.assertRaises(batch.BatchError):
            batch.apply_actions(self.doc, [{'action': 'set_inserts', 'target': 'master', 'workflow_name': 'chain'}], None)


class SlotBatchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.sounds = []
        for index, (seconds, frequency) in enumerate([(0.3, 300.0), (0.6, 400.0), (0.2, 500.0)]):
            path = self.root / f'sound{index}.wav'
            write_wav(path, tone(seconds, RATE, 1, frequency, amplitude=0.5))
            self.sounds.append(path)
        self.doc = Document(RATE)
        self.doc.add_track(tone(1.0, RATE, 2, 110.0, amplitude=0.1), 'Bed')
        placeholder = self.doc.add_track(np.zeros((1, 10), np.float32), 'Voice', offset_seconds=0.25)
        placeholder.gain_db = -6.0
        self.doc.add_insert(placeholder, workflow_model.new_node('effect', effect='ir_reverb', params={'decay_seconds': 0.8, 'mix': 0.5}))
        self.doc.tail['max_seconds'] = 2.0

    def tearDown(self):
        self.folder.cleanup()

    def render(self, document, stem):
        audio = document.mixdown()
        path = self.root / (stem + '.wav')
        write_wav(path, audio)
        return {'file': str(path), 'frames': int(audio.shape[1])}

    def test_placeholder_slot_keeps_chain_and_renders_each_sound(self):
        results, failed = batch.batch_session(self.doc, [str(p) for p in self.sounds] + ['missing.wav'], {'track': 'Voice', 'offset_seconds': 0.25}, self.render)
        self.assertEqual(len(results), 3)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['code'], 'MissingInput')
        voice = batch.find_track(self.doc, 'Voice')
        self.assertEqual([n['effect'] for n in voice.inserts], ['ir_reverb'])
        self.assertEqual(voice.gain_db, -6.0)
        self.assertEqual(voice.offset, RATE // 4)
        frames = [r['frames'] for r in results]
        self.assertGreater(frames[1], frames[0])                         # the 0.6 s sound renders longer than the 0.3 s one
        self.assertTrue(all(f >= RATE for f in frames))                  # never shorter than the bed
        self.assertTrue(all(Path(r['file']).is_file() for r in results))
        self.assertEqual(len(self.doc.tracks), 2)

    def test_new_slot_track_is_removed_between_sounds(self):
        doc = Document(RATE)
        bed = doc.add_track(tone(0.5, RATE, 2, 110.0, amplitude=0.1), 'Bed')
        doc.add_insert(bed, workflow_model.new_node('effect', effect='gain', params={'gain_db': -3.0}))
        seen = []

        def render(document, stem):
            seen.append([t.name for t in document.tracks])
            return {'file': stem, 'frames': document.frames}
        results, failed = batch.batch_session(doc, [str(p) for p in self.sounds[:2]], {'track': 'Slot', 'inserts_from': 'Bed', 'gain_db': -1.0, 'solo': True}, render)
        self.assertEqual(failed, [])
        self.assertEqual(seen, [['Bed', 'Slot'], ['Bed', 'Slot']])
        self.assertEqual([t.name for t in doc.tracks], ['Bed'])          # the slot track is gone afterwards
        self.assertFalse(bed.solo)                                        # solo restored
        self.assertEqual(len(results), 2)


if __name__ == '__main__':
    unittest.main()
