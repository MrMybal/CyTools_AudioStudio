"""Mastering and utility processors: dynamic EQ, stereo imager, mid/side tool, look-ahead
maximizer, multiband saturation, hum remover, de-clicker, dither, loudness meter (LUFS),
test-signal generator, channel tool.
"""
import math

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d

from .effects import EffectSpec, Param, register
from . import processors as P
from .distortion import shape_tape


class DynamicEQ(P.Processor):
    """Three peak bands whose gain follows the level of their own band (compressing or expanding)."""

    BANDS = 3
    STEP = 64

    def configure(self, p):
        if not hasattr(self, 'detectors'):
            self.detectors = [P.BiquadChain() for _ in range(self.BANDS)]
            self.filters = [P.BiquadChain() for _ in range(self.BANDS)]
            self.followers = [P.EnvelopeFollower(self.sr) for _ in range(self.BANDS)]
            self.current_gain = [0.0] * self.BANDS
        for n in range(self.BANDS):
            k = f'b{n + 1}_'
            self.detectors[n].set_sos(P.biquad('bandpass', p[k + 'freq'], p[k + 'q'], 0.0, self.sr))
            self.followers[n].set(p[k + 'attack_ms'], p[k + 'release_ms'], 'rms')

    def reset(self):
        for chain in self.detectors + self.filters:
            chain.reset()
        for follower in self.followers:
            follower.reset()
        self.current_gain = [0.0] * self.BANDS

    def response(self, frequencies):
        total = np.zeros(len(frequencies))
        p = self.params
        for n in range(self.BANDS):
            k = f'b{n + 1}_'
            if not p[k + 'on']:
                continue
            total += P.response_db(P.biquad('peak', p[k + 'freq'], p[k + 'q'], self.current_gain[n] + p[k + 'static_db'], self.sr), frequencies, self.sr)
        return total

    def process(self, block, sidechain=None):
        p = self.params
        x = np.asarray(block, dtype=np.float64)
        count = x.shape[1]
        out = x
        reductions = []
        for n in range(self.BANDS):
            k = f'b{n + 1}_'
            if not p[k + 'on']:
                reductions.append(0.0)
                continue
            key = self.detectors[n].process(x)
            env = self.followers[n].run(P.linked_detector(key))
            level_db = P.gain_to_db(env)
            if p[k + 'mode'] == 'expand':
                gain = -np.maximum(P.expander_curve(level_db, p[k + 'threshold_db'], p[k + 'ratio'], -float(p[k + 'range_db']), 3.0), -float(p[k + 'range_db']))
                gain = np.where(level_db < p[k + 'threshold_db'], gain, 0.0)
            else:
                gain = np.maximum(P.gain_computer(level_db, p[k + 'threshold_db'], p[k + 'ratio'], 3.0), -float(p[k + 'range_db']))
            result = np.empty_like(out)
            for start in range(0, count, self.STEP):
                stop = min(count, start + self.STEP)
                g = float(gain[start]) + float(p[k + 'static_db'])
                self.filters[n].set_sos(P.biquad('peak', p[k + 'freq'], p[k + 'q'], g, self.sr))
                result[:, start:stop] = self.filters[n].process(out[:, start:stop])
            out = result
            self.current_gain[n] = float(gain[-1])
            reductions.append(float(gain.min()) if p[k + 'mode'] != 'expand' else float(gain.max()))
        self.meters['band_reduction_db'] = reductions
        self.meters['gain_reduction_db'] = min(reductions) if reductions else 0.0
        return out.astype(np.float32)


