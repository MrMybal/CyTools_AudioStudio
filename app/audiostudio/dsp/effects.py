"""Registry of native effects.

Every effect declares typed parameters and either builds a stateful pedalboard plugin
(``build``) or applies a whole-buffer numpy transform (``apply``). Stateful plugins are
what makes tail rendering meaningful (reverb, delay, compressor release...).

Buffers are float32 (channels, frames).
"""
from dataclasses import dataclass, field
import math
import numpy as np


@dataclass
class Param:
    id: str
    label: str
    kind: str = 'float'          # float | int | bool | enum
    default: object = 0.0
    minimum: object = None
    maximum: object = None
    unit: str = ''
    step: object = None
    choices: tuple = ()
    help: str = ''
    automatable: bool = True     # False for parameters whose change rebuilds a heavy state (impulse responses)

    def schema(self):
        if self.kind == 'bool':
            spec = {'type': 'boolean', 'default': bool(self.default)}
        elif self.kind == 'string':
            spec = {'type': 'string', 'default': str(self.default or ''), 'maxLength': 1024}
        elif self.kind == 'enum':
            spec = {'enum': list(self.choices), 'default': self.default}
        else:
            spec = {'type': 'integer' if self.kind == 'int' else 'number', 'default': self.default}
            if self.minimum is not None: spec['minimum'] = self.minimum
            if self.maximum is not None: spec['maximum'] = self.maximum
        text = self.label + (f' ({self.unit})' if self.unit else '')
        spec['description'] = (text + '. ' + self.help).strip()
        return spec

    def coerce(self, value):
        if value is None:
            return self.default
        if self.kind == 'bool':
            return bool(value)
        if self.kind == 'string':
            return str(value)[:1024]
        if self.kind == 'enum':
            return value if value in self.choices else self.default
        if self.kind == 'int':
            value = int(round(float(value)))
        else:
            value = float(value)
            if not math.isfinite(value):
                value = self.default
        if self.minimum is not None: value = max(self.minimum, value)
        if self.maximum is not None: value = min(self.maximum, value)
        return value


@dataclass
class EffectSpec:
    id: str
    name: str
    category: str
    params: list = field(default_factory=list)
    build: object = None       # (params) -> pedalboard.Plugin
    apply: object = None       # (audio, sr, params) -> audio
    help: str = ''
    changes_length: bool = False
    processor: object = None   # (params, samplerate) -> processors.Processor (block-wise, real-time capable)
    ui: str = ''               # interface family drawn by gui/effect_ui.py ('' = generic)
    attrs: dict = field(default_factory=dict)   # param id -> pedalboard attribute name when they differ
    update: object = None      # (plugin, params) -> None: live parameter update of a pedalboard plugin
    sidechain: bool = False    # accepts a side-chain input (another track)

    @property
    def stateful(self):
        """Keeps state between blocks: tails are meaningful, tail rendering applies."""
        return self.build is not None or self.processor is not None

    @property
    def realtime(self):
        """Can run block by block in a track insert (whole-buffer effects cannot)."""
        return self.apply is None or self.processor is not None

    def defaults(self):
        return {p.id: p.default for p in self.params}

    def normalize(self, values):
        values = values or {}
        return {p.id: p.coerce(values.get(p.id)) for p in self.params}

    def describe(self):
        return {'id': self.id, 'name': self.name, 'category': self.category, 'help': self.help,
                'stateful': self.stateful, 'realtime': self.realtime, 'changesLength': self.changes_length, 'ui': self.ui, 'sidechain': self.sidechain,
                'parameters': {p.id: p.schema() for p in self.params}}


REGISTRY = {}


def register(spec):
    REGISTRY[spec.id] = spec
    return spec


def get(effect_id):
    spec = REGISTRY.get(effect_id)
    if spec is None:
        raise KeyError('Unknown effect: ' + str(effect_id))
    return spec


def catalogue():
    return [spec.describe() for spec in REGISTRY.values()]


