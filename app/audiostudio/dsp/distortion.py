"""Saturation and lo-fi: tape, tube, overdrive, fuzz, wave shaper, exciter, sample reducer,
telephone, vinyl. Each shaper exposes ``curve(x)`` (its transfer function) for the interface.
"""
import numpy as np

from .effects import EffectSpec, Param, register, REGISTRY
from . import processors as P


def _tanh_norm(x, drive):
    drive = max(1e-3, drive)
    return np.tanh(x * drive) / np.tanh(drive)


def shape_tape(x, drive):
    return _tanh_norm(x, drive)


def shape_tube(x, drive):
    # Asymmetric: positive half clips softer than the negative one (even harmonics).
    return np.where(x >= 0, _tanh_norm(x, drive * 0.7), _tanh_norm(x, drive * 1.3))


def shape_overdrive(x, drive):
    y = x * drive
    return np.clip(y - (y ** 3) / 3.0, -2.0 / 3.0, 2.0 / 3.0) * 1.5


def shape_fuzz(x, drive):
    return np.clip(x * drive * 4.0, -1.0, 1.0)


def shape_fold(x, drive):
    y = x * drive
    return np.abs(np.mod(y + 1.0, 4.0) - 2.0) - 1.0


SHAPES = {'tape': shape_tape, 'tube': shape_tube, 'overdrive': shape_overdrive, 'fuzz': shape_fuzz, 'fold': shape_fold}


class WaveShaper(P.Processor):
    """Drive -> shaper -> tone -> output, with a DC blocker after asymmetric curves."""

    shape = 'tape'

    def configure(self, p):
        if not hasattr(self, 'tone'):
            self.tone = P.OnePole(self.sr, p['tone_hz'])
            self.dc = P.BiquadChain(P.biquad('highpass', 12.0, 0.707, 0.0, self.sr))
        self.tone.set(p['tone_hz'])
        self.drive = P.db_to_gain(p['drive_db'])
        self.output = P.db_to_gain(p['output_db'])
        self.kind = p.get('shape', self.shape)

    def reset(self):
        self.tone.reset()
        self.dc.reset()

    def curve(self, x):
        """Transfer function for input values in [-1, 1] (drive included)."""
        return SHAPES[self.kind](np.asarray(x, dtype=np.float64), self.drive)

    def process(self, block, sidechain=None):
        p = self.params
        x = np.asarray(block, dtype=np.float64)
        shaped = self.curve(x)
        if self.kind == 'tube':
            # Removing the DC offset of the asymmetric curve shifts the wave: scale so peaks stay near 1.
            shaped = self.dc.process(shaped) * 0.85
        shaped = self.tone.process(shaped) * self.output
        return P.mix_dry_wet(x, shaped, p['mix']).astype(np.float32)


class Exciter(P.Processor):
    """Adds saturated harmonics of the high band (presence, air)."""

    def configure(self, p):
        if not hasattr(self, 'split'):
            self.split = P.BiquadChain()
        self.split.set_sos(P.biquad('highpass', p['frequency_hz'], 0.707, 0.0, self.sr))
        self.drive = P.db_to_gain(p['drive_db'])
        self.amount = P.db_to_gain(p['amount_db'])

    def reset(self):
        self.split.reset()

    def process(self, block, sidechain=None):
        x = np.asarray(block, dtype=np.float64)
        high = self.split.process(x)
        harmonics = _tanh_norm(high, self.drive) * 0.5
        return (x + harmonics * self.amount).astype(np.float32)


