"""Equalisers and filters: parametric EQ, graphic EQ, tilt, band-pass, notch, DC blocker, auto-wah,
LFO filter. Every processor exposes ``response(frequencies)`` in dB for the interfaces.
"""
import numpy as np
from scipy import signal

from .effects import EffectSpec, Param, register, REGISTRY, _pb
from . import processors as P

BAND_TYPES = ('peak', 'low_shelf', 'high_shelf', 'lowpass', 'highpass', 'notch', 'bandpass')
EQ_BANDS = 8
GRAPHIC_FREQS = (31.25, 62.5, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0)


def _design_bands(bands, sr):
    sections = []
    for kind, freq, gain, q in bands:
        sections.append(P.biquad(kind, freq, q, gain, sr))
    return np.concatenate(sections) if sections else None


class ParametricEQ(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'chain'):
            self.chain = P.BiquadChain()
        bands = []
        for n in range(1, EQ_BANDS + 1):
            if not p.get(f'b{n}_on', False):
                continue
            bands.append((p[f'b{n}_type'], p[f'b{n}_freq'], p[f'b{n}_gain'], p[f'b{n}_q']))
        self.chain.set_sos(_design_bands(bands, self.sr))
        self.output = P.db_to_gain(p.get('output_db', 0.0))

    def reset(self):
        self.chain.reset()

    def response(self, frequencies):
        return P.response_db(self.chain.sos, frequencies, self.sr) + float(self.params.get('output_db', 0.0))

    def band_response(self, n, frequencies):
        p = self.params
        if not p.get(f'b{n}_on', False):
            return np.zeros(len(frequencies))
        return P.response_db(P.biquad(p[f'b{n}_type'], p[f'b{n}_freq'], p[f'b{n}_q'], p[f'b{n}_gain'], self.sr), frequencies, self.sr)

    def process(self, block, sidechain=None):
        return (self.chain.process(block) * self.output).astype(np.float32)


class GraphicEQ(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'chain'):
            self.chain = P.BiquadChain()
        bands = [('peak', f, p[f'g{index}'], 1.41) for index, f in enumerate(GRAPHIC_FREQS) if abs(p[f'g{index}']) > 0.01]
        self.chain.set_sos(_design_bands(bands, self.sr))
        self.output = P.db_to_gain(p.get('output_db', 0.0))

    def reset(self):
        self.chain.reset()

    def response(self, frequencies):
        return P.response_db(self.chain.sos, frequencies, self.sr) + float(self.params.get('output_db', 0.0))

    def process(self, block, sidechain=None):
        return (self.chain.process(block) * self.output).astype(np.float32)


class SimpleFilter(P.Processor):
    """One RBJ section (band-pass, notch, tilt made of two shelves, DC blocker)."""

    kind = 'bandpass'

    def design(self, p):
        return P.biquad(self.kind, p['frequency_hz'], p['q'], 0.0, self.sr)

    def configure(self, p):
        if not hasattr(self, 'chain'):
            self.chain = P.BiquadChain()
        self.chain.set_sos(self.design(p))

    def reset(self):
        self.chain.reset()

    def response(self, frequencies):
        return P.response_db(self.chain.sos, frequencies, self.sr)

    def process(self, block, sidechain=None):
        return self.chain.process(block).astype(np.float32)


class BandPass(SimpleFilter):
    kind = 'bandpass'


class Notch(SimpleFilter):
    kind = 'notch'


class TiltEQ(SimpleFilter):
    def design(self, p):
        tilt = float(p['tilt_db'])
        return np.concatenate([P.biquad('low_shelf', p['centre_hz'], 0.5, -tilt, self.sr), P.biquad('high_shelf', p['centre_hz'], 0.5, tilt, self.sr)])


class DCBlocker(SimpleFilter):
    def design(self, p):
        return P.biquad('highpass', p['cutoff_hz'], 0.707, 0.0, self.sr)


