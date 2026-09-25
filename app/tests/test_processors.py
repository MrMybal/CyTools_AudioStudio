"""Block processors: dynamics, filters, modulation, space, distortion, vocoder (no GPU, no files)."""
import unittest

import numpy as np

from tests._fixtures import tone
from audiostudio.dsp import effects
from audiostudio.dsp import processors as P
from audiostudio.dsp import dynamics, filters, space

RATE = 48000


def blocks(processor, audio, size=1024, sidechain=None):
    parts = []
    for start in range(0, audio.shape[1], size):
        key = None if sidechain is None else sidechain[:, start:start + size]
        parts.append(processor.process(audio[:, start:start + size], sidechain=key))
    return np.concatenate(parts, axis=1)


def rms_db(block):
    return float(20.0 * np.log10(np.sqrt(np.mean(block.astype(np.float64) ** 2)) + 1e-12))


class HelperTests(unittest.TestCase):
    def test_release_hold_matches_loop(self):
        rng = np.random.default_rng(1)
        detector = np.abs(rng.standard_normal(5000))
        coef = 0.999
        expected = np.empty_like(detector)
        previous = 0.3
        for index, value in enumerate(detector):
            previous = max(value, coef * previous)
            expected[index] = previous
        got, last = P.release_hold(detector, 0.3, coef)
        self.assertTrue(np.allclose(got, expected, rtol=1e-9, atol=1e-12))
        self.assertAlmostEqual(last, expected[-1])

    def test_gain_computer(self):
        levels = np.array([-40.0, -20.0, -10.0, 0.0])
        hard = P.gain_computer(levels, -20.0, 4.0, 0.0)
        self.assertTrue(np.allclose(hard, [0.0, 0.0, -7.5, -15.0]))
        soft = P.gain_computer(levels, -20.0, 4.0, 6.0)
        self.assertLess(soft[1], 0.0)                     # inside the knee already compresses a little
        self.assertAlmostEqual(soft[3], -15.0)
        gate = P.expander_curve(np.array([-70.0, -50.0, -30.0]), -40.0, 10.0, -60.0)
        self.assertEqual(list(gate), [-60.0, -60.0, 0.0])

    def test_biquad_response(self):
        freqs = np.array([50.0, 1000.0, 15000.0])
        peak = P.biquad('peak', 1000.0, 1.0, 6.0, RATE)
        response = P.response_db(peak, freqs, RATE)
        self.assertAlmostEqual(response[1], 6.0, places=2)
        self.assertLess(abs(response[0]), 0.3)
        low = P.response_db(P.biquad('lowpass', 1000.0, 0.707, 0.0, RATE), freqs, RATE)
        self.assertLess(low[2], -40.0)
        with self.assertRaises(ValueError):
            P.biquad('bogus', 100.0, 1.0, 0.0, RATE)

    def test_crossover_sums_flat(self):
        crossover = P.Crossover(RATE, 1000.0)
        impulse = np.zeros((1, 8192))
        impulse[0, 0] = 1.0
        low, high = crossover.split(impulse)
        spectrum = np.abs(np.fft.rfft((low + high)[0]))
        self.assertTrue(np.allclose(spectrum[10:-10], 1.0, atol=0.02))

    def test_biquad_chain_keeps_state_across_blocks(self):
        chain = P.BiquadChain(P.biquad('lowpass', 500.0, 0.707, 0.0, RATE))
        audio = tone(0.5, RATE, 2, 200.0)
        whole = P.BiquadChain(P.biquad('lowpass', 500.0, 0.707, 0.0, RATE)).process(audio)
        parts = np.concatenate([chain.process(audio[:, i:i + 777]) for i in range(0, audio.shape[1], 777)], axis=1)
        self.assertTrue(np.allclose(whole, parts, atol=1e-6))


