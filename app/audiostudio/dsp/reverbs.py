"""Reverb variants built from the impulse-response reverb: shimmer (octave-up feedback) and gated."""
import numpy as np

from .effects import EffectSpec, Param, register
from . import processors as P
from .space import IRReverb, REVERB_TYPES
from .creative import PitchShifter
from .dynamics import Gate


class ShimmerReverb(P.Processor):
    """Reverb whose output is pitch-shifted up and fed back: rising, choir-like tails."""

    def configure(self, p):
        if not hasattr(self, 'reverb'):
            self.reverb = IRReverb(self._reverb_params(p), self.sr)
            self.shifter = PitchShifter({'semitones': float(p['interval']), 'cents': 0.0, 'window_ms': 70.0, 'mix': 1.0}, self.sr)
            self.previous = None
        else:
            self.reverb.set_params(self._reverb_params(p))
            self.shifter.set_params({'semitones': float(p['interval'])})
        self.feedback = float(p['shimmer'])

    @staticmethod
    def _reverb_params(p):
        return {'type': 'hall', 'decay_seconds': p['decay_seconds'], 'predelay_ms': 10.0, 'size': 0.8, 'damping': p['damping'],
                'low_cut_hz': 150.0, 'high_cut_hz': 14000.0, 'width': 1.0, 'wet_db': 0.0, 'mix': 1.0}

    def envelope(self, points=200):
        return self.reverb.envelope(points)

    def reset(self):
        self.reverb.reset()
        self.shifter.reset()
        self.previous = None

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.ascontiguousarray(block, dtype=np.float32))
        feed = stereo
        if self.previous is not None and self.feedback > 0.0:
            previous = self.previous
            if previous.shape[1] != stereo.shape[1]:
                previous = np.resize(previous, stereo.shape)
            feed = stereo + previous * self.feedback
        wet = self.reverb.process(feed)
        shifted = self.shifter.process(wet)
        self.previous = np.tanh(shifted)                     # keeps the loop bounded
        out = P.mix_dry_wet(stereo, wet * P.db_to_gain(p['wet_db']), p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


class GatedReverb(P.Processor):
    """Big reverb cut by a gate keyed from the dry signal (80s drums)."""

    def configure(self, p):
        reverb = {'type': p['type'], 'decay_seconds': p['decay_seconds'], 'predelay_ms': 5.0, 'size': 0.7, 'damping': 0.3,
                  'low_cut_hz': 120.0, 'high_cut_hz': 12000.0, 'width': 1.0, 'wet_db': 0.0, 'mix': 1.0}
        gate = {'threshold_db': p['threshold_db'], 'ratio': 40.0, 'range_db': -80.0, 'attack_ms': 0.5, 'release_ms': p['hold_ms'],
                'knee_db': 2.0, 'detector': 'peak', 'sc_highpass_hz': 0.0, 'sidechain_input': True}
        if not hasattr(self, 'reverb'):
            self.reverb = IRReverb(reverb, self.sr)
            self.gate = Gate(gate, self.sr)
        else:
            self.reverb.set_params(reverb)
            self.gate.set_params(gate)

    def envelope(self, points=200):
        return self.reverb.envelope(points)

    def reset(self):
        self.reverb.reset()
        self.gate.reset()

    def process(self, block, sidechain=None):
        p = self.params
        stereo = P.as_stereo(np.ascontiguousarray(block, dtype=np.float32))
        wet = self.reverb.process(stereo)
        gated = self.gate.process(wet, sidechain=stereo)
        self.meters['gain_reduction_db'] = self.gate.meters.get('gain_reduction_db', 0.0)
        out = P.mix_dry_wet(stereo, gated * P.db_to_gain(p['wet_db']), p['mix'])
        return P.match_channels(out, block.shape[0]).astype(np.float32)


register(EffectSpec('shimmer_reverb', 'Shimmer reverb', 'Space',
    [Param('decay_seconds', 'Decay', 'float', 4.0, 0.5, 12.0, 's', automatable=False),
     Param('damping', 'Damping', 'float', 0.3, 0.0, 1.0, automatable=False),
     Param('interval', 'Shimmer interval', 'enum', 12.0, choices=(12.0, 7.0, 5.0, 19.0, 24.0), help='semitones added at each pass'),
     Param('shimmer', 'Shimmer amount', 'float', 0.5, 0.0, 0.9),
     Param('wet_db', 'Wet level', 'float', -3.0, -24.0, 6.0, 'dB'),
     Param('mix', 'Mix', 'float', 0.4, 0.0, 1.0)],
    processor=ShimmerReverb, ui='reverb', help='Octave-up feedback through the reverb: pads and ambient washes.'))

register(EffectSpec('gated_reverb', 'Gated reverb', 'Space',
    [Param('type', 'Type', 'enum', 'room', choices=REVERB_TYPES, automatable=False),
     Param('decay_seconds', 'Decay', 'float', 2.5, 0.3, 8.0, 's', automatable=False),
     Param('threshold_db', 'Gate threshold', 'float', -30.0, -70.0, 0.0, 'dB', help='on the dry signal'),
     Param('hold_ms', 'Hold / release', 'float', 120.0, 10.0, 1000.0, 'ms'),
     Param('wet_db', 'Wet level', 'float', 0.0, -24.0, 6.0, 'dB'),
     Param('mix', 'Mix', 'float', 0.5, 0.0, 1.0)],
    processor=GatedReverb, ui='reverb', help='The reverb only sounds while the dry signal is above the threshold.'))