class StereoImager(P.Processor):
    """Width per band (low / mid / high) through two Linkwitz-Riley crossovers."""

    def configure(self, p):
        if not hasattr(self, 'low_x'):
            self.low_x = P.Crossover(self.sr, p['crossover_1_hz'])
            self.high_x = P.Crossover(self.sr, p['crossover_2_hz'])
        if abs(self.low_x.frequency - float(p['crossover_1_hz'])) > 1e-6:
            self.low_x.set(p['crossover_1_hz'])
        if abs(self.high_x.frequency - float(p['crossover_2_hz'])) > 1e-6:
            self.high_x.set(p['crossover_2_hz'])

    def reset(self):
        self.low_x.reset()
        self.high_x.reset()

    @staticmethod
    def _width(band, width):
        mid = 0.5 * (band[0] + band[1])
        side = 0.5 * (band[0] - band[1]) * width
        return np.stack([mid + side, mid - side])

    def process(self, block, sidechain=None):
        if block.shape[0] != 2:
            return block
        p = self.params
        x = np.asarray(block, dtype=np.float64)
        low, rest = self.low_x.split(x)
        low = self.high_x.allpass(low)
        mid, high = self.high_x.split(rest)
        out = self._width(low, p['low_width']) + self._width(mid, p['mid_width']) + self._width(high, p['high_width'])
        return out.astype(np.float32)


class MidSideTool(P.Processor):
    def process(self, block, sidechain=None):
        if block.shape[0] != 2:
            return block
        p = self.params
        mid = 0.5 * (block[0] + block[1]) * P.db_to_gain(p['mid_db'])
        side = 0.5 * (block[0] - block[1]) * P.db_to_gain(p['side_db'])
        if p['output'] == 'mid_side':
            return np.stack([mid, side]).astype(np.float32)
        if p['output'] == 'mid_only':
            return np.stack([mid, mid]).astype(np.float32)
        if p['output'] == 'side_only':
            return np.stack([side, -side]).astype(np.float32)
        return np.stack([mid + side, mid - side]).astype(np.float32)


