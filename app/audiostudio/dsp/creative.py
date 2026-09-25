"""Creative effects built on modulated delay reads: real-time pitch shifter and octaver, frequency
shifter (Hilbert), rotary speaker, ensemble chorus, doubler, tape delay, tempo-synced delay,
formant (vowel) filter, resonator, cassette.
"""
import math

import numpy as np
from scipy import signal

from .effects import EffectSpec, Param, register
from . import processors as P
from .space import PingPongDelay


class PitchShifter(P.Processor):
    """Two crossfaded grains read from a sawtooth-modulated delay (classic real-time shifter)."""

    def configure(self, p):
        self.window = max(64, int(float(p['window_ms']) * 1e-3 * self.sr))
        self.ratio = 2.0 ** ((float(p['semitones']) + float(p['cents']) / 100.0) / 12.0)
        if not hasattr(self, 'tap'):
            self.tap = P.ModulatedTap(2, int(self.sr * 0.5) + 8192)
            self.phase = 0.0

    def reset(self):
        self.tap.reset()
        self.phase = 0.0

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        if abs(self.ratio - 1.0) < 1e-6:
            wet = stereo
            self.tap.read(stereo, np.zeros(count))
        else:
            increment = (self.ratio - 1.0) / self.window
            phase1 = np.mod(self.phase + np.arange(count) * increment, 1.0)
            self.phase = float(np.mod(self.phase + count * increment, 1.0))
            phase2 = np.mod(phase1 + 0.5, 1.0)
            d1 = self.window * (1.0 - phase1)
            d2 = self.window * (1.0 - phase2)
            g1 = np.sin(np.pi * phase1) ** 2
            g2 = np.sin(np.pi * phase2) ** 2
            self.tap.line.push(stereo)
            wet = self._read(d1, count) * g1 + self._read(d2, count) * g2
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)

    def _read(self, delays, count):
        line = self.tap.line
        position = line.write - count + np.arange(count) - delays
        base = np.floor(position)
        frac = (position - base)[np.newaxis, :]
        i0 = base.astype(np.int64) % line.max_frames
        i1 = (i0 + 1) % line.max_frames
        return line.buffer[:, i0] * (1.0 - frac) + line.buffer[:, i1] * frac


