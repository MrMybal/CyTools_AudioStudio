"""Guitar amplifier (tone stack, two gain stages, sag, presence) and speaker cabinets (synthesised
impulse responses through the JUCE convolution)."""
import numpy as np
from scipy import signal

from .effects import EffectSpec, Param, register, _pb
from . import processors as P

CABINETS = ('none', '1x12 open', '2x12 combo', '4x12 closed', 'bass 1x15')
MODELS = ('clean', 'crunch', 'lead', 'bass')


def cabinet_impulse(kind, samplerate, mic_distance=0.5, seed=4):
    """Short impulse response shaped like a guitar speaker: low cut, resonance, roll-off, box comb."""
    sr = int(samplerate)
    length = int(sr * 0.03)
    impulse = np.zeros(length)
    impulse[0] = 1.0
    profiles = {'1x12 open': (95.0, 2400.0, 4.0, 4800.0, 0.0013, 0.35), '2x12 combo': (85.0, 2000.0, 3.0, 4400.0, 0.0016, 0.4),
                '4x12 closed': (75.0, 1800.0, 5.0, 3900.0, 0.0021, 0.5), 'bass 1x15': (45.0, 900.0, 2.0, 2600.0, 0.0028, 0.45)}
    low, peak, peak_db, high, comb_s, comb_gain = profiles.get(kind, profiles['1x12 open'])
    high = high * (1.0 + 0.6 * (1.0 - float(mic_distance)))          # close mic = brighter
    sos = np.concatenate([P.biquad('highpass', low, 0.8, 0.0, sr), P.biquad('peak', peak, 1.2, peak_db, sr),
                          signal.butter(4, min(high, sr * 0.45), 'lowpass', fs=sr, output='sos')])
    shaped = signal.sosfilt(sos, impulse)
    comb = int(comb_s * sr)
    if 0 < comb < length:
        shaped[comb:] += shaped[:-comb] * comb_gain * (0.3 + 0.7 * float(mic_distance))
    rng = np.random.default_rng(seed)
    decay = np.exp(-np.arange(length) / (0.004 * sr))
    shaped += rng.standard_normal(length) * decay * 0.02
    shaped /= max(1e-9, float(np.max(np.abs(shaped))))
    return np.stack([shaped, shaped]).astype(np.float32) * 0.8


