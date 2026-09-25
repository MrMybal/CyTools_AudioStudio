"""Space: ping-pong and multi-tap delays, impulse-response reverbs (hall, plate, room, chamber,
cathedral, spring) synthesised from their parameters, convolution with a file, Haas widening.
"""
import math

import numpy as np

from .effects import EffectSpec, Param, register, REGISTRY, _pb
from . import processors as P

REVERB_TYPES = ('room', 'hall', 'plate', 'chamber', 'cathedral', 'spring')


class PingPongDelay(P.Processor):
    """Stereo delay with cross-feedback; the feedback path has a tone control."""

    def configure(self, p):
        self.delay_frames = max(8, int(round(float(p['delay_ms']) * 1e-3 * self.sr)))
        max_frames = int(self.sr * 5.1) + 64
        if not hasattr(self, 'line'):
            self.line = P.DelayLine(2, max_frames)
            self.tone = P.OnePole(self.sr, p['tone_hz'])
        self.tone.set(p['tone_hz'])

    def reset(self):
        self.line.reset()
        self.tone.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        feedback = float(p['feedback'])
        cross = float(p['ping_pong'])
        wet = np.empty_like(stereo)
        step = self.delay_frames
        for start in range(0, stereo.shape[1], step):
            stop = min(stereo.shape[1], start + step)
            delayed = self.line.read(self.delay_frames, stop - start)
            wet[:, start:stop] = delayed
            fed = self.tone.process(delayed) * feedback
            # ping-pong: the left echo feeds the right line and vice versa
            swapped = fed[::-1] * cross + fed * (1.0 - cross)
            self.line.push(stereo[:, start:stop] + swapped)
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class MultiTapDelay(P.Processor):
    """Four taps without feedback: rhythmic echoes with individual gains and pans."""

    TAPS = 4

    def configure(self, p):
        base = float(p['delay_ms']) * 1e-3 * self.sr
        self.taps = []
        for n in range(1, self.TAPS + 1):
            if not p.get(f'tap{n}_on', False):
                continue
            frames = max(1, int(round(base * float(p[f'tap{n}_time']))))
            self.taps.append((frames, P.db_to_gain(p[f'tap{n}_gain_db']), float(p[f'tap{n}_pan'])))
        self.max_delay = max([t[0] for t in self.taps] + [1])
        needed = self.max_delay + 8192
        if not hasattr(self, 'line') or self.line.max_frames < needed:
            self.line = P.DelayLine(2, needed + int(self.sr * 2))

    def reset(self):
        self.line.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        wet = np.zeros_like(stereo)
        # Push first so that taps shorter than the block still read the current audio.
        self.line.push(stereo)
        for frames, gain, pan in self.taps:
            delayed = self.line.read(frames + count, count)
            angle = (pan + 1.0) * 0.25 * math.pi
            wet[0] += delayed[0] * gain * math.cos(angle) * math.sqrt(2.0)
            wet[1] += delayed[1] * gain * math.sin(angle) * math.sqrt(2.0)
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


