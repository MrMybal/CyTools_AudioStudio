"""Rhythmic effects: stutter (beat repeat), trance gate (step pattern), reverse delay, dual L/R delay."""
import numpy as np
from scipy import signal

from .effects import EffectSpec, Param, register
from . import processors as P
from .creative import NOTE_DIVISIONS


def _division_frames(bpm, division, sr):
    beat = 60.0 / max(20.0, float(bpm))
    return max(16, int(round(beat * NOTE_DIVISIONS.get(division, 1.0) * sr)))


class Stutter(P.Processor):
    """Records the start of every period and repeats it for the rest of the period."""

    def configure(self, p):
        self.period = _division_frames(p['bpm'], p['period'], self.sr)
        fraction = {'1/2': 0.5, '1/4': 0.25, '1/8': 0.125, '1/3': 1.0 / 3.0}[p['grain']]
        self.grain = max(8, int(self.period * fraction))
        if not hasattr(self, 'buffer') or self.buffer.shape[1] != self.grain:
            self.buffer = np.zeros((2, self.grain), np.float64)
            self.phase = 0

    def reset(self):
        self.buffer[:] = 0.0
        self.phase = 0

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        if not p['active']:
            self.phase = (self.phase + count) % self.period
            return block
        out = np.empty_like(stereo)
        start = 0
        decay = float(p['decay'])
        while start < count:
            phase = self.phase
            if phase < self.grain:
                take = min(count - start, self.grain - phase)
                self.buffer[:, phase:phase + take] = stereo[:, start:start + take]
                out[:, start:start + take] = stereo[:, start:start + take]
            else:
                take = min(count - start, self.period - phase)
                index = np.arange(phase - self.grain, phase - self.grain + take)
                repeat = index // self.grain
                out[:, start:start + take] = self.buffer[:, index % self.grain] * (decay ** (repeat + 1))
            self.phase = (phase + take) % self.period
            start += take
        self.meters['step'] = float(self.phase) / self.period
        return P.match_channels(P.mix_dry_wet(stereo, out, p['mix']), block.shape[0]).astype(np.float32)


class TranceGate(P.Processor):
    """A 16-step on/off pattern at the tempo, with smoothed edges."""

    STEPS = 16

    def configure(self, p):
        self.step_frames = _division_frames(p['bpm'], p['division'], self.sr)
        pattern = str(p['pattern'])
        self.pattern = [c in '1xX' for c in pattern[:self.STEPS]] + [False] * max(0, self.STEPS - len(pattern))
        self.coef = P.time_coef(float(p['smooth_ms']), self.sr)
        if not hasattr(self, 'phase'):
            self.phase = 0
            self.zi = np.zeros(1)

    def reset(self):
        self.phase = 0
        self.zi = np.zeros(1)

    def process(self, block, sidechain=None):
        p = self.params
        count = block.shape[1]
        index = (self.phase + np.arange(count)) // self.step_frames % self.STEPS
        target = np.asarray(self.pattern, dtype=np.float64)[index]
        self.phase = (self.phase + count) % (self.step_frames * self.STEPS)
        if self.coef > 0.0:
            target, self.zi = signal.lfilter([1.0 - self.coef], [1.0, -self.coef], target, zi=self.zi)
        depth = float(p['depth'])
        gain = (1.0 - depth) + depth * target
        self.meters['step'] = int(index[-1])
        self.meters['gate'] = float(target[-1])
        return (block * gain[np.newaxis, :].astype(np.float32)).astype(np.float32)