# ----------------------------------------------------------------------------- helpers

def _db_to_gain(db):
    return float(10.0 ** (float(db) / 20.0))


def _fade_curve(n, shape):
    t = np.linspace(0.0, 1.0, n, dtype=np.float32, endpoint=True)
    if shape == 'logarithmic':
        return np.log10(1.0 + 9.0 * t).astype(np.float32)
    if shape == 'exponential':
        return (t ** 2).astype(np.float32)
    if shape == 'scurve':
        return (0.5 - 0.5 * np.cos(np.pi * t)).astype(np.float32)
    return t


# ----------------------------------------------------------------------------- pedalboard effects

def _pb():
    import pedalboard
    return pedalboard


register(EffectSpec('gain', 'Gain', 'Dynamics',
    [Param('gain_db', 'Gain', 'float', 0.0, -60.0, 24.0, 'dB')],
    build=lambda p: _pb().Gain(gain_db=p['gain_db']), help='Adjust level in decibels.'))

register(EffectSpec('compressor', 'Compressor', 'Dynamics',
    [Param('threshold_db', 'Threshold', 'float', -12.0, -60.0, 0.0, 'dB'),
     Param('ratio', 'Ratio', 'float', 4.0, 1.0, 30.0, ':1'),
     Param('attack_ms', 'Attack', 'float', 5.0, 0.1, 500.0, 'ms'),
     Param('release_ms', 'Release', 'float', 100.0, 5.0, 5000.0, 'ms')],
    build=lambda p: _pb().Compressor(threshold_db=p['threshold_db'], ratio=p['ratio'], attack_ms=p['attack_ms'], release_ms=p['release_ms'])))

register(EffectSpec('limiter', 'Limiter', 'Dynamics',
    [Param('threshold_db', 'Threshold', 'float', -1.0, -30.0, 0.0, 'dB'),
     Param('release_ms', 'Release', 'float', 100.0, 5.0, 2000.0, 'ms')],
    build=lambda p: _pb().Limiter(threshold_db=p['threshold_db'], release_ms=p['release_ms'])))

register(EffectSpec('noise_gate', 'Noise gate', 'Dynamics',
    [Param('threshold_db', 'Threshold', 'float', -60.0, -100.0, 0.0, 'dB'),
     Param('ratio', 'Ratio', 'float', 10.0, 1.0, 100.0, ':1'),
     Param('attack_ms', 'Attack', 'float', 1.0, 0.1, 500.0, 'ms'),
     Param('release_ms', 'Release', 'float', 100.0, 5.0, 5000.0, 'ms')],
    build=lambda p: _pb().NoiseGate(threshold_db=p['threshold_db'], ratio=p['ratio'], attack_ms=p['attack_ms'], release_ms=p['release_ms'])))

register(EffectSpec('clipping', 'Clipping', 'Distortion',
    [Param('threshold_db', 'Threshold', 'float', -6.0, -40.0, 0.0, 'dB')],
    build=lambda p: _pb().Clipping(threshold_db=p['threshold_db'])))

register(EffectSpec('distortion', 'Distortion', 'Distortion',
    [Param('drive_db', 'Drive', 'float', 25.0, 0.0, 60.0, 'dB')],
    build=lambda p: _pb().Distortion(drive_db=p['drive_db'])))

register(EffectSpec('bitcrush', 'Bitcrush', 'Distortion',
    [Param('bit_depth', 'Bit depth', 'float', 8.0, 1.0, 32.0, 'bits')],
    build=lambda p: _pb().Bitcrush(bit_depth=p['bit_depth'])))

register(EffectSpec('highpass', 'High-pass filter', 'EQ',
    [Param('cutoff_hz', 'Cutoff', 'float', 80.0, 10.0, 20000.0, 'Hz')],
    build=lambda p: _pb().HighpassFilter(cutoff_frequency_hz=p['cutoff_hz'])))