class SampleReducer(P.Processor):
    """Sample-and-hold decimation with an optional bit depth (aliasing lo-fi)."""

    def configure(self, p):
        self.factor = max(1, int(round(float(p['factor']))))
        self.levels = 2.0 ** float(p['bit_depth'])
        self.hold = None
        self.count = 0

    def reset(self):
        self.hold = None
        self.count = 0

    def process(self, block, sidechain=None):
        x = np.asarray(block, dtype=np.float64)
        n = x.shape[1]
        if self.factor > 1:
            # Keep every ``factor``-th sample, continuing the phase across blocks.
            index = np.arange(n) + self.count
            hold_index = (index // self.factor) * self.factor - self.count
            picked = np.where(hold_index >= 0, hold_index, 0)
            out = x[:, np.clip(picked, 0, n - 1)]
            if self.hold is not None:
                out[:, hold_index < 0] = self.hold[:, np.newaxis]
            self.hold = out[:, -1].copy()
            self.count = int((self.count + n) % self.factor)
        else:
            out = x
        if self.levels < 2.0 ** 24:
            out = np.round(out * self.levels) / self.levels
        return P.mix_dry_wet(x, out, self.params['mix']).astype(np.float32)


class Telephone(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'chain'):
            self.chain = P.BiquadChain()
        self.chain.set_sos(np.concatenate([P.biquad('highpass', p['low_hz'], 0.9, 0.0, self.sr), P.biquad('highpass', p['low_hz'], 0.9, 0.0, self.sr),
                                           P.biquad('lowpass', p['high_hz'], 0.9, 0.0, self.sr), P.biquad('lowpass', p['high_hz'], 0.9, 0.0, self.sr)]))
        self.drive = P.db_to_gain(p['drive_db'])

    def reset(self):
        self.chain.reset()

    def response(self, frequencies):
        return P.response_db(self.chain.sos, frequencies, self.sr)

    def process(self, block, sidechain=None):
        x = self.chain.process(block)
        return (_tanh_norm(x * self.drive, 1.5) / self.drive * P.db_to_gain(6.0) * 0.5).astype(np.float32)


class Vinyl(P.Processor):
    """Surface noise, crackle and a dull top end."""

    def configure(self, p):
        if not hasattr(self, 'tone'):
            self.tone = P.OnePole(self.sr, p['tone_hz'])
            self.rng = np.random.default_rng(11)
        self.tone.set(p['tone_hz'])
        self.noise = P.db_to_gain(p['noise_db'])
        self.crackle = float(p['crackle']) * 40.0 / self.sr      # impulses per frame

    def reset(self):
        self.tone.reset()

    def process(self, block, sidechain=None):
        x = np.asarray(block, dtype=np.float64)
        out = self.tone.process(x)
        hiss = self.rng.standard_normal(x.shape) * self.noise * 0.3
        clicks = (self.rng.random(x.shape[1]) < self.crackle) * (self.rng.random(x.shape[1]) * 0.6 + 0.2)
        return (out + hiss + clicks[np.newaxis, :] * self.noise * 12.0).astype(np.float32)


# ----------------------------------------------------------------------------- registrations

def _shaper(effect_id, name, shape, drive=12.0, tone=8000.0, help_text=''):
    cls = type(name.replace(' ', ''), (WaveShaper,), {'shape': shape})
    register(EffectSpec(effect_id, name, 'Distortion',
        [Param('drive_db', 'Drive', 'float', drive, 0.0, 48.0, 'dB'),
         Param('tone_hz', 'Tone', 'float', tone, 500.0, 20000.0, 'Hz'),
         Param('output_db', 'Output', 'float', -6.0, -36.0, 12.0, 'dB'),
         Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)],
        processor=cls, ui='distortion', help=help_text))


_shaper('tape_saturation', 'Tape saturation', 'tape', 6.0, 12000.0, 'Smooth symmetric saturation (odd harmonics).')
_shaper('tube_drive', 'Tube drive', 'tube', 10.0, 9000.0, 'Asymmetric saturation (even harmonics).')
_shaper('overdrive', 'Overdrive', 'overdrive', 12.0, 6000.0, 'Soft cubic clipping.')
_shaper('fuzz', 'Fuzz', 'fuzz', 18.0, 4000.0, 'Hard clipping with a lot of gain.')
_shaper('wavefolder', 'Wave folder', 'fold', 6.0, 12000.0, 'Folds the wave back on itself (west-coast timbres).')

register(EffectSpec('exciter', 'Exciter', 'Distortion',
    [Param('frequency_hz', 'From', 'float', 3000.0, 1000.0, 12000.0, 'Hz'),
     Param('drive_db', 'Drive', 'float', 12.0, 0.0, 36.0, 'dB'),
     Param('amount_db', 'Amount', 'float', -12.0, -40.0, 6.0, 'dB')],
    processor=Exciter, ui='distortion'))

register(EffectSpec('sample_reducer', 'Sample rate reducer', 'Lo-fi',
    [Param('factor', 'Decimation', 'int', 4, 1, 64, 'x', help='keeps one sample out of N'),
     Param('bit_depth', 'Bit depth', 'float', 12.0, 2.0, 24.0, 'bits'),
     Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)],
    processor=SampleReducer, ui='distortion'))

register(EffectSpec('telephone', 'Telephone', 'Lo-fi',
    [Param('low_hz', 'Low cut', 'float', 300.0, 100.0, 1000.0, 'Hz'),
     Param('high_hz', 'High cut', 'float', 3400.0, 1000.0, 8000.0, 'Hz'),
     Param('drive_db', 'Drive', 'float', 6.0, 0.0, 24.0, 'dB')],
    processor=Telephone, ui='filter'))

register(EffectSpec('vinyl', 'Vinyl', 'Lo-fi',
    [Param('noise_db', 'Noise', 'float', -40.0, -80.0, -10.0, 'dB'),
     Param('crackle', 'Crackle', 'float', 0.3, 0.0, 1.0),
     Param('tone_hz', 'Tone', 'float', 9000.0, 1000.0, 20000.0, 'Hz')],
    processor=Vinyl, ui='generic'))

for _id in ('distortion', 'clipping', 'bitcrush'):
    REGISTRY[_id].ui = 'distortion'
