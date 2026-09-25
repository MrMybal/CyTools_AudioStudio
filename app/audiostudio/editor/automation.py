"""Automation lanes: (time, value) breakpoints with linear interpolation.

A lane belongs to a track or to the master bus and is addressed by a key: ``gain_db``,
``pan``, ``mute`` or ``<insert node id>.<parameter id>``. Values are stored in the parameter's
own unit (dB for volume, Hz for a cutoff...), so a lane survives when the parameter range of
an effect changes. Points are kept sorted; ``write`` replaces what lies inside a small window
around the written time, which is how live "write" automation records knob moves.
"""
import bisect

import numpy as np

MERGE_WINDOW = 1e-4


class AutomationLane:
    def __init__(self, key, points=None, enabled=True):
        self.key = str(key)
        self.enabled = bool(enabled)
        self.points = []
        for point in points or []:
            self.add_point(float(point[0]), float(point[1]))

    # ------------------------------------------------------------------ evaluation
    def __len__(self):
        return len(self.points)

    @property
    def active(self):
        return self.enabled and bool(self.points)

    def times(self):
        return np.fromiter((p[0] for p in self.points), dtype=np.float64, count=len(self.points))

    def value_at(self, time, default=0.0):
        if not self.points:
            return float(default)
        if len(self.points) == 1:
            return float(self.points[0][1])
        times = self.times()
        values = np.fromiter((p[1] for p in self.points), dtype=np.float64, count=len(self.points))
        return float(np.interp(float(time), times, values))

    def values(self, times, default=0.0):
        """Interpolated values for an array of times (constant before the first and after the last point)."""
        times = np.asarray(times, dtype=np.float64)
        if not self.points:
            return np.full(times.shape, float(default))
        if len(self.points) == 1:
            return np.full(times.shape, float(self.points[0][1]))
        xs = self.times()
        ys = np.fromiter((p[1] for p in self.points), dtype=np.float64, count=len(self.points))
        return np.interp(times, xs, ys)

    # ------------------------------------------------------------------ editing
    def add_point(self, time, value):
        """Insert (or replace a point at the same time); returns the index of the point."""
        time, value = float(max(0.0, time)), float(value)
        times = [p[0] for p in self.points]
        index = bisect.bisect_left(times, time)
        if index < len(self.points) and abs(self.points[index][0] - time) <= MERGE_WINDOW:
            self.points[index] = [time, value]
            return index
        if index > 0 and abs(self.points[index - 1][0] - time) <= MERGE_WINDOW:
            self.points[index - 1] = [time, value]
            return index - 1
        self.points.insert(index, [time, value])
        return index

    def move_point(self, index, time, value):
        """Move a point; it cannot cross its neighbours. Returns its (unchanged) index."""
        if not 0 <= index < len(self.points):
            return index
        low = self.points[index - 1][0] + MERGE_WINDOW if index > 0 else 0.0
        high = self.points[index + 1][0] - MERGE_WINDOW if index + 1 < len(self.points) else float('inf')
        self.points[index] = [float(min(max(time, low), high)), float(value)]
        return index

    def remove_point(self, index):
        if 0 <= index < len(self.points):
            del self.points[index]
            return True
        return False

    def clear(self):
        self.points = []

    def write(self, time, value, window=0.02):
        """Record a live value: replaces the points inside +-window around ``time``."""
        time = float(max(0.0, time))
        self.points = [p for p in self.points if abs(p[0] - time) > window]
        return self.add_point(time, value)

    def nearest(self, time, max_distance):
        """Index of the closest point within max_distance seconds, or None."""
        best, best_distance = None, max_distance
        for index, (t, _) in enumerate(self.points):
            distance = abs(t - time)
            if distance <= best_distance:
                best, best_distance = index, distance
        return best

    def shift(self, from_time, delta):
        """Move every point at or after from_time by delta seconds (clip moves, inserted silence)."""
        self.points = sorted([[max(0.0, t + delta), v] if t >= from_time else [t, v] for t, v in self.points])

    # ------------------------------------------------------------------ persistence
    def to_dict(self):
        return {'key': self.key, 'enabled': self.enabled, 'points': [[round(t, 6), v] for t, v in self.points]}

    @classmethod
    def from_dict(cls, value):
        return cls(value.get('key', ''), value.get('points') or [], value.get('enabled', True))

    def copy(self):
        return AutomationLane(self.key, [list(p) for p in self.points], self.enabled)