class Octaver(P.Processor):
    """Sub-octave from a pitch-shifted copy (-12 st) plus an analogue-style rectified sub."""

    def configure(self, p):
        if not hasattr(self, 'shifter'):
            self.shifter = PitchShifter({'semitones': -12.0, 'cents': 0.0, 'window_ms': 60.0, 'mix': 1.0}, self.sr)
            self.low = P.BiquadChain()
            self.dc = P.BiquadChain(P.biquad('highpass', 20.0, 0.707, 0.0, self.sr))
        self.low.set_sos(np.concatenate([P.biquad('lowpass', p['tone_hz'], 0.707, 0.0, self.sr)] * 2))
        self.sub_gain = P.db_to_gain(p['sub_db'])
        self.analog_gain = P.db_to_gain(p['analog_db'])
        self.dry_gain = P.db_to_gain(p['dry_db'])

    def reset(self):
        self.shifter.reset()
        self.low.reset()
        self.dc.reset()

    def process(self, block, sidechain=None):
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        shifted = self.shifter.process(stereo.astype(np.float32)).astype(np.float64)
        rectified = self.dc.process(np.abs(stereo) * 2.0 - np.mean(np.abs(stereo)))
        sub = self.low.process(shifted * self.sub_gain + rectified * self.analog_gain)
        out = stereo * self.dry_gain + sub
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class FrequencyShifter(P.Processor):
    """Single-sideband modulation: every partial moves by the same number of hertz (inharmonic)."""

    TAPS = 127

    def configure(self, p):
        if not hasattr(self, 'hilbert'):
            n = np.arange(self.TAPS) - (self.TAPS - 1) / 2
            with np.errstate(divide='ignore', invalid='ignore'):
                h = np.where(n == 0, 0.0, (1.0 - np.cos(np.pi * n)) / (np.pi * n))
            self.hilbert = h * np.hamming(self.TAPS)
            self.zi = None
            self.delay = P.DelayLine(2, self.TAPS + 8192 + 4096)
            self.phase = 0.0
        self.shift = float(p['shift_hz'])

    def reset(self):
        self.zi = None
        self.delay.reset()
        self.phase = 0.0

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        if self.zi is None:
            self.zi = np.zeros((2, self.TAPS - 1))
        quadrature, self.zi = signal.lfilter(self.hilbert, [1.0], stereo, axis=-1, zi=self.zi)
        # the real path is delayed by the group delay of the FIR
        self.delay.push(stereo)
        in_phase = self.delay.read((self.TAPS - 1) // 2 + count, count)
        phases = self.phase + np.arange(count) * self.shift / self.sr
        self.phase = float(np.mod(self.phase + count * self.shift / self.sr, 1.0))
        carrier_c, carrier_s = np.cos(2 * np.pi * phases), np.sin(2 * np.pi * phases)
        wet = in_phase * carrier_c - quadrature * carrier_s
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class RotarySpeaker(P.Processor):
    """Leslie-style cabinet: a horn and a drum with amplitude and Doppler modulation, stereo."""

    def configure(self, p):
        if not hasattr(self, 'crossover'):
            self.crossover = P.Crossover(self.sr, 800.0)
            self.horn_tap = P.ModulatedTap(2, 4096 + 8192)
            self.drum_tap = P.ModulatedTap(2, 4096 + 8192)
            self.horn_phase = 0.0
            self.drum_phase = 0.0
            self.horn_rate = 0.8
            self.drum_rate = 0.7
        fast = p['speed'] == 'fast'
        self.target_horn = (6.8 if fast else 0.8) * float(p['rate_scale'])
        self.target_drum = (5.7 if fast else 0.7) * float(p['rate_scale'])
        self.accel = float(p['acceleration_s'])

    def reset(self):
        self.crossover.reset()
        self.horn_tap.reset()
        self.drum_tap.reset()

    def _rotor(self, tap, block, rate_attr, target, phase_attr, depth_ms, am_depth, spread):
        count = block.shape[1]
        rate = getattr(self, rate_attr)
        coef = math.exp(-count / (max(self.accel, 0.05) * self.sr))
        rate = target + (rate - target) * coef
        setattr(self, rate_attr, rate)
        phase = getattr(self, phase_attr) + np.arange(count) * rate / self.sr
        setattr(self, phase_attr, float(np.mod(getattr(self, phase_attr) + count * rate / self.sr, 1.0)))
        angle = 2 * np.pi * phase
        depth = depth_ms * 1e-3 * self.sr
        delays = depth * (1.0 + np.sin(angle)) + 1.0
        moved = tap.read(block, delays)
        am = 1.0 - am_depth * 0.5 * (1.0 - np.cos(angle))
        left = moved[0] * am * (1.0 - spread * 0.5 * (1.0 - np.cos(angle)))
        right = moved[1] * am * (1.0 - spread * 0.5 * (1.0 + np.cos(angle)))
        return np.stack([left, right])

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        low, high = self.crossover.split(stereo)
        horn = self._rotor(self.horn_tap, high, 'horn_rate', self.target_horn, 'horn_phase', 0.6 * float(p['depth']), 0.7 * float(p['depth']), float(p['stereo']))
        drum = self._rotor(self.drum_tap, low, 'drum_rate', self.target_drum, 'drum_phase', 0.25 * float(p['depth']), 0.4 * float(p['depth']), float(p['stereo']) * 0.5)
        wet = horn + drum
        self.meters['lfo'] = float(math.sin(2 * math.pi * self.horn_phase))
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class EnsembleChorus(P.Processor):
    """Three modulated voices spread across the stereo field (string-machine ensemble)."""

    def configure(self, p):
        if not hasattr(self, 'taps'):
            self.taps = [P.ModulatedTap(2, 8192 + 8192) for _ in range(3)]
            self.lfos = [P.LFO(self.sr) for _ in range(3)]
        for index, lfo in enumerate(self.lfos):
            lfo.set(float(p['rate_hz']) * (1.0, 1.13, 0.87)[index], 'sine')

    def reset(self):
        for tap in self.taps:
            tap.reset()
        for lfo in self.lfos:
            lfo.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        base = float(p['delay_ms']) * 1e-3 * self.sr
        depth = float(p['depth']) * 0.4 * base
        wet = np.zeros_like(stereo)
        pans = ((0.9, 0.1), (0.5, 0.5), (0.1, 0.9))
        for index, (tap, lfo) in enumerate(zip(self.taps, self.lfos)):
            delays = base + depth * lfo.block(count, phase_offset=index / 3.0)
            voice = tap.read(stereo, delays)
            mono = voice.mean(axis=0)
            wet[0] += mono * pans[index][0]
            wet[1] += mono * pans[index][1]
        wet *= 0.8
        self.meters['lfo'] = float(math.sin(2 * math.pi * self.lfos[0].phase))
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class Doubler(P.Processor):
    """Artificial double tracking: a slightly detuned, delayed copy on one side."""

    def configure(self, p):
        if not hasattr(self, 'tap'):
            self.tap = P.ModulatedTap(2, 8192 + 8192)
            self.lfo = P.LFO(self.sr)
        self.lfo.set(float(p['wobble_hz']), 'sine')

    def reset(self):
        self.tap.reset()
        self.lfo.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        base = float(p['delay_ms']) * 1e-3 * self.sr
        delays = base + float(p['wobble_ms']) * 1e-3 * self.sr * self.lfo.block(count)
        copy = self.tap.read(stereo, delays).mean(axis=0) * P.db_to_gain(p['level_db'])
        pan = float(p['pan'])
        angle = (pan + 1.0) * 0.25 * math.pi
        out = stereo.copy()
        out[0] += copy * math.cos(angle) * math.sqrt(2.0)
        out[1] += copy * math.sin(angle) * math.sqrt(2.0)
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class TapeDelay(P.Processor):
    """Feedback delay with wow/flutter on the tape speed, a dull, saturating feedback path."""

    def configure(self, p):
        self.base = max(int(0.005 * self.sr), int(round(float(p['delay_ms']) * 1e-3 * self.sr)))
        if not hasattr(self, 'line'):
            self.line = P.DelayLine(2, int(self.sr * 5.2) + 8192)
            self.tone = P.OnePole(self.sr, p['tone_hz'])
            self.wow = P.LFO(self.sr, 0.5)
            self.flutter = P.LFO(self.sr, 6.3)
        self.tone.set(p['tone_hz'])
        self.wow.set(0.4 + 0.3 * float(p['wow']), 'sine')
        self.flutter.set(5.0 + 3.0 * float(p['flutter']), 'triangle')
        self.drive = P.db_to_gain(p['saturation_db'])

    def reset(self):
        self.line.reset()
        self.tone.reset()
        self.wow.reset()
        self.flutter.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        modulation = (self.wow.block(count) * float(p['wow']) * 0.004 + self.flutter.block(count) * float(p['flutter']) * 0.0006) * self.sr
        delays = np.maximum(self.base * 0.9, self.base + modulation)
        step = max(8, int(self.base * 0.85))
        wet = np.empty_like(stereo)
        feedback = float(p['feedback'])
        for start in range(0, count, step):
            stop = min(count, start + step)
            n = stop - start
            delayed = self.line.read_at(delays[start:stop], n)
            wet[:, start:stop] = delayed
            fed = self.tone.process(delayed)
            fed = np.tanh(fed * self.drive) / max(self.drive, 1e-3) * feedback
            self.line.push(stereo[:, start:stop] + fed)
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


NOTE_DIVISIONS = {'1/1': 4.0, '1/2': 2.0, '1/4': 1.0, '1/8': 0.5, '1/16': 0.25, '1/4.': 1.5, '1/8.': 0.75, '1/4T': 2.0 / 3.0, '1/8T': 1.0 / 3.0}


class TempoDelay(PingPongDelay):
    """Ping-pong delay whose time follows a tempo and a note value."""

    def configure(self, p):
        beat_ms = 60000.0 / max(20.0, float(p['bpm']))
        delay_ms = min(5000.0, beat_ms * NOTE_DIVISIONS.get(p['division'], 1.0))
        self.params['delay_ms'] = delay_ms
        super().configure({**p, 'delay_ms': delay_ms})


VOWELS = {'a': (800, 1150, 2900), 'e': (400, 1600, 2700), 'i': (350, 1700, 2700), 'o': (450, 800, 2830), 'u': (325, 700, 2530)}
VOWEL_ORDER = ('a', 'e', 'i', 'o', 'u')


class FormantFilter(P.Processor):
    """Three parallel resonances morphing between the vowels a, e, i, o, u."""

    def configure(self, p):
        if not hasattr(self, 'chains'):
            self.chains = [P.BiquadChain() for _ in range(3)]
        morph = float(np.clip(p['vowel'], 0.0, len(VOWEL_ORDER) - 1))
        low, high = int(math.floor(morph)), min(len(VOWEL_ORDER) - 1, int(math.ceil(morph)))
        t = morph - low
        shift = 2.0 ** (float(p['shift_semitones']) / 12.0)
        self.formants = []
        for index, chain in enumerate(self.chains):
            f_low, f_high = VOWELS[VOWEL_ORDER[low]][index], VOWELS[VOWEL_ORDER[high]][index]
            frequency = math.exp(math.log(f_low) * (1 - t) + math.log(f_high) * t) * shift
            frequency = min(frequency, self.sr * 0.45)
            self.formants.append(frequency)
            chain.set_sos(P.biquad('bandpass', frequency, float(p['resonance']), 0.0, self.sr))
        self.gains = (1.0, 0.7, 0.4)

    def reset(self):
        for chain in self.chains:
            chain.reset()

    def response(self, frequencies):
        total = np.zeros(len(frequencies), dtype=np.complex128)
        w = 2 * np.pi * np.asarray(frequencies, dtype=np.float64) / self.sr
        for chain, gain in zip(self.chains, self.gains):
            _, h = signal.sosfreqz(chain.sos, worN=w)
            total += h * gain
        return P.gain_to_db(np.abs(total) * float(self.params['resonance']) ** 0.5)

    def process(self, block, sidechain=None):
        p = self.params
        x = np.asarray(block, dtype=np.float64)
        wet = sum(chain.process(x) * gain for chain, gain in zip(self.chains, self.gains)) * float(p['resonance']) ** 0.5
        out = P.mix_dry_wet(x, wet, p['mix'])
        return out.astype(np.float32)


class Resonator(P.Processor):
    """Tuned feedback comb (Karplus-like ring): pitch, decay, damping."""

    def configure(self, p):
        self.delay = max(4, int(round(self.sr / max(20.0, float(p['pitch_hz'])))))
        if not hasattr(self, 'line'):
            self.line = P.DelayLine(2, 8192 + 4096)
            self.damp = P.OnePole(self.sr, p['damping_hz'])
        self.damp.set(p['damping_hz'])
        self.feedback = float(p['feedback']) * (-1.0 if p['polarity'] == 'negative' else 1.0)

    def reset(self):
        self.line.reset()
        self.damp.reset()

    def process(self, block, sidechain=None):
        p = self.params
        x = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = x.shape[1]
        wet = np.empty_like(x)
        step = self.delay
        for start in range(0, count, step):
            stop = min(count, start + step)
            delayed = self.line.read(self.delay, stop - start)
            fed = self.damp.process(delayed) * self.feedback
            value = x[:, start:stop] + fed
            wet[:, start:stop] = value
            self.line.push(value)
        out = P.mix_dry_wet(x, wet * 0.5, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class Cassette(P.Processor):
    """Wow and flutter, dull top end, tape saturation and hiss."""

    def configure(self, p):
        if not hasattr(self, 'tap'):
            self.tap = P.ModulatedTap(2, 8192 + 8192)
            self.wow = P.LFO(self.sr, 0.55)
            self.flutter = P.LFO(self.sr, 7.0, 'triangle')
            self.tone = P.OnePole(self.sr, p['tone_hz'])
            self.rng = np.random.default_rng(5)
        self.tone.set(p['tone_hz'])
        self.drive = P.db_to_gain(p['saturation_db'])
        self.hiss = P.db_to_gain(p['hiss_db'])

    def reset(self):
        self.tap.reset()
        self.wow.reset()
        self.flutter.reset()
        self.tone.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        base = 0.006 * self.sr
        delays = base + (self.wow.block(count) * 0.003 * float(p['wow']) + self.flutter.block(count) * 0.0004 * float(p['flutter'])) * self.sr
        moved = self.tap.read(stereo, delays)
        shaped = np.tanh(moved * self.drive) / max(self.drive, 1e-3)
        dull = self.tone.process(shaped)
        out = dull + self.rng.standard_normal(dull.shape) * self.hiss * 0.3
        return P.match_channels(out, block.shape[0]).astype(np.float32)


# ----------------------------------------------------------------------------- registrations

register(EffectSpec('pitch_shifter', 'Pitch shifter (real-time)', 'Pitch & time',
    [Param('semitones', 'Semitones', 'float', 0.0, -24.0, 24.0, 'st'),
     Param('cents', 'Fine', 'float', 0.0, -100.0, 100.0, 'cents'),
     Param('window_ms', 'Grain', 'float', 60.0, 10.0, 120.0, 'ms', help='shorter = tighter timing, longer = purer pitch on sustained notes'),
     Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0, help='below 1 = harmoniser (dry + shifted)')],
    processor=PitchShifter, ui='modulation', help='Granular shifter usable as an insert (two crossfaded grains). For the best quality on a selection use Pitch shift.'))

register(EffectSpec('octaver', 'Octaver / sub-bass', 'Pitch & time',
    [Param('sub_db', 'Sub octave', 'float', -6.0, -60.0, 6.0, 'dB', help='pitch-shifted copy one octave down'),
     Param('analog_db', 'Analogue sub', 'float', -18.0, -60.0, 6.0, 'dB', help='rectified sub harmonics (old-school octaver)'),
     Param('tone_hz', 'Sub tone', 'float', 250.0, 60.0, 2000.0, 'Hz'),
     Param('dry_db', 'Dry', 'float', 0.0, -60.0, 6.0, 'dB')],
    processor=Octaver, ui='generic'))

register(EffectSpec('frequency_shifter', 'Frequency shifter', 'Modulation',
    [Param('shift_hz', 'Shift', 'float', 5.0, -2000.0, 2000.0, 'Hz'),
     Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)],
    processor=FrequencyShifter, ui='modulation', help='Bode-style single-sideband shift: small values = barber-pole phasing, large = metallic inharmonic tones.'))

