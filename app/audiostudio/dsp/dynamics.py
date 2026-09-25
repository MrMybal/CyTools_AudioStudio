"""Dynamics processors: compressor, expander/gate, multiband compressor, de-esser, transient shaper.

All of them expose real gain reduction in ``meters['gain_reduction_db']`` (the interfaces draw
it), accept a side-chain block (ducking, keyed gates) and run block by block.
"""
import numpy as np

from .effects import EffectSpec, Param, register, REGISTRY, _pb
from . import processors as P

DETECTORS = ('peak', 'rms')


def _detector_chain(params, sr):
    cutoff = float(params.get('sc_highpass_hz', 0.0) or 0.0)
    return P.BiquadChain(P.biquad('highpass', cutoff, 0.707, 0.0, sr)) if cutoff >= 20.0 else None


class Compressor(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'follower'):
            self.follower = P.EnvelopeFollower(self.sr)
        self.follower.set(p['attack_ms'], p['release_ms'], p.get('detector', 'peak'))
        self.sc_filter = _detector_chain(p, self.sr)
        self.makeup = P.db_to_gain(p.get('makeup_db', 0.0))

    def reset(self):
        self.follower.reset()
        if self.sc_filter is not None:
            self.sc_filter.reset()
        self.meters = {}

    def curve(self, level_db):
        p = self.params
        return level_db + P.gain_computer(level_db, p['threshold_db'], p['ratio'], p.get('knee_db', 0.0)) + p.get('makeup_db', 0.0)

    def process(self, block, sidechain=None):
        p = self.params
        key = sidechain if (sidechain is not None and p.get('sidechain_input', False)) else block
        detector = np.asarray(key, dtype=np.float64)
        if self.sc_filter is not None:
            detector = self.sc_filter.process(detector)
        env = self.follower.run(P.linked_detector(detector))
        level_db = P.gain_to_db(env)
        reduction = P.gain_computer(level_db, p['threshold_db'], p['ratio'], p.get('knee_db', 0.0))
        gain = (10.0 ** (reduction / 20.0)) * self.makeup
        self.meters['gain_reduction_db'] = float(reduction.min()) if reduction.size else 0.0
        self.meters['level_db'] = float(level_db.max()) if level_db.size else -100.0
        return (block * gain[np.newaxis, :].astype(np.float32)).astype(np.float32)


class Gate(P.Processor):
    """Downward expander; a high ratio and a deep range make it a noise gate."""

    def configure(self, p):
        if not hasattr(self, 'follower'):
            self.follower = P.EnvelopeFollower(self.sr)
        self.follower.set(p['attack_ms'], p['release_ms'], p.get('detector', 'peak'))
        self.sc_filter = _detector_chain(p, self.sr)

    def reset(self):
        self.follower.reset()
        if self.sc_filter is not None:
            self.sc_filter.reset()
        self.meters = {}

    def curve(self, level_db):
        p = self.params
        return level_db + P.expander_curve(level_db, p['threshold_db'], p['ratio'], p.get('range_db', -80.0), p.get('knee_db', 0.0))

    def process(self, block, sidechain=None):
        p = self.params
        key = sidechain if (sidechain is not None and p.get('sidechain_input', False)) else block
        detector = np.asarray(key, dtype=np.float64)
        if self.sc_filter is not None:
            detector = self.sc_filter.process(detector)
        env = self.follower.run(P.linked_detector(detector))
        level_db = P.gain_to_db(env)
        reduction = P.expander_curve(level_db, p['threshold_db'], p['ratio'], p.get('range_db', -80.0), p.get('knee_db', 0.0))
        gain = 10.0 ** (reduction / 20.0)
        self.meters['gain_reduction_db'] = float(reduction.min()) if reduction.size else 0.0
        self.meters['level_db'] = float(level_db.max()) if level_db.size else -100.0
        return (block * gain[np.newaxis, :].astype(np.float32)).astype(np.float32)


MAX_BANDS = 4


