"""Modulation effects: tremolo, auto-pan, ring modulator, vibrato, flanger (JUCE chorus core),
plus the interface family of the existing chorus and phaser.
"""
import numpy as np

from .effects import EffectSpec, Param, register, REGISTRY, _pb
from . import processors as P

SHAPES = ('sine', 'triangle', 'square', 'saw')


class Tremolo(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'lfo'):
            self.lfo = P.LFO(self.sr)
        self.lfo.set(p['rate_hz'], p['shape'])

    def reset(self):
        self.lfo.reset()

    def process(self, block, sidechain=None):
        p = self.params
        depth = float(p['depth'])
        phases = self.lfo.phases(block.shape[1])
        wave = P.lfo(p['shape'], phases)
        gain_l = 1.0 - depth * 0.5 * (1.0 - wave)
        if block.shape[0] >= 2 and p['stereo_phase'] > 0:
            wave_r = P.lfo(p['shape'], phases + p['stereo_phase'] / 360.0)
            gain_r = 1.0 - depth * 0.5 * (1.0 - wave_r)
            gains = np.stack([gain_l, gain_r] + [gain_l] * (block.shape[0] - 2))
        else:
            gains = np.repeat(gain_l[np.newaxis, :], block.shape[0], axis=0)
        self.meters['lfo'] = float(wave[-1])
        return (block * gains.astype(np.float32)).astype(np.float32)


class AutoPan(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'lfo'):
            self.lfo = P.LFO(self.sr)
        self.lfo.set(p['rate_hz'], p['shape'])

    def reset(self):
        self.lfo.reset()

    def process(self, block, sidechain=None):
        if block.shape[0] < 2:
            return block
        p = self.params
        position = self.lfo.block(block.shape[1]) * float(p['depth'])      # -1 left .. +1 right
        angle = (position + 1.0) * 0.25 * np.pi
        left, right = np.cos(angle) * np.sqrt(2.0), np.sin(angle) * np.sqrt(2.0)
        out = np.array(block, dtype=np.float32)
        out[0] *= left.astype(np.float32)
        out[1] *= right.astype(np.float32)
        self.meters['lfo'] = float(position[-1])
        return out


class RingModulator(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'lfo'):
            self.lfo = P.LFO(self.sr)
        self.lfo.set(p['frequency_hz'], p['shape'])

    def reset(self):
        self.lfo.reset()

    def process(self, block, sidechain=None):
        p = self.params
        carrier = self.lfo.block(block.shape[1]).astype(np.float32)
        wet = block * carrier[np.newaxis, :]
        return P.mix_dry_wet(block, wet, p['mix']).astype(np.float32)


# ----------------------------------------------------------------------------- registrations

register(EffectSpec('tremolo', 'Tremolo', 'Modulation',
    [Param('rate_hz', 'Rate', 'float', 5.0, 0.05, 30.0, 'Hz'),
     Param('depth', 'Depth', 'float', 0.6, 0.0, 1.0),
     Param('shape', 'Shape', 'enum', 'sine', choices=SHAPES),
     Param('stereo_phase', 'Stereo phase', 'float', 0.0, 0.0, 180.0, '°', help='180 = left and right alternate')],
    processor=Tremolo, ui='modulation'))

register(EffectSpec('auto_pan', 'Auto-pan', 'Modulation',
    [Param('rate_hz', 'Rate', 'float', 0.5, 0.05, 20.0, 'Hz'),
     Param('depth', 'Depth', 'float', 1.0, 0.0, 1.0),
     Param('shape', 'Shape', 'enum', 'sine', choices=SHAPES)],
    processor=AutoPan, ui='modulation'))

register(EffectSpec('ring_mod', 'Ring modulator', 'Modulation',
    [Param('frequency_hz', 'Carrier', 'float', 440.0, 1.0, 5000.0, 'Hz'),
     Param('shape', 'Carrier shape', 'enum', 'sine', choices=SHAPES),
     Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)],
    processor=RingModulator, ui='modulation'))


def _chorus_like(centre_ms, feedback, mix):
    return lambda p: _pb().Chorus(rate_hz=p['rate_hz'], depth=p['depth'], centre_delay_ms=p.get('centre_delay_ms', centre_ms),
                                  feedback=p.get('feedback', feedback), mix=p.get('mix', mix))


register(EffectSpec('flanger', 'Flanger', 'Modulation',
    [Param('rate_hz', 'Rate', 'float', 0.3, 0.01, 10.0, 'Hz'),
     Param('depth', 'Depth', 'float', 0.7, 0.0, 1.0),
     Param('centre_delay_ms', 'Delay', 'float', 2.0, 1.0, 12.0, 'ms'),
     Param('feedback', 'Feedback', 'float', 0.5, -0.95, 0.95),
     Param('mix', 'Mix', 'float', 0.5, 0.0, 1.0)],
    build=_chorus_like(2.0, 0.5, 0.5), ui='modulation', help='Short modulated delay with feedback (jet sweep).'))

register(EffectSpec('vibrato', 'Vibrato', 'Modulation',
    [Param('rate_hz', 'Rate', 'float', 5.0, 0.1, 15.0, 'Hz'),
     Param('depth', 'Depth', 'float', 0.3, 0.0, 1.0)],
    build=lambda p: _pb().Chorus(rate_hz=p['rate_hz'], depth=p['depth'], centre_delay_ms=6.0, feedback=0.0, mix=1.0),
    ui='modulation', help='Pitch wobble (fully wet modulated delay).'))

for _id in ('chorus', 'phaser'):
    REGISTRY[_id].ui = 'modulation'