register(EffectSpec('rotary_speaker', 'Rotary speaker', 'Modulation',
    [Param('speed', 'Speed', 'enum', 'slow', choices=('slow', 'fast')),
     Param('rate_scale', 'Rate scale', 'float', 1.0, 0.5, 2.0, 'x'),
     Param('acceleration_s', 'Acceleration', 'float', 1.5, 0.1, 6.0, 's'),
     Param('depth', 'Depth', 'float', 0.8, 0.0, 1.0),
     Param('stereo', 'Stereo spread', 'float', 0.8, 0.0, 1.0),
     Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)],
    processor=RotarySpeaker, ui='modulation', help='Horn above 800 Hz and drum below, each with Doppler and amplitude modulation; automate Speed for the classic ramp.'))

register(EffectSpec('ensemble', 'Ensemble chorus', 'Modulation',
    [Param('rate_hz', 'Rate', 'float', 0.6, 0.05, 5.0, 'Hz'),
     Param('depth', 'Depth', 'float', 0.5, 0.0, 1.0),
     Param('delay_ms', 'Delay', 'float', 18.0, 5.0, 40.0, 'ms'),
     Param('mix', 'Mix', 'float', 0.6, 0.0, 1.0)],
    processor=EnsembleChorus, ui='modulation', help='Three voices spread left / centre / right.'))

