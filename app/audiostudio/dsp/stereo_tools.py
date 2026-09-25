"""Stereo and utility processors: width, pan, balance, bass mono, mute, analyser (pass-through
with real-time views) and real-time versions of the older whole-buffer utilities.
"""
import math

import numpy as np

from .effects import EffectSpec, Param, register, REGISTRY
from . import processors as P


class StereoWidth(P.Processor):
    def process(self, block, sidechain=None):
        if block.shape[0] != 2:
            return block
        width = float(self.params['width'])
        mid = 0.5 * (block[0] + block[1])
        side = 0.5 * (block[0] - block[1]) * width
        return np.stack([mid + side, mid - side]).astype(np.float32)


class Pan(P.Processor):
    def process(self, block, sidechain=None):
        if block.shape[0] != 2:
            return block
        angle = (float(self.params['pan']) + 1.0) * 0.25 * math.pi
        out = np.array(block, dtype=np.float32)
        out[0] *= math.cos(angle) * math.sqrt(2.0)
        out[1] *= math.sin(angle) * math.sqrt(2.0)
        return out


class Balance(P.Processor):
    def process(self, block, sidechain=None):
        if block.shape[0] != 2:
            return block
        balance = float(self.params['balance'])
        out = np.array(block, dtype=np.float32)
        out[0] *= min(1.0, 1.0 - balance)
        out[1] *= min(1.0, 1.0 + balance)
        return out


class BassMono(P.Processor):
    """Sums the band below the crossover to mono (vinyl-safe, tighter low end)."""

    def configure(self, p):
        if not hasattr(self, 'crossover'):
            self.crossover = P.Crossover(self.sr, p['frequency_hz'])
        elif abs(self.crossover.frequency - float(p['frequency_hz'])) > 1e-6:
            self.crossover.set(p['frequency_hz'])

    def reset(self):
        self.crossover.reset()

    def process(self, block, sidechain=None):
        if block.shape[0] != 2:
            return block
        low, high = self.crossover.split(block)
        mono = np.mean(low, axis=0, keepdims=True)
        return (np.repeat(mono, 2, axis=0) + high).astype(np.float32)


class Mute(P.Processor):
    def process(self, block, sidechain=None):
        return np.zeros_like(block)


class Analyzer(P.Processor):
    """Pass-through; the interface reads the taps kept by the renderer (scope, spectrum, goniometer)."""

    def process(self, block, sidechain=None):
        return block


register(EffectSpec('balance', 'Balance', 'Stereo',
    [Param('balance', 'Balance', 'float', 0.0, -1.0, 1.0, help='-1 left only, +1 right only')], processor=Balance, ui='stereo'))
register(EffectSpec('bass_mono', 'Bass to mono', 'Stereo',
    [Param('frequency_hz', 'Below', 'float', 120.0, 40.0, 500.0, 'Hz')], processor=BassMono, ui='stereo'))
register(EffectSpec('mute', 'Mute', 'Utility', [], processor=Mute, ui='generic'))
register(EffectSpec('analyzer', 'Analyser (scope, spectrum, goniometer)', 'Analysis', [], processor=Analyzer, ui='analyzer',
                    help='Does not change the sound: shows the waveform, spectrum, stereo field and levels at this point of the chain.'))

# Real-time versions of the older whole-buffer utilities (same ids, same parameters).
REGISTRY['stereo_width'].processor = StereoWidth
REGISTRY['stereo_width'].apply = None
REGISTRY['stereo_width'].ui = 'stereo'
REGISTRY['pan'].processor = Pan
REGISTRY['pan'].apply = None
REGISTRY['pan'].ui = 'stereo'
REGISTRY['invert'].ui = 'generic'
