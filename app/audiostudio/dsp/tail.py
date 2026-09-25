"""Tail rendering: keep processing after the input ends until the output is silent.

A delay or a reverb keeps producing sound after the last input sample. Without this
step an export cuts the decay. The workflow engine appends ``max_seconds`` of silence
before the chain, then ``trim`` removes the silent part that remains at the end, never
shortening the result below the original length.
"""
from dataclasses import dataclass
import numpy as np


@dataclass
class TailSettings:
    enabled: bool = True
    threshold_db: float = -60.0     # output below this level counts as silence
    max_seconds: float = 10.0       # upper bound of the extension
    hold_seconds: float = 0.1       # kept after the last non-silent sample

    @classmethod
    def from_dict(cls, value):
        value = value or {}
        item = cls()
        item.enabled = bool(value.get('enabled', item.enabled))
        item.threshold_db = float(value.get('threshold_db', item.threshold_db))
        item.max_seconds = float(value.get('max_seconds', item.max_seconds))
        item.hold_seconds = float(value.get('hold_seconds', item.hold_seconds))
        item.threshold_db = max(-120.0, min(0.0, item.threshold_db))
        item.max_seconds = max(0.0, min(600.0, item.max_seconds))
        item.hold_seconds = max(0.0, min(10.0, item.hold_seconds))
        return item

    def as_dict(self):
        return {'enabled': self.enabled, 'threshold_db': self.threshold_db,
                'max_seconds': self.max_seconds, 'hold_seconds': self.hold_seconds}


def extend(audio, samplerate, settings):
    """Append the silence that gives stateful effects room to decay."""
    if not settings.enabled or settings.max_seconds <= 0:
        return audio
    pad = int(round(settings.max_seconds * samplerate))
    if pad <= 0:
        return audio
    return np.ascontiguousarray(np.concatenate([audio, np.zeros((audio.shape[0], pad), dtype=audio.dtype)], axis=1))


def last_audible_index(audio, threshold_db):
    """Index of the last sample above the threshold, or -1 when the whole buffer is silent."""
    if audio.size == 0:
        return -1
    threshold = float(10.0 ** (threshold_db / 20.0))
    envelope = np.max(np.abs(audio), axis=0)
    above = np.nonzero(envelope > threshold)[0]
    return int(above[-1]) if above.size else -1


def trim(audio, samplerate, settings, original_frames):
    """Remove trailing silence produced by the extension, keeping at least the original length."""
    if not settings.enabled:
        return audio
    if audio.shape[1] <= original_frames:
        return audio
    last = last_audible_index(audio[:, original_frames:], settings.threshold_db)
    hold = int(round(settings.hold_seconds * samplerate))
    end = original_frames if last < 0 else min(audio.shape[1], original_frames + last + 1 + hold)
    return np.ascontiguousarray(audio[:, :end])


def measure_tail(audio, samplerate, original_frames, threshold_db=-60.0):
    """Seconds of audible sound beyond the original input length (for reports and tests)."""
    if audio.shape[1] <= original_frames:
        return 0.0
    last = last_audible_index(audio[:, original_frames:], threshold_db)
    return 0.0 if last < 0 else (last + 1) / float(samplerate)
