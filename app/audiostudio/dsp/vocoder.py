"""Channel vocoder: the input (modulator) shapes a carrier through a bank of band-pass filters.

Carrier: an internal oscillator (saw, pulse, noise) at a fixed pitch or a side-chain track
(a synth pad, another voice). Band levels are exposed for the interface.
"""
import math

import numpy as np

from .effects import EffectSpec, Param, register
from . import processors as P

CARRIERS = ('saw', 'pulse', 'noise', 'sidechain')
MAX_BANDS = 32


class Vocoder(P.Processor):
    def configure(self, p):
        bands = int(p['bands'])
        low, high = float(p['low_hz']), float(min(p['high_hz'], self.sr * 0.45))
        centres = np.exp(np.linspace(math.log(low), math.log(high), bands))
        shift = 2.0 ** (float(p['formant_shift']) / 12.0)
        q = float(p['q'])
        signature = (bands, low, high, shift, q)
        if getattr(self, 'signature', None) != signature:
            self.mod_bank = [P.BiquadChain(np.concatenate([P.biquad('bandpass', f, q, 0.0, self.sr)] * 2)) for f in centres]
            self.car_bank = [P.BiquadChain(np.concatenate([P.biquad('bandpass', min(f * shift, self.sr * 0.45), q, 0.0, self.sr)] * 2)) for f in centres]
            self.followers = [P.EnvelopeFollower(self.sr) for _ in centres]
            self.signature = signature
            self.centres = centres
        for follower in self.followers:
            follower.set(float(p['attack_ms']), float(p['release_ms']), 'peak')
        if not hasattr(self, 'phase'):
            self.phase = 0.0
            self.rng = np.random.default_rng(3)

    def reset(self):
        for chain in self.mod_bank + self.car_bank:
            chain.reset()
        for follower in self.followers:
            follower.reset()
        self.phase = 0.0

    def carrier(self, count, sidechain):
        p = self.params
        kind = p['carrier']
        if kind == 'sidechain':
            if sidechain is None:
                kind = 'saw'
            else:
                return np.mean(np.asarray(sidechain, dtype=np.float64), axis=0)
        if kind == 'noise':
            return self.rng.standard_normal(count) * 0.5
        pitch = float(p['pitch_hz'])
        phases = np.mod(self.phase + np.arange(count) * pitch / self.sr, 1.0)
        self.phase = float(np.mod(self.phase + count * pitch / self.sr, 1.0))
        if kind == 'pulse':
            return np.where(phases < 0.5, 0.6, -0.6)
        return (2.0 * phases - 1.0) * 0.6

    def process(self, block, sidechain=None):
        p = self.params
        modulator = np.mean(np.asarray(block, dtype=np.float64), axis=0, keepdims=True)
        carrier = self.carrier(block.shape[1], sidechain)
        if float(p['breath']) > 0.0:
            carrier = carrier + self.rng.standard_normal(block.shape[1]) * float(p['breath']) * 0.3
        carrier = carrier[np.newaxis, :]
        out = np.zeros((1, block.shape[1]))
        levels = []
        for mod_chain, car_chain, follower in zip(self.mod_bank, self.car_bank, self.followers):
            env = follower.run(np.abs(mod_chain.process(modulator)[0]))
            out[0] += car_chain.process(carrier)[0] * env
            levels.append(float(P.gain_to_db(env.max())) if env.size else -100.0)
        self.meters['band_level_db'] = levels
        wet = out * P.db_to_gain(p['output_db']) * 2.0
        wet = np.repeat(wet, block.shape[0], axis=0)
        return P.mix_dry_wet(np.asarray(block, dtype=np.float64), wet, p['mix']).astype(np.float32)


register(EffectSpec('vocoder', 'Vocoder', 'Vocal',
    [Param('carrier', 'Carrier', 'enum', 'saw', choices=CARRIERS, help='sidechain = another track (choose it in the insert)'),
     Param('pitch_hz', 'Carrier pitch', 'float', 110.0, 30.0, 1000.0, 'Hz'),
     Param('bands', 'Bands', 'int', 16, 4, MAX_BANDS, automatable=False),
     Param('low_hz', 'Lowest band', 'float', 80.0, 40.0, 500.0, 'Hz', automatable=False),
     Param('high_hz', 'Highest band', 'float', 8000.0, 1000.0, 16000.0, 'Hz', automatable=False),
     Param('q', 'Band Q', 'float', 6.0, 1.0, 20.0, automatable=False),
     Param('formant_shift', 'Formant shift', 'float', 0.0, -12.0, 12.0, 'st', automatable=False),
     Param('attack_ms', 'Envelope attack', 'float', 5.0, 0.5, 100.0, 'ms'),
     Param('release_ms', 'Envelope release', 'float', 40.0, 5.0, 500.0, 'ms'),
     Param('breath', 'Breath (noise)', 'float', 0.1, 0.0, 1.0, help='adds noise to the carrier for consonants'),
     Param('output_db', 'Output', 'float', 0.0, -24.0, 24.0, 'dB'),
     Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)],
    processor=Vocoder, ui='vocoder', sidechain=True, help='Classic channel vocoder; the input is the voice (modulator).'))
