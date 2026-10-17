"""Editor document: tracks, edits, undo/redo, mixing, sessions and peaks (run from the app directory)."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tests._fixtures import tone, write_wav
from audiostudio.editor import document as editor
from audiostudio.editor.document import Document
from audiostudio.editor.peaks import Peaks, BASE

RATE = 48000


def ramp(frames, channels=1):
    values = np.linspace(0.0, 1.0, frames, dtype=np.float32)
    return np.ascontiguousarray(np.stack([values * (index + 1) for index in range(channels)]))


class TrackManagementTests(unittest.TestCase):
    def test_add_tracks(self):
        doc = editor.Document(RATE)
        mono = doc.add_track(np.zeros(100, np.float32), 'Mono')
        self.assertEqual(mono.audio.shape, (1, 100))
        self.assertEqual(mono.channels, 1)
        self.assertEqual(mono.frames, 100)
        self.assertEqual(doc.selected_track, 0)
        self.assertTrue(doc.dirty)
        many = doc.add_track(np.zeros((4, 50), np.float32), 'Quad', offset_seconds=0.5)
        self.assertEqual(many.channels, 2)
        self.assertEqual(many.offset, RATE // 2)
        self.assertEqual(many.end, RATE // 2 + 50)
        self.assertEqual(doc.frames, RATE // 2 + 50)
        self.assertAlmostEqual(doc.duration, (RATE // 2 + 50) / RATE)
        self.assertEqual(doc.selected_track, 1)
        self.assertEqual(doc.current_track(), many)
        self.assertEqual(doc.track(mono.id), mono)
        self.assertIsNone(doc.track('nope'))
        # Different sample rate on a non-empty document: resampled to the document rate.
        other = doc.add_track(np.zeros((1, 44100), np.float32), 'Other', samplerate=44100)
        self.assertEqual(other.frames, RATE)
        # First track with a rate adopts that rate.
        fresh = editor.Document(RATE)
        fresh.add_track(np.zeros((1, 10), np.float32), samplerate=22050)
        self.assertEqual(fresh.samplerate, 22050)
        self.assertEqual(len(doc.undo_stack), 3)
        self.assertEqual(doc.version, 6)

    def test_import_remove_move(self):
        with tempfile.TemporaryDirectory() as workdir:
            path = write_wav(Path(workdir) / 'clip.wav', tone(0.25, 44100, 2), 44100)
            doc = editor.Document(RATE)
            doc.cursor = 1.0
            imported = doc.import_file(path)
            self.assertEqual(imported.name, 'clip')
            self.assertEqual(imported.source, str(path))
            self.assertEqual(doc.samplerate, 44100)      # first track adopts the file rate
            self.assertEqual(imported.offset, 44100)
            self.assertEqual(imported.frames, 44100 // 4)
            second = doc.import_file(path, offset_seconds=0.0, name='Second')
            third = doc.add_track(np.zeros((1, 10), np.float32), 'Third')
            self.assertEqual([t.name for t in doc.tracks], ['clip', 'Second', 'Third'])
            doc.move_track(third.id, -1)
            self.assertEqual([t.name for t in doc.tracks], ['clip', 'Third', 'Second'])
            self.assertEqual(doc.selected_track, 1)
            doc.move_track(imported.id, -1)             # already first: no change, no undo entry
            self.assertEqual(doc.tracks[0], imported)
            doc.move_track('missing', 1)
            doc.remove_track(second.id)
            self.assertEqual([t.name for t in doc.tracks], ['clip', 'Third'])
            doc.remove_track('missing')
            self.assertEqual(len(doc.tracks), 2)
            self.assertEqual(doc.undo()[:13], 'Remove track ')
            self.assertEqual([t.name for t in doc.tracks], ['clip', 'Third', 'Second'])

    def test_selection_frames(self):
        doc = editor.Document(RATE)
        self.assertEqual(doc.selection_frames(), (0, 0))
        track = doc.add_track(np.zeros((1, 1000), np.float32), offset_seconds=0.5)
        self.assertEqual(doc.selection_frames(), (0, RATE // 2 + 1000))
        self.assertEqual(doc.selection_frames(track), (RATE // 2, RATE // 2 + 1000))
        doc.selection = (0.75, 0.25)
        self.assertEqual(doc.selection_frames(), (RATE // 4, 3 * RATE // 4))
        self.assertEqual(doc.selection_frames(track), (RATE // 4, 3 * RATE // 4))
        self.assertEqual(doc.seconds_to_frame(1.5), int(1.5 * RATE))
        self.assertEqual(doc.frame_to_seconds(RATE), 1.0)
        self.assertEqual(editor.Document().current_track(), None)
        self.assertEqual(editor.Document().targets(), [])


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.doc = editor.Document(RATE)
        self.original = ramp(RATE, 1)
        self.track = self.doc.add_track(self.original.copy(), 'Ramp')

    def test_copy_cut_paste_insert_round_trip(self):
        self.assertFalse(self.doc.copy())
        self.doc.selection = (0.25, 0.5)
        self.assertTrue(self.doc.copy())
        block, rate = self.doc.clipboard
        self.assertEqual(rate, RATE)
        self.assertTrue(np.array_equal(block, self.original[:, 12000:24000]))
        self.assertTrue(self.doc.cut())
        self.assertEqual(self.track.frames, 36000)
        self.assertEqual(self.doc.cursor, 0.25)
        self.assertIsNone(self.doc.selection)
        self.assertTrue(np.array_equal(self.track.audio[:, 12000:], self.original[:, 24000:]))
        self.assertTrue(self.doc.paste())
        self.assertEqual(self.track.frames, RATE)
        self.assertTrue(np.array_equal(self.track.audio, self.original))
        self.assertEqual(self.doc.selection, (0.25, 0.5))
        # Paste with a selection inserts at the selection start.
        self.doc.selection = (0.0, 0.1)
        self.assertTrue(self.doc.paste())
        self.assertEqual(self.track.frames, RATE + 12000)
        self.assertTrue(np.array_equal(self.track.audio[:, :12000], block))
        self.assertTrue(np.array_equal(self.track.audio[:, 12000:], self.original))

    def test_paste_replace_and_before_track(self):
        self.doc.clipboard = (np.ones((1, 12000), np.float32), RATE)
        self.doc.cursor = 0.25
        self.assertTrue(self.doc.paste(insert=False))
        self.assertEqual(self.track.frames, RATE)
        self.assertTrue(np.all(self.track.audio[:, 12000:24000] == 1.0))
        self.assertTrue(np.array_equal(self.track.audio[:, 24000:], self.original[:, 24000:]))
        # Clipboard at another rate is resampled to the document rate.
        self.doc.clipboard = (np.ones((1, 6000), np.float32), RATE // 2)
        self.doc.selection = None
        self.doc.cursor = 0.0
        self.assertTrue(self.doc.paste())
        self.assertEqual(self.track.frames, RATE + 12000)
        # Paste (cursor, no selection) before a track's start moves the track back to that position.
        self.doc.selection = None
        self.track.offset = RATE
        self.doc.cursor = 0.5
        self.doc.clipboard = (np.zeros((1, 100), np.float32), RATE)
        self.assertTrue(self.doc.paste())
        self.assertEqual(self.track.offset, RATE // 2)
        # Paste into an empty document creates a track.
        empty = editor.Document(RATE)
        empty.clipboard = (np.zeros((2, 10), np.float32), RATE)
        self.assertTrue(empty.paste())
        self.assertEqual(empty.tracks[0].name, 'Pasted')
        self.assertFalse(editor.Document(RATE).paste())

    def test_delete_silence_trim(self):
        self.assertFalse(self.doc.delete())
        self.assertFalse(self.doc.silence())
        self.assertFalse(self.doc.trim())
        self.doc.selection = (0.5, 0.75)
        self.assertTrue(self.doc.silence())
        self.assertTrue(np.all(self.track.audio[:, 24000:36000] == 0.0))
        self.assertTrue(np.array_equal(self.track.audio[:, :24000], self.original[:, :24000]))
        self.assertTrue(self.doc.delete())
        self.assertEqual(self.track.frames, 36000)
        self.assertTrue(np.array_equal(self.track.audio[:, 24000:], self.original[:, 36000:]))
        # Deleting a region before a later track shifts that track back.
        later = self.doc.add_track(np.zeros((1, 100), np.float32), 'Later', offset_seconds=2.0)
        self.doc.selection = (0.0, 0.5)
        self.doc.selected_track = 1
        self.assertTrue(self.doc.delete())
        self.assertEqual(later.offset, int(1.5 * RATE))
        self.assertEqual(later.frames, 100)
        # Trim keeps only the selection on all tracks.
        self.doc.selection = (0.25, 0.5)
        self.assertTrue(self.doc.trim(all_tracks=True))
        self.assertEqual(self.track.frames, 12000)
        self.assertEqual(self.track.offset, 12000)
        self.assertTrue(np.array_equal(self.track.audio, self.original[:, 12000:24000]))
        self.assertEqual(later.frames, 0)

    def test_split_and_insert_silence(self):
        self.assertFalse(self.doc.split())          # cursor at 0: nothing to split
        self.doc.cursor = 0.5
        self.assertTrue(self.doc.split())
        self.assertEqual(len(self.doc.tracks), 1)                    # both halves stay on the track (same inserts)
        left, right = self.track.clips
        self.assertEqual((left.frames, right.frames, right.offset), (24000, 24000, 24000))
        self.assertEqual(right.name, 'Ramp (2)')
        self.assertTrue(np.array_equal(np.concatenate([left.view(), right.view()], axis=1), self.original))
        self.assertTrue(np.array_equal(self.track.view(), self.original))
        self.doc.selected_track = 0
        self.doc.cursor = 0.25
        self.assertTrue(self.doc.insert_silence(0.5, all_tracks=True))
        self.assertEqual(left.frames, 24000 + 24000)
        self.assertTrue(np.all(left.view()[:, 12000:36000] == 0.0))
        self.assertTrue(np.array_equal(left.view()[:, 36000:], self.original[:, 12000:24000]))
        self.assertEqual(right.offset, 24000 + 24000)   # clips after the cursor move later
        self.doc.set_offset(self.track, 3.0, clip=right)
        self.assertEqual(right.offset, 3 * RATE)
        self.assertEqual(left.offset, 0)
        self.assertFalse(editor.Document(RATE).split())

    def test_apply_with_tail_overlap(self):
        self.track.audio[:] = 0.5
        self.doc.selection = (0.0, 0.5)
        tail_frames = 6000

        def with_tail(block, rate):
            self.assertEqual(rate, RATE)
            self.assertEqual(block.shape, (1, 24000))
            return np.concatenate([block * 2.0, np.full((1, tail_frames), 0.25, np.float32)], axis=1)
        self.assertTrue(self.doc.apply('Tail', with_tail))
        self.assertEqual(self.track.frames, RATE)                                   # tail overlapped, no extension
        self.assertTrue(np.all(self.track.audio[:, :24000] == 1.0))
        self.assertTrue(np.allclose(self.track.audio[:, 24000:24000 + tail_frames], 0.75))
        self.assertTrue(np.all(self.track.audio[:, 24000 + tail_frames:] == 0.5))
        # A tail running past the end of the track extends it.
        self.doc.selection = None
        self.assertTrue(self.doc.apply('Extend', lambda block, rate: np.concatenate([block, np.ones((1, 1000), np.float32)], axis=1), whole_track=True))
        self.assertEqual(self.track.frames, RATE + 1000)
        self.assertTrue(np.all(self.track.audio[:, RATE:] == 1.0))
        # A shorter result shrinks the region; 1-D and channel-mismatched results are adapted.
        self.doc.selection = (0.0, 0.25)
        self.assertTrue(self.doc.apply('Shrink', lambda block, rate: np.zeros(100, np.float32)))
        self.assertEqual(self.track.frames, RATE + 1000 - 12000 + 100)
        stereo = self.doc.add_track(np.ones((2, 1000), np.float32), 'Stereo')
        self.doc.selection = None
        self.assertTrue(self.doc.apply('Mono result', lambda block, rate: np.zeros((1, 1000), np.float32)))
        self.assertEqual(stereo.audio.shape, (2, 1000))
        self.assertTrue(np.all(stereo.audio == 0.0))
        self.assertFalse(editor.Document(RATE).apply('x', lambda b, r: b))

    def test_undo_redo_structural_and_audio(self):
        doc = self.doc
        self.assertIsNone(doc.redo())
        doc.selection = (0.0, 0.5)
        self.assertTrue(doc.silence())
        self.assertTrue(np.all(self.track.audio[:, :24000] == 0.0))
        self.assertEqual(doc.undo(), 'Silence')
        self.assertTrue(np.array_equal(self.track.audio, self.original))
        self.assertEqual(doc.selection, (0.0, 0.5))
        self.assertEqual(doc.redo(), 'Silence')
        self.assertTrue(np.all(self.track.audio[:, :24000] == 0.0))
        self.assertEqual(doc.undo(), 'Silence')
        second = doc.add_track(np.zeros((1, 10), np.float32), 'Second')
        self.assertEqual(len(doc.tracks), 2)
        self.assertEqual(doc.undo(), 'Add track Second')
        self.assertEqual([t.id for t in doc.tracks], [self.track.id])
        self.assertEqual(doc.redo(), 'Add track Second')
        self.assertEqual([t.id for t in doc.tracks], [self.track.id, second.id])
        doc.cursor = 0.5
        doc.selected_track = 0
        self.assertTrue(doc.split())
        self.assertEqual(len(self.track.clips), 2)
        self.assertEqual(doc.undo(), 'Split')
        self.assertEqual(len(self.track.clips), 1)
        self.assertEqual(self.track.frames, RATE)
        self.assertTrue(np.array_equal(self.track.view(), self.original))
        self.assertEqual(doc.redo(), 'Split')
        self.assertEqual(len(self.track.clips), 2)
        self.assertEqual(self.track.clips[0].frames, 24000)
        # A new edit clears the redo stack.
        doc.undo()
        doc.selection = (0.1, 0.2)
        doc.silence()
        self.assertEqual(doc.redo_stack, [])
        self.assertIsNone(doc.redo())
        self.assertIsNone(editor.Document().undo())

    def test_undo_stack_is_bounded(self):
        self.doc.selection = (0.0, 0.1)
        for _ in range(editor.MAX_UNDO + 10):
            self.doc.silence()
        self.assertEqual(len(self.doc.undo_stack), editor.MAX_UNDO)
        for _ in range(editor.MAX_UNDO):
            self.assertEqual(self.doc.undo(), 'Silence')
        self.assertIsNone(self.doc.undo())
        self.assertEqual(len(self.doc.redo_stack), editor.MAX_UNDO)


class MixTests(unittest.TestCase):
    def test_mix_block_mute_solo_gain_pan(self):
        doc = editor.Document(RATE)
        a = doc.add_track(np.ones((1, 4800), np.float32), 'A')
        b = doc.add_track(np.full((1, 4800), 0.5, np.float32), 'B', offset_seconds=0.05)   # starts at frame 2400
        out = doc.mix_block(0, 7200)
        self.assertEqual(out.shape, (2, 7200))
        self.assertTrue(np.allclose(out[:, :2400], 1.0))
        self.assertTrue(np.allclose(out[:, 2400:4800], 1.5))
        self.assertTrue(np.allclose(out[:, 4800:7200], 0.5))
        b.mute = True
        self.assertTrue(np.allclose(doc.mix_block(0, 7200)[:, 2400:4800], 1.0))
        b.mute = False
        b.solo = True
        out = doc.mix_block(0, 7200)
        self.assertTrue(np.allclose(out[:, :2400], 0.0))
        self.assertTrue(np.allclose(out[:, 2400:7200], 0.5))
        b.solo = False
        a.gain_db = -6.0206
        self.assertTrue(np.allclose(doc.mix_block(0, 2400), 0.5, atol=1e-4))
        a.gain_db = 0.0
        a.pan = -1.0
        out = doc.mix_block(0, 2400)
        self.assertTrue(np.allclose(out[0], np.sqrt(2.0), atol=1e-5))
        self.assertTrue(np.allclose(out[1], 0.0, atol=1e-5))
        # Mono mixdown applies gain only, no pan law.
        a.pan = 1.0
        mono = doc.mix_block(0, 7200, channels=1)
        self.assertEqual(mono.shape, (1, 7200))
        self.assertTrue(np.allclose(mono[0, 2400:4800], 1.5))
        a.pan = 0.0
        # Stereo track keeps its channels; partial windows and empty windows.
        stereo = doc.add_track(np.stack([np.ones(100, np.float32), np.zeros(100, np.float32)]), 'S', offset_seconds=1.0)
        window = doc.mix_block(RATE - 50, 100)
        self.assertTrue(np.allclose(window[0, 50:], 1.0))
        self.assertTrue(np.allclose(window[1, 50:], 0.0))
        self.assertTrue(np.allclose(window[:, :50], 0.0))
        self.assertTrue(np.all(doc.mix_block(10 * RATE, 100) == 0.0))
        self.assertEqual(stereo.stereo_gains(), a.stereo_gains())

    def test_mixdown(self):
        doc = editor.Document(RATE)
        doc.add_track(np.ones((2, 4800), np.float32), 'A')
        doc.add_track(np.ones((1, 4800), np.float32), 'B', offset_seconds=0.1)
        whole = doc.mixdown()
        self.assertEqual(whole.shape, (2, 4800 + 4800))
        self.assertTrue(np.allclose(whole, 1.0))
        part = doc.mixdown(0.05, 0.1)
        self.assertEqual(part.shape, (2, 2400))
        self.assertEqual(doc.mixdown(0.2, 0.1).shape, (2, 0))
        self.assertEqual(editor.Document(RATE).mixdown().shape, (2, 0))


class SessionTests(unittest.TestCase):
    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as workdir:
            folder = Path(workdir) / 'my session'
            doc = editor.Document(RATE)
            first = doc.add_track(tone(0.1, RATE, 2), 'First', source='C:/x.wav')
            second = doc.add_track(ramp(500, 1), 'Second', offset_seconds=0.25)
            first.gain_db, first.pan, first.mute, second.solo, second.height = -3.0, 0.5, True, True, 80.0
            doc.selection = (0.1, 0.2)
            doc.cursor = 0.05
            folder.mkdir()
            (folder / 'stale.wav').write_bytes(b'')
            index = doc.save_session(folder)
            self.assertEqual(index, folder / 'session.json')
            self.assertFalse((folder / 'stale.wav').exists())
            self.assertEqual(sorted(p.suffix for p in folder.iterdir()), ['.json', '.wav', '.wav'])
            self.assertEqual((doc.name, doc.path, doc.dirty), ('my session', folder, False))
            loaded = editor.Document.load_session(index)     # accepts the index file or the folder
            self.assertEqual(loaded.samplerate, RATE)
            self.assertEqual([t.id for t in loaded.tracks], [first.id, second.id])
            for before, after in zip(doc.tracks, loaded.tracks):
                self.assertTrue(np.array_equal(before.audio, after.audio))
                self.assertEqual((before.name, before.offset, before.gain_db, before.pan, before.mute, before.solo, tuple(before.colour), before.source, before.height),
                                 (after.name, after.offset, after.gain_db, after.pan, after.mute, after.solo, after.colour, after.source, after.height))
            self.assertEqual(loaded.selection, (0.1, 0.2))
            self.assertEqual(loaded.cursor, 0.05)
            self.assertFalse(loaded.dirty)
            self.assertEqual(loaded.undo_stack, [])
            self.assertTrue(np.allclose(loaded.mixdown(), doc.mixdown()))
            (folder / 'session.json').write_text('{"format": "other"}', encoding='utf-8')
            with self.assertRaises(ValueError):
                editor.Document.load_session(folder)


class PeaksTests(unittest.TestCase):
    def test_read_coarse_and_sample_level(self):
        audio = tone(100000 / RATE, RATE, 2, amplitude=0.8)
        peaks = Peaks(audio)
        self.assertEqual(peaks.frames, 100000)
        self.assertGreater(len(peaks.levels), 1)
        self.assertLessEqual(len(peaks.levels[-1][0]), 128)
        low, high = peaks.read(0, 100000, 100)
        self.assertEqual(len(low), 100)
        self.assertEqual(len(high), 100)
        self.assertTrue(np.all(high >= low))
        self.assertAlmostEqual(float(low.min()), -0.8, delta=0.01)
        self.assertAlmostEqual(float(high.max()), 0.8, delta=0.01)
        low, high = peaks.read(0, 100000, 100000)      # more columns than pairs: whole base level
        self.assertEqual(len(low), int(np.ceil(100000 / BASE)))
        exact_low, exact_high = peaks.read(1000, 1050, 50, audio=audio)
        self.assertEqual(len(exact_low), 50)
        self.assertTrue(np.array_equal(exact_low, audio[:, 1000:1050].min(axis=0)))
        self.assertTrue(np.array_equal(exact_high, audio[:, 1000:1050].max(axis=0)))
        reduced_low, reduced_high = peaks.read(0, 200, 10, audio=audio)
        self.assertEqual(len(reduced_low), 10)
        self.assertTrue(np.all(reduced_high >= reduced_low))
        empty = peaks.read(50, 50, 10)
        self.assertEqual((len(empty[0]), len(empty[1])), (0, 0))
        self.assertEqual(len(peaks.read(0, 10 ** 9, 10, audio=audio)[0]), 10)
        self.assertEqual(Peaks(np.zeros((1, 0), np.float32)).frames, 0)
        self.assertEqual(len(Peaks(np.zeros((1, 0), np.float32)).read(0, 10, 5)[0]), 0)
        tiny = Peaks(np.full((1, 10), 0.3, np.float32))
        self.assertEqual(len(tiny.levels), 1)
        self.assertEqual(float(tiny.read(0, 10, 4)[1][0]), np.float32(0.3))

    def test_track_peaks_cache(self):
        track = editor.Track('t1', 'T', np.zeros((1, 1000), np.float32))
        first = track.peaks()
        self.assertIs(track.peaks(), first)
        track.invalidate()
        self.assertIsNot(track.peaks(), first)
        state = track.snapshot()
        track.audio[:] = 1.0
        track.name = 'changed'
        track.restore(state)
        self.assertTrue(np.all(track.audio == 0.0))
        self.assertEqual(track.name, 'T')


if __name__ == '__main__':
    unittest.main()


class ClipTrimAndFadeTests(unittest.TestCase):
    """Clip edges trim a window over the audio; fades are applied at mix time."""

    def setUp(self):
        self.document = Document(48000)
        tone = np.ones((2, 48000 * 2), np.float32) * 0.5
        self.track = self.document.add_track(tone, 'clip', samplerate=48000)

    def test_right_edge_trims_without_losing_audio(self):
        self.document.resize_clip(self.track, 'right', 1.0)
        self.assertEqual(self.track.frames, 48000)
        self.assertEqual(self.track.total_frames, 96000)
        self.assertEqual(self.track.end, 48000)
        self.document.resize_clip(self.track, 'right', 2.0)
        self.assertEqual(self.track.frames, 96000)

    def test_left_edge_moves_the_in_point_and_the_position(self):
        self.document.resize_clip(self.track, 'left', 0.5)
        self.assertEqual((self.track.start, self.track.offset, self.track.frames), (24000, 24000, 72000))
        self.assertTrue(np.array_equal(self.track.view(), self.track.audio[:, 24000:]))
        self.assertIsNotNone(self.document.undo())
        self.assertEqual((self.track.start, self.track.offset, self.track.frames), (0, 0, 96000))

    def test_a_trimmed_clip_is_flattened_before_a_sample_edit(self):
        self.document.resize_clip(self.track, 'left', 0.5)
        self.document.selection = (0.6, 0.8)
        self.document.silence()
        self.assertEqual((self.track.start, self.track.length), (0, -1))
        self.assertEqual(self.track.frames, 72000)

    def test_fades_shape_the_mix_and_are_bounded_by_the_clip(self):
        self.document.set_fade(self.track, 'in', 0.5)
        self.document.set_fade(self.track, 'out', 0.5)
        mix = self.document.mixdown()
        self.assertLess(abs(float(mix[0, 10])), 0.05)
        self.assertAlmostEqual(float(mix[0, 48000]), 0.5, places=2)
        self.assertLess(abs(float(mix[0, -10])), 0.05)
        self.document.set_fade(self.track, 'in', 99.0)
        self.assertLessEqual(self.track.fade_in + self.track.fade_out, self.track.frames / 48000 + 1e-6)

    def test_trim_and_fades_survive_a_session_round_trip(self):
        self.document.resize_clip(self.track, 'left', 0.25)
        self.document.resize_clip(self.track, 'right', 1.5)
        self.document.set_fade(self.track, 'in', 0.2)
        self.document.set_fade(self.track, 'out', 0.3)
        with tempfile.TemporaryDirectory() as folder:
            self.document.save_session(Path(folder) / 'session')
            reloaded = Document.load_session(Path(folder) / 'session')
        track = reloaded.tracks[0]
        self.assertEqual((track.start, track.length), (self.track.start, self.track.length))
        self.assertEqual(track.total_frames, self.track.total_frames)
        self.assertAlmostEqual(track.fade_in, 0.2)
        self.assertAlmostEqual(track.fade_out, 0.3)


class MultiClipTests(unittest.TestCase):
    """A track holds several clips; a clip moved to another track goes through that track's inserts."""

    def setUp(self):
        self.doc = Document(RATE)
        self.a = self.doc.add_track(np.full((1, RATE), 0.25, np.float32), 'A')
        self.b = self.doc.add_track(np.full((1, RATE), 0.5, np.float32), 'B', offset_seconds=0.5)

    def test_a_clip_added_where_another_one_is_goes_after_it(self):
        clip = self.doc.add_clip(self.a, np.ones((1, 1000), np.float32), RATE, offset_seconds=0.2, name='late')
        self.assertEqual((len(self.a.clips), clip.offset), (2, RATE))      # 0.2 s is taken: after the last clip
        free = self.doc.add_clip(self.a, np.ones((1, 1000), np.float32), RATE, offset_seconds=3.0, name='free')
        self.assertEqual(free.offset, 3 * RATE)                              # a free place is kept
        self.assertEqual((self.a.offset, self.a.end), (0, 3 * RATE + 1000))
        self.assertEqual(self.doc.undo(), 'Add clip free')
        self.assertEqual(len(self.a.clips), 2)
        resampled = self.doc.add_clip(self.b, np.ones((2, 500), np.float32), RATE // 2, offset_seconds=0.0)
        self.assertEqual((resampled.frames, resampled.channels), (1000, 2))

    def test_the_mix_sums_every_clip_of_a_track(self):
        self.doc.add_clip(self.a, np.full((1, RATE), 0.25, np.float32), RATE, offset_seconds=2.0)
        mix = self.doc.mixdown(channels=1, tail={'enabled': False})
        self.assertEqual(mix.shape[1], 3 * RATE)
        self.assertAlmostEqual(float(mix[0, 100]), 0.25, places=4)
        self.assertAlmostEqual(float(mix[0, int(0.75 * RATE)]), 0.75, places=4)
        self.assertAlmostEqual(float(mix[0, int(1.75 * RATE)]), 0.0, places=4)       # the gap is silent
        self.assertAlmostEqual(float(mix[0, int(2.5 * RATE)]), 0.25, places=4)

    def test_moving_a_clip_to_another_track_uses_that_track_and_undoes(self):
        clip = self.a.clips[0]
        self.b.gain_db = -6.0206
        self.assertIs(self.doc.move_clip(self.a, clip, self.b, offset_seconds=2.0), clip)
        self.assertEqual((len(self.a.clips), len(self.b.clips)), (0, 2))
        self.assertEqual(self.b.clips[-1].offset, 2 * RATE)
        mix = self.doc.mixdown(channels=1, tail={'enabled': False})
        self.assertAlmostEqual(float(mix[0, int(2.5 * RATE)]), 0.125, places=3)        # B's gain now applies to it
        self.assertEqual(self.doc.undo(), 'Move clip')
        self.assertEqual((len(self.a.clips), len(self.b.clips)), (1, 1))
        self.assertEqual(self.a.clips[0].offset, 0)
        self.assertEqual(self.doc.redo(), 'Move clip')
        self.assertEqual((len(self.a.clips), len(self.b.clips)), (0, 2))

    def test_a_drag_opened_on_the_source_track_also_restores_the_target(self):
        clip = self.a.clips[0]
        self.doc.edit('Move clip', [self.a.id])                  # what the timeline does when the drag starts
        clip.offset = RATE // 4
        self.doc.move_clip(self.a, clip, self.b, record=False)
        self.assertEqual(len(self.b.clips), 2)
        self.assertEqual(self.doc.undo(), 'Move clip')
        self.assertEqual((len(self.a.clips), len(self.b.clips)), (1, 1))
        self.assertEqual(self.a.clips[0].offset, 0)

    def test_delete_duplicate_and_edits_across_clips(self):
        first = self.a.clips[0]
        twin = self.doc.duplicate_clip(self.a, first)
        self.assertEqual((twin.offset, len(self.a.clips)), (RATE, 2))
        self.assertIsNot(twin.audio, first.audio)
        self.doc.selected_track = 0
        self.doc.selection = (0.75, 1.25)                        # over the joint of the two clips
        self.assertTrue(self.doc.silence())
        self.assertTrue(np.all(first.view()[:, int(0.75 * RATE):] == 0.0))
        self.assertTrue(np.all(twin.view()[:, :int(0.25 * RATE)] == 0.0))
        self.assertTrue(self.doc.delete())                       # ripple: the second clip moves back
        self.assertEqual((first.frames, twin.offset, twin.frames), (int(0.75 * RATE), int(0.75 * RATE), int(0.75 * RATE)))
        self.assertTrue(self.doc.remove_clip(self.a, twin))
        self.assertEqual(len(self.a.clips), 1)
        self.assertEqual(self.doc.undo(), 'Delete clip A')
        self.assertEqual(len(self.a.clips), 2)

    def test_sessions_keep_the_clips_and_old_sessions_load(self):
        self.doc.add_clip(self.a, np.full((1, 2000), 0.1, np.float32), RATE, offset_seconds=4.0, name='second')
        self.doc.set_fade(self.a, 'in', 0.01, clip=self.a.clips[1])
        expected = self.doc.mixdown(tail={'enabled': False})
        with tempfile.TemporaryDirectory() as folder:
            self.doc.save_session(folder)
            loaded = Document.load_session(folder)
            self.assertEqual([c.name for c in loaded.tracks[0].clips], ['A', 'second'])
            self.assertAlmostEqual(loaded.tracks[0].clips[1].fade_in, 0.01)
            self.assertTrue(np.allclose(loaded.mixdown(tail={'enabled': False}), expected, atol=1e-6))
            # a schema 2 session (one clip per track, fields on the track) still opens
            import json
            index = json.loads((Path(folder) / 'session.json').read_text('utf-8'))
            legacy = dict(index, schemaVersion=2)
            legacy['tracks'] = [{k: v for k, v in item.items() if k != 'clips'} for item in index['tracks']]
            for item, original in zip(legacy['tracks'], index['tracks']):
                clip = original['clips'][0]
                item.update(file=clip['file'], offset=clip['offset'], start=clip['start'], length=clip['length'], fadeIn=clip['fadeIn'], fadeOut=clip['fadeOut'])
            (Path(folder) / 'session.json').write_text(json.dumps(legacy), 'utf-8')
            old = Document.load_session(folder)
        self.assertEqual([len(t.clips) for t in old.tracks], [1, 1])
        self.assertEqual(old.tracks[1].offset, RATE // 2)

    def test_an_empty_track_has_no_clip_and_keeps_its_channels(self):
        empty = self.doc.add_empty_track(channels=1)
        self.assertEqual((empty.clips, empty.frames, empty.channels, empty.audio.shape), ([], 0, 1, (1, 0)))
        self.doc.fill_track(empty, np.ones((1, 100), np.float32), RATE, offset_seconds=1.0)
        self.assertEqual((len(empty.clips), empty.offset), (1, RATE))

    def test_reverse_keeps_the_trimmed_audio_and_undoes(self):
        material = ramp(RATE)
        track = self.doc.add_track(material.copy(), 'R')
        clip = track.clips[0]
        self.doc.resize_clip(track, 'left', 0.25, clip=clip)                 # window = material[12000:48000]
        self.doc.resize_clip(track, 'right', 0.75, clip=clip)                # window = material[12000:36000]
        shown = clip.view().copy()
        self.assertIs(self.doc.reverse_clip(track, clip), clip)
        self.assertTrue(np.array_equal(clip.view(), shown[:, ::-1]))
        self.assertEqual((clip.offset, clip.frames, clip.total_frames), (12000, 24000, RATE))    # same place, nothing lost
        self.doc.resize_clip(track, 'right', 1.0, clip=clip)                 # the hidden audio is still there
        self.assertEqual(clip.frames, 36000)
        self.assertEqual(self.doc.undo(), 'Resize clip')
        self.assertEqual(self.doc.undo(), 'Reverse clip R')
        self.assertTrue(np.array_equal(clip.view(), shown) or np.array_equal(track.clips[0].view(), shown))
        again = track.clips[0]
        self.doc.reverse_clip(track, again)
        self.doc.reverse_clip(track, again)
        self.assertTrue(np.array_equal(again.view(), shown))
        self.a.mute = self.b.mute = True                                     # only this clip in the mix
        mono = self.doc.mixdown(channels=1, tail={'enabled': False})
        self.doc.reverse_clip(track, again)
        backwards = self.doc.mixdown(channels=1, tail={'enabled': False})
        self.assertTrue(np.allclose(backwards[0, 12000:36000], mono[0, 12000:36000][::-1], atol=1e-6))