register(EffectSpec('lowpass', 'Low-pass filter', 'EQ',
    [Param('cutoff_hz', 'Cutoff', 'float', 8000.0, 10.0, 20000.0, 'Hz')],
    build=lambda p: _pb().LowpassFilter(cutoff_frequency_hz=p['cutoff_hz'])))

register(EffectSpec('peak_eq', 'Peak EQ', 'EQ',
    [Param('frequency_hz', 'Frequency', 'float', 1000.0, 10.0, 20000.0, 'Hz'),
     Param('gain_db', 'Gain', 'float', 0.0, -30.0, 30.0, 'dB'),
     Param('q', 'Q', 'float', 0.707, 0.05, 20.0)],
    build=lambda p: _pb().PeakFilter(cutoff_frequency_hz=p['frequency_hz'], gain_db=p['gain_db'], q=p['q'])))

register(EffectSpec('low_shelf', 'Low shelf', 'EQ',
    [Param('frequency_hz', 'Frequency', 'float', 200.0, 10.0, 20000.0, 'Hz'),
     Param('gain_db', 'Gain', 'float', 0.0, -30.0, 30.0, 'dB'),
     Param('q', 'Q', 'float', 0.707, 0.05, 20.0)],
    build=lambda p: _pb().LowShelfFilter(cutoff_frequency_hz=p['frequency_hz'], gain_db=p['gain_db'], q=p['q'])))

register(EffectSpec('high_shelf', 'High shelf', 'EQ',
    [Param('frequency_hz', 'Frequency', 'float', 4000.0, 10.0, 20000.0, 'Hz'),
     Param('gain_db', 'Gain', 'float', 0.0, -30.0, 30.0, 'dB'),
     Param('q', 'Q', 'float', 0.707, 0.05, 20.0)],
    build=lambda p: _pb().HighShelfFilter(cutoff_frequency_hz=p['frequency_hz'], gain_db=p['gain_db'], q=p['q'])))

register(EffectSpec('ladder_filter', 'Ladder filter', 'EQ',
    [Param('mode', 'Mode', 'enum', 'LPF12', choices=('LPF12', 'HPF12', 'BPF12', 'LPF24', 'HPF24', 'BPF24')),
     Param('cutoff_hz', 'Cutoff', 'float', 1000.0, 10.0, 20000.0, 'Hz'),
     Param('resonance', 'Resonance', 'float', 0.0, 0.0, 1.0),
     Param('drive', 'Drive', 'float', 1.0, 1.0, 20.0)],
    build=lambda p: _pb().LadderFilter(mode=getattr(_pb().LadderFilter.Mode, p['mode']), cutoff_hz=p['cutoff_hz'], resonance=p['resonance'], drive=p['drive'])))

register(EffectSpec('reverb', 'Reverb', 'Space',
    [Param('room_size', 'Room size', 'float', 0.5, 0.0, 1.0),
     Param('damping', 'Damping', 'float', 0.5, 0.0, 1.0),
     Param('wet_level', 'Wet', 'float', 0.33, 0.0, 1.0),
     Param('dry_level', 'Dry', 'float', 0.4, 0.0, 1.0),
     Param('width', 'Width', 'float', 1.0, 0.0, 1.0),
     Param('freeze_mode', 'Freeze', 'float', 0.0, 0.0, 1.0)],
    build=lambda p: _pb().Reverb(room_size=p['room_size'], damping=p['damping'], wet_level=p['wet_level'], dry_level=p['dry_level'], width=p['width'], freeze_mode=p['freeze_mode']),
    help='Algorithmic reverb. Use tail rendering so the decay is not cut.'))

register(EffectSpec('delay', 'Delay', 'Space',
    [Param('delay_seconds', 'Delay', 'float', 0.35, 0.001, 10.0, 's'),
     Param('feedback', 'Feedback', 'float', 0.35, 0.0, 0.99),
     Param('mix', 'Mix', 'float', 0.4, 0.0, 1.0)],
    build=lambda p: _pb().Delay(delay_seconds=p['delay_seconds'], feedback=p['feedback'], mix=p['mix']),
    help='Echo. Use tail rendering so the repeats are not cut.'))

