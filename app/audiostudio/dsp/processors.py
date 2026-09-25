"""Block processors: the real-time engine behind track inserts, the master bus and offline renders.

A ``Processor`` is built for a sample rate, receives ``(channels, frames)`` float32 blocks in
order and keeps its state between blocks, so the same code renders the editor in real time
(``gui/player.py`` through ``editor/renderer.py``) and offline (``Document.mixdown`` and
``apply_effect``). Parameters change live with ``set_params`` without resetting the state,
which is what makes automation and knob moves click-free.

Everything here is vectorised numpy/scipy: envelope followers use the "peak hold with
exponential release" identity (a cumulative maximum on a rescaled signal), filters are
second-order sections with carried state, and feedback delay lines process sub-blocks no
longer than their shortest delay. Meters exposed in ``Processor.meters`` are what the
interfaces display (gain reduction, band levels...).
"""
import math

import numpy as np
from scipy import signal

SUB_BLOCK = 2048          # longest run of the release recursion (keeps the rescaling finite)
OFFLINE_BLOCK = 4096      # block size of process_all
EPS = 1e-9


def db_to_gain(db):
    return float(10.0 ** (float(db) / 20.0))


def gain_to_db(value):
    return 20.0 * np.log10(np.maximum(value, EPS))


def time_coef(ms, samplerate):
    """One-pole coefficient for a time constant in milliseconds (0 -> instantaneous)."""
    seconds = max(0.0, float(ms)) * 1e-3
    if seconds <= 0.0:
        return 0.0
    return float(math.exp(-1.0 / (seconds * float(samplerate))))


class Processor:
    """Base class. Subclasses override ``configure`` (coefficients) and ``process``."""

    latency_frames = 0

    def __init__(self, params, samplerate, channels=2):
        self.sr = int(samplerate)
        self.channels = int(channels)
        self.params = dict(params)
        self.meters = {}
        self.configure(self.params)

    def configure(self, params):
        pass

    def set_params(self, params):
        """Update the parameters that changed; the state is preserved."""
        changed = False
        for key, value in params.items():
            if self.params.get(key) != value:
                self.params[key] = value
                changed = True
        if changed:
            self.configure(self.params)
        return changed

    def reset(self):
        pass

    def process(self, block, sidechain=None):
        return block

    def process_all(self, audio):
        """Offline: reset, then render the whole buffer as one block."""
        self.reset()
        audio = np.ascontiguousarray(np.asarray(audio, dtype=np.float32))
        if audio.ndim == 1:
            audio = audio[np.newaxis, :]
        if audio.shape[1] == 0:
            return audio
        # Same block size as the real-time path so offline and live renders match.
        parts = [np.asarray(self.process(audio[:, start:start + OFFLINE_BLOCK]), dtype=np.float32) for start in range(0, audio.shape[1], OFFLINE_BLOCK)]
        return np.ascontiguousarray(np.concatenate(parts, axis=1))


# ----------------------------------------------------------------------------- envelope followers

def release_hold(detector, previous, coef):
    """env[n] = max(d[n], coef * env[n-1]) for a whole block, without a Python loop.

    Rescaling by coef**-n turns the recursion into a cumulative maximum; the block is cut in
    SUB_BLOCK runs so the rescaling stays representable in float64.
    """
    if coef <= 0.0:
        return detector.astype(np.float64), float(detector[-1]) if detector.size else previous
    out = np.empty(detector.shape[0], np.float64)
    for start in range(0, detector.shape[0], SUB_BLOCK):
        part = detector[start:start + SUB_BLOCK].astype(np.float64)
        n = np.arange(1, part.shape[0] + 1, dtype=np.float64)
        scale = coef ** n                       # coef^n, n = 1..len
        rescaled = part / scale
        rescaled = np.maximum.accumulate(np.concatenate(([previous], rescaled)))[1:]
        env = rescaled * scale
        out[start:start + part.shape[0]] = env
        previous = float(env[-1])
    return out, previous