class MultibandCompressor(P.Processor):
    """Up to four bands split by Linkwitz-Riley crossovers, each with its own compressor."""

    def configure(self, p):
        bands = int(p['bands'])
        freqs = [p['crossover_1_hz'], p['crossover_2_hz'], p['crossover_3_hz']][:bands - 1]
        freqs = sorted(min(max(f, 20.0), self.sr * 0.45) for f in freqs)
        if not hasattr(self, 'crossovers') or len(self.crossovers) != len(freqs):
            self.crossovers = [P.Crossover(self.sr, f) for f in freqs]
        else:
            for crossover, f in zip(self.crossovers, freqs):
                if abs(crossover.frequency - f) > 1e-6:
                    crossover.set(f)
        if not hasattr(self, 'followers') or len(self.followers) != MAX_BANDS:
            self.followers = [P.EnvelopeFollower(self.sr) for _ in range(MAX_BANDS)]
        for index, follower in enumerate(self.followers):
            follower.set(p[f'b{index + 1}_attack_ms'], p[f'b{index + 1}_release_ms'], p.get('detector', 'peak'))
        self.bands = bands
        self.frequencies = freqs

    def reset(self):
        for crossover in getattr(self, 'crossovers', []):
            crossover.reset()
        for follower in self.followers:
            follower.reset()
        self.meters = {}

    def split(self, block):
        """Bands from low to high, phase aligned so that their sum is flat."""
        bands = []
        rest = np.asarray(block, dtype=np.float64)
        for index, crossover in enumerate(self.crossovers):
            low, rest = crossover.split(rest)
            # Lower bands go through the all-pass of every following crossover.
            for later in self.crossovers[index + 1:]:
                low = later.allpass(low)
            bands.append(low)
        bands.append(rest)
        return bands

    def process(self, block, sidechain=None):
        p = self.params
        bands = self.split(block)
        out = np.zeros(block.shape, np.float64)
        reductions = []
        levels = []
        for index, band in enumerate(bands):
            n = index + 1
            if p.get(f'b{n}_mute', False):
                reductions.append(0.0)
                levels.append(-100.0)
                continue
            env = self.followers[index].run(P.linked_detector(band))
            level_db = P.gain_to_db(env)
            reduction = P.gain_computer(level_db, p[f'b{n}_threshold_db'], p[f'b{n}_ratio'], p.get('knee_db', 6.0))
            gain = 10.0 ** ((reduction + p[f'b{n}_gain_db']) / 20.0)
            out += band * gain[np.newaxis, :]
            reductions.append(float(reduction.min()) if reduction.size else 0.0)
            levels.append(float(level_db.max()) if level_db.size else -100.0)
        self.meters['band_reduction_db'] = reductions
        self.meters['band_level_db'] = levels
        self.meters['gain_reduction_db'] = min(reductions) if reductions else 0.0
        return (out * P.db_to_gain(p.get('output_db', 0.0))).astype(np.float32)


class DeEsser(P.Processor):
    """Compresses only the sibilance band (split mode) or the whole signal keyed by that band."""

    def configure(self, p):
        if not hasattr(self, 'follower'):
            self.follower = P.EnvelopeFollower(self.sr)
            self.crossover = P.Crossover(self.sr, p['frequency_hz'])
            self.detector = P.BiquadChain()
        self.follower.set(0.5, p['release_ms'], 'peak')
        if abs(self.crossover.frequency - float(p['frequency_hz'])) > 1e-6:
            self.crossover.set(p['frequency_hz'])
        self.detector.set_sos(P.biquad('bandpass', p['frequency_hz'] * 1.4, 1.0, 0.0, self.sr))

    def reset(self):
        self.follower.reset()
        self.crossover.reset()
        self.detector.reset()
        self.meters = {}

    def process(self, block, sidechain=None):
        p = self.params
        low, high = self.crossover.split(block)
        key = self.detector.process(np.asarray(block, dtype=np.float64))
        env = self.follower.run(P.linked_detector(key))
        level_db = P.gain_to_db(env)
        reduction = np.maximum(P.gain_computer(level_db, p['threshold_db'], p['ratio'], 3.0), float(p['range_db']))
        gain = (10.0 ** (reduction / 20.0))[np.newaxis, :]
        self.meters['gain_reduction_db'] = float(reduction.min()) if reduction.size else 0.0
        if p['mode'] == 'wideband':
            return (np.asarray(block, dtype=np.float64) * gain).astype(np.float32)
        return (low + high * gain).astype(np.float32)


