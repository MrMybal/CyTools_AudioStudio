"""Short microphone recordings (voice references), independent of the editor transport."""
import time
from pathlib import Path

import numpy as np

from audiostudio.paths import INPUTS
from audiostudio import audio_io


class MicRecorder:
    MAX_SECONDS = 60.0

    def __init__(self, device=None, samplerate=48000):
        self.device = device
        self.samplerate = samplerate
        self.stream = None
        self.blocks = []
        self.level = 0.0
        self.started = 0.0
        self.error = ''

    @property
    def active(self):
        return self.stream is not None

    def seconds(self):
        return sum(len(b) for b in self.blocks) / float(self.samplerate)

    def start(self):
        import sounddevice as sd
        if self.stream is not None:
            return
        self.blocks = []
        self.error = ''

        def callback(indata, frames, time_info, status):
            if self.seconds() < self.MAX_SECONDS:
                self.blocks.append(np.array(indata[:, 0], dtype=np.float32, copy=True))
            self.level = float(np.max(np.abs(indata))) if indata.size else 0.0
        try:
            self.stream = sd.InputStream(samplerate=self.samplerate, channels=1, dtype='float32', callback=callback, device=self.device)
            self.stream.start()
            self.started = time.monotonic()
        except Exception as exc:
            self.stream = None
            self.error = 'Microphone unavailable: ' + str(exc)

    def stop(self, folder=None):
        """Stop and save the take as a WAV (silence trimmed at both ends). Returns the path or None."""
        stream, self.stream = self.stream, None
        if stream is None:
            return None
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        self.level = 0.0
        if not self.blocks:
            return None
        audio = np.concatenate(self.blocks)[np.newaxis, :]
        envelope = np.abs(audio[0])
        above = np.nonzero(envelope > 10 ** (-45 / 20))[0]
        if above.size:
            pad = int(0.15 * self.samplerate)
            audio = audio[:, max(0, above[0] - pad):min(audio.shape[1], above[-1] + pad)]
        folder = Path(folder or INPUTS / 'voices')
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'recording-{time.strftime("%Y%m%d-%H%M%S")}.wav'
        audio_io.save(path, audio, self.samplerate, fmt='wav', subtype='PCM_24')
        return path