class EnvelopeFollower:
    """Peak (or RMS) detector with attack and release times, one value per frame."""

    def __init__(self, samplerate, attack_ms=5.0, release_ms=100.0, mode='peak'):
        self.sr = int(samplerate)
        self.set(attack_ms, release_ms, mode)
        self.reset()

    def set(self, attack_ms, release_ms, mode='peak'):
        self.attack = time_coef(attack_ms, self.sr)
        self.release = time_coef(max(1.0, release_ms), self.sr)
        self.mode = mode
        self.rms_coef = time_coef(10.0, self.sr)

    def reset(self):
        self.hold = 0.0
        self.smooth = np.zeros(1)
        self.rms_state = np.zeros(1)

    def run(self, detector):
        """detector: 1-D non-negative signal (already rectified / linked)."""
        detector = np.asarray(detector, dtype=np.float64)
        if self.mode == 'rms':
            squared, self.rms_state = signal.lfilter([1.0 - self.rms_coef], [1.0, -self.rms_coef], detector ** 2, zi=self.rms_state)
            detector = np.sqrt(np.maximum(squared, 0.0))
        env, self.hold = release_hold(detector, self.hold, self.release)
        if self.attack > 0.0:
            env, self.smooth = signal.lfilter([1.0 - self.attack], [1.0, -self.attack], env, zi=self.smooth)
        return env


def linked_detector(block):
    """Stereo-linked rectified detector signal: the loudest channel per frame."""
    return np.max(np.abs(block), axis=0) if block.shape[0] > 1 else np.abs(block[0])


def gain_computer(level_db, threshold_db, ratio, knee_db=0.0):
    """Static compressor curve: gain reduction in dB (<= 0) for input levels in dB."""
    level_db = np.asarray(level_db, dtype=np.float64)
    over = level_db - float(threshold_db)
    slope = 1.0 / max(1.0, float(ratio)) - 1.0
    knee = max(0.0, float(knee_db))
    if knee <= 0.0:
        return np.where(over > 0.0, slope * over, 0.0)
    half = knee / 2.0
    inside = (over > -half) & (over < half)
    result = np.where(over >= half, slope * over, 0.0)
    result = np.where(inside, slope * (over + half) ** 2 / (2.0 * knee), result)
    return result


def expander_curve(level_db, threshold_db, ratio, range_db=-80.0, knee_db=0.0):
    """Downward expander / gate: attenuation (<= 0) below the threshold, floored at range_db."""
    level_db = np.asarray(level_db, dtype=np.float64)
    under = float(threshold_db) - level_db
    slope = 1.0 - max(1.0, float(ratio))            # negative
    knee = max(0.0, float(knee_db))
    if knee <= 0.0:
        result = np.where(under > 0.0, slope * under, 0.0)
    else:
        half = knee / 2.0
        inside = (under > -half) & (under < half)
        result = np.where(under >= half, slope * under, 0.0)
        result = np.where(inside, slope * (under + half) ** 2 / (2.0 * knee), result)
    return np.maximum(result, float(range_db))


# ----------------------------------------------------------------------------- biquads

def biquad(kind, frequency, q, gain_db, samplerate):
    """RBJ cookbook second-order section (1, 6) for one band."""
    sr = float(samplerate)
    f0 = float(min(max(frequency, 1.0), sr * 0.49))
    q = float(max(0.05, q))
    w0 = 2.0 * math.pi * f0 / sr
    cos_w0, sin_w0 = math.cos(w0), math.sin(w0)
    alpha = sin_w0 / (2.0 * q)
    a = 10.0 ** (float(gain_db) / 40.0)
    if kind == 'peak':
        b0, b1, b2 = 1 + alpha * a, -2 * cos_w0, 1 - alpha * a
        a0, a1, a2 = 1 + alpha / a, -2 * cos_w0, 1 - alpha / a
    elif kind == 'low_shelf':
        sq = 2 * math.sqrt(a) * alpha
        b0 = a * ((a + 1) - (a - 1) * cos_w0 + sq)
        b1 = 2 * a * ((a - 1) - (a + 1) * cos_w0)
        b2 = a * ((a + 1) - (a - 1) * cos_w0 - sq)
        a0 = (a + 1) + (a - 1) * cos_w0 + sq
        a1 = -2 * ((a - 1) + (a + 1) * cos_w0)
        a2 = (a + 1) + (a - 1) * cos_w0 - sq
    elif kind == 'high_shelf':
        sq = 2 * math.sqrt(a) * alpha
        b0 = a * ((a + 1) + (a - 1) * cos_w0 + sq)
        b1 = -2 * a * ((a - 1) + (a + 1) * cos_w0)
        b2 = a * ((a + 1) + (a - 1) * cos_w0 - sq)
        a0 = (a + 1) - (a - 1) * cos_w0 + sq
        a1 = 2 * ((a - 1) - (a + 1) * cos_w0)
        a2 = (a + 1) - (a - 1) * cos_w0 - sq
    elif kind == 'lowpass':
        b0, b1, b2 = (1 - cos_w0) / 2, 1 - cos_w0, (1 - cos_w0) / 2
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == 'highpass':
        b0, b1, b2 = (1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == 'bandpass':
        b0, b1, b2 = alpha, 0.0, -alpha
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == 'notch':
        b0, b1, b2 = 1.0, -2 * cos_w0, 1.0
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == 'allpass':
        b0, b1, b2 = 1 - alpha, -2 * cos_w0, 1 + alpha
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    else:
        raise ValueError('Unknown biquad kind: ' + str(kind))
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)