register(EffectSpec('chorus', 'Chorus', 'Modulation',
    [Param('rate_hz', 'Rate', 'float', 1.0, 0.01, 20.0, 'Hz'),
     Param('depth', 'Depth', 'float', 0.25, 0.0, 1.0),
     Param('centre_delay_ms', 'Centre delay', 'float', 7.0, 1.0, 100.0, 'ms'),
     Param('feedback', 'Feedback', 'float', 0.0, -0.95, 0.95),
     Param('mix', 'Mix', 'float', 0.5, 0.0, 1.0)],
    build=lambda p: _pb().Chorus(rate_hz=p['rate_hz'], depth=p['depth'], centre_delay_ms=p['centre_delay_ms'], feedback=p['feedback'], mix=p['mix'])))

register(EffectSpec('phaser', 'Phaser', 'Modulation',
    [Param('rate_hz', 'Rate', 'float', 1.0, 0.01, 20.0, 'Hz'),
     Param('depth', 'Depth', 'float', 0.5, 0.0, 1.0),
     Param('centre_frequency_hz', 'Centre frequency', 'float', 1300.0, 20.0, 20000.0, 'Hz'),
     Param('feedback', 'Feedback', 'float', 0.0, -0.95, 0.95),
     Param('mix', 'Mix', 'float', 0.5, 0.0, 1.0)],
    build=lambda p: _pb().Phaser(rate_hz=p['rate_hz'], depth=p['depth'], centre_frequency_hz=p['centre_frequency_hz'], feedback=p['feedback'], mix=p['mix'])))

register(EffectSpec('pitch_shift', 'Pitch shift', 'Pitch & time',
    [Param('semitones', 'Semitones', 'float', 0.0, -72.0, 72.0, 'st')],
    apply=lambda a, sr, p: np.ascontiguousarray(_pb().PitchShift(semitones=p['semitones'])(a, float(sr)).astype(np.float32)),
    help='Whole-buffer pitch shift (Rubber Band): the streaming mode of this plugin produces no output, so it is not available as a track insert.'))

register(EffectSpec('gsm_codec', 'GSM codec (lo-fi)', 'Lo-fi',
    [], build=lambda p: _pb().GSMFullRateCompressor()))

register(EffectSpec('mp3_codec', 'MP3 codec (lo-fi)', 'Lo-fi',
    [Param('vbr_quality', 'VBR quality', 'float', 2.0, 0.0, 9.999)],
    build=lambda p: _pb().MP3Compressor(vbr_quality=p['vbr_quality'])))

register(EffectSpec('invert', 'Invert polarity', 'Utility', [], build=lambda p: _pb().Invert()))


# ----------------------------------------------------------------------------- numpy effects

def _normalize_peak(audio, sr, p):
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 0.0:
        return audio
    return (audio * (_db_to_gain(p['target_db']) / peak)).astype(np.float32)

register(EffectSpec('normalize', 'Normalize (peak)', 'Dynamics',
    [Param('target_db', 'Target peak', 'float', -1.0, -60.0, 0.0, 'dBFS')], apply=_normalize_peak))


def _normalize_loudness(audio, sr, p):
    import pyloudnorm
    meter = pyloudnorm.Meter(int(sr))
    frames = audio.T.astype(np.float64)
    if frames.shape[0] < int(sr * 0.4):
        # pyloudnorm needs at least one 400 ms block; pad with silence for the measurement only.
        pad = np.zeros((int(sr * 0.4) - frames.shape[0] + 1, frames.shape[1]))
        measured = meter.integrated_loudness(np.concatenate([frames, pad], axis=0))
    else:
        measured = meter.integrated_loudness(frames)
    if not np.isfinite(measured):
        return audio
    gain = _db_to_gain(p['target_lufs'] - measured)
    result = (audio * gain).astype(np.float32)
    if p['true_peak_limit']:
        ceiling = _db_to_gain(p['ceiling_db'])
        peak = float(np.max(np.abs(result))) if result.size else 0.0
        if peak > ceiling:
            result = _pb().Limiter(threshold_db=p['ceiling_db'], release_ms=50.0)(result, float(sr))
    return result