register(EffectSpec('doubler', 'Doubler (ADT)', 'Modulation',
    [Param('delay_ms', 'Delay', 'float', 28.0, 8.0, 80.0, 'ms'),
     Param('wobble_ms', 'Wobble', 'float', 1.0, 0.0, 5.0, 'ms'),
     Param('wobble_hz', 'Wobble rate', 'float', 0.3, 0.05, 3.0, 'Hz'),
     Param('level_db', 'Copy level', 'float', -3.0, -30.0, 6.0, 'dB'),
     Param('pan', 'Copy pan', 'float', 0.7, -1.0, 1.0)],
    processor=Doubler, ui='modulation', help='Artificial double tracking: a delayed, wobbling copy panned to one side.'))

register(EffectSpec('tape_delay', 'Tape delay', 'Space',
    [Param('delay_ms', 'Delay', 'float', 320.0, 20.0, 2000.0, 'ms'),
     Param('feedback', 'Feedback', 'float', 0.45, 0.0, 1.1, help='above 1 self-oscillates (saturation keeps it bounded)'),
     Param('tone_hz', 'Tone', 'float', 3500.0, 300.0, 12000.0, 'Hz'),
     Param('saturation_db', 'Saturation', 'float', 6.0, 0.0, 24.0, 'dB'),
     Param('wow', 'Wow', 'float', 0.3, 0.0, 1.0),
     Param('flutter', 'Flutter', 'float', 0.2, 0.0, 1.0),
     Param('mix', 'Mix', 'float', 0.4, 0.0, 1.0)],
    processor=TapeDelay, ui='delay', help='Echoes get darker and softer with every repeat; the tape speed wobbles.'))

