"""In-memory min/max peak pyramid of a track buffer, for drawing at any zoom."""
import numpy as np

BASE = 256
FACTOR = 4
MIN_PAIRS = 128


class Peaks:
    def __init__(self, audio):
        self.frames = int(audio.shape[1]) if audio is not None and audio.ndim == 2 else 0
        self.levels = []
        if self.frames == 0:
            return
        low = np.min(audio, axis=0)
        high = np.max(audio, axis=0)
        full = (self.frames // BASE) * BASE
        lows, highs = [], []
        if full:
            lows.append(low[:full].reshape(-1, BASE).min(axis=1))
            highs.append(high[:full].reshape(-1, BASE).max(axis=1))
        if full < self.frames:
            lows.append(np.array([low[full:].min()], dtype=np.float32))
            highs.append(np.array([high[full:].max()], dtype=np.float32))
        low = np.concatenate(lows).astype(np.float32)
        high = np.concatenate(highs).astype(np.float32)
        while True:
            self.levels.append((low, high))
            if len(low) <= MIN_PAIRS:
                break
            pad = (-len(low)) % FACTOR
            if pad:
                low = np.concatenate([low, np.full(pad, low[-1], dtype=np.float32)])
                high = np.concatenate([high, np.full(pad, high[-1], dtype=np.float32)])
            low = low.reshape(-1, FACTOR).min(axis=1)
            high = high.reshape(-1, FACTOR).max(axis=1)

    def samples_per_pair(self, level):
        return BASE * FACTOR ** level

    def read(self, start_frame, stop_frame, columns, audio=None):
        """(low, high) arrays with at most ``columns`` entries for the frame range.

        When the range is finer than the base resolution and ``audio`` is given, the
        exact samples are reduced instead (sample-accurate zoom)."""
        columns = max(1, int(columns))
        start_frame = max(0, int(start_frame))
        stop_frame = min(self.frames, int(stop_frame))
        if stop_frame <= start_frame or not self.levels:
            return np.zeros(0, np.float32), np.zeros(0, np.float32)
        wanted = (stop_frame - start_frame) / columns
        if wanted < BASE and audio is not None:
            block = audio[:, start_frame:stop_frame]
            low, high = np.min(block, axis=0), np.max(block, axis=0)
            if len(low) > columns:
                edges = np.linspace(0, len(low), columns + 1).astype(int)[:-1]
                return np.minimum.reduceat(low, edges), np.maximum.reduceat(high, edges)
            return low.astype(np.float32), high.astype(np.float32)
        level = 0
        while level + 1 < len(self.levels) and self.samples_per_pair(level + 1) <= wanted:
            level += 1
        step = self.samples_per_pair(level)
        low_level, high_level = self.levels[level]
        a, b = start_frame // step, min(len(low_level), int(np.ceil(stop_frame / step)))
        low, high = low_level[a:max(a + 1, b)], high_level[a:max(a + 1, b)]
        if len(low) > columns:
            edges = np.linspace(0, len(low), columns + 1).astype(int)[:-1]
            return np.minimum.reduceat(low, edges), np.maximum.reduceat(high, edges)
        return low.copy(), high.copy()