class DynamicsTests(unittest.TestCase):
    def test_compressor_reduces_loud_material_and_reports_gain_reduction(self):
        audio = tone(1.0, RATE, 2, 440.0, amplitude=0.9)
        processor = effects.make_processor('compressor', {'threshold_db': -30.0, 'ratio': 10.0, 'attack_ms': 1.0, 'release_ms': 50.0, 'knee_db': 0.0}, RATE)
        out = blocks(processor, audio)
        self.assertEqual(out.shape, audio.shape)
        self.assertLess(rms_db(out[:, RATE // 2:]), rms_db(audio[:, RATE // 2:]) - 15.0)
        self.assertLess(processor.meters['gain_reduction_db'], -15.0)
        quiet = blocks(effects.make_processor('compressor', {'threshold_db': -30.0, 'ratio': 10.0}, RATE), audio * 0.01)
        self.assertTrue(np.allclose(quiet, audio * 0.01, atol=1e-4))

    def test_compressor_curve_and_live_parameter_change(self):
        processor = effects.make_processor('compressor', {'threshold_db': -20.0, 'ratio': 4.0, 'knee_db': 0.0, 'makeup_db': 3.0}, RATE)
        curve = processor.curve(np.array([-40.0, 0.0]))
        self.assertTrue(np.allclose(curve, [-37.0, -12.0]))
        audio = tone(0.2, RATE, 2, 440.0, amplitude=0.9)
        blocks(processor, audio)
        processor.set_params({'threshold_db': -60.0, 'ratio': 20.0})
        self.assertEqual(processor.params['ratio'], 20.0)
        out = blocks(processor, audio)
        self.assertLess(rms_db(out), rms_db(audio) - 20.0)

    def test_sidechain_ducking(self):
        pad = np.full((2, RATE), 0.5, np.float32)
        key = np.concatenate([np.zeros((2, RATE // 2), np.float32), np.full((2, RATE // 2), 0.9, np.float32)], axis=1)
        processor = effects.make_processor('compressor', {'threshold_db': -40.0, 'ratio': 20.0, 'attack_ms': 1.0, 'release_ms': 30.0, 'sidechain_input': True}, RATE)
        out = blocks(processor, pad, sidechain=key)
        self.assertGreater(float(np.abs(out[0, 1000:20000]).max()), 0.45)
        self.assertLess(float(np.abs(out[0, 30000:]).max()), 0.05)

    def test_gate_closes_on_silence(self):
        loud = tone(0.5, RATE, 2, 440.0, amplitude=0.5)
        hiss = (np.random.default_rng(2).standard_normal((2, RATE // 2)) * 0.001).astype(np.float32)
        audio = np.concatenate([loud, hiss], axis=1)
        processor = effects.make_processor('noise_gate', {'threshold_db': -40.0, 'ratio': 50.0, 'range_db': -90.0, 'release_ms': 20.0}, RATE)
        out = blocks(processor, audio)
        self.assertGreater(rms_db(out[:, 1000:RATE // 2 - 1000]), -12.0)
        self.assertLess(rms_db(out[:, -8000:]), rms_db(hiss[:, -8000:]) - 30.0)

    def test_multiband_bands_sum_flat_and_report(self):
        params = {'bands': 3}
        for n in range(1, 5):
            params[f'b{n}_threshold_db'] = 0.0
        processor = effects.make_processor('multiband_compressor', params, RATE)
        impulse = np.zeros((2, 8192), np.float32)
        impulse[:, 100] = 0.5
        out = processor.process(impulse)
        spectrum = np.abs(np.fft.rfft(out[0])) / 0.5
        self.assertTrue(np.allclose(spectrum[20:-20], 1.0, atol=0.05), spectrum[20:30])
        self.assertEqual(len(processor.meters['band_reduction_db']), 3)
        bands = processor.split(tone(0.1, RATE, 2, 60.0))
        self.assertEqual(len(bands), 3)
        self.assertGreater(rms_db(bands[0]), rms_db(bands[2]) + 30.0)

    def test_de_esser_only_touches_sibilance(self):
        low = tone(0.5, RATE, 2, 200.0, amplitude=0.4)
        high = tone(0.5, RATE, 2, 8000.0, amplitude=0.4)
        processor = effects.make_processor('de_esser', {'frequency_hz': 5000.0, 'threshold_db': -30.0, 'ratio': 10.0, 'range_db': -30.0}, RATE)
        out = blocks(processor, low + high)
        spectrum_in = np.abs(np.fft.rfft((low + high)[0, -8192:]))
        spectrum_out = np.abs(np.fft.rfft(out[0, -8192:]))
        bin_low, bin_high = int(200 * 8192 / RATE), int(8000 * 8192 / RATE)
        self.assertGreater(spectrum_out[bin_low], spectrum_in[bin_low] * 0.7)
        self.assertLess(spectrum_out[bin_high], spectrum_in[bin_high] * 0.4)

    def test_transient_shaper_boosts_attacks(self):
        audio = np.zeros((2, RATE // 2), np.float32)
        audio[:, 2000:2100] = 0.5                      # a click, then silence
        audio[:, 2100:20000] = 0.05
        processor = effects.make_processor('transient_shaper', {'attack_amount': 100.0, 'sustain_amount': 0.0}, RATE)
        first = processor.process(audio[:, :4096])
        self.assertGreater(processor.meters['gain_boost_db'], 3.0)       # meters describe the last block
        out = np.concatenate([first, blocks(processor, audio[:, 4096:])], axis=1)
        self.assertGreater(float(np.abs(out[:, 2000:2100]).max()), 0.6)


class FilterTests(unittest.TestCase):
    def test_parametric_eq_response_and_bands(self):
        params = {'b1_on': True, 'b1_type': 'peak', 'b1_freq': 1000.0, 'b1_gain': 8.0, 'b1_q': 2.0}
        for n in range(2, 9):
            params[f'b{n}_on'] = False
        processor = effects.make_processor('parametric_eq', params, RATE)
        freqs = np.array([100.0, 1000.0, 10000.0])
        response = processor.response(freqs)
        self.assertAlmostEqual(response[1], 8.0, places=1)
        self.assertLess(abs(response[0]), 0.5)
        self.assertTrue(np.allclose(processor.band_response(2, freqs), 0.0))
        audio = tone(0.5, RATE, 1, 1000.0, amplitude=0.1)
        out = blocks(processor, audio)
        self.assertAlmostEqual(rms_db(out[:, -8000:]) - rms_db(audio[:, -8000:]), 8.0, delta=0.3)

    def test_graphic_eq_and_notch(self):
        eq = effects.make_processor('graphic_eq', {'g5': -12.0}, RATE)          # 1 kHz band
        self.assertAlmostEqual(eq.response(np.array([1000.0]))[0], -12.0, delta=0.5)
        notch = effects.make_processor('notch', {'frequency_hz': 50.0, 'q': 10.0}, RATE)
        hum = tone(1.0, RATE, 1, 50.0, amplitude=0.5)
        out = blocks(notch, hum)
        self.assertLess(rms_db(out[:, -8000:]), rms_db(hum[:, -8000:]) - 30.0)

    def test_auto_wah_moves_cutoff(self):
        processor = effects.make_processor('auto_wah', {'min_hz': 300.0, 'max_hz': 3000.0, 'sensitivity_db': 24.0}, RATE)
        quiet = blocks(processor, tone(0.2, RATE, 2, 500.0, amplitude=0.001))
        low_cutoff = processor.meters['cutoff_hz']
        loud = blocks(processor, tone(0.2, RATE, 2, 500.0, amplitude=0.9))
        self.assertGreater(processor.meters['cutoff_hz'], low_cutoff * 2.0)
        self.assertEqual(loud.shape, quiet.shape)

    def test_static_response_of_juce_filters(self):
        response = filters.static_response('lowpass', {'cutoff_hz': 1000.0}, np.array([100.0, 10000.0]), RATE)
        self.assertLess(response[1], -15.0)
        self.assertGreater(response[0], -1.0)
        self.assertEqual(filters.static_response('ladder_filter', {'mode': 'LPF24', 'cutoff_hz': 500.0, 'resonance': 0.5}, np.array([5000.0]), RATE).shape, (1,))


class ModulationAndSpaceTests(unittest.TestCase):
    def test_tremolo_and_autopan(self):
        audio = np.full((2, RATE), 0.5, np.float32)
        out = blocks(effects.make_processor('tremolo', {'rate_hz': 4.0, 'depth': 1.0, 'shape': 'sine'}, RATE), audio)
        self.assertLess(float(out.min()), 0.05)
        self.assertGreater(float(out.max()), 0.45)
        panned = blocks(effects.make_processor('auto_pan', {'rate_hz': 1.0, 'depth': 1.0}, RATE), audio)
        self.assertGreater(float(np.abs(panned[0] - panned[1]).max()), 0.5)

    def test_pingpong_delay_alternates_channels_and_offline_matches_live(self):
        audio = np.zeros((2, RATE), np.float32)
        audio[:, :100] = 0.8
        params = {'delay_ms': 100.0, 'feedback': 0.5, 'ping_pong': 1.0, 'mix': 1.0, 'tone_hz': 20000.0}
        out = blocks(effects.make_processor('pingpong_delay', params, RATE), audio)
        first = int(0.1 * RATE)
        self.assertGreater(float(np.abs(out[:, first:first + 200]).max()), 0.3)
        self.assertGreater(float(np.abs(out[:, 2 * first:2 * first + 200]).max()), 0.1)
        offline = effects.apply_effect('pingpong_delay', audio, RATE, params)
        self.assertTrue(np.allclose(out, offline, atol=1e-5))

    def test_multitap_delay_taps(self):
        audio = np.zeros((2, RATE), np.float32)
        audio[:, :10] = 1.0
        params = {'delay_ms': 100.0, 'mix': 1.0, 'tap1_on': True, 'tap1_time': 1.0, 'tap1_gain_db': 0.0, 'tap2_on': True, 'tap2_time': 2.0, 'tap2_gain_db': -6.0,
                  'tap3_on': False, 'tap4_on': False}
        out = blocks(effects.make_processor('multitap_delay', params, RATE), audio)
        self.assertGreater(float(np.abs(out[:, 4800:4815]).max()), 0.3)
        self.assertGreater(float(np.abs(out[:, 9600:9615]).max()), 0.15)
        self.assertLess(float(np.abs(out[:, 14400:14415]).max()), 0.01)

    def test_ir_reverb_has_a_tail_of_the_requested_decay(self):
        impulse = space.synth_impulse('hall', 1.0, 0.0, 0.5, 0.5, 20.0, 20000.0, 1.0, RATE)
        self.assertEqual(impulse.shape[0], 2)
        early = float(np.sqrt(np.mean(impulse[:, :4800] ** 2)))
        late = float(np.sqrt(np.mean(impulse[:, int(0.9 * RATE):int(1.0 * RATE)] ** 2)))
        self.assertLess(20 * np.log10(late / early), -35.0)
        processor = effects.make_processor('ir_reverb', {'type': 'plate', 'decay_seconds': 0.8, 'mix': 1.0}, RATE)
        audio = np.zeros((2, RATE), np.float32)
        audio[:, :50] = 0.5
        out = blocks(processor, audio)
        self.assertGreater(float(np.abs(out[:, RATE // 4:RATE // 2]).max()), 0.001)
        times, levels = processor.envelope(50)
        self.assertEqual(len(times), 50)
        self.assertLess(levels[-1], levels[3])
        # changing a non-IR parameter keeps the impulse, changing the type rebuilds it
        before = processor.impulse
        processor.set_params({'mix': 0.5})
        self.assertIs(processor.impulse, before)
        processor.set_params({'type': 'room'})
        self.assertIsNot(processor.impulse, before)

    def test_vocoder_follows_the_modulator(self):
        voice = np.concatenate([tone(0.3, RATE, 1, 300.0, amplitude=0.6), np.zeros((1, RATE // 2), np.float32)], axis=1)
        voice = np.repeat(voice, 2, axis=0)
        processor = effects.make_processor('vocoder', {'carrier': 'saw', 'pitch_hz': 110.0, 'bands': 8, 'mix': 1.0}, RATE)
        out = blocks(processor, voice)
        self.assertGreater(rms_db(out[:, 2000:12000]), rms_db(out[:, -12000:]) + 20.0)
        self.assertEqual(len(processor.meters['band_level_db']), 8)
        keyed = effects.make_processor('vocoder', {'carrier': 'sidechain', 'bands': 8, 'mix': 1.0}, RATE)
        out2 = blocks(keyed, voice, sidechain=tone(0.8, RATE, 2, 220.0, amplitude=0.5))
        self.assertGreater(rms_db(out2[:, 2000:12000]), -40.0)


class DistortionTests(unittest.TestCase):
    def test_shapers_limit_peaks_and_expose_curves(self):
        audio = tone(0.2, RATE, 2, 220.0, amplitude=1.0)
        for effect_id in ('tape_saturation', 'tube_drive', 'overdrive', 'fuzz', 'wavefolder'):
            processor = effects.make_processor(effect_id, {'drive_db': 18.0, 'output_db': 0.0}, RATE)
            out = blocks(processor, audio)
            self.assertLessEqual(float(np.abs(out).max()), 1.05, effect_id)
            curve = processor.curve(np.linspace(-1.0, 1.0, 11))
            self.assertEqual(curve.shape, (11,))
            self.assertTrue(np.all(np.isfinite(curve)))

    def test_sample_reducer_holds_samples(self):
        audio = np.linspace(0.0, 1.0, 64, dtype=np.float32)[np.newaxis, :]
        processor = effects.make_processor('sample_reducer', {'factor': 4, 'bit_depth': 24.0, 'mix': 1.0}, RATE)
        out = np.concatenate([processor.process(audio[:, :30]), processor.process(audio[:, 30:])], axis=1)
        self.assertTrue(np.allclose(out[0, :4], audio[0, 0]))
        self.assertTrue(np.allclose(out[0, 28:32], audio[0, 28]))     # the hold continues across the block boundary


class CreativeTests(unittest.TestCase):
    def test_pitch_shifter_moves_the_pitch_one_octave(self):
        audio = tone(1.0, RATE, 1, 220.0, amplitude=0.5)
        out = blocks(effects.make_processor('pitch_shifter', {'semitones': 12.0, 'mix': 1.0}, RATE), np.repeat(audio, 2, axis=0))[0, RATE // 4:]
        spectrum = np.abs(np.fft.rfft(out * np.hanning(out.size)))
        freqs = np.fft.rfftfreq(out.size, 1.0 / RATE)
        self.assertAlmostEqual(freqs[spectrum.argmax()], 440.0, delta=30.0)
        unity = blocks(effects.make_processor('pitch_shifter', {'semitones': 0.0}, RATE), np.repeat(audio, 2, axis=0))
        self.assertTrue(np.allclose(unity[:, 100:], np.repeat(audio, 2, axis=0)[:, 100:], atol=1e-5))

    def test_frequency_shifter_shifts_by_hertz(self):
        audio = np.repeat(tone(1.0, RATE, 1, 220.0, amplitude=0.5), 2, axis=0)
        out = blocks(effects.make_processor('frequency_shifter', {'shift_hz': 100.0, 'mix': 1.0}, RATE), audio)[0, RATE // 4:]
        spectrum = np.abs(np.fft.rfft(out * np.hanning(out.size)))
        freqs = np.fft.rfftfreq(out.size, 1.0 / RATE)
        self.assertAlmostEqual(freqs[spectrum.argmax()], 320.0, delta=3.0)

    def test_tempo_delay_time_follows_bpm(self):
        audio = np.zeros((2, RATE), np.float32)
        audio[:, :20] = 0.8
        processor = effects.make_processor('tempo_delay', {'bpm': 120.0, 'division': '1/4', 'feedback': 0.0, 'mix': 1.0}, RATE)
        out = blocks(processor, audio)
        self.assertAlmostEqual(processor.params['delay_ms'], 500.0)
        self.assertGreater(float(np.abs(out[:, 24000:24040]).max()), 0.3)
        self.assertLess(float(np.abs(out[:, 12000:12040]).max()), 0.01)

    def test_tape_delay_and_resonator_ring(self):
        audio = np.zeros((2, RATE), np.float32)
        audio[:, :30] = 0.8
        out = blocks(effects.make_processor('tape_delay', {'delay_ms': 200.0, 'feedback': 0.5, 'mix': 1.0, 'wow': 0.0, 'flutter': 0.0}, RATE), audio)
        self.assertGreater(float(np.abs(out[:, 9500:9800]).max()), 0.2)
        self.assertGreater(float(np.abs(out[:, 19100:19400]).max()), 0.05)
        ring = blocks(effects.make_processor('resonator', {'pitch_hz': 200.0, 'feedback': 0.95, 'mix': 1.0}, RATE), audio)
        self.assertGreater(rms_db(ring[:, 2000:6000]), rms_db(audio[:, 2000:6000]) + 20.0)

    def test_formant_filter_and_rotary_and_ensemble_run(self):
        noise = (np.random.default_rng(3).standard_normal((2, RATE // 2)) * 0.2).astype(np.float32)
        formant = effects.make_processor('formant_filter', {'vowel': 2.0}, RATE)      # 'i': formants 350 / 1700 / 2700 Hz
        out = blocks(formant, noise)
        self.assertEqual(out.shape, noise.shape)
        response = formant.response(np.array([100.0, 1700.0]))
        self.assertGreater(response[1], response[0] + 10.0)
        rotary = effects.make_processor('rotary_speaker', {'speed': 'fast'}, RATE)
        out = blocks(rotary, noise)
        self.assertGreater(float(np.abs(out[0] - out[1]).max()), 0.05)
        ensemble = blocks(effects.make_processor('ensemble', {'mix': 1.0}, RATE), noise)
        self.assertGreater(float(np.abs(ensemble[0] - ensemble[1]).max()), 0.01)


class MasteringTests(unittest.TestCase):
    def test_maximizer_holds_the_ceiling_and_reports(self):
        audio = tone(0.5, RATE, 2, 440.0, amplitude=0.9)
        processor = effects.make_processor('maximizer', {'gain_db': 12.0, 'ceiling_db': -1.0}, RATE)
        out = blocks(processor, audio)
        self.assertLessEqual(float(np.abs(out).max()), 10 ** (-1.0 / 20.0) + 1e-4)
        self.assertLess(processor.meters['gain_reduction_db'], -6.0)
        self.assertEqual(processor.latency_frames, int(3.0e-3 * RATE))
        quiet = blocks(effects.make_processor('maximizer', {'gain_db': 0.0, 'ceiling_db': -1.0}, RATE), audio * 0.1)
        self.assertTrue(np.allclose(quiet[:, 2000:], (audio * 0.1)[:, 2000 - 144:-144], atol=1e-4))

    def test_dynamic_eq_cuts_only_when_the_band_is_loud(self):
        params = {'b1_on': True, 'b1_freq': 1000.0, 'b1_q': 2.0, 'b1_threshold_db': -30.0, 'b1_ratio': 10.0, 'b1_range_db': 12.0,
                  'b1_attack_ms': 1.0, 'b1_release_ms': 30.0, 'b2_on': False, 'b3_on': False}
        loud = tone(0.5, RATE, 1, 1000.0, amplitude=0.8)
        processor = effects.make_processor('dynamic_eq', params, RATE)
        out = blocks(processor, loud)
        self.assertLess(rms_db(out[:, -8000:]), rms_db(loud[:, -8000:]) - 4.0)
        self.assertLess(processor.meters['band_reduction_db'][0], -4.0)
        soft = blocks(effects.make_processor('dynamic_eq', params, RATE), loud * 0.01)
        self.assertTrue(np.allclose(soft[:, -8000:], (loud * 0.01)[:, -8000:], atol=1e-4))

    def test_stereo_imager_and_mid_side(self):
        left = tone(0.3, RATE, 1, 60.0, amplitude=0.5)
        audio = np.concatenate([left, np.zeros_like(left)], axis=0)          # hard left bass
        mono_bass = blocks(effects.make_processor('stereo_imager', {'crossover_1_hz': 300.0, 'low_width': 0.0, 'mid_width': 1.0, 'high_width': 1.0}, RATE), audio)
        self.assertLess(float(np.abs(mono_bass[0, -4000:] - mono_bass[1, -4000:]).max()), 0.03)
        wide = blocks(effects.make_processor('stereo_imager', {'crossover_1_hz': 300.0, 'low_width': 1.0}, RATE), audio)
        self.assertGreater(float(np.abs(wide[0, -4000:] - wide[1, -4000:]).max()), 0.4)
        ms = blocks(effects.make_processor('mid_side', {'output': 'mid_side'}, RATE), audio)
        self.assertTrue(np.allclose(ms[0], ms[1], atol=1e-6))              # mid == side for a hard-left signal
        narrowed = blocks(effects.make_processor('mid_side', {'side_db': -24.0}, RATE), audio)   # side at its minimum gain
        self.assertLess(float(np.abs(narrowed[0] - narrowed[1]).max()), 0.5 * 10 ** (-24.0 / 20.0) * 1.05)

    def test_hum_remover_and_declicker(self):
        hum = tone(1.0, RATE, 1, 50.0, amplitude=0.3) + tone(1.0, RATE, 1, 150.0, amplitude=0.2)
        out = blocks(effects.make_processor('hum_remover', {'base_hz': 50.0, 'harmonics': 4, 'q': 30.0}, RATE), hum)
        self.assertLess(rms_db(out[:, -8000:]), rms_db(hum[:, -8000:]) - 25.0)
        clean = tone(0.5, RATE, 1, 200.0, amplitude=0.4)
        dirty = clean.copy()
        dirty[0, 5000] += 0.9
        dirty[0, 12000] -= 0.9
        processor = effects.make_processor('declicker', {'sensitivity': 12.0, 'width': 2}, RATE)
        repaired = blocks(processor, dirty)
        self.assertLess(float(np.abs(repaired - clean).max()), 0.1)
        self.assertGreaterEqual(processor.meters['total_clicks'], 2)

    def test_loudness_meter_of_a_known_sine(self):
        audio = np.repeat(tone(1.0, RATE, 1, 1000.0, amplitude=0.5), 2, axis=0)    # -6 dBFS both channels
        processor = effects.make_processor('loudness_meter', {}, RATE)
        out = blocks(processor, audio)
        self.assertTrue(np.array_equal(out, audio))
        meters = processor.meters
        self.assertAlmostEqual(meters['lufs_m'], -6.7, delta=1.0)
        self.assertAlmostEqual(meters['lufs_i'], -6.7, delta=1.0)
        self.assertAlmostEqual(meters['peak_db'], -6.0, delta=0.1)
        processor.reset_integration()
        self.assertEqual(processor.meters['lufs_i'], -100.0)

    def test_tone_generator_dither_channel_tool(self):
        silence = np.zeros((2, 4096), np.float32)
        out = blocks(effects.make_processor('tone_generator', {'shape': 'sine', 'frequency_hz': 1000.0, 'level_db': -6.0, 'mode': 'replace'}, RATE), silence)
        self.assertAlmostEqual(float(np.abs(out).max()), 0.5, places=2)
        pink = blocks(effects.make_processor('tone_generator', {'shape': 'pink', 'level_db': -20.0}, RATE), silence)
        self.assertGreater(float(np.abs(pink).max()), 0.0)
        dithered = blocks(effects.make_processor('dither', {'bits': 16, 'quantize': True}, RATE), silence + 0.3)
        self.assertLess(float(np.abs(dithered - 0.3).max()), 3.0 / 32768)
        stereo = np.stack([np.full(1000, 0.5, np.float32), np.full(1000, -0.25, np.float32)])
        swapped = blocks(effects.make_processor('channel_tool', {'swap': True, 'invert_left': True}, RATE), stereo)
        self.assertAlmostEqual(float(swapped[0, 10]), 0.25, places=5)
        self.assertAlmostEqual(float(swapped[1, 10]), 0.5, places=5)
        mono = blocks(effects.make_processor('channel_tool', {'mono': True}, RATE), stereo)
        self.assertAlmostEqual(float(mono[0, 10]), 0.125, places=5)


class WaveThreeTests(unittest.TestCase):
    def test_spectral_denoiser_reduces_noise_and_keeps_alignment(self):
        rng = np.random.default_rng(0)
        signal_tone = tone(1.0, RATE, 1, 220.0, amplitude=0.5)
        clean = np.repeat(np.concatenate([np.zeros((1, RATE), np.float32), signal_tone, np.zeros((1, RATE), np.float32)], axis=1), 2, axis=0)
        noisy = clean + (rng.standard_normal(clean.shape) * 0.02).astype(np.float32)
        processor = effects.make_processor('spectral_denoiser', {'reduction_db': 20.0}, RATE)
        out = blocks(processor, noisy, size=256)
        latency = processor.latency_frames
        self.assertEqual(latency, 2048 + 3 * 512)
        self.assertLess(rms_db(out[:, 8000 + latency:40000 + latency]), rms_db(noisy[:, 8000:40000]) - 10.0)
        self.assertGreater(rms_db(out[:, RATE + 8000 + latency:2 * RATE - 4000 + latency]), rms_db(noisy[:, RATE + 8000:2 * RATE - 4000]) - 1.5)
        unity = effects.make_processor('spectral_denoiser', {'reduction_db': 0.0}, RATE)
        out = blocks(unity, clean, size=777)
        self.assertLess(float(np.abs(out[:, RATE + 8000 + unity.latency_frames:2 * RATE] - clean[:, RATE + 8000:2 * RATE - unity.latency_frames]).max()), 1e-3)
        offline = effects.apply_effect('spectral_denoiser', clean, RATE, {'reduction_db': 0.0})
        self.assertEqual(offline.shape, clean.shape)
        self.assertLess(float(np.abs(offline[:, RATE + 8000:2 * RATE] - clean[:, RATE + 8000:2 * RATE]).max()), 1e-3)

    def test_trance_gate_and_stutter_follow_the_tempo(self):
        ones = np.ones((2, RATE), np.float32)
        gate = effects.make_processor('trance_gate', {'pattern': '1000100010001000', 'bpm': 120.0, 'division': '1/16', 'smooth_ms': 0.0}, RATE)
        out = blocks(gate, ones)
        self.assertAlmostEqual(float(out[0].mean()), 0.25, delta=0.02)
        ramp = np.linspace(0.0, 1.0, RATE, dtype=np.float32)[np.newaxis, :].repeat(2, axis=0)
        stutter = effects.make_processor('stutter', {'bpm': 120.0, 'period': '1/4', 'grain': '1/4', 'decay': 1.0, 'mix': 1.0}, RATE)
        out = blocks(stutter, ramp)
        period, grain = RATE // 2, RATE // 8
        self.assertTrue(np.allclose(out[0, :grain], ramp[0, :grain]))
        self.assertTrue(np.allclose(out[0, grain:2 * grain], ramp[0, :grain], atol=1e-6))       # first repeat
        self.assertTrue(np.allclose(out[0, period:period + grain], ramp[0, period:period + grain]))
        stutter.set_params({'active': False})
        self.assertTrue(np.array_equal(stutter.process(ramp[:, :1024]), ramp[:, :1024]))

    def test_reverse_and_dual_delays(self):
        audio = np.zeros((2, RATE), np.float32)
        audio[:, :100] = np.linspace(1.0, 0.0, 100, dtype=np.float32)
        length = int(0.1 * RATE)
        out = blocks(effects.make_processor('reverse_delay', {'length_ms': 100.0, 'feedback': 0.0, 'mix': 1.0}, RATE), audio)
        self.assertAlmostEqual(float(out[0, 2 * length - 1]), 1.0, places=3)      # the grain comes back reversed one grain later
        self.assertLess(float(np.abs(out[0, :length]).max()), 1e-6)
        dual = blocks(effects.make_processor('dual_delay', {'left_ms': 100.0, 'right_ms': 200.0, 'feedback': 0.0, 'cross': 0.0, 'mix': 1.0}, RATE), audio)
        self.assertGreater(float(np.abs(dual[0, 4800:4900]).max()), 0.5)
        self.assertLess(float(np.abs(dual[1, 4800:4900]).max()), 0.01)
        self.assertGreater(float(np.abs(dual[1, 9600:9700]).max()), 0.5)

    def test_guitar_amp_and_cabinet(self):
        audio = tone(0.3, RATE, 2, 110.0, amplitude=0.3)
        amp = effects.make_processor('guitar_amp', {'model': 'lead', 'gain': 8.0, 'cabinet': '4x12 closed'}, RATE)
        out = blocks(amp, audio)
        self.assertLessEqual(float(np.abs(out).max()), 1.5)
        spectrum = np.abs(np.fft.rfft(out[0, -8192:]))
        freqs = np.fft.rfftfreq(8192, 1.0 / RATE)
        fundamental = spectrum[np.argmin(np.abs(freqs - 110.0))]
        third = spectrum[np.argmin(np.abs(freqs - 330.0))]
        self.assertGreater(third, fundamental * 0.05)                   # harmonics were added
        curve = amp.curve(np.linspace(-1.0, 1.0, 21))
        self.assertTrue(np.all(np.isfinite(curve)))
        cab = effects.make_processor('cabinet', {'cabinet': '1x12 open'}, RATE)
        bright = tone(0.3, RATE, 2, 8000.0, amplitude=0.3)
        self.assertLess(rms_db(blocks(cab, bright)[:, -4000:]), rms_db(bright[:, -4000:]) - 12.0)

    def test_pitch_correction_snaps_to_the_scale(self):
        from audiostudio.dsp.pitch import detect_pitch
        audio = np.repeat(tone(1.0, RATE, 1, 230.0, amplitude=0.5), 2, axis=0)
        frequency, confidence = detect_pitch(audio[0, :2048], RATE)
        self.assertAlmostEqual(frequency, 230.0, delta=2.0)
        self.assertGreater(confidence, 0.5)
        processor = effects.make_processor('pitch_correction', {'key': 'C', 'scale': 'major', 'strength': 1.0, 'speed_ms': 5.0}, RATE)
        blocks(processor, audio)
        self.assertEqual(processor.meters['note'], 'A3')
        self.assertAlmostEqual(processor.meters['correction_st'], -0.77, delta=0.1)
        self.assertEqual(detect_pitch(np.zeros(2048), RATE), (0.0, 0.0))

    def test_harmonizer_adds_voices(self):
        audio = np.repeat(tone(0.5, RATE, 1, 220.0, amplitude=0.4), 2, axis=0)
        out = blocks(effects.make_processor('harmonizer', {'voice_1': '+12', 'voice_2': 'off', 'voices_db': 0.0, 'dry_db': -60.0, 'spread': 0.0}, RATE), audio)[0, RATE // 4:]
        spectrum = np.abs(np.fft.rfft(out * np.hanning(out.size)))
        freqs = np.fft.rfftfreq(out.size, 1.0 / RATE)
        self.assertAlmostEqual(freqs[spectrum.argmax()], 440.0, delta=30.0)

    def test_shimmer_and_gated_reverb(self):
        audio = np.zeros((2, RATE), np.float32)
        audio[:, :200] = 0.8
        shimmer = blocks(effects.make_processor('shimmer_reverb', {'decay_seconds': 2.0, 'shimmer': 0.6, 'mix': 1.0}, RATE), audio)
        self.assertGreater(float(np.abs(shimmer[:, RATE // 2:]).max()), 0.001)
        self.assertTrue(np.all(np.isfinite(shimmer)))
        gated = effects.make_processor('gated_reverb', {'decay_seconds': 3.0, 'threshold_db': -20.0, 'hold_ms': 50.0, 'mix': 1.0}, RATE)
        out = blocks(gated, audio)
        self.assertGreater(float(np.abs(out[:, 300:2400]).max()), 0.01)        # reverb (5 ms pre-delay) while the gate is open
        self.assertLess(float(np.abs(out[:, RATE // 2:]).max()), 0.02)          # the gate closed long before the tail ended

    def test_vintage_compressor_styles(self):
        audio = tone(1.0, RATE, 2, 440.0, amplitude=0.9)
        for style in ('opto', 'vca', 'fet', 'varimu'):
            processor = effects.make_processor('vintage_compressor', {'style': style, 'threshold_db': -30.0, 'ratio': 8.0}, RATE)
            out = blocks(processor, audio)
            self.assertLess(rms_db(out[:, RATE // 2:]), rms_db(audio[:, RATE // 2:]) - 6.0, style)
            self.assertLess(processor.meters['gain_reduction_db'], -6.0, style)
            curve = processor.curve(np.array([-60.0, -30.0, 0.0]))
            self.assertLess(curve[2], 0.0)


class PedalboardWrapperTests(unittest.TestCase):
    def test_live_parameter_update_keeps_state(self):
        processor = effects.make_processor('lowpass', {'cutoff_hz': 200.0}, RATE)
        audio = tone(0.3, RATE, 2, 5000.0, amplitude=0.5)
        dark = blocks(processor, audio)
        processor.set_params({'cutoff_hz': 15000.0})
        self.assertEqual(processor.plugin.cutoff_frequency_hz, 15000.0)
        bright = blocks(processor, audio)
        self.assertGreater(rms_db(bright[:, -4000:]), rms_db(dark[:, -4000:]) + 10.0)
        ladder = effects.make_processor('ladder_filter', {'mode': 'LPF24', 'cutoff_hz': 300.0}, RATE)
        ladder.set_params({'mode': 'HPF24'})
        self.assertEqual(str(ladder.plugin.mode).split('.')[-1], 'HPF24')

    def test_latency_plugins_stream_through_a_fifo(self):
        processor = effects.make_processor('mp3_codec', {}, RATE)
        audio = tone(1.0, RATE, 2, 440.0, amplitude=0.5)
        out = blocks(processor, audio)
        self.assertEqual(out.shape, audio.shape)
        self.assertGreater(processor.latency_frames, 0)
        self.assertTrue(np.allclose(out[:, :processor.latency_frames // 2], 0.0))
        offline = effects.apply_effect('mp3_codec', audio, RATE, {})
        self.assertEqual(offline.shape, audio.shape)
        self.assertGreater(float(np.abs(offline[:, -4000:]).max()), 0.3)

    def test_catalogue_flags(self):
        by_id = {e['id']: e for e in effects.catalogue()}
        self.assertTrue(by_id['compressor']['realtime'])
        self.assertTrue(by_id['compressor']['sidechain'])
        self.assertEqual(by_id['compressor']['ui'], 'dynamics')
        self.assertFalse(by_id['normalize']['realtime'])
        self.assertFalse(by_id['pitch_shift']['realtime'])
        self.assertIsNone(effects.make_processor('normalize', {}, RATE))
        self.assertGreaterEqual(sum(1 for e in by_id.values() if e['realtime']), 92)


if __name__ == '__main__':
    unittest.main()