class ReverseDelay(P.Processor):
    """Plays every recorded grain backwards, one grain late."""

    def configure(self, p):
        self.length = max(64, int(float(p['length_ms']) * 1e-3 * self.sr))
        if not hasattr(self, 'record') or self.record.shape[1] != self.length:
            self.record = np.zeros((2, self.length), np.float64)
            self.play = np.zeros((2, self.length), np.float64)
            self.phase = 0

    def reset(self):
        self.record[:] = 0.0
        self.play[:] = 0.0
        self.phase = 0

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        wet = np.empty_like(stereo)
        feedback = float(p['feedback'])
        start = 0
        while start < count:
            take = min(count - start, self.length - self.phase)
            chunk = stereo[:, start:start + take]
            reversed_out = self.play[:, self.length - self.phase - take:self.length - self.phase][:, ::-1]
            wet[:, start:start + take] = reversed_out
            self.record[:, self.phase:self.phase + take] = chunk + reversed_out * feedback
            self.phase += take
            start += take
            if self.phase >= self.length:
                self.play, self.record = self.record, np.zeros_like(self.record)
                self.phase = 0
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class DualDelay(P.Processor):
    """Independent left and right delay times with feedback and cross-feedback."""

    def configure(self, p):
        self.delays = [max(int(0.005 * self.sr), int(round(float(p[k]) * 1e-3 * self.sr))) for k in ('left_ms', 'right_ms')]
        if not hasattr(self, 'line'):
            self.line = P.DelayLine(2, int(self.sr * 5.2) + 8192)
            self.tone = P.OnePole(self.sr, p['tone_hz'])
        self.tone.set(p['tone_hz'])

    def reset(self):
        self.line.reset()
        self.tone.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.asarray(block, dtype=np.float64))
        count = stereo.shape[1]
        step = min(self.delays)
        wet = np.empty_like(stereo)
        feedback, cross = float(p['feedback']), float(p['cross'])
        for start in range(0, count, step):
            stop = min(count, start + step)
            n = stop - start
            left = self.line.read(self.delays[0], n)[0]
            right = self.line.read(self.delays[1], n)[1]
            delayed = np.stack([left, right])
            wet[:, start:stop] = delayed
            fed = self.tone.process(delayed) * feedback
            fed = fed * (1.0 - cross) + fed[::-1] * cross
            self.line.push(stereo[:, start:stop] + fed)
        out = P.mix_dry_wet(stereo, wet, p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


register(EffectSpec('stutter', 'Stutter (beat repeat)', 'Rhythm',
    [Param('active', 'Active', 'bool', True, help='automate this to stutter only on some beats'),
     Param('bpm', 'Tempo', 'float', 120.0, 20.0, 300.0, 'BPM'),
     Param('period', 'Period', 'enum', '1/4', choices=('1/1', '1/2', '1/4', '1/8')),
     Param('grain', 'Repeat length', 'enum', '1/4', choices=('1/2', '1/3', '1/4', '1/8'), help='fraction of the period'),
     Param('decay', 'Decay', 'float', 0.85, 0.0, 1.0, help='level of each repeat relative to the previous one'),
     Param('mix', 'Mix', 'float', 1.0, 0.0, 1.0)],
    processor=Stutter, ui='pattern', help='Records the start of each period and repeats it (glitch / beat repeat).'))

register(EffectSpec('trance_gate', 'Trance gate (step pattern)', 'Rhythm',
    [Param('bpm', 'Tempo', 'float', 120.0, 20.0, 300.0, 'BPM'),
     Param('division', 'Step', 'enum', '1/16', choices=('1/4', '1/8', '1/16', '1/8T', '1/4T')),
     Param('pattern', 'Pattern', 'string', '1010110110101100', help='16 steps, 1 = open, 0 = closed'),
     Param('smooth_ms', 'Smoothing', 'float', 4.0, 0.0, 60.0, 'ms'),
     Param('depth', 'Depth', 'float', 1.0, 0.0, 1.0)],
    processor=TranceGate, ui='pattern', help='Rhythmic volume gate driven by a 16-step pattern.'))

register(EffectSpec('reverse_delay', 'Reverse delay', 'Space',
    [Param('length_ms', 'Grain', 'float', 500.0, 50.0, 4000.0, 'ms'),
     Param('feedback', 'Feedback', 'float', 0.3, 0.0, 0.9),
     Param('mix', 'Mix', 'float', 0.5, 0.0, 1.0)],
    processor=ReverseDelay, ui='delay', help='Each grain is played backwards one grain later (backwards echoes).'))

register(EffectSpec('dual_delay', 'Dual delay (L / R)', 'Space',
    [Param('left_ms', 'Left', 'float', 300.0, 5.0, 5000.0, 'ms'),
     Param('right_ms', 'Right', 'float', 450.0, 5.0, 5000.0, 'ms'),
     Param('feedback', 'Feedback', 'float', 0.4, 0.0, 0.98),
     Param('cross', 'Cross-feed', 'float', 0.3, 0.0, 1.0),
     Param('tone_hz', 'Feedback tone', 'float', 6000.0, 200.0, 20000.0, 'Hz'),
     Param('mix', 'Mix', 'float', 0.4, 0.0, 1.0)],
    processor=DualDelay, ui='delay'))