register(EffectSpec('loudness', 'Normalize (LUFS)', 'Dynamics',
    [Param('target_lufs', 'Target loudness', 'float', -14.0, -40.0, -5.0, 'LUFS', help='-14 streaming, -16 podcast, -23 broadcast'),
     Param('true_peak_limit', 'Limit peaks', 'bool', True),
     Param('ceiling_db', 'Peak ceiling', 'float', -1.0, -6.0, 0.0, 'dBFS')],
    apply=_normalize_loudness, help='Integrated loudness normalization (ITU-R BS.1770).'))


def _fade(audio, sr, p, direction):
    n = min(audio.shape[1], max(0, int(round(p['duration_seconds'] * sr))))
    if n <= 1:
        return audio
    curve = _fade_curve(n, p['shape'])
    result = audio.copy()
    if direction == 'in':
        result[:, :n] *= curve
    else:
        result[:, -n:] *= curve[::-1]
    return result

register(EffectSpec('fade_in', 'Fade in', 'Envelope',
    [Param('duration_seconds', 'Duration', 'float', 1.0, 0.0, 600.0, 's'),
     Param('shape', 'Shape', 'enum', 'linear', choices=('linear', 'logarithmic', 'exponential', 'scurve'))],
    apply=lambda a, sr, p: _fade(a, sr, p, 'in')))

register(EffectSpec('fade_out', 'Fade out', 'Envelope',
    [Param('duration_seconds', 'Duration', 'float', 1.0, 0.0, 600.0, 's'),
     Param('shape', 'Shape', 'enum', 'linear', choices=('linear', 'logarithmic', 'exponential', 'scurve'))],
    apply=lambda a, sr, p: _fade(a, sr, p, 'out')))

register(EffectSpec('reverse', 'Reverse', 'Utility', [], apply=lambda a, sr, p: np.ascontiguousarray(a[:, ::-1])))

register(EffectSpec('silence', 'Silence', 'Utility', [], apply=lambda a, sr, p: np.zeros_like(a)))


def _dc_offset(audio, sr, p):
    return (audio - np.mean(audio, axis=1, keepdims=True)).astype(np.float32)

register(EffectSpec('dc_offset', 'Remove DC offset', 'Utility', [], apply=_dc_offset))


def _stereo_width(audio, sr, p):
    if audio.shape[0] != 2:
        return audio
    mid = 0.5 * (audio[0] + audio[1])
    side = 0.5 * (audio[0] - audio[1]) * float(p['width'])
    return np.ascontiguousarray(np.stack([mid + side, mid - side]).astype(np.float32))

register(EffectSpec('stereo_width', 'Stereo width', 'Stereo',
    [Param('width', 'Width', 'float', 1.0, 0.0, 3.0, help='0 = mono, 1 = unchanged, >1 wider')], apply=_stereo_width))


def _pan(audio, sr, p):
    if audio.shape[0] != 2:
        return audio
    angle = (float(p['pan']) + 1.0) * 0.25 * np.pi
    left, right = float(np.cos(angle)) * np.sqrt(2.0), float(np.sin(angle)) * np.sqrt(2.0)
    return np.ascontiguousarray(np.stack([audio[0] * left, audio[1] * right]).astype(np.float32))

register(EffectSpec('pan', 'Pan', 'Stereo',
    [Param('pan', 'Pan', 'float', 0.0, -1.0, 1.0, help='-1 left, 0 centre, +1 right')], apply=_pan))