register(EffectSpec('tempo_delay', 'Tempo delay', 'Space',
    [Param('bpm', 'Tempo', 'float', 120.0, 20.0, 300.0, 'BPM'),
     Param('division', 'Note', 'enum', '1/8', choices=tuple(NOTE_DIVISIONS)),
     Param('feedback', 'Feedback', 'float', 0.45, 0.0, 0.98),
     Param('ping_pong', 'Ping-pong', 'float', 0.0, 0.0, 1.0),
     Param('tone_hz', 'Feedback tone', 'float', 6000.0, 200.0, 20000.0, 'Hz'),
     Param('mix', 'Mix', 'float', 0.4, 0.0, 1.0)],
    processor=TempoDelay, ui='delay', help='Delay time = tempo x note value (dotted and triplet notes included).'))

register(EffectSpec('formant_filter', 'Formant filter (vowels)', 'Vocal',
    [Param('vowel', 'Vowel', 'float', 0.0, 0.0, 4.0, help='0 a, 1 e, 2 i, 3 o, 4 u (morphs in between)'),
     Param('shift_semitones', 'Formant shift', 'float', 0.0, -12.0, 12.0, 'st'),
     Param('resonance', 'Resonance', 'float', 8.0, 2.0, 30.0),
     Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)],
    processor=FormantFilter, ui='filter', help='Talk-box vowels; automate Vowel for a talking effect.'))