class Maximizer(P.Processor):
    """Look-ahead peak limiter: input gain, ceiling, release; the audio is delayed by the look-ahead."""

    def configure(self, p):
        self.lookahead = max(1, int(float(p['lookahead_ms']) * 1e-3 * self.sr))
        self.gain = P.db_to_gain(p['gain_db'])
        self.ceiling = P.db_to_gain(p['ceiling_db'])
        self.release = P.time_coef(max(1.0, float(p['release_ms'])), self.sr)
        self.attack = P.time_coef(0.3, self.sr)
        if not hasattr(self, 'line'):
            self.line = P.DelayLine(2, int(self.sr * 0.05) + 8192 + 4096)
            self.tail = np.ones(self.lookahead)
            self.hold = 1.0
            self.smooth = np.zeros(1)
        if self.tail.shape[0] != self.lookahead:
            self.tail = np.ones(self.lookahead)
        self.latency_frames = self.lookahead

    def reset(self):
        self.line.reset()
        self.tail = np.ones(self.lookahead)
        self.hold = 1.0
        self.smooth = np.zeros(1)

    def process(self, block, sidechain=None):
        x = P.as_stereo(np.asarray(block, dtype=np.float64)) * self.gain
        count = x.shape[1]
        peak = np.maximum(P.linked_detector(x), 1e-9)
        attenuation = np.maximum(1.0, peak / self.ceiling)              # >= 1 where limiting is needed
        joined = np.concatenate([self.tail, attenuation])
        # each delayed frame sees the loudest of the next ``lookahead`` frames
        needed = -minimum_filter1d(-joined, size=self.lookahead + 1, origin=self.lookahead // 2, mode='nearest')
        needed = needed[self.lookahead:self.lookahead + count]
        self.tail = attenuation[-self.lookahead:] if count >= self.lookahead else np.concatenate([self.tail, attenuation])[-self.lookahead:]
        env, self.hold = P.release_hold(needed, self.hold, self.release)
        env, self.smooth = signal.lfilter([1.0 - self.attack], [1.0, -self.attack], env, zi=self.smooth)
        env = np.maximum(env, needed)                                  # never late on a peak
        gains = 1.0 / env
        self.line.push(x)
        delayed = self.line.read(self.lookahead + count, count)
        out = np.clip(delayed * gains[np.newaxis, :], -self.ceiling, self.ceiling)
        self.meters['gain_reduction_db'] = float(P.gain_to_db(gains.min()))
        self.meters['level_db'] = float(P.gain_to_db(peak.max()))
        return P.match_channels(out, block.shape[0]).astype(np.float32)

    def curve(self, level_db):
        return np.minimum(level_db + float(self.params['gain_db']), float(self.params['ceiling_db']))


class MultibandSaturation(P.Processor):
    def configure(self, p):
        bands = int(p['bands'])
        freqs = sorted(min(max(f, 20.0), self.sr * 0.45) for f in [p['crossover_1_hz'], p['crossover_2_hz'], p['crossover_3_hz']][:bands - 1])
        if not hasattr(self, 'crossovers') or len(self.crossovers) != len(freqs):
            self.crossovers = [P.Crossover(self.sr, f) for f in freqs]
        else:
            for crossover, f in zip(self.crossovers, freqs):
                if abs(crossover.frequency - f) > 1e-6:
                    crossover.set(f)
        self.bands = bands
        self.frequencies = freqs

    def reset(self):
        for crossover in self.crossovers:
            crossover.reset()

    def process(self, block, sidechain=None):
        p = self.params
        rest = np.asarray(block, dtype=np.float64)
        parts = []
        for index, crossover in enumerate(self.crossovers):
            low, rest = crossover.split(rest)
            for later in self.crossovers[index + 1:]:
                low = later.allpass(low)
            parts.append(low)
        parts.append(rest)
        out = np.zeros(rest.shape)
        levels = []
        for n, band in enumerate(parts, start=1):
            drive = P.db_to_gain(p[f'b{n}_drive_db'])
            shaped = shape_tape(band, drive) if drive > 1.001 else band
            out += shaped * P.db_to_gain(p[f'b{n}_level_db'])
            levels.append(float(P.gain_to_db(np.abs(band).max() + 1e-9)))
        self.meters['band_level_db'] = levels
        return (out * P.db_to_gain(p['output_db'])).astype(np.float32)


class HumRemover(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'chain'):
            self.chain = P.BiquadChain()
        base = float(p['base_hz'])
        sections = [P.biquad('notch', base * k, float(p['q']), 0.0, self.sr) for k in range(1, int(p['harmonics']) + 1) if base * k < self.sr * 0.45]
        self.chain.set_sos(np.concatenate(sections) if sections else None)

    def reset(self):
        self.chain.reset()

    def response(self, frequencies):
        return P.response_db(self.chain.sos, frequencies, self.sr)

    def process(self, block, sidechain=None):
        return self.chain.process(block).astype(np.float32)


class DeClicker(P.Processor):
    """Replaces isolated spikes (clicks, crackle) by linear interpolation."""

    def configure(self, p):
        self.threshold = float(p['sensitivity'])
        self.width = int(p['width'])
        self.count = 0

    def reset(self):
        self.count = 0

    def process(self, block, sidechain=None):
        x = np.array(block, dtype=np.float64)
        count = x.shape[1]
        if count < 8:
            return block
        second = np.abs(np.diff(x, n=2, axis=-1, prepend=x[:, :1], append=x[:, -1:]))
        floor = np.median(second, axis=-1, keepdims=True) * self.threshold + 1e-5
        clicks = second > floor
        total = 0
        for channel in range(x.shape[0]):
            mask = clicks[channel]
            if not mask.any():
                continue
            if self.width > 1:
                kernel = np.ones(self.width * 2 + 1, dtype=bool)
                mask = np.convolve(mask.astype(np.int8), kernel.astype(np.int8), mode='same') > 0
            mask[:2] = mask[-2:] = False
            total += int(mask.sum())
            good = np.nonzero(~mask)[0]
            x[channel, mask] = np.interp(np.nonzero(mask)[0], good, x[channel, good])
        self.count += total
        self.meters['clicks'] = total
        self.meters['total_clicks'] = self.count
        return x.astype(np.float32)


class Dither(P.Processor):
    """TPDF dither (and optional preview quantisation) for a 16 or 24 bit export."""

    def configure(self, p):
        self.levels = 2.0 ** (float(p['bits']) - 1)
        self.rng = np.random.default_rng(9)

    def process(self, block, sidechain=None):
        p = self.params
        x = np.asarray(block, dtype=np.float64)
        step = 1.0 / self.levels
        noise = (self.rng.random(x.shape) + self.rng.random(x.shape) - 1.0) * step * float(p['amount'])
        out = x + noise
        if p['quantize']:
            out = np.round(out * self.levels) / self.levels
        return out.astype(np.float32)


class LoudnessMeter(P.Processor):
    """ITU-R BS.1770 style loudness: momentary (400 ms), short-term (3 s), gated integrated, peak."""

    def configure(self, p):
        if not hasattr(self, 'weighting'):
            self.weighting = P.BiquadChain(np.concatenate([P.biquad('high_shelf', 1681.0, 0.7071, 3.99, self.sr), P.biquad('highpass', 38.13, 0.5, 0.0, self.sr)]))
            self.reset_integration()
            self.block_ms = []            # (frames, mean square) of recent blocks

    def reset(self):
        self.weighting.reset()
        self.reset_integration()

    def reset_integration(self):
        self.gated = []               # mean squares of 400 ms windows above the absolute gate
        self.peak = 0.0
        self.block_ms = []
        self.meters = {'lufs_m': -100.0, 'lufs_s': -100.0, 'lufs_i': -100.0, 'peak_db': -100.0, 'range_lu': 0.0}

    def _window_ms(self, seconds):
        frames_needed = int(seconds * self.sr)
        total, weight = 0.0, 0
        for frames, ms in reversed(self.block_ms):
            take = min(frames, frames_needed - weight)
            total += ms * take
            weight += take
            if weight >= frames_needed:
                break
        return total / weight if weight else 0.0

    @staticmethod
    def _lufs(mean_square):
        return -0.691 + 10.0 * math.log10(mean_square + 1e-12)

    def process(self, block, sidechain=None):
        x = P.as_stereo(np.asarray(block, dtype=np.float64))
        weighted = self.weighting.process(x)
        ms = float(np.mean(np.sum(weighted ** 2, axis=0)))
        self.block_ms.append((x.shape[1], ms))
        keep = int(3.5 * self.sr)
        while sum(f for f, _ in self.block_ms) > keep + x.shape[1] and len(self.block_ms) > 1:
            self.block_ms.pop(0)
        momentary = self._lufs(self._window_ms(0.4))
        short = self._lufs(self._window_ms(3.0))
        if momentary > -70.0:
            self.gated.append(self._window_ms(0.4))
        integrated = -100.0
        if self.gated:
            relative = self._lufs(sum(self.gated) / len(self.gated)) - 10.0
            above = [v for v in self.gated if self._lufs(v) > relative]
            if above:
                integrated = self._lufs(sum(above) / len(above))
        self.peak = max(self.peak, float(np.abs(x).max()) if x.size else 0.0)
        self.meters.update({'lufs_m': momentary, 'lufs_s': short, 'lufs_i': integrated, 'peak_db': float(P.gain_to_db(self.peak)),
                            'range_lu': float(max(0.0, short - momentary)) if short > -70 else 0.0})
        return block


class ToneGenerator(P.Processor):
    def configure(self, p):
        if not hasattr(self, 'phase'):
            self.phase = 0.0
            self.rng = np.random.default_rng(12)
            self.pink_zi = None
        self.level = P.db_to_gain(p['level_db'])
        self.frequency = float(p['frequency_hz'])

    def reset(self):
        self.phase = 0.0
        self.pink_zi = None

    def process(self, block, sidechain=None):
        p = self.params
        count = block.shape[1]
        shape = p['shape']
        if shape == 'white':
            tone = self.rng.standard_normal(count) * 0.3
        elif shape == 'pink':
            white = self.rng.standard_normal(count)
            b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
            a = [1.0, -2.494956002, 2.017265875, -0.522189400]
            if self.pink_zi is None:
                self.pink_zi = np.zeros(3)
            tone, self.pink_zi = signal.lfilter(b, a, white, zi=self.pink_zi)
            tone = tone * 3.0
        else:
            phases = np.mod(self.phase + np.arange(count) * self.frequency / self.sr, 1.0)
            self.phase = float(np.mod(self.phase + count * self.frequency / self.sr, 1.0))
            tone = np.where(phases < 0.5, 1.0, -1.0) * 0.7 if shape == 'square' else np.sin(2 * np.pi * phases)
        tone = (tone * self.level).astype(np.float32)[np.newaxis, :]
        tone = np.repeat(tone, block.shape[0], axis=0)
        if p['mode'] == 'replace':
            return tone
        return (block + tone).astype(np.float32)


class ChannelTool(P.Processor):
    def process(self, block, sidechain=None):
        p = self.params
        out = np.array(P.as_stereo(np.asarray(block, dtype=np.float32)))
        if p['swap']:
            out = out[::-1].copy()
        out[0] *= P.db_to_gain(p['left_db']) * (-1.0 if p['invert_left'] else 1.0)
        out[1] *= P.db_to_gain(p['right_db']) * (-1.0 if p['invert_right'] else 1.0)
        if p['mono']:
            mono = out.mean(axis=0)
            out = np.stack([mono, mono])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


# ----------------------------------------------------------------------------- registrations

_dyn = []
for _n, (_f, _on) in enumerate([(120.0, True), (2500.0, True), (8000.0, False)], start=1):
    _dyn += [Param(f'b{_n}_on', f'Band {_n}', 'bool', _on),
             Param(f'b{_n}_freq', f'Band {_n} frequency', 'float', _f, 20.0, 20000.0, 'Hz'),
             Param(f'b{_n}_q', f'Band {_n} Q', 'float', 1.5, 0.2, 10.0),
             Param(f'b{_n}_mode', f'Band {_n} mode', 'enum', 'compress', choices=('compress', 'expand')),
             Param(f'b{_n}_threshold_db', f'Band {_n} threshold', 'float', -30.0, -70.0, 0.0, 'dB'),
             Param(f'b{_n}_ratio', f'Band {_n} ratio', 'float', 3.0, 1.0, 10.0, ':1'),
             Param(f'b{_n}_range_db', f'Band {_n} range', 'float', 12.0, 0.0, 24.0, 'dB', help='maximum gain change'),
             Param(f'b{_n}_static_db', f'Band {_n} static gain', 'float', 0.0, -12.0, 12.0, 'dB'),
             Param(f'b{_n}_attack_ms', f'Band {_n} attack', 'float', 10.0, 0.5, 200.0, 'ms'),
             Param(f'b{_n}_release_ms', f'Band {_n} release', 'float', 150.0, 10.0, 2000.0, 'ms')]
register(EffectSpec('dynamic_eq', 'Dynamic EQ', 'EQ', _dyn, processor=DynamicEQ, ui='dynamic_eq',
                    help='Each band cuts (or boosts) only when its own level crosses the threshold.'))

register(EffectSpec('stereo_imager', 'Stereo imager (3 bands)', 'Stereo',
    [Param('crossover_1_hz', 'Low / mid', 'float', 150.0, 40.0, 1000.0, 'Hz'),
     Param('crossover_2_hz', 'Mid / high', 'float', 3000.0, 500.0, 12000.0, 'Hz'),
     Param('low_width', 'Low width', 'float', 0.0, 0.0, 2.0, help='0 = mono bass'),
     Param('mid_width', 'Mid width', 'float', 1.0, 0.0, 2.0),
     Param('high_width', 'High width', 'float', 1.3, 0.0, 2.0)],
    processor=StereoImager, ui='stereo'))

register(EffectSpec('mid_side', 'Mid / side tool', 'Stereo',
    [Param('mid_db', 'Mid', 'float', 0.0, -24.0, 12.0, 'dB'),
     Param('side_db', 'Side', 'float', 0.0, -24.0, 12.0, 'dB'),
     Param('output', 'Output', 'enum', 'stereo', choices=('stereo', 'mid_side', 'mid_only', 'side_only'), help='mid_side outputs M on the left and S on the right')],
    processor=MidSideTool, ui='stereo'))

register(EffectSpec('maximizer', 'Maximizer (look-ahead limiter)', 'Dynamics',
    [Param('gain_db', 'Input gain', 'float', 0.0, 0.0, 24.0, 'dB'),
     Param('ceiling_db', 'Ceiling', 'float', -0.3, -12.0, 0.0, 'dBFS'),
     Param('release_ms', 'Release', 'float', 80.0, 5.0, 1000.0, 'ms'),
     Param('lookahead_ms', 'Look-ahead', 'float', 3.0, 0.5, 10.0, 'ms', automatable=False)],
    processor=Maximizer, ui='dynamics', help='Transparent peak limiting with look-ahead (adds that latency). Sample-peak ceiling, no oversampling.'))

_mbs = [Param('bands', 'Bands', 'int', 3, 2, 4),
        Param('crossover_1_hz', 'Crossover 1', 'float', 150.0, 40.0, 2000.0, 'Hz'),
        Param('crossover_2_hz', 'Crossover 2', 'float', 2000.0, 200.0, 8000.0, 'Hz'),
        Param('crossover_3_hz', 'Crossover 3', 'float', 6000.0, 1000.0, 16000.0, 'Hz'),
        Param('output_db', 'Output', 'float', 0.0, -24.0, 24.0, 'dB')]
for _n in range(1, 5):
    _mbs += [Param(f'b{_n}_drive_db', f'Band {_n} drive', 'float', 6.0, 0.0, 36.0, 'dB'),
             Param(f'b{_n}_level_db', f'Band {_n} level', 'float', 0.0, -24.0, 12.0, 'dB')]
register(EffectSpec('multiband_saturation', 'Multiband saturation', 'Distortion', _mbs, processor=MultibandSaturation, ui='multiband',
                    help='Tape saturation per band: warm the lows without fuzzing the highs.'))

register(EffectSpec('hum_remover', 'Hum remover', 'Restoration',
    [Param('base_hz', 'Mains frequency', 'float', 50.0, 40.0, 70.0, 'Hz'),
     Param('harmonics', 'Harmonics', 'int', 4, 1, 12),
     Param('q', 'Q', 'float', 30.0, 5.0, 100.0, help='higher = narrower notches')],
    processor=HumRemover, ui='filter', help='Notches at the mains frequency and its harmonics.'))

register(EffectSpec('declicker', 'De-clicker', 'Restoration',
    [Param('sensitivity', 'Sensitivity', 'float', 12.0, 3.0, 60.0, help='lower = more aggressive'),
     Param('width', 'Repair width', 'int', 2, 1, 8, 'smp')],
    processor=DeClicker, ui='generic', help='Detects isolated spikes and interpolates over them (clicks, crackle).'))

register(EffectSpec('dither', 'Dither', 'Utility',
    [Param('bits', 'Target bits', 'enum', 16, choices=(8, 12, 16, 20, 24)),
     Param('amount', 'Amount', 'float', 1.0, 0.0, 2.0, 'LSB'),
     Param('quantize', 'Preview quantisation', 'bool', False)],
    processor=Dither, ui='generic', help='TPDF dither before a 16-bit export; put it last on the master.'))

register(EffectSpec('loudness_meter', 'Loudness meter (LUFS)', 'Analysis', [],
    processor=LoudnessMeter, ui='loudness', help='Momentary, short-term and integrated loudness (BS.1770 gating), peak. Does not change the sound.'))

register(EffectSpec('tone_generator', 'Test signal generator', 'Utility',
    [Param('shape', 'Signal', 'enum', 'sine', choices=('sine', 'square', 'white', 'pink')),
     Param('frequency_hz', 'Frequency', 'float', 1000.0, 20.0, 20000.0, 'Hz'),
     Param('level_db', 'Level', 'float', -18.0, -80.0, 0.0, 'dBFS'),
     Param('mode', 'Mode', 'enum', 'add', choices=('add', 'replace'))],
    processor=ToneGenerator, ui='generic', help='Sine, square, white or pink noise, added to or replacing the track (calibration, testing chains).'))

register(EffectSpec('channel_tool', 'Channel tool', 'Utility',
    [Param('left_db', 'Left gain', 'float', 0.0, -60.0, 12.0, 'dB'),
     Param('right_db', 'Right gain', 'float', 0.0, -60.0, 12.0, 'dB'),
     Param('invert_left', 'Invert left', 'bool', False),
     Param('invert_right', 'Invert right', 'bool', False),
     Param('swap', 'Swap channels', 'bool', False),
     Param('mono', 'Sum to mono', 'bool', False)],
    processor=ChannelTool, ui='generic'))