class Cabinet(P.Processor):
    def configure(self, p):
        signature = (p['cabinet'], round(float(p['mic_distance']), 3))
        if getattr(self, 'signature', None) != signature:
            self.signature = signature
            self.plugin = None
            if p['cabinet'] != 'none':
                self.impulse = cabinet_impulse(p['cabinet'], self.sr, p['mic_distance'])
                self.plugin = _pb().Convolution(self.impulse, mix=1.0, sample_rate=float(self.sr))
        self.level = P.db_to_gain(p['level_db'])

    def reset(self):
        if self.plugin is not None:
            try:
                self.plugin.reset()
            except Exception:
                pass

    def process(self, block, sidechain=None):
        if self.plugin is None:
            return (block * self.level).astype(np.float32)
        stereo = P.as_stereo(np.ascontiguousarray(block, dtype=np.float32))
        out = np.asarray(self.plugin(stereo, float(self.sr), reset=False), dtype=np.float32) * self.level
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class GuitarAmp(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'input_hp'):
            self.input_hp = P.BiquadChain(P.biquad('highpass', 70.0, 0.707, 0.0, self.sr))
            self.tone = P.BiquadChain()
            self.stage_lp = P.OnePole(self.sr, 6500.0)
            self.dc = P.BiquadChain(P.biquad('highpass', 15.0, 0.707, 0.0, self.sr))
            self.presence = P.BiquadChain()
            self.sag = P.EnvelopeFollower(self.sr, 30.0, 250.0, 'rms')
            self.cabinet = Cabinet({'cabinet': p['cabinet'], 'mic_distance': 0.5, 'level_db': 0.0}, self.sr)
        model = p['model']
        self.tone.set_sos(np.concatenate([P.biquad('low_shelf', 120.0 if model != 'bass' else 80.0, 0.7, (float(p['bass']) - 5.0) * 2.4, self.sr),
                                          P.biquad('peak', 750.0 if model != 'bass' else 500.0, 0.9, (float(p['mid']) - 5.0) * 2.4, self.sr),
                                          P.biquad('high_shelf', 3200.0 if model != 'bass' else 2500.0, 0.7, (float(p['treble']) - 5.0) * 2.4, self.sr)]))
        self.presence.set_sos(P.biquad('high_shelf', 4500.0, 0.7, (float(p['presence']) - 5.0) * 1.6, self.sr))
        gain = float(p['gain'])
        stages = {'clean': (1.0 + gain * 0.4, 1.0, 0.05), 'crunch': (1.0 + gain * 1.5, 1.5 + gain * 0.3, 0.12),
                  'lead': (2.0 + gain * 4.0, 2.0 + gain * 0.8, 0.18), 'bass': (1.0 + gain * 0.8, 1.2, 0.05)}[model]
        self.drive1, self.drive2, self.bias = stages
        self.stage_lp.set(9000.0 if model == 'clean' else (6500.0 if model != 'bass' else 4500.0))
        self.level = P.db_to_gain(p['level_db'])
        self.cabinet.set_params({'cabinet': p['cabinet'], 'mic_distance': 0.5, 'level_db': 0.0})

    def reset(self):
        for chain in (self.input_hp, self.tone, self.dc, self.presence):
            chain.reset()
        self.stage_lp.reset()
        self.sag.reset()
        self.cabinet.reset()

    def curve(self, x):
        x = np.asarray(x, dtype=np.float64)
        stage1 = np.tanh(x * self.drive1 + self.bias) - np.tanh(self.bias)
        return np.tanh(stage1 * self.drive2) / np.tanh(max(self.drive2, 1e-3))

    def process(self, block, sidechain=None):
        p = self.params
        x = np.asarray(block, dtype=np.float64)
        x = self.tone.process(self.input_hp.process(x))
        stage1 = np.tanh(x * self.drive1 + self.bias) - np.tanh(self.bias)
        stage1 = self.stage_lp.process(stage1)
        # power-amp sag: the louder the sustained signal, the more the gain drops
        env = self.sag.run(P.linked_detector(stage1))
        sag = 1.0 / (1.0 + float(p['sag']) * env * 2.0)
        stage2 = np.tanh(stage1 * self.drive2 * sag[np.newaxis, :]) / np.tanh(max(self.drive2, 1e-3))
        out = self.presence.process(self.dc.process(stage2))
        out = self.cabinet.process(out.astype(np.float32)).astype(np.float64) * self.level
        self.meters['gain_reduction_db'] = float(P.gain_to_db(sag.min()))
        return out.astype(np.float32)


register(EffectSpec('guitar_amp', 'Guitar / bass amp', 'Distortion',
    [Param('model', 'Model', 'enum', 'crunch', choices=MODELS),
     Param('gain', 'Gain', 'float', 5.0, 0.0, 10.0),
     Param('bass', 'Bass', 'float', 5.0, 0.0, 10.0),
     Param('mid', 'Mid', 'float', 5.0, 0.0, 10.0),
     Param('treble', 'Treble', 'float', 5.0, 0.0, 10.0),
     Param('presence', 'Presence', 'float', 5.0, 0.0, 10.0),
     Param('sag', 'Sag', 'float', 0.3, 0.0, 1.0, help='power-amp compression on loud passages'),
     Param('cabinet', 'Cabinet', 'enum', '2x12 combo', choices=CABINETS, automatable=False),
     Param('level_db', 'Level', 'float', -6.0, -36.0, 12.0, 'dB')],
    processor=GuitarAmp, ui='distortion', help='Two tube-style stages with a tone stack, sag and a speaker cabinet.'))

register(EffectSpec('cabinet', 'Speaker cabinet', 'Distortion',
    [Param('cabinet', 'Cabinet', 'enum', '4x12 closed', choices=CABINETS, automatable=False),
     Param('mic_distance', 'Mic distance', 'float', 0.5, 0.0, 1.0, help='0 = close (bright), 1 = far (rounder)', automatable=False),
     Param('level_db', 'Level', 'float', 0.0, -36.0, 12.0, 'dB')],
    processor=Cabinet, ui='generic', help='Synthesised speaker impulse responses; use Convolution reverb for your own cabinet IR files.'))
