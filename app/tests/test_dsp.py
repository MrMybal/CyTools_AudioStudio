"""Native effects, tail rendering, analysis and audio file I/O (run from the app directory)."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tests._fixtures import tone, write_wav
from audiostudio import audio_io
from audiostudio.dsp import effects, tail, analysis

RATE = 44100


def non_default(param, workdir):
    """A legal value different from the default, chosen per parameter kind."""
    if param.kind == 'bool':
        return not param.default
    if param.kind == 'enum':
        return next(c for c in param.choices if c != param.default)
    if param.kind == 'string':
        # convolution impulse response: a real short impulse file
        impulse = np.zeros((1, 2000), np.float32)
        impulse[0, 0] = 1.0
        impulse[0, 1000] = 0.25
        return str(write_wav(Path(workdir) / 'impulse.wav', impulse, RATE))
    minimum = param.minimum if param.minimum is not None else param.default - 1
    maximum = param.maximum if param.maximum is not None else param.default + 1
    if param.default + 1 <= maximum:
        value = param.default + 1
    elif param.default - 1 >= minimum:
        value = param.default - 1
    else:
        value = minimum
    return int(value) if param.kind == 'int' else float(value)


class EffectRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audio = tone(0.3, RATE, 2)

    def assertAudio(self, output, effect_id):
        self.assertIsInstance(output, np.ndarray, effect_id)
        self.assertEqual(output.dtype, np.float32, effect_id)
        self.assertEqual(output.ndim, 2, effect_id)
        self.assertTrue(np.isfinite(output).all(), effect_id)

    def test_every_effect_renders_with_defaults(self):
        for effect_id in effects.REGISTRY:
            with self.subTest(effect=effect_id):
                self.assertAudio(effects.apply_effect(effect_id, self.audio, RATE, {}), effect_id)

    def test_every_effect_renders_with_non_default_values(self):
        with tempfile.TemporaryDirectory() as workdir:
            for effect_id, spec in effects.REGISTRY.items():
                values = {p.id: non_default(p, workdir) for p in spec.params}
                for p in spec.params:
                    self.assertNotEqual(values[p.id], p.default, f'{effect_id}.{p.id}')
                with self.subTest(effect=effect_id, values=values):
                    output = effects.apply_effect(effect_id, self.audio, RATE, values)
                    self.assertAudio(output, effect_id)
                    if not spec.changes_length:
                        self.assertEqual(output.shape[1], self.audio.shape[1], effect_id)

    def test_known_effect_behaviours(self):
        silent = effects.apply_effect('silence', self.audio, RATE, {})
        self.assertEqual(float(np.abs(silent).max()), 0.0)
        gained = effects.apply_effect('gain', self.audio, RATE, {'gain_db': -6.0})
        self.assertAlmostEqual(float(np.abs(gained).max()) / float(np.abs(self.audio).max()), 10 ** (-6 / 20), places=3)
        self.assertTrue(np.allclose(effects.apply_effect('reverse', self.audio, RATE, {}), self.audio[:, ::-1]))
        self.assertTrue(np.allclose(effects.apply_effect('invert', self.audio, RATE, {}), -self.audio, atol=1e-6))
        mono = effects.apply_effect('channels', self.audio, RATE, {'mode': 'mono'})
        self.assertEqual(mono.shape[0], 1)
        stretched = effects.apply_effect('time_stretch', self.audio, RATE, {'stretch_factor': 2.0})
        self.assertAlmostEqual(stretched.shape[1] / self.audio.shape[1], 0.5, delta=0.05)
        padded = effects.apply_effect('add_silence', self.audio, RATE, {'duration_seconds': 0.5, 'position': 'start'})
        self.assertEqual(padded.shape[1], self.audio.shape[1] + int(0.5 * RATE))
        self.assertEqual(float(np.abs(padded[:, :int(0.5 * RATE)]).max()), 0.0)
        resampled = effects.apply_effect('resample', self.audio, RATE, {'target_rate': 22050})
        self.assertEqual(resampled.shape[1], self.audio.shape[1] // 2)
        normalized = effects.apply_effect('normalize', self.audio * 0.1, RATE, {'target_db': -3.0})
        self.assertAlmostEqual(float(np.abs(normalized).max()), 10 ** (-3 / 20), places=4)
        offset = effects.apply_effect('dc_offset', self.audio + 0.2, RATE, {})
        self.assertAlmostEqual(float(np.mean(offset)), 0.0, places=4)
        trimmed = effects.apply_effect('trim_silence', padded, RATE, {'padding_ms': 0.0})
        self.assertLess(trimmed.shape[1], padded.shape[1])

    def test_normalize_coerces_and_clamps(self):
        spec = effects.get('delay')
        values = spec.normalize({'delay_seconds': 99.0, 'feedback': -1.0, 'mix': None, 'unknown': 5})
        self.assertEqual(values['delay_seconds'], 10.0)
        self.assertEqual(values['feedback'], 0.0)
        self.assertEqual(values['mix'], spec.defaults()['mix'])
        self.assertNotIn('unknown', values)
        self.assertEqual(effects.get('fade_in').normalize({'shape': 'bogus'})['shape'], 'linear')
        self.assertEqual(effects.get('loudness').normalize({'true_peak_limit': 0})['true_peak_limit'], False)
        self.assertEqual(effects.get('gain').normalize({'gain_db': float('nan')})['gain_db'], 0.0)
        with self.assertRaises(KeyError):
            effects.get('no_such_effect')
        self.assertIsNone(effects.build_plugin('reverse', {}))
        self.assertIsNotNone(effects.build_plugin('reverb', {}))

    def test_catalogue_schema(self):
        catalogue = effects.catalogue()
        self.assertEqual(len(catalogue), len(effects.REGISTRY))
        for entry in catalogue:
            self.assertEqual(set(entry), {'id', 'name', 'category', 'help', 'stateful', 'realtime', 'changesLength', 'parameters', 'ui', 'sidechain'})
            self.assertIsInstance(entry['realtime'], bool)
            self.assertIsInstance(entry['stateful'], bool)
            self.assertIsInstance(entry['changesLength'], bool)
            for name, schema in entry['parameters'].items():
                self.assertTrue('type' in schema or 'enum' in schema, f'{entry["id"]}.{name}')
                self.assertIn('default', schema)
                self.assertIn('description', schema)
                if 'enum' in schema:
                    self.assertIn(schema['default'], schema['enum'])
                if schema.get('type') == 'number':
                    self.assertIsInstance(schema['default'], (int, float))
                    if 'minimum' in schema:
                        self.assertLessEqual(schema['minimum'], schema['default'])
                    if 'maximum' in schema:
                        self.assertGreaterEqual(schema['maximum'], schema['default'])
        by_id = {e['id']: e for e in catalogue}
        self.assertTrue(by_id['reverb']['stateful'])
        self.assertFalse(by_id['normalize']['stateful'])
        self.assertTrue(by_id['time_stretch']['changesLength'])
        self.assertEqual(by_id['convolution']['parameters']['impulse_response']['type'], 'string')


class TailTests(unittest.TestCase):
    def test_delay_produces_measurable_tail(self):
        audio = tone(0.5, RATE, 2)
        settings = tail.TailSettings(enabled=True, threshold_db=-60.0, max_seconds=3.0, hold_seconds=0.1)
        extended = tail.extend(audio, RATE, settings)
        self.assertEqual(extended.shape[1], audio.shape[1] + int(3.0 * RATE))
        self.assertEqual(float(np.abs(extended[:, audio.shape[1]:]).max()), 0.0)
        plugin = effects.build_plugin('delay', {'delay_seconds': 0.2, 'feedback': 0.5, 'mix': 0.5})
        rendered = np.ascontiguousarray(plugin(extended, float(RATE), reset=True).astype(np.float32))
        measured = tail.measure_tail(rendered, RATE, audio.shape[1], -60.0)
        self.assertGreater(measured, 0.2)
        self.assertLess(measured, 3.0)
        trimmed = tail.trim(rendered, RATE, settings, audio.shape[1])
        self.assertGreater(trimmed.shape[1], audio.shape[1])
        self.assertLess(trimmed.shape[1], rendered.shape[1])
        self.assertAlmostEqual(trimmed.shape[1], audio.shape[1] + measured * RATE + 0.1 * RATE, delta=2)

    def test_trim_never_shortens_below_original_length(self):
        audio = tone(0.5, RATE, 1)
        settings = tail.TailSettings(max_seconds=1.0)
        extended = tail.extend(audio, RATE, settings)            # silent extension: nothing to keep
        trimmed = tail.trim(extended, RATE, settings, audio.shape[1])
        self.assertEqual(trimmed.shape[1], audio.shape[1])
        self.assertEqual(tail.measure_tail(extended, RATE, audio.shape[1]), 0.0)
        # A buffer shorter than the original is returned untouched.
        short = audio[:, :100]
        self.assertIs(tail.trim(short, RATE, settings, audio.shape[1]), short)
        self.assertEqual(tail.measure_tail(short, RATE, audio.shape[1]), 0.0)

    def test_disabled_tail_keeps_length(self):
        audio = tone(0.25, RATE, 2)
        settings = tail.TailSettings(enabled=False, max_seconds=5.0)
        self.assertIs(tail.extend(audio, RATE, settings), audio)
        longer = np.concatenate([audio, audio], axis=1)
        self.assertIs(tail.trim(longer, RATE, settings, audio.shape[1]), longer)
        self.assertIs(tail.extend(audio, RATE, tail.TailSettings(max_seconds=0.0)), audio)

    def test_settings_from_dict_clamps(self):
        settings = tail.TailSettings.from_dict({'enabled': 1, 'threshold_db': 5.0, 'max_seconds': 9999, 'hold_seconds': -3})
        self.assertEqual((settings.enabled, settings.threshold_db, settings.max_seconds, settings.hold_seconds), (True, 0.0, 600.0, 0.0))
        self.assertEqual(tail.TailSettings.from_dict(None).as_dict(), tail.TailSettings().as_dict())
        self.assertEqual(tail.last_audible_index(np.zeros((1, 10), np.float32), -60.0), -1)
        self.assertEqual(tail.last_audible_index(np.zeros((1, 0), np.float32), -60.0), -1)


class AnalysisTests(unittest.TestCase):
    def test_statistics_keys_and_values(self):
        audio = tone(1.0, RATE, 2)
        stats = analysis.statistics(audio, RATE)
        for key in ('channels', 'frames', 'samplerate', 'durationSeconds', 'peakDbfs', 'rmsDbfs', 'clippedSamples', 'dcOffset', 'integratedLufs', 'truePeakDbtp'):
            self.assertIn(key, stats)
        self.assertEqual((stats['channels'], stats['frames'], stats['samplerate']), (2, RATE, RATE))
        self.assertAlmostEqual(stats['durationSeconds'], 1.0)
        self.assertAlmostEqual(stats['peakDbfs'], 20 * np.log10(0.5), delta=0.05)
        self.assertAlmostEqual(stats['rmsDbfs'], 20 * np.log10(0.5 / np.sqrt(2)), delta=0.05)
        self.assertEqual(stats['clippedSamples'], 0)
        self.assertEqual(len(stats['dcOffset']), 2)
        self.assertLess(stats['integratedLufs'], 0.0)
        self.assertGreaterEqual(stats['truePeakDbtp'], stats['peakDbfs'] - 0.01)
        clipped = analysis.statistics(np.ones((1, 100), np.float32), RATE)
        self.assertEqual(clipped['clippedSamples'], 100)
        silent = analysis.statistics(np.zeros((1, 100), np.float32), RATE)
        self.assertIsNone(silent['peakDbfs'])
        self.assertIsNone(silent['rmsDbfs'])

    def test_silence_and_peaks(self):
        audio = np.zeros((1, RATE), np.float32)
        audio[0, RATE // 4:RATE // 2] = 0.5
        silence = analysis.leading_trailing_silence(audio, RATE)
        self.assertAlmostEqual(silence['leadingSeconds'], 0.25, places=3)
        self.assertAlmostEqual(silence['trailingSeconds'], 0.5, delta=0.001)
        whole = analysis.leading_trailing_silence(np.zeros((1, RATE), np.float32), RATE)
        self.assertEqual((whole['leadingSeconds'], whole['trailingSeconds']), (1.0, 0.0))
        peaks = analysis.peaks(audio, 8)
        self.assertEqual(peaks.shape, (8, 2))
        self.assertEqual(peaks[3, 1], 0.5)
        self.assertEqual(peaks[0, 1], 0.0)
        self.assertEqual(analysis.peaks(audio, 0).shape, (0, 2))
        spectrum, seconds_per_column = analysis.spectrogram(tone(0.5, RATE, 2), RATE)
        self.assertEqual(spectrum.shape[0], 513)
        self.assertGreater(spectrum.shape[1], 0)
        self.assertGreater(seconds_per_column, 0.0)


class AudioIoTests(unittest.TestCase):
    def test_round_trip_every_write_format(self):
        audio = tone(1.0, RATE, 2)
        with tempfile.TemporaryDirectory() as workdir:
            for fmt, spec in audio_io.WRITE_FORMATS.items():
                with self.subTest(format=fmt):
                    path = Path(workdir) / f'tone_{fmt}{spec["suffix"]}'
                    written = audio_io.save(path, audio, RATE, fmt=fmt, subtype=None if spec['lossy'] else spec['subtypes'][-1])
                    self.assertEqual(written, path)
                    self.assertTrue(path.is_file())
                    info = audio_io.probe(path)
                    self.assertEqual((info.samplerate, info.channels), (RATE, 2))
                    self.assertAlmostEqual(info.duration, 1.0, delta=0.1)
                    loaded, rate = audio_io.load(path)
                    self.assertEqual(rate, RATE)
                    self.assertEqual(loaded.dtype, np.float32)
                    self.assertEqual(loaded.shape[0], 2)
                    self.assertAlmostEqual(loaded.shape[1] / RATE, 1.0, delta=0.1)
                    frames = min(loaded.shape[1], audio.shape[1]) - 2000
                    correlation = float(np.corrcoef(loaded[0, :frames], audio[0, :frames])[0, 1])
                    if spec['lossy']:
                        self.assertGreater(abs(correlation), 0.95, fmt)
                    else:
                        self.assertEqual(loaded.shape, audio.shape)
                        self.assertTrue(np.allclose(loaded, audio, atol=1e-6 if fmt in ('wav', 'aiff') else 1e-4), fmt)

    def test_save_infers_format_and_rejects_bad_subtype(self):
        audio = tone(0.1, RATE, 1)
        with tempfile.TemporaryDirectory() as workdir:
            path = audio_io.save(Path(workdir) / 'inferred.flac', audio, RATE)
            self.assertEqual(audio_io.probe(path).format, 'FLAC')
            path = audio_io.save(Path(workdir) / 'inferred.aif', audio, RATE)
            self.assertEqual(audio_io.probe(path).format, 'AIFF')
            with self.assertRaises(ValueError):
                audio_io.save(Path(workdir) / 'x.xyz', audio, RATE)
            with self.assertRaises(ValueError):
                audio_io.save(Path(workdir) / 'x.flac', audio, RATE, fmt='flac', subtype='FLOAT')
            with self.assertRaises(FileNotFoundError):
                audio_io.load(Path(workdir) / 'missing.wav')
            with self.assertRaises(FileNotFoundError):
                audio_io.probe(Path(workdir) / 'missing.wav')

    def test_load_options(self):
        audio = tone(0.5, 48000, 2)
        with tempfile.TemporaryDirectory() as workdir:
            path = write_wav(Path(workdir) / 'x.wav', audio, 48000)
            mono, rate = audio_io.load(path, mono=True)
            self.assertEqual((mono.shape[0], rate), (1, 48000))
            self.assertTrue(np.allclose(mono[0], audio.mean(axis=0), atol=1e-6))
            converted, rate = audio_io.load(path, samplerate=24000)
            self.assertEqual((converted.shape, rate), ((2, 12000), 24000))

    def test_resample_length_is_exact(self):
        cases = [(48000, 44100, 48000, 44100), (44100, 48000, 44100, 48000), (48000, 24000, 48000, 24000), (22050, 44100, 1000, 2000), (48000, 48000, 777, 777)]
        for source, target, frames, expected in cases:
            with self.subTest(source=source, target=target):
                audio = np.zeros((2, frames), np.float32)
                out = audio_io.resample(audio, source, target)
                self.assertEqual(out.shape, (2, expected))
                self.assertEqual(out.dtype, np.float32)
        same = tone(0.1, 48000, 1)
        self.assertIs(audio_io.resample(same, 48000, 48000), same)
        sine = tone(1.0, 48000, 1)
        down = audio_io.resample(sine, 48000, 16000)
        self.assertAlmostEqual(float(np.abs(down[0, 100:-100]).max()), 0.5, delta=0.02)

    def test_levels(self):
        self.assertAlmostEqual(audio_io.peak_dbfs(np.array([[0.5, -0.25]], np.float32)), 20 * np.log10(0.5))
        self.assertEqual(audio_io.peak_dbfs(np.zeros((1, 4), np.float32)), -np.inf)
        self.assertEqual(audio_io.rms_dbfs(np.zeros((1, 0), np.float32)), -np.inf)
        self.assertAlmostEqual(audio_io.rms_dbfs(np.full((1, 8), 0.5, np.float32)), 20 * np.log10(0.5), places=5)


if __name__ == '__main__':
    unittest.main()