def synth_impulse(kind, decay_seconds, predelay_ms, size, damping, low_cut_hz, high_cut_hz, width, samplerate, seed=7):
    """Stereo impulse response (2, frames) built from decaying noise and early reflections."""
    sr = int(samplerate)
    decay = float(min(max(decay_seconds, 0.1), 20.0))
    length = int(sr * (decay * 1.2 + 0.15))
    rng = np.random.default_rng(seed)
    t = np.arange(length) / sr
    noise = rng.standard_normal((2, length))
    # Frequency dependent decay: three bands, the highs die faster with damping.
    from scipy import signal
    low = signal.sosfilt(signal.butter(2, 400.0, 'lowpass', fs=sr, output='sos'), noise, axis=-1)
    high = signal.sosfilt(signal.butter(2, 4000.0, 'highpass', fs=sr, output='sos'), noise, axis=-1)
    mid = noise - low - high
    tau = decay / 6.9078                                      # -60 dB after ``decay`` seconds
    profile = {'room': (0.9, 1.0, 0.7), 'hall': (1.2, 1.0, 0.55), 'plate': (0.8, 1.0, 0.95), 'chamber': (1.0, 1.0, 0.8),
               'cathedral': (1.5, 1.0, 0.45), 'spring': (0.5, 1.0, 0.6)}[kind]
    damp = 1.0 - 0.75 * float(min(max(damping, 0.0), 1.0))
    late = (low * np.exp(-t / (tau * profile[0])) + mid * np.exp(-t / (tau * profile[1])) + high * np.exp(-t / (tau * profile[2] * damp)))
    # Late field builds up over the first milliseconds (diffusion), plates are instantaneous.
    build = 0.004 if kind == 'plate' else 0.02 + 0.06 * float(size)
    late *= np.minimum(1.0, t / max(build, 1e-3))
    if kind == 'spring':
        late *= (1.0 + 0.6 * np.sin(2.0 * np.pi * (12.0 + 30.0 * t) * t))    # chirpy "boing"
    # Early reflections: sparse impulses whose spacing grows with the room size.
    early = np.zeros((2, length))
    count = 6 if kind == 'plate' else 14
    spacing = 0.004 + 0.02 * float(size)
    for index in range(count):
        at = int((0.002 + spacing * (index + 1) * (0.7 + 0.6 * rng.random())) * sr)
        if at >= length:
            break
        gain = 0.7 * (0.85 ** index)
        early[0, at] += gain * (1.0 if index % 2 == 0 else 0.8)
        early[1, min(length - 1, at + int(0.0004 * sr * rng.random()))] += gain * (0.8 if index % 2 == 0 else 1.0)
    ir = late * 0.22 + early
    pre = int(float(predelay_ms) * 1e-3 * sr)
    if pre > 0:
        ir = np.concatenate([np.zeros((2, pre)), ir], axis=1)
    if low_cut_hz > 20.0:
        ir = signal.sosfilt(signal.butter(2, min(low_cut_hz, sr * 0.45), 'highpass', fs=sr, output='sos'), ir, axis=-1)
    if high_cut_hz < sr * 0.45:
        ir = signal.sosfilt(signal.butter(2, max(high_cut_hz, 100.0), 'lowpass', fs=sr, output='sos'), ir, axis=-1)
    # Stereo width by mid/side scaling.
    mid_ir, side_ir = 0.5 * (ir[0] + ir[1]), 0.5 * (ir[0] - ir[1]) * float(width)
    ir = np.stack([mid_ir + side_ir, mid_ir - side_ir])
    peak = float(np.max(np.abs(ir))) or 1.0
    return (ir / peak * 0.5).astype(np.float32)


class IRReverb(P.Processor):
    """Convolution with a synthesised impulse response (parameters rebuild the response)."""

    IR_KEYS = ('type', 'decay_seconds', 'predelay_ms', 'size', 'damping', 'low_cut_hz', 'high_cut_hz', 'width')

    def configure(self, p):
        signature = tuple(p[k] for k in self.IR_KEYS)
        if getattr(self, 'signature', None) != signature:
            self.impulse = synth_impulse(p['type'], p['decay_seconds'], p['predelay_ms'], p['size'], p['damping'],
                                         p['low_cut_hz'], p['high_cut_hz'], p['width'], self.sr)
            self.plugin = _pb().Convolution(self.impulse, mix=1.0, sample_rate=float(self.sr))
            self.signature = signature
        self.wet_gain = P.db_to_gain(p['wet_db'])

    def envelope(self, points=200):
        """Decay envelope of the impulse in dB for the interface (times, levels)."""
        ir = self.impulse
        edges = np.linspace(0, ir.shape[1], points + 1).astype(int)
        levels = [P.gain_to_db(np.sqrt(np.mean(ir[:, a:b] ** 2)) if b > a else 0.0) for a, b in zip(edges[:-1], edges[1:])]
        return edges[:-1] / float(self.sr), np.asarray(levels)

    def reset(self):
        try:
            self.plugin.reset()
        except Exception:
            pass

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.ascontiguousarray(block, dtype=np.float32))
        wet = np.asarray(self.plugin(stereo, float(self.sr), reset=False), dtype=np.float32) * self.wet_gain
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class FileConvolution(P.Processor):
    """Convolution reverb from an impulse response file (real-time)."""

    def configure(self, p):
        path = str(p.get('impulse_response') or '')
        if getattr(self, 'path', None) != path:
            self.path = path
            self.plugin = _pb().Convolution(path, mix=1.0) if path else None

    def reset(self):
        if self.plugin is not None:
            try:
                self.plugin.reset()
            except Exception:
                pass

    def process(self, block, sidechain=None):
        if self.plugin is None:
            return block
        wet = np.asarray(self.plugin(np.ascontiguousarray(block, dtype=np.float32), float(self.sr), reset=False), dtype=np.float32)
        if wet.shape != block.shape:
            wet = P.match_channels(wet, block.shape[0])[:, :block.shape[1]]
        return P.mix_dry_wet(block, wet, self.params['mix']).astype(np.float32)