def response_db(sos, frequencies, samplerate):
    """Magnitude response in dB of a cascade of sections at the given frequencies."""
    if sos is None or len(sos) == 0:
        return np.zeros(len(frequencies))
    w = 2.0 * np.pi * np.asarray(frequencies, dtype=np.float64) / float(samplerate)
    _, h = signal.sosfreqz(np.asarray(sos), worN=w)
    return gain_to_db(np.abs(h))


class BiquadChain:
    """A cascade of second-order sections with per-channel state that survives coefficient changes."""

    def __init__(self, sos=None):
        self.sos = None
        self.zi = None
        self.set_sos(sos)

    def set_sos(self, sos):
        sos = None if sos is None or len(sos) == 0 else np.ascontiguousarray(sos, dtype=np.float64)
        if sos is None:
            self.sos, self.zi = None, None
            return
        if self.sos is None or self.zi is None or self.sos.shape[0] != sos.shape[0]:
            self.zi = None
        self.sos = sos

    def reset(self):
        self.zi = None

    def process(self, block):
        if self.sos is None:
            return block
        block = np.asarray(block, dtype=np.float64)
        if self.zi is None or self.zi.shape[1] != block.shape[0]:
            self.zi = np.zeros((self.sos.shape[0], block.shape[0], 2))
        out, self.zi = signal.sosfilt(self.sos, block, axis=-1, zi=self.zi)
        return out


class OnePole:
    """First-order lowpass (tone controls, damping) with state per channel."""

    def __init__(self, samplerate, cutoff_hz=8000.0):
        self.sr = int(samplerate)
        self.zi = None
        self.set(cutoff_hz)

    def set(self, cutoff_hz):
        cutoff = float(min(max(cutoff_hz, 5.0), self.sr * 0.49))
        self.coef = float(math.exp(-2.0 * math.pi * cutoff / self.sr))
        self.b = [1.0 - self.coef]
        self.a = [1.0, -self.coef]

    def reset(self):
        self.zi = None

    def process(self, block):
        block = np.asarray(block, dtype=np.float64)
        if self.zi is None or self.zi.shape[0] != block.shape[0]:
            self.zi = np.zeros((block.shape[0], 1))
        out, self.zi = signal.lfilter(self.b, self.a, block, axis=-1, zi=self.zi)
        return out


class Crossover:
    """Linkwitz-Riley 4th-order crossover: ``split`` gives (low, high) that sum flat."""

    def __init__(self, samplerate, frequency):
        self.sr = int(samplerate)
        self.low = BiquadChain()
        self.high = BiquadChain()
        self.ap_low = BiquadChain()
        self.ap_high = BiquadChain()
        self.set(frequency)

    def set(self, frequency):
        f = float(min(max(frequency, 20.0), self.sr * 0.45))
        lp = signal.butter(2, f, 'lowpass', fs=self.sr, output='sos')
        hp = signal.butter(2, f, 'highpass', fs=self.sr, output='sos')
        self.low.set_sos(np.concatenate([lp, lp]))
        self.high.set_sos(np.concatenate([hp, hp]))
        self.ap_low.set_sos(np.concatenate([lp, lp]))
        self.ap_high.set_sos(np.concatenate([hp, hp]))
        self.frequency = f

    def reset(self):
        for chain in (self.low, self.high, self.ap_low, self.ap_high):
            chain.reset()

    def split(self, block):
        return self.low.process(block), self.high.process(block)

    def allpass(self, block):
        """Phase of this crossover without the split: keeps lower bands aligned with upper ones."""
        return self.ap_low.process(block) + self.ap_high.process(block)


# ----------------------------------------------------------------------------- delay lines

