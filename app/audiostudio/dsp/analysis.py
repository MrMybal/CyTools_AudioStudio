"""Measurements: peaks, loudness, spectrum, silence, clipping. No UI, no heavy engine."""
import numpy as np


def loudness(audio, samplerate):
    """Integrated loudness (LUFS), loudness range and true-peak estimate (dBTP)."""
    import pyloudnorm
    frames = audio.T.astype(np.float64)
    meter = pyloudnorm.Meter(int(samplerate))
    minimum = int(samplerate * 0.4) + 1
    padded = frames if frames.shape[0] >= minimum else np.concatenate([frames, np.zeros((minimum - frames.shape[0], frames.shape[1]))])
    integrated = float(meter.integrated_loudness(padded))
    # True peak: 4x oversampling of the peak region is enough for an estimate.
    from scipy.signal import resample_poly
    peak = 0.0
    for channel in audio:
        over = resample_poly(channel.astype(np.float64), 4, 1)
        peak = max(peak, float(np.max(np.abs(over))) if over.size else 0.0)
    true_peak_db = 20.0 * np.log10(peak) if peak > 0 else -np.inf
    return {'integratedLufs': integrated if np.isfinite(integrated) else None,
            'truePeakDbtp': float(true_peak_db) if np.isfinite(true_peak_db) else None}


def statistics(audio, samplerate):
    from ..audio_io import peak_dbfs, rms_dbfs
    peak = peak_dbfs(audio)
    rms = rms_dbfs(audio)
    clipped = int(np.count_nonzero(np.abs(audio) >= 0.999))
    dc = [float(x) for x in np.mean(audio, axis=1)] if audio.size else []
    result = {'channels': int(audio.shape[0]), 'frames': int(audio.shape[1]), 'samplerate': int(samplerate),
              'durationSeconds': float(audio.shape[1]) / float(samplerate),
              'peakDbfs': float(peak) if np.isfinite(peak) else None,
              'rmsDbfs': float(rms) if np.isfinite(rms) else None,
              'clippedSamples': clipped, 'dcOffset': dc}
    try:
        result.update(loudness(audio, samplerate))
    except Exception as exc:  # loudness is optional information
        result['loudnessError'] = str(exc)
    return result


def leading_trailing_silence(audio, samplerate, threshold_db=-60.0):
    threshold = float(10.0 ** (threshold_db / 20.0))
    envelope = np.max(np.abs(audio), axis=0) if audio.size else np.zeros(0)
    above = np.nonzero(envelope > threshold)[0]
    if above.size == 0:
        return {'leadingSeconds': audio.shape[1] / float(samplerate), 'trailingSeconds': 0.0}
    return {'leadingSeconds': float(above[0]) / samplerate,
            'trailingSeconds': float(audio.shape[1] - 1 - above[-1]) / samplerate}


def spectrogram(audio, samplerate, size=1024, hop=None, max_columns=2048):
    """Log-magnitude spectrogram (dB) of the channel mix as a (bins, columns) float32 array."""
    from scipy.signal import stft
    mono = np.mean(audio, axis=0) if audio.shape[0] > 1 else audio[0]
    total = mono.shape[0]
    if total == 0:
        return np.zeros((size // 2 + 1, 0), dtype=np.float32), 0.0
    hop = hop or max(size // 4, total // max_columns)
    _, _, spectrum = stft(mono, fs=samplerate, nperseg=size, noverlap=size - hop, padded=False, boundary=None)
    magnitude = 20.0 * np.log10(np.abs(spectrum) + 1e-9)
    return magnitude.astype(np.float32), float(hop) / samplerate


def peaks(audio, columns):
    """Min/max pairs per column for a quick waveform sketch of a whole buffer."""
    if audio.size == 0 or columns <= 0:
        return np.zeros((0, 2), dtype=np.float32)
    envelope_min = np.min(audio, axis=0)
    envelope_max = np.max(audio, axis=0)
    edges = np.linspace(0, audio.shape[1], columns + 1).astype(np.int64)
    result = np.zeros((columns, 2), dtype=np.float32)
    for index in range(columns):
        start, stop = edges[index], max(edges[index] + 1, edges[index + 1])
        result[index, 0] = envelope_min[start:stop].min()
        result[index, 1] = envelope_max[start:stop].max()
    return result