class TransientShaper(P.Processor):
    """Boosts or softens attacks and sustain by comparing a fast and a slow envelope."""

    def configure(self, p):
        if not hasattr(self, 'fast'):
            self.fast = P.EnvelopeFollower(self.sr)
            self.slow = P.EnvelopeFollower(self.sr)
        self.fast.set(0.2, p['attack_ms'] * 2.0, 'peak')
        self.slow.set(p['attack_ms'] * 4.0, p['sustain_ms'], 'peak')

    def reset(self):
        self.fast.reset()
        self.slow.reset()
        self.meters = {}

    def process(self, block, sidechain=None):
        p = self.params
        detector = P.linked_detector(np.asarray(block, dtype=np.float64))
        fast = self.fast.run(detector)
        slow = self.slow.run(detector)
        diff = P.gain_to_db(fast) - P.gain_to_db(slow)
        attack = np.maximum(diff, 0.0) * (float(p['attack_amount']) / 100.0)
        sustain = np.minimum(diff, 0.0) * (-float(p['sustain_amount']) / 100.0)
        gain_db = np.clip(attack + sustain, -24.0, 24.0) + float(p['output_db'])
        self.meters['gain_reduction_db'] = float(gain_db.min())
        self.meters['gain_boost_db'] = float(gain_db.max())
        return (block * (10.0 ** (gain_db / 20.0))[np.newaxis, :].astype(np.float32)).astype(np.float32)


# ----------------------------------------------------------------------------- registrations

def _dyn_common(threshold=-18.0):
    return [Param('threshold_db', 'Threshold', 'float', threshold, -60.0, 0.0, 'dB'),
            Param('ratio', 'Ratio', 'float', 4.0, 1.0, 30.0, ':1'),
            Param('attack_ms', 'Attack', 'float', 5.0, 0.1, 500.0, 'ms'),
            Param('release_ms', 'Release', 'float', 100.0, 1.0, 5000.0, 'ms'),
            Param('knee_db', 'Knee', 'float', 6.0, 0.0, 24.0, 'dB')]


register(EffectSpec('compressor', 'Compressor', 'Dynamics',
    _dyn_common() + [Param('makeup_db', 'Make-up gain', 'float', 0.0, -12.0, 24.0, 'dB'),
                     Param('detector', 'Detector', 'enum', 'peak', choices=DETECTORS),
                     Param('sc_highpass_hz', 'Side-chain high-pass', 'float', 0.0, 0.0, 2000.0, 'Hz', help='0 = off; ignores the bass in the detector'),
                     Param('sidechain_input', 'Key from side-chain track', 'bool', False, help='duck this track when the side-chain track plays')],
    processor=Compressor, ui='dynamics', sidechain=True, help='Feed-forward compressor with soft knee, peak or RMS detection and side-chain key.'))

register(EffectSpec('expander', 'Expander', 'Dynamics',
    [Param('threshold_db', 'Threshold', 'float', -40.0, -90.0, 0.0, 'dB'),
     Param('ratio', 'Ratio', 'float', 2.0, 1.0, 20.0, ':1'),
     Param('range_db', 'Range', 'float', -40.0, -100.0, 0.0, 'dB', help='maximum attenuation'),
     Param('attack_ms', 'Attack', 'float', 2.0, 0.1, 500.0, 'ms'),
     Param('release_ms', 'Release', 'float', 150.0, 1.0, 5000.0, 'ms'),
     Param('knee_db', 'Knee', 'float', 6.0, 0.0, 24.0, 'dB'),
     Param('detector', 'Detector', 'enum', 'peak', choices=DETECTORS),
     Param('sc_highpass_hz', 'Side-chain high-pass', 'float', 0.0, 0.0, 2000.0, 'Hz'),
     Param('sidechain_input', 'Key from side-chain track', 'bool', False)],
    processor=Gate, ui='dynamics', sidechain=True, help='Downward expander: quiet passages get quieter.'))