class DelayLine:
    """Feedback delay line(s) processed in sub-blocks no longer than the shortest delay.

    ``taps`` is a list of (delay_frames, feedback_matrix_row) definitions handled by the
    subclass through ``step``; this class only owns the circular buffer.
    """

    def __init__(self, channels, max_frames):
        self.max_frames = int(max(2, max_frames))
        self.channels = int(channels)
        self.reset()

    def reset(self):
        self.buffer = np.zeros((self.channels, self.max_frames), np.float64)
        self.write = 0

    def read(self, delay_frames, count, channel_map=None):
        """Read ``count`` frames that were written ``delay_frames`` ago (delay >= count)."""
        start = (self.write - int(delay_frames)) % self.max_frames
        index = (start + np.arange(count)) % self.max_frames
        block = self.buffer[:, index]
        if channel_map is not None:
            block = block[channel_map]
        return block

    def read_at(self, delays, count):
        """Fractional per-frame delays (array of ``count`` values, each >= count) relative to the
        frames about to be written: frame n reads what was written ``delays[n] - n`` frames before the
        write pointer, with linear interpolation."""
        n = np.arange(count)
        position = self.write + n - np.asarray(delays, dtype=np.float64)
        base = np.floor(position)
        frac = (position - base)[np.newaxis, :]
        i0 = (base.astype(np.int64)) % self.max_frames
        i1 = (i0 + 1) % self.max_frames
        return self.buffer[:, i0] * (1.0 - frac) + self.buffer[:, i1] * frac

    def push(self, block):
        count = block.shape[1]
        index = (self.write + np.arange(count)) % self.max_frames
        self.buffer[:, index] = block
        self.write = (self.write + count) % self.max_frames


class ModulatedTap:
    """Input history read at fractional, per-frame delays (no feedback): chorus voices, pitch
    shifting grains, Doppler. ``read(block, delays)`` pushes the block first, so a delay of 0 is the
    current frame; every delay must stay below ``max_frames - block length``."""

    def __init__(self, channels, max_frames):
        self.line = DelayLine(channels, max_frames)

    def reset(self):
        self.line.reset()

    def read(self, block, delays):
        count = block.shape[1]
        self.line.push(block)
        delays = np.maximum(np.asarray(delays, dtype=np.float64), 0.0)
        position = self.line.write - count + np.arange(count) - delays
        base = np.floor(position)
        frac = (position - base)[np.newaxis, :]
        i0 = base.astype(np.int64) % self.line.max_frames
        i1 = (i0 + 1) % self.line.max_frames
        return self.line.buffer[:, i0] * (1.0 - frac) + self.line.buffer[:, i1] * frac


# ----------------------------------------------------------------------------- LFO

def lfo(shape, phase):
    """Waveform in [-1, 1] for phases in cycles (float array)."""
    frac = np.mod(phase, 1.0)
    if shape == 'triangle':
        return 1.0 - 4.0 * np.abs(frac - 0.5)
    if shape == 'square':
        return np.where(frac < 0.5, 1.0, -1.0)
    if shape == 'saw':
        return 2.0 * frac - 1.0
    if shape == 'ramp_down':
        return 1.0 - 2.0 * frac
    return np.sin(2.0 * np.pi * frac)


class LFO:
    def __init__(self, samplerate, rate_hz=1.0, shape='sine'):
        self.sr = int(samplerate)
        self.phase = 0.0
        self.set(rate_hz, shape)

    def set(self, rate_hz, shape='sine'):
        self.rate = float(max(0.0, rate_hz))
        self.shape = shape

    def reset(self):
        self.phase = 0.0

    def phases(self, count):
        """Phase (in cycles) of every frame of the next block; advances the oscillator."""
        phases = self.phase + np.arange(count) * (self.rate / self.sr)
        self.phase = float(np.mod(self.phase + count * self.rate / self.sr, 1.0))
        return phases

    def block(self, count, phase_offset=0.0):
        return lfo(self.shape, self.phases(count) + phase_offset)


# ----------------------------------------------------------------------------- pedalboard wrapper

