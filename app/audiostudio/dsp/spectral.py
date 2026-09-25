"""Real-time spectral noise reduction: STFT (2048 / hop 512, sqrt-Hann WOLA), a noise profile that
is learnt on demand or tracked adaptively (minimum statistics), spectral subtraction with a floor and
gain smoothing over frequency and time. Adds 2048 frames of latency.
"""
import numpy as np

from .effects import EffectSpec, Param, register
from . import processors as P


class SpectralDenoiser(P.Processor):
    SIZE = 2048
    HOP = 512

    def configure(self, p):
        if not hasattr(self, 'window'):
            self.window = np.sqrt(np.hanning(self.SIZE + 1)[:-1])
            self.bins = self.SIZE // 2 + 1
            # WOLA normalisation: sum of window^2 over the overlapping frames
            overlap = sum(np.roll(self.window ** 2, k * self.HOP) for k in range(self.SIZE // self.HOP))
            self.norm = 1.0 / float(overlap.max())
            self.reset()
        self.floor = P.db_to_gain(-float(p['reduction_db']))
        self.sensitivity = float(p['sensitivity'])
        self.release = float(p['smoothing'])

    def reset(self):
        self.pending = np.zeros((2, 0), np.float64)
        self.position = 0                       # next frame start inside ``pending``
        self.ola = np.zeros((2, self.SIZE), np.float64)
        self.ola_start = 0                      # absolute index of ola[:, 0]
        self.emitted = 0                        # absolute index of the next frame to emit
        self.profile = np.full(self.bins, 1e-4)
        self.frames_seen = 0
        self.gains = np.ones(self.bins)
        # Fixed latency: the FIFO starts primed with silence so that blocks of any size never run it
        # dry (the analysis lags the input by up to SIZE + 3 * HOP frames with small blocks).
        self.latency_frames = self.SIZE + 3 * self.HOP
        self.fifo = np.zeros((2, self.latency_frames), np.float32)
        self.meters = {'reduction_db': 0.0}

    def _frame(self, frame):
        p = self.params
        spectrum = np.fft.rfft(frame * self.window, axis=-1)
        magnitude = np.abs(spectrum).mean(axis=0)
        self.frames_seen += 1
        if p['learn'] or self.frames_seen <= 6:
            # explicit learning, or the first frames after a reset seed the profile
            self.profile = magnitude if self.frames_seen == 1 else 0.7 * self.profile + 0.3 * magnitude
        elif p['adaptive']:
            self.profile = np.where(magnitude < self.profile, 0.9 * self.profile + 0.1 * magnitude, self.profile * 1.003)
        clean = magnitude - self.sensitivity * self.profile
        gain = np.clip(clean / np.maximum(magnitude, 1e-9), self.floor, 1.0)
        gain = np.convolve(np.pad(gain, 2, mode='edge'), np.ones(5) / 5.0, mode='valid')   # smooth over frequency, edges kept
        self.gains = np.maximum(gain, self.gains * self.release)
        out = np.fft.irfft(spectrum * self.gains[np.newaxis, :], n=self.SIZE, axis=-1) * self.window * self.norm
        self.meters['reduction_db'] = float(P.gain_to_db(self.gains.mean()))
        self.meters['profile_db'] = P.gain_to_db(self.profile * 2.0 / self.window.sum() * 2.0)
        self.meters['spectrum_db'] = P.gain_to_db(magnitude * 2.0 / self.window.sum() * 2.0)
        return out

    def process(self, block, sidechain=None):
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        self.pending = np.concatenate([self.pending, stereo], axis=1)
        produced = []
        while self.pending.shape[1] - self.position >= self.SIZE:
            frame = self.pending[:, self.position:self.position + self.SIZE]
            out = self._frame(frame)
            # overlap-add at absolute index ``self.emitted + self.position``... keep it relative to ola_start
            offset = self.position - self.ola_start
            if offset + self.SIZE > self.ola.shape[1]:
                self.ola = np.concatenate([self.ola, np.zeros((2, offset + self.SIZE - self.ola.shape[1]))], axis=1)
            self.ola[:, offset:offset + self.SIZE] += out
            self.position += self.HOP
            ready = self.position - (self.SIZE - self.HOP) - self.ola_start
            if ready > 0:
                produced.append(self.ola[:, :ready].copy())
                self.ola = self.ola[:, ready:]
                self.ola_start += ready
        # trim the input history
        if self.position > self.SIZE * 4:
            drop = self.position - self.SIZE
            self.pending = self.pending[:, drop:]
            self.position -= drop
            self.ola_start -= drop
        ready = np.concatenate(produced, axis=1).astype(np.float32) if produced else np.zeros((2, 0), np.float32)
        self.fifo = np.concatenate([self.fifo, ready], axis=1)
        if self.fifo.shape[1] < count:                      # safety only: keep the stream continuous
            self.fifo = np.concatenate([self.fifo, np.zeros((2, count - self.fifo.shape[1]), np.float32)], axis=1)
        result, self.fifo = self.fifo[:, :count], np.ascontiguousarray(self.fifo[:, count:])
        return P.match_channels(result, block.shape[0]).astype(np.float32)

    def process_all(self, audio):
        """Offline: pad with silence so the whole input comes out, then remove the latency."""
        self.reset()
        audio = np.ascontiguousarray(np.asarray(audio, dtype=np.float32))
        if audio.ndim == 1:
            audio = audio[np.newaxis, :]
        total = audio.shape[1]
        if total == 0:
            return audio
        padded = np.concatenate([audio, np.zeros((audio.shape[0], self.SIZE * 2), np.float32)], axis=1)
        parts = [self.process(padded[:, start:start + P.OFFLINE_BLOCK]) for start in range(0, padded.shape[1], P.OFFLINE_BLOCK)]
        out = np.concatenate(parts, axis=1)
        return np.ascontiguousarray(out[:, self.latency_frames:self.latency_frames + total])


register(EffectSpec('spectral_denoiser', 'Noise reduction (real-time)', 'Restoration',
    [Param('reduction_db', 'Reduction', 'float', 12.0, 0.0, 40.0, 'dB'),
     Param('sensitivity', 'Sensitivity', 'float', 1.5, 0.5, 6.0, help='how far above the noise profile a bin must be to pass'),
     Param('smoothing', 'Smoothing', 'float', 0.6, 0.0, 0.95, help='holds gains open between frames (less musical noise)'),
     Param('learn', 'Learn noise profile', 'bool', False, help='enable during a noise-only passage, then disable'),
     Param('adaptive', 'Adaptive profile', 'bool', True, help='track the noise floor continuously')],
    processor=SpectralDenoiser, ui='denoise', help='Spectral subtraction against a noise profile; 75 ms latency. Learn the profile on a noise-only passage for the best result.'))
