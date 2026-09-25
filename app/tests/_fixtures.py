"""Shared fixtures for the AudioStudio test-suite: synthetic audio only, no downloads, no GPU."""
from pathlib import Path
import os
import sys

import numpy as np

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Optional VST3 used by the plugin tests: point AUDIOSTUDIO_TEST_VST3 at any build of the JUCE
# gain plugin 'CyDAW Test Gain'; the tests skip themselves when it is absent.
CYDAW_PLUGIN = Path(os.environ.get('AUDIOSTUDIO_TEST_VST3', ROOT.parents[1] / 'CyDAW_Project' / 'build' / 'desktop' / 'CyDAWTestGain_artefacts' / 'Release' / 'VST3' / 'CyDAW Test Gain.vst3'))
PIPER_VOICE = 'fr_FR-siwis-medium'
PIPER_MODEL_ID = 'piper.' + PIPER_VOICE


def tone(seconds=1.0, samplerate=48000, channels=2, frequency=440.0, amplitude=0.5):
    """Deterministic float32 (channels, frames) sine tone; the right channel is a fifth above."""
    t = np.arange(int(round(seconds * samplerate)), dtype=np.float64) / samplerate
    rows = [np.sin(2 * np.pi * frequency * (1.5 ** index) * t) for index in range(channels)]
    return np.ascontiguousarray((np.stack(rows) * amplitude).astype(np.float32))


def write_wav(path, audio, samplerate=48000, subtype='FLOAT'):
    from audiostudio import audio_io
    return audio_io.save(Path(path), audio, samplerate, fmt='wav', subtype=subtype)


def cydaw_available():
    return CYDAW_PLUGIN.exists()


def piper_available():
    try:
        from audiostudio import models
        from audiostudio.engines import registry as engines
        return bool(models.status(PIPER_MODEL_ID)['installed'] and engines.status('piper')['installed'])
    except Exception:
        return False


def rms_db(audio):
    from audiostudio.audio_io import rms_dbfs
    return float(rms_dbfs(np.asarray(audio, dtype=np.float32)))