register(EffectSpec('noise_gate', 'Noise gate', 'Dynamics',
    [Param('threshold_db', 'Threshold', 'float', -50.0, -100.0, 0.0, 'dB'),
     Param('ratio', 'Ratio', 'float', 20.0, 1.0, 100.0, ':1'),
     Param('range_db', 'Range', 'float', -80.0, -100.0, 0.0, 'dB', help='attenuation when closed'),
     Param('attack_ms', 'Attack', 'float', 1.0, 0.1, 500.0, 'ms'),
     Param('release_ms', 'Release', 'float', 100.0, 1.0, 5000.0, 'ms'),
     Param('knee_db', 'Knee', 'float', 2.0, 0.0, 24.0, 'dB'),
     Param('detector', 'Detector', 'enum', 'peak', choices=DETECTORS),
     Param('sc_highpass_hz', 'Side-chain high-pass', 'float', 0.0, 0.0, 2000.0, 'Hz'),
     Param('sidechain_input', 'Key from side-chain track', 'bool', False, help='open the gate from another track (keyed gate)')],
    processor=Gate, ui='dynamics', sidechain=True))

_mb = [Param('bands', 'Bands', 'int', 3, 2, 4),
       Param('crossover_1_hz', 'Crossover 1', 'float', 150.0, 40.0, 2000.0, 'Hz'),
       Param('crossover_2_hz', 'Crossover 2', 'float', 2000.0, 200.0, 8000.0, 'Hz'),
       Param('crossover_3_hz', 'Crossover 3', 'float', 6000.0, 1000.0, 16000.0, 'Hz'),
       Param('knee_db', 'Knee', 'float', 6.0, 0.0, 24.0, 'dB'),
       Param('detector', 'Detector', 'enum', 'rms', choices=DETECTORS),
       Param('output_db', 'Output', 'float', 0.0, -24.0, 24.0, 'dB')]
for _n in range(1, MAX_BANDS + 1):
    _mb += [Param(f'b{_n}_threshold_db', f'Band {_n} threshold', 'float', -20.0, -60.0, 0.0, 'dB'),
            Param(f'b{_n}_ratio', f'Band {_n} ratio', 'float', 3.0, 1.0, 20.0, ':1'),
            Param(f'b{_n}_attack_ms', f'Band {_n} attack', 'float', [20.0, 10.0, 5.0, 2.0][_n - 1], 0.1, 500.0, 'ms'),
            Param(f'b{_n}_release_ms', f'Band {_n} release', 'float', [200.0, 120.0, 80.0, 50.0][_n - 1], 1.0, 5000.0, 'ms'),
            Param(f'b{_n}_gain_db', f'Band {_n} gain', 'float', 0.0, -24.0, 24.0, 'dB'),
            Param(f'b{_n}_mute', f'Band {_n} mute', 'bool', False)]
register(EffectSpec('multiband_compressor', 'Multiband compressor', 'Dynamics', _mb,
    processor=MultibandCompressor, ui='multiband', help='Linkwitz-Riley crossovers (24 dB/oct) and one compressor per band.'))

register(EffectSpec('de_esser', 'De-esser', 'Dynamics',
    [Param('frequency_hz', 'Sibilance from', 'float', 5500.0, 2000.0, 12000.0, 'Hz'),
     Param('threshold_db', 'Threshold', 'float', -30.0, -60.0, 0.0, 'dB'),
     Param('ratio', 'Ratio', 'float', 6.0, 1.0, 20.0, ':1'),
     Param('range_db', 'Maximum reduction', 'float', -18.0, -40.0, 0.0, 'dB'),
     Param('release_ms', 'Release', 'float', 60.0, 5.0, 500.0, 'ms'),
     Param('mode', 'Mode', 'enum', 'split', choices=('split', 'wideband'), help='split: only the high band is reduced')],
    processor=DeEsser, ui='dynamics'))

register(EffectSpec('transient_shaper', 'Transient shaper', 'Dynamics',
    [Param('attack_amount', 'Attack', 'float', 30.0, -100.0, 100.0, '%', help='positive = sharper attacks'),
     Param('sustain_amount', 'Sustain', 'float', 0.0, -100.0, 100.0, '%', help='positive = longer sustain'),
     Param('attack_ms', 'Attack time', 'float', 10.0, 1.0, 100.0, 'ms'),
     Param('sustain_ms', 'Sustain time', 'float', 300.0, 50.0, 2000.0, 'ms'),
     Param('output_db', 'Output', 'float', 0.0, -24.0, 24.0, 'dB')],
    processor=TransientShaper, ui='dynamics'))

STYLES = ('opto', 'vca', 'fet', 'varimu')