def _channels(audio, sr, p):
    mode = p['mode']
    if mode == 'mono' and audio.shape[0] > 1:
        return np.mean(audio, axis=0, keepdims=True).astype(np.float32)
    if mode == 'stereo' and audio.shape[0] == 1:
        return np.ascontiguousarray(np.repeat(audio, 2, axis=0))
    if mode == 'swap' and audio.shape[0] == 2:
        return np.ascontiguousarray(audio[::-1])
    if mode == 'left' and audio.shape[0] >= 2:
        return np.ascontiguousarray(audio[:1])
    if mode == 'right' and audio.shape[0] >= 2:
        return np.ascontiguousarray(audio[1:2])
    return audio

register(EffectSpec('channels', 'Channels', 'Stereo',
    [Param('mode', 'Mode', 'enum', 'mono', choices=('mono', 'stereo', 'swap', 'left', 'right'))], apply=_channels))


def _time_stretch(audio, sr, p):
    from pedalboard import time_stretch
    factor = float(p['stretch_factor'])
    semitones = float(p['pitch_semitones'])
    if abs(factor - 1.0) < 1e-6 and abs(semitones) < 1e-6:
        return audio
    return np.ascontiguousarray(time_stretch(audio, float(sr), stretch_factor=factor, pitch_shift_in_semitones=semitones, high_quality=bool(p['high_quality'])).astype(np.float32))

register(EffectSpec('time_stretch', 'Time stretch', 'Pitch & time',
    [Param('stretch_factor', 'Speed factor', 'float', 1.0, 0.1, 10.0, 'x', help='2.0 = twice as fast (half length)'),
     Param('pitch_semitones', 'Pitch', 'float', 0.0, -36.0, 36.0, 'st'),
     Param('high_quality', 'High quality', 'bool', True)],
    apply=_time_stretch, changes_length=True))


def _trim_silence(audio, sr, p):
    threshold = _db_to_gain(p['threshold_db'])
    envelope = np.max(np.abs(audio), axis=0)
    above = np.nonzero(envelope > threshold)[0]
    if above.size == 0:
        return audio[:, :0]
    pad = int(p['padding_ms'] * sr / 1000.0)
    start = max(0, int(above[0]) - pad) if p['start'] else 0
    end = min(audio.shape[1], int(above[-1]) + 1 + pad) if p['end'] else audio.shape[1]
    return np.ascontiguousarray(audio[:, start:end])

register(EffectSpec('trim_silence', 'Trim silence', 'Utility',
    [Param('threshold_db', 'Threshold', 'float', -50.0, -100.0, 0.0, 'dBFS'),
     Param('padding_ms', 'Keep padding', 'float', 20.0, 0.0, 5000.0, 'ms'),
     Param('start', 'Trim start', 'bool', True), Param('end', 'Trim end', 'bool', True)],
    apply=_trim_silence, changes_length=True))


def _add_silence(audio, sr, p):
    n = int(round(p['duration_seconds'] * sr))
    pad = np.zeros((audio.shape[0], n), dtype=np.float32)
    return np.ascontiguousarray(np.concatenate([pad, audio] if p['position'] == 'start' else [audio, pad], axis=1))

register(EffectSpec('add_silence', 'Add silence', 'Utility',
    [Param('duration_seconds', 'Duration', 'float', 1.0, 0.0, 3600.0, 's'),
     Param('position', 'Position', 'enum', 'end', choices=('start', 'end'))],
    apply=_add_silence, changes_length=True))


def _resample_effect(audio, sr, p):
    # Length changes with the ratio; the workflow engine reports the new sample rate.
    from ..audio_io import resample
    return resample(audio, sr, int(p['target_rate']))

register(EffectSpec('resample', 'Resample', 'Utility',
    [Param('target_rate', 'Target rate', 'enum', 48000, choices=(8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000))],
    apply=_resample_effect, changes_length=True, help='Changes the sample rate of the whole stream.'))