class PedalboardProcessor(Processor):
    """Wraps a pedalboard plugin built by an EffectSpec; parameters are updated in place."""

    def __init__(self, spec, params, samplerate, channels=2):
        self.spec = spec
        self.plugin = None
        self.fifo = None
        self.latency_frames = 0
        super().__init__(params, samplerate, channels)

    def configure(self, params):
        if self.plugin is None:
            self.plugin = self.spec.build(params)
            self._applied = dict(params)
            return
        if self.spec.update is not None:
            try:
                self.spec.update(self.plugin, params)
                self._applied = dict(params)
                return
            except Exception:
                pass
        for key, value in params.items():
            if self._applied.get(key) == value:
                continue
            attr = self.spec.attrs.get(key, key)
            try:
                setattr(self.plugin, attr, value)
                self._applied[key] = value
            except Exception:
                # A parameter that cannot change live: rebuild (state is lost for this plugin only).
                self.plugin = self.spec.build(params)
                self._applied = dict(params)
                return

    def reset(self):
        self.fifo = None
        self.latency_frames = 0
        try:
            self.plugin.reset()
        except Exception:
            self.plugin = self.spec.build(self.params)
            self._applied = dict(self.params)

    def _run(self, block):
        out = self.plugin(np.ascontiguousarray(block, dtype=np.float32), float(self.sr), reset=False)
        out = np.asarray(out, dtype=np.float32)
        return out[np.newaxis, :] if out.ndim == 1 else out

    def process(self, block, sidechain=None):
        """Streams through a FIFO: a plugin with latency (pitch shift, codecs) withholds frames at
        the start; zeros are played meanwhile and the audio arrives ``latency_frames`` later."""
        out = self._run(block)
        n = block.shape[1]
        if out.shape[1] == n and self.fifo is None:
            return out
        self.fifo = out if self.fifo is None else np.concatenate([self.fifo, out], axis=1)
        available = self.fifo.shape[1]
        if available >= n:
            result, self.fifo = self.fifo[:, :n], np.ascontiguousarray(self.fifo[:, n:])
        else:
            missing = n - available
            self.latency_frames += missing
            result = np.concatenate([np.zeros((self.fifo.shape[0], missing), np.float32), self.fifo], axis=1)
            self.fifo = np.zeros((self.fifo.shape[0], 0), np.float32)
        return np.ascontiguousarray(result)

    def process_all(self, audio):
        """Offline: pedalboard already compensates the latency; flush the withheld tail with silence."""
        self.reset()
        audio = np.ascontiguousarray(np.asarray(audio, dtype=np.float32))
        if audio.ndim == 1:
            audio = audio[np.newaxis, :]
        total = audio.shape[1]
        if total == 0:
            return audio
        parts = [self._run(audio[:, start:start + OFFLINE_BLOCK]) for start in range(0, total, OFFLINE_BLOCK)]
        got = sum(p.shape[1] for p in parts)
        silence = np.zeros((audio.shape[0], OFFLINE_BLOCK), np.float32)
        rounds = 0
        while got < total and rounds < 4096:
            part = self._run(silence)
            parts.append(part)
            got += part.shape[1]
            rounds += 1
        out = np.concatenate(parts, axis=1)[:, :total]
        if out.shape[1] < total:
            out = np.concatenate([out, np.zeros((out.shape[0], total - out.shape[1]), np.float32)], axis=1)
        return np.ascontiguousarray(out)


class VST3Processor(PedalboardProcessor):
    """A loaded VST3 instance (pedalboard ExternalPlugin) as an insert; state and parameters are
    applied through vst.host so a node saved by the Workflows tab loads identically."""

    def __init__(self, plugin, params, samplerate, channels=2, state=''):
        self.plugin = plugin
        self.fifo = None
        self.latency_frames = 0
        self._applied = {}
        Processor.__init__(self, params, samplerate, channels)
        if state:
            self.restore_state(state)

    def configure(self, params):
        from ..vst import host
        changed = {key: value for key, value in params.items() if self._applied.get(key) != value}
        if changed:
            host.apply_settings(self.plugin, changed)
            self._applied.update(changed)

    def restore_state(self, state):
        from ..vst import host
        host.apply_settings(self.plugin, None, state)
        self._applied = {}
        self.configure(self.params)

    def capture(self):
        from ..vst import host
        return host.capture(self.plugin)

    def reset(self):
        self.fifo = None
        self.latency_frames = 0
        try:
            self.plugin.reset()
        except Exception:
            pass


# ----------------------------------------------------------------------------- shared helpers for subclasses

def as_stereo(block):
    if block.shape[0] == 1:
        return np.repeat(block, 2, axis=0)
    return block[:2]


def match_channels(block, channels):
    if block.shape[0] == channels:
        return block
    if channels == 1:
        return np.mean(block, axis=0, keepdims=True)
    if block.shape[0] == 1:
        return np.repeat(block, channels, axis=0)
    return block[:channels]


def mix_dry_wet(dry, wet, mix):
    mix = float(min(1.0, max(0.0, mix)))
    if mix >= 1.0:
        return wet
    if mix <= 0.0:
        return dry
    return dry * (1.0 - mix) + wet * mix