class ModulatedFilter(P.Processor):
    """Resonant filter whose cutoff moves every 64 frames (envelope or LFO driven)."""

    STEP = 64

    def configure(self, p):
        if not hasattr(self, 'chain'):
            self.chain = P.BiquadChain()
            self.follower = P.EnvelopeFollower(self.sr)
            self.lfo = P.LFO(self.sr)
        self.follower.set(p.get('attack_ms', 10.0), p.get('release_ms', 120.0), 'peak')
        self.lfo.set(p.get('rate_hz', 1.0), p.get('shape', 'sine'))
        self.last_cutoff = float(p['min_hz'])

    def reset(self):
        self.chain.reset()
        self.follower.reset()
        self.lfo.reset()

    def cutoffs(self, block):
        raise NotImplementedError

    def response(self, frequencies):
        p = self.params
        return P.response_db(P.biquad(p['mode'], self.last_cutoff, p['resonance'], 0.0, self.sr), frequencies, self.sr)

    def process(self, block, sidechain=None):
        p = self.params
        cutoffs = self.cutoffs(block)
        out = np.empty(block.shape, np.float64)
        for start in range(0, block.shape[1], self.STEP):
            stop = min(block.shape[1], start + self.STEP)
            cutoff = float(np.clip(cutoffs[start], 20.0, self.sr * 0.45))
            self.chain.set_sos(P.biquad(p['mode'], cutoff, p['resonance'], 0.0, self.sr))
            out[:, start:stop] = self.chain.process(block[:, start:stop])
            self.last_cutoff = cutoff
        self.meters['cutoff_hz'] = self.last_cutoff
        return P.mix_dry_wet(np.asarray(block, np.float64), out, p.get('mix', 1.0)).astype(np.float32)


class AutoWah(ModulatedFilter):
    def cutoffs(self, block):
        p = self.params
        env = self.follower.run(P.linked_detector(np.asarray(block, np.float64)))
        drive = np.clip(env * P.db_to_gain(p['sensitivity_db']), 0.0, 1.0)
        lo, hi = np.log(float(p['min_hz'])), np.log(float(p['max_hz']))
        return np.exp(lo + (hi - lo) * drive)


class LFOFilter(ModulatedFilter):
    def cutoffs(self, block):
        p = self.params
        wave = (self.lfo.block(block.shape[1]) + 1.0) * 0.5
        lo, hi = np.log(float(p['min_hz'])), np.log(float(p['max_hz']))
        return np.exp(lo + (hi - lo) * wave)


# ----------------------------------------------------------------------------- registrations

_eq = [Param('output_db', 'Output', 'float', 0.0, -24.0, 24.0, 'dB')]
_defaults = [(True, 'low_shelf', 100.0, 0.0, 0.707), (True, 'peak', 400.0, 0.0, 1.0), (True, 'peak', 1000.0, 0.0, 1.0),
             (True, 'peak', 3000.0, 0.0, 1.0), (True, 'high_shelf', 8000.0, 0.0, 0.707), (False, 'peak', 6000.0, 0.0, 1.0),
             (False, 'highpass', 40.0, 0.0, 0.707), (False, 'lowpass', 16000.0, 0.0, 0.707)]
for _n, (_on, _type, _freq, _gain, _q) in enumerate(_defaults, start=1):
    _eq += [Param(f'b{_n}_on', f'Band {_n}', 'bool', _on),
            Param(f'b{_n}_type', f'Band {_n} type', 'enum', _type, choices=BAND_TYPES),
            Param(f'b{_n}_freq', f'Band {_n} frequency', 'float', _freq, 10.0, 20000.0, 'Hz'),
            Param(f'b{_n}_gain', f'Band {_n} gain', 'float', _gain, -24.0, 24.0, 'dB'),
            Param(f'b{_n}_q', f'Band {_n} Q', 'float', _q, 0.1, 18.0)]
register(EffectSpec('parametric_eq', 'Parametric EQ', 'EQ', _eq, processor=ParametricEQ, ui='eq',
                    help='Eight bands (peak, shelves, cuts, notch). Drag the points on the curve.'))

register(EffectSpec('graphic_eq', 'Graphic EQ (10 bands)', 'EQ',
    [Param(f'g{i}', f'{int(f) if f >= 100 else f} Hz', 'float', 0.0, -12.0, 12.0, 'dB') for i, f in enumerate(GRAPHIC_FREQS)] +
    [Param('output_db', 'Output', 'float', 0.0, -24.0, 24.0, 'dB')],
    processor=GraphicEQ, ui='graphic_eq'))

register(EffectSpec('tilt_eq', 'Tilt EQ', 'EQ',
    [Param('tilt_db', 'Tilt', 'float', 0.0, -12.0, 12.0, 'dB', help='negative = darker, positive = brighter'),
     Param('centre_hz', 'Pivot', 'float', 650.0, 100.0, 5000.0, 'Hz')],
    processor=TiltEQ, ui='filter'))

register(EffectSpec('bandpass', 'Band-pass filter', 'EQ',
    [Param('frequency_hz', 'Frequency', 'float', 1000.0, 20.0, 20000.0, 'Hz'),
     Param('q', 'Q', 'float', 1.0, 0.1, 18.0)],
    processor=BandPass, ui='filter'))