class VintageCompressor(Compressor):
    """Compressor characters: opto (slow, program-dependent release), VCA (clean, precise), FET (very
    fast, aggressive, a little saturation), vari-mu (soft knee, ratio grows with the overshoot)."""

    def configure(self, p):
        style = p['style']
        attack = {'opto': 10.0, 'vca': p['attack_ms'], 'fet': 0.2, 'varimu': 15.0}[style]
        release = {'opto': 60.0, 'vca': p['release_ms'], 'fet': 50.0, 'varimu': 200.0}[style]
        super().configure({**p, 'attack_ms': attack, 'release_ms': release, 'detector': 'rms' if style in ('opto', 'varimu') else 'peak',
                           'makeup_db': p['makeup_db'], 'sc_highpass_hz': 0.0})
        if not hasattr(self, 'slow'):
            self.slow = P.EnvelopeFollower(self.sr)
        self.slow.set(attack, release * 12.0, self.follower.mode)
        self.style = style

    def reset(self):
        super().reset()
        self.slow.reset()

    def _reduction(self, level_db):
        p = self.params
        if self.style == 'varimu':
            over = np.maximum(level_db - float(p['threshold_db']), 0.0)
            ratio = 1.5 + over / 6.0
            return -over * (1.0 - 1.0 / ratio)
        ratio = {'opto': 3.0, 'fet': max(4.0, float(p['ratio'])), 'vca': float(p['ratio'])}[self.style]
        knee = {'opto': 10.0, 'fet': 1.0, 'vca': float(p['knee_db'])}[self.style]
        return P.gain_computer(level_db, p['threshold_db'], ratio, knee)

    def curve(self, level_db):
        return level_db + self._reduction(np.asarray(level_db, dtype=np.float64)) + float(self.params['makeup_db'])

    def process(self, block, sidechain=None):
        p = self.params
        detector = P.linked_detector(np.asarray(block, dtype=np.float64))
        fast = self.follower.run(detector)
        env = fast
        if self.style in ('opto', 'varimu'):
            slow = self.slow.run(detector)
            env = np.maximum(fast, slow * 0.7)          # program-dependent: long passages release slowly
        level_db = P.gain_to_db(env)
        reduction = self._reduction(level_db)
        gain = (10.0 ** (reduction / 20.0)) * self.makeup
        wet = np.asarray(block, dtype=np.float64) * gain[np.newaxis, :]
        if self.style == 'fet':
            wet = np.tanh(wet * 1.2) / np.tanh(1.2)
        self.meters['gain_reduction_db'] = float(reduction.min()) if reduction.size else 0.0
        self.meters['level_db'] = float(level_db.max()) if level_db.size else -100.0
        out = P.mix_dry_wet(np.asarray(block, dtype=np.float64), wet, p['mix'])
        return out.astype(np.float32)


register(EffectSpec('vintage_compressor', 'Vintage compressor (opto / VCA / FET / vari-mu)', 'Dynamics',
    [Param('style', 'Style', 'enum', 'opto', choices=STYLES),
     Param('threshold_db', 'Threshold', 'float', -20.0, -60.0, 0.0, 'dB'),
     Param('ratio', 'Ratio (VCA, FET)', 'float', 4.0, 1.0, 20.0, ':1'),
     Param('attack_ms', 'Attack (VCA)', 'float', 5.0, 0.1, 200.0, 'ms'),
     Param('release_ms', 'Release (VCA)', 'float', 120.0, 5.0, 3000.0, 'ms'),
     Param('knee_db', 'Knee (VCA)', 'float', 6.0, 0.0, 24.0, 'dB'),
     Param('makeup_db', 'Make-up gain', 'float', 0.0, -12.0, 24.0, 'dB'),
     Param('mix', 'Mix (parallel)', 'float', 1.0, 0.0, 1.0)],
    processor=VintageCompressor, ui='dynamics', help='Opto: slow and musical; VCA: precise bus compressor; FET: fast and punchy; vari-mu: soft, level-dependent ratio.'))


# The JUCE limiter keeps its own place (true brick wall); give it the dynamics interface.
REGISTRY['limiter'].ui = 'dynamics'
REGISTRY['limiter'].help = 'Brick-wall limiter (JUCE). Gain reduction shown is measured on the output.'
REGISTRY['gain'].ui = 'generic'