register(EffectSpec('resonator', 'Resonator (comb)', 'Modulation',
    [Param('pitch_hz', 'Pitch', 'float', 220.0, 30.0, 4000.0, 'Hz'),
     Param('feedback', 'Feedback', 'float', 0.85, 0.0, 0.99),
     Param('damping_hz', 'Damping', 'float', 6000.0, 300.0, 20000.0, 'Hz'),
     Param('polarity', 'Polarity', 'enum', 'positive', choices=('positive', 'negative')),
     Param('mix', 'Mix', 'float', 0.5, 0.0, 1.0)],
    processor=Resonator, ui='modulation', help='Tuned feedback comb: the input rings at the chosen pitch.'))

register(EffectSpec('cassette', 'Cassette', 'Lo-fi',
    [Param('wow', 'Wow', 'float', 0.4, 0.0, 1.0),
     Param('flutter', 'Flutter', 'float', 0.3, 0.0, 1.0),
     Param('saturation_db', 'Saturation', 'float', 6.0, 0.0, 24.0, 'dB'),
     Param('tone_hz', 'Tone', 'float', 7000.0, 1000.0, 16000.0, 'Hz'),
     Param('hiss_db', 'Hiss', 'float', -50.0, -90.0, -20.0, 'dB')],
    processor=Cassette, ui='generic'))
