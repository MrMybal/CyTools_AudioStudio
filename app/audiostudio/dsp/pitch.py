"""Pitch tools: automatic pitch correction (scale-aware) and a two-voice harmoniser, both built on the
real-time granular shifter."""
import math

import numpy as np

from .effects import EffectSpec, Param, register
from . import processors as P
from .creative import PitchShifter

NOTE_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
SCALES = {'chromatic': tuple(range(12)), 'major': (0, 2, 4, 5, 7, 9, 11), 'minor': (0, 2, 3, 5, 7, 8, 10),
          'harmonic minor': (0, 2, 3, 5, 7, 8, 11), 'pentatonic major': (0, 2, 4, 7, 9), 'pentatonic minor': (0, 3, 5, 7, 10), 'blues': (0, 3, 5, 6, 7, 10)}
INTERVALS = ('off', '-12', '-7', '-5', '-4', '-3', '+3', '+4', '+5', '+7', '+12')


def detect_pitch(mono, samplerate, low_hz=60.0, high_hz=1000.0):
    """(frequency, confidence) by normalised autocorrelation; 0 Hz when unvoiced."""
    x = np.asarray(mono, dtype=np.float64)
    x = x - x.mean()
    n = x.size
    energy = float(np.dot(x, x))
    if n < 256 or energy < 1e-6:
        return 0.0, 0.0
    spectrum = np.fft.rfft(x, 2 * n)
    corr = np.fft.irfft(spectrum * np.conj(spectrum))[:n]
    lag_min, lag_max = int(samplerate / high_hz), min(n - 2, int(samplerate / low_hz))
    if lag_max <= lag_min:
        return 0.0, 0.0
    window = corr[lag_min:lag_max]
    best = int(np.argmax(window)) + lag_min
    confidence = float(corr[best] / (corr[0] + 1e-12))
    if confidence < 0.4:
        return 0.0, confidence
    # parabolic interpolation around the peak
    if 1 <= best < n - 1:
        a, b, c = corr[best - 1], corr[best], corr[best + 1]
        denominator = a - 2 * b + c
        shift = 0.5 * (a - c) / denominator if abs(denominator) > 1e-12 else 0.0
    else:
        shift = 0.0
    return float(samplerate / (best + shift)), confidence


class PitchCorrection(P.Processor):
    WINDOW = 2048

    def configure(self, p):
        if not hasattr(self, 'shifter'):
            self.shifter = PitchShifter({'semitones': 0.0, 'cents': 0.0, 'window_ms': 50.0, 'mix': 1.0}, self.sr)
            self.history = np.zeros(self.WINDOW)
            self.correction = 0.0
        self.key = NOTE_NAMES.index(p['key']) if p['key'] in NOTE_NAMES else 0
        self.scale = SCALES.get(p['scale'], SCALES['chromatic'])
        self.strength = float(p['strength'])
        self.speed = P.time_coef(float(p['speed_ms']), self.sr)

    def reset(self):
        self.shifter.reset()
        self.history[:] = 0.0
        self.correction = 0.0

    def _target(self, midi):
        """Nearest scale note (in MIDI) to a fractional MIDI value."""
        best, distance = midi, 99.0
        base = int(math.floor(midi)) - 12
        for candidate in range(base, base + 25):
            if (candidate - self.key) % 12 in self.scale and abs(candidate - midi) < distance:
                best, distance = candidate, abs(candidate - midi)
        return best

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        mono = stereo.mean(axis=0)
        self.history = np.concatenate([self.history, mono])[-self.WINDOW:]
        frequency, confidence = detect_pitch(self.history, self.sr)
        if frequency > 0.0:
            midi = 69.0 + 12.0 * math.log2(frequency / 440.0)
            target = self._target(midi)
            wanted = (target - midi) * self.strength
            self.meters['note'] = NOTE_NAMES[int(target) % 12] + str(int(target) // 12 - 1)
        else:
            wanted = 0.0
            self.meters['note'] = '-'
        # glide towards the wanted correction (per block, using the per-sample coefficient)
        coef = self.speed ** count
        self.correction = wanted + (self.correction - wanted) * coef
        self.meters.update({'pitch_hz': frequency, 'confidence': confidence, 'correction_st': self.correction})
        self.shifter.set_params({'semitones': float(self.correction)})
        wet = self.shifter.process(stereo.astype(np.float32)).astype(np.float64)
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class Harmonizer(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'voices'):
            self.voices = [PitchShifter({'semitones': 0.0, 'cents': 0.0, 'window_ms': 60.0, 'mix': 1.0}, self.sr) for _ in range(2)]
        self.intervals = []
        for key in ('voice_1', 'voice_2'):
            value = p[key]
            self.intervals.append(None if value == 'off' else float(value))
        for voice, interval in zip(self.voices, self.intervals):
            if interval is not None:
                voice.set_params({'semitones': interval, 'cents': float(p['detune_cents'])})

    def reset(self):
        for voice in self.voices:
            voice.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        out = stereo * P.db_to_gain(p['dry_db'])
        level = P.db_to_gain(p['voices_db'])
        spread = float(p['spread'])
        for index, (voice, interval) in enumerate(zip(self.voices, self.intervals)):
            if interval is None:
                continue
            shifted = voice.process(stereo.astype(np.float32)).astype(np.float64).mean(axis=0)
            pan = spread * (-1.0 if index == 0 else 1.0)
            angle = (pan + 1.0) * 0.25 * math.pi
            out[0] += shifted * level * math.cos(angle) * math.sqrt(2.0) * 0.7
            out[1] += shifted * level * math.sin(angle) * math.sqrt(2.0) * 0.7
        return P.match_channels(out, block.shape[0]).astype(np.float32)


register(EffectSpec('pitch_correction', 'Pitch correction (auto-tune)', 'Vocal',
    [Param('key', 'Key', 'enum', 'C', choices=NOTE_NAMES),
     Param('scale', 'Scale', 'enum', 'chromatic', choices=tuple(SCALES)),
     Param('strength', 'Strength', 'float', 1.0, 0.0, 1.0, help='1 = snap fully to the note'),
     Param('speed_ms', 'Speed', 'float', 20.0, 1.0, 400.0, 'ms', help='fast = robotic, slow = natural'),
     Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)],
    processor=PitchCorrection, ui='pitch', help='Detects the pitch (60-1000 Hz, monophonic) and shifts it to the nearest note of the scale.'))

register(EffectSpec('harmonizer', 'Harmoniser', 'Vocal',
    [Param('voice_1', 'Voice 1', 'enum', '+4', choices=INTERVALS),
     Param('voice_2', 'Voice 2', 'enum', '+7', choices=INTERVALS),
     Param('detune_cents', 'Detune', 'float', 5.0, -50.0, 50.0, 'cents'),
     Param('voices_db', 'Voices level', 'float', -6.0, -40.0, 6.0, 'dB'),
     Param('spread', 'Stereo spread', 'float', 0.7, 0.0, 1.0),
     Param('dry_db', 'Dry', 'float', 0.0, -40.0, 6.0, 'dB')],
    processor=Harmonizer, ui='generic', help='Two fixed-interval harmony voices (semitones) panned left and right.'))