register(EffectSpec('notch', 'Notch filter', 'EQ',
    [Param('frequency_hz', 'Frequency', 'float', 50.0, 20.0, 20000.0, 'Hz'),
     Param('q', 'Q', 'float', 8.0, 0.1, 40.0, help='high Q = narrow notch (hum removal)')],
    processor=Notch, ui='filter'))

register(EffectSpec('dc_blocker', 'DC blocker', 'Utility',
    [Param('cutoff_hz', 'Cutoff', 'float', 10.0, 2.0, 40.0, 'Hz')],
    processor=DCBlocker, ui='filter', help='Real-time high-pass below the audible range.'))

_mod_filter = [Param('mode', 'Mode', 'enum', 'bandpass', choices=('lowpass', 'bandpass', 'highpass')),
               Param('min_hz', 'Minimum', 'float', 250.0, 20.0, 5000.0, 'Hz'),
               Param('max_hz', 'Maximum', 'float', 2500.0, 100.0, 16000.0, 'Hz'),
               Param('resonance', 'Resonance (Q)', 'float', 4.0, 0.3, 20.0),
               Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)]
register(EffectSpec('auto_wah', 'Auto-wah', 'Modulation',
    _mod_filter + [Param('sensitivity_db', 'Sensitivity', 'float', 12.0, -24.0, 48.0, 'dB'),
                   Param('attack_ms', 'Attack', 'float', 10.0, 1.0, 200.0, 'ms'),
                   Param('release_ms', 'Release', 'float', 120.0, 10.0, 2000.0, 'ms')],
    processor=AutoWah, ui='filter', help='Envelope-controlled resonant filter.'))

register(EffectSpec('lfo_filter', 'LFO filter (wah)', 'Modulation',
    _mod_filter + [Param('rate_hz', 'Rate', 'float', 0.5, 0.01, 20.0, 'Hz'),
                   Param('shape', 'Shape', 'enum', 'sine', choices=('sine', 'triangle', 'square', 'saw'))],
    processor=LFOFilter, ui='filter'))

# Existing JUCE filters: live attribute names and the filter interface.
for _id, _attrs in (('highpass', {'cutoff_hz': 'cutoff_frequency_hz'}), ('lowpass', {'cutoff_hz': 'cutoff_frequency_hz'}),
                    ('peak_eq', {'frequency_hz': 'cutoff_frequency_hz'}), ('low_shelf', {'frequency_hz': 'cutoff_frequency_hz'}),
                    ('high_shelf', {'frequency_hz': 'cutoff_frequency_hz'})):
    REGISTRY[_id].attrs = _attrs
    REGISTRY[_id].ui = 'filter'


def _ladder_update(plugin, params):
    plugin.mode = getattr(_pb().LadderFilter.Mode, params['mode'])
    plugin.cutoff_hz = params['cutoff_hz']
    plugin.resonance = params['resonance']
    plugin.drive = params['drive']


REGISTRY['ladder_filter'].update = _ladder_update
REGISTRY['ladder_filter'].ui = 'filter'


def static_response(effect_id, params, frequencies, samplerate):
    """Approximate magnitude response of the JUCE filters for the interface curves."""
    sr = float(samplerate)
    f = np.asarray(frequencies, dtype=np.float64)
    if effect_id in ('highpass', 'lowpass'):
        sos = signal.butter(1, min(max(params['cutoff_hz'], 1.0), sr * 0.49), effect_id, fs=sr, output='sos')
        return P.response_db(sos, f, sr)
    if effect_id == 'peak_eq':
        return P.response_db(P.biquad('peak', params['frequency_hz'], params['q'], params['gain_db'], sr), f, sr)
    if effect_id in ('low_shelf', 'high_shelf'):
        return P.response_db(P.biquad(effect_id, params['frequency_hz'], params['q'], params['gain_db'], sr), f, sr)
    if effect_id == 'ladder_filter':
        mode = params['mode']
        kind = {'LPF': 'lowpass', 'HPF': 'highpass', 'BPF': 'bandpass'}[mode[:3]]
        order = 2 if mode.endswith('12') else 4
        cutoff = min(max(params['cutoff_hz'], 1.0), sr * 0.49)
        if kind == 'bandpass':
            sos = signal.butter(max(1, order // 2), [cutoff / 1.5, min(cutoff * 1.5, sr * 0.49)], 'bandpass', fs=sr, output='sos')
        else:
            sos = signal.butter(order, cutoff, kind, fs=sr, output='sos')
        base = P.response_db(sos, f, sr)
        return base + float(params['resonance']) * 12.0 * np.exp(-((np.log(f) - np.log(cutoff)) ** 2) / 0.05)
    return np.zeros(len(f))