def _spectral_denoise(audio, sr, p):
    """Spectral gating: estimate a noise profile from the quietest frames and subtract it."""
    from scipy.signal import stft, istft
    result = np.empty_like(audio)
    nperseg = 2048
    for channel in range(audio.shape[0]):
        _, _, spectrum = stft(audio[channel], fs=sr, nperseg=nperseg, noverlap=nperseg * 3 // 4)
        magnitude = np.abs(spectrum)
        energy = magnitude.mean(axis=0)
        count = max(4, int(len(energy) * p['noise_fraction']))
        quiet = np.argsort(energy)[:count]
        profile = magnitude[:, quiet].mean(axis=1, keepdims=True)
        gate = magnitude > profile * p['sensitivity']
        strength = float(p['reduction_db'])
        floor = _db_to_gain(-strength)
        mask = np.where(gate, 1.0, floor)
        # Smooth the mask over time to limit musical noise.
        kernel = np.ones(5) / 5.0
        mask = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode='same'), 1, mask)
        _, cleaned = istft(spectrum * mask, fs=sr, nperseg=nperseg, noverlap=nperseg * 3 // 4)
        cleaned = cleaned[:audio.shape[1]]
        if cleaned.shape[0] < audio.shape[1]:
            cleaned = np.pad(cleaned, (0, audio.shape[1] - cleaned.shape[0]))
        result[channel] = cleaned.astype(np.float32)
    return result

register(EffectSpec('noise_reduction', 'Noise reduction (spectral)', 'Restoration',
    [Param('reduction_db', 'Reduction', 'float', 12.0, 0.0, 40.0, 'dB'),
     Param('sensitivity', 'Sensitivity', 'float', 2.0, 1.0, 10.0),
     Param('noise_fraction', 'Noise profile share', 'float', 0.1, 0.01, 0.5, help='share of quietest frames used as noise profile')],
    apply=_spectral_denoise, help='Spectral gating similar to Audacity noise reduction, without AI.'))


def _convolution(audio, sr, p):
    path = p['impulse_response']
    if not path:
        return audio
    plugin = _pb().Convolution(impulse_response_filename=path, mix=float(p['mix']))
    return plugin(audio, float(sr))

register(EffectSpec('convolution', 'Convolution reverb', 'Space',
    [Param('impulse_response', 'Impulse response file', 'enum', '', choices=('',), help='path to a WAV impulse response'),
     Param('mix', 'Mix', 'float', 0.5, 0.0, 1.0)],
    apply=_convolution, help='Real-space reverb from an impulse response file.'))
# The impulse response parameter accepts any path: relax the enum for that one field.
REGISTRY['convolution'].params[0].kind = 'string'
REGISTRY['convolution'].params[0].coerce = lambda value: '' if value is None else str(value)
REGISTRY['convolution'].params[0].schema = lambda: {'type': 'string', 'default': '', 'description': 'Impulse response WAV file path'}


def build_plugin(effect_id, params):
    spec = get(effect_id)
    if spec.build is None:
        return None
    return spec.build(spec.normalize(params))


def apply_effect(effect_id, audio, sr, params):
    """Apply one effect to a whole buffer (stateful plugins are reset first)."""
    spec = get(effect_id)
    values = spec.normalize(params)
    if spec.processor is not None:
        return spec.processor(values, sr).process_all(np.ascontiguousarray(audio, dtype=np.float32))
    if spec.apply is not None:
        return spec.apply(audio, sr, values)
    plugin = spec.build(values)
    return np.ascontiguousarray(plugin(audio, float(sr), reset=True).astype(np.float32))


def make_processor(effect_id, params, samplerate):
    """Block processor for a real-time capable effect (None for whole-buffer effects)."""
    spec = get(effect_id)
    values = spec.normalize(params)
    if spec.processor is not None:
        return spec.processor(values, samplerate)
    if spec.build is not None:
        from .processors import PedalboardProcessor
        return PedalboardProcessor(spec, values, samplerate)
    return None