class Haas(P.Processor):
    """Delays one channel by a few milliseconds: wide stereo from a mono source."""

    def configure(self, p):
        self.delay_frames = max(1, int(round(float(p['delay_ms']) * 1e-3 * self.sr)))
        if not hasattr(self, 'line'):
            self.line = P.DelayLine(1, int(self.sr * 0.1) + 8192)

    def reset(self):
        self.line.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        channel = 1 if p['side'] == 'right' else 0
        source = stereo[channel:channel + 1]
        self.line.push(source)
        delayed = self.line.read(self.delay_frames + source.shape[1], source.shape[1])[0]
        out = stereo.copy()
        out[channel] = delayed * P.db_to_gain(p['level_db'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


# ----------------------------------------------------------------------------- registrations

register(EffectSpec('pingpong_delay', 'Ping-pong delay', 'Space',
    [Param('delay_ms', 'Delay', 'float', 350.0, 5.0, 5000.0, 'ms'),
     Param('feedback', 'Feedback', 'float', 0.45, 0.0, 0.98),
     Param('ping_pong', 'Ping-pong', 'float', 1.0, 0.0, 1.0, help='0 = plain stereo delay, 1 = echoes alternate left/right'),
     Param('tone_hz', 'Feedback tone', 'float', 5000.0, 200.0, 20000.0, 'Hz'),
     Param('mix', 'Mix', 'float', 0.4, 0.0, 1.0)],
    processor=PingPongDelay, ui='delay', help='Use tail rendering so the echoes are not cut.'))

_taps = [Param('delay_ms', 'Base delay', 'float', 250.0, 5.0, 2000.0, 'ms'), Param('mix', 'Mix', 'float', 0.5, 0.0, 1.0)]
for _n, (_time, _gain, _pan) in enumerate([(1.0, -3.0, -0.6), (2.0, -6.0, 0.6), (3.0, -10.0, -0.3), (4.0, -14.0, 0.3)], start=1):
    _taps += [Param(f'tap{_n}_on', f'Tap {_n}', 'bool', _n <= 3),
              Param(f'tap{_n}_time', f'Tap {_n} time', 'float', _time, 0.1, 8.0, 'x', help='multiple of the base delay'),
              Param(f'tap{_n}_gain_db', f'Tap {_n} level', 'float', _gain, -60.0, 6.0, 'dB'),
              Param(f'tap{_n}_pan', f'Tap {_n} pan', 'float', _pan, -1.0, 1.0)]
register(EffectSpec('multitap_delay', 'Multi-tap delay', 'Space', _taps, processor=MultiTapDelay, ui='delay'))

register(EffectSpec('ir_reverb', 'Reverb (hall / plate / room)', 'Space',
    [Param('type', 'Type', 'enum', 'hall', choices=REVERB_TYPES, automatable=False),
     Param('decay_seconds', 'Decay (RT60)', 'float', 2.2, 0.1, 15.0, 's', automatable=False),
     Param('predelay_ms', 'Pre-delay', 'float', 15.0, 0.0, 250.0, 'ms', automatable=False),
     Param('size', 'Size', 'float', 0.6, 0.0, 1.0, automatable=False),
     Param('damping', 'Damping', 'float', 0.5, 0.0, 1.0, help='high frequencies decay faster', automatable=False),
     Param('low_cut_hz', 'Low cut', 'float', 80.0, 20.0, 1000.0, 'Hz', automatable=False),
     Param('high_cut_hz', 'High cut', 'float', 12000.0, 1000.0, 20000.0, 'Hz', automatable=False),
     Param('width', 'Width', 'float', 1.0, 0.0, 1.5, automatable=False),
     Param('wet_db', 'Wet level', 'float', 0.0, -24.0, 12.0, 'dB'),
     Param('mix', 'Mix', 'float', 0.3, 0.0, 1.0)],
    processor=IRReverb, ui='reverb', help='Convolution with a response synthesised from the parameters; the tail is rendered in full.'))

register(EffectSpec('haas', 'Haas widener', 'Stereo',
    [Param('delay_ms', 'Delay', 'float', 12.0, 1.0, 40.0, 'ms'),
     Param('side', 'Delayed side', 'enum', 'right', choices=('left', 'right')),
     Param('level_db', 'Delayed level', 'float', 0.0, -24.0, 0.0, 'dB')],
    processor=Haas, ui='stereo'))

# The file convolution becomes real-time capable; the JUCE reverb and delay get their interfaces.
_conv = REGISTRY['convolution']
_conv.processor = FileConvolution
_conv.apply = None
_conv.ui = 'reverb'
_conv.params[0].automatable = False
REGISTRY['reverb'].ui = 'reverb'
REGISTRY['delay'].ui = 'delay'
