"""Pure NumPy synthesis primitives for the procedural SFX backend (ported from dsp.py).

Every function is deterministic for a given Generator and returns float32 mono
audio. Filters are implemented in the frequency domain so that no recursive
per-sample Python loop is required.
"""
import numpy as np

TWO_PI = 2.0*np.pi


def generator(seed):
    return np.random.default_rng(int(seed) & 0xFFFFFFFFFFFFFFFF)


def f32(values):
    return np.asarray(values, dtype=np.float32)


def white(rng, count):
    return rng.standard_normal(count).astype(np.float32)


def _tilt(rng, count, rate, exponent):
    """Unit-RMS noise whose magnitude spectrum follows 1/f**exponent."""
    if count < 8: return white(rng, count)
    spectrum = np.fft.rfft(rng.standard_normal(count))
    bins = np.arange(spectrum.size, dtype=np.float64)
    bins[0] = 1.0
    spectrum = spectrum/bins**exponent
    # Drop the sub-audio part: brown noise would otherwise spend the entire
    # headroom on inaudible DC drift instead of the intended rumble.
    spectrum[np.fft.rfftfreq(count, 1.0/rate) < 18.0] = 0.0
    shaped = np.fft.irfft(spectrum, count)
    return f32(shaped/max(float(np.sqrt(np.mean(np.square(shaped)))), 1e-12))


def pink(rng, count, rate): return _tilt(rng, count, rate, 0.5)
def brown(rng, count, rate): return _tilt(rng, count, rate, 1.0)


def line(points, count):
    """Piecewise-linear envelope; points are (position 0..1, value)."""
    positions = [p for p, _ in points]
    values = [v for _, v in points]
    return f32(np.interp(np.linspace(0.0, 1.0, max(count, 1)), positions, values))


def exp_decay(count, rate, tau):
    return f32(np.exp(-np.arange(max(count, 1))/max(tau*rate, 1e-6)))


def ad(count, rate, attack, decay, curve=1.6):
    """Attack/decay envelope; decay is the time constant of the falling part."""
    count = max(count, 1)
    envelope = exp_decay(count, rate, decay)**curve
    ramp = min(max(int(attack*rate), 1), count)
    envelope[:ramp] *= np.linspace(0.0, 1.0, ramp, dtype=np.float32)
    return envelope


def smooth_random(rng, count, rate, frequency):
    """Band-limited random control signal in [-1, 1] at about `frequency` Hz."""
    knots = max(int(count*max(frequency, 0.01)/rate)+2, 2)
    return f32(np.interp(np.linspace(0.0, knots-1.0, max(count, 1)),
                         np.arange(knots), rng.uniform(-1.0, 1.0, knots)))


def osc(frequency, rate, shape='sine'):
    """Oscillator driven by a per-sample frequency envelope (Hz)."""
    frequency = np.asarray(frequency, dtype=np.float64)
    phase = np.cumsum(TWO_PI*np.abs(frequency)/rate)
    if shape == 'sine': return f32(np.sin(phase))
    cycle = (phase/TWO_PI) % 1.0
    if shape == 'saw': return f32(2.0*cycle-1.0)
    if shape == 'square': return f32(np.where(cycle < 0.5, 1.0, -1.0))
    if shape == 'triangle': return f32(4.0*np.abs(cycle-0.5)-1.0)
    raise ValueError('Unknown oscillator shape: '+str(shape))


def _mask(signal, mask):
    return f32(np.fft.irfft(np.fft.rfft(signal)*mask, signal.size))


def lowpass(signal, rate, cutoff, order=2):
    if signal.size < 4: return signal
    freqs = np.fft.rfftfreq(signal.size, 1.0/rate)
    return _mask(signal, 1.0/np.sqrt(1.0+(freqs/max(float(cutoff), 1.0))**(2*order)))


def highpass(signal, rate, cutoff, order=2):
    if signal.size < 4: return signal
    freqs = np.maximum(np.fft.rfftfreq(signal.size, 1.0/rate), 1e-3)
    return _mask(signal, 1.0/np.sqrt(1.0+(max(float(cutoff), 1.0)/freqs)**(2*order)))


def bandpass(signal, rate, low, high, order=2):
    return lowpass(highpass(signal, rate, low, order), rate, high, order)


def resonator(signal, rate, centre, q=12.0):
    """Narrow resonant band used for metallic and friction textures."""
    if signal.size < 4: return signal
    freqs = np.maximum(np.fft.rfftfreq(signal.size, 1.0/rate), 1e-3)
    centre = max(float(centre), 1.0)
    return _mask(signal, 1.0/np.sqrt(1.0+(q*(freqs/centre-centre/freqs))**2))


def sweep_lowpass(signal, rate, cutoff, frame=1024):
    """Time-varying lowpass through overlap-add STFT masking."""
    count = signal.size
    if count < frame*2: return lowpass(signal, rate, float(np.mean(cutoff)))
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), (count,))
    hop = frame//2
    window = f32(np.hanning(frame+1)[:-1])
    padded = np.concatenate([signal, np.zeros(frame, dtype=np.float32)])
    output = np.zeros(count+frame)
    weight = np.zeros(count+frame)
    freqs = np.fft.rfftfreq(frame, 1.0/rate)
    for start in range(0, count, hop):
        limit = float(np.clip(cutoff[min(start+hop, count-1)], 20.0, rate*0.49))
        mask = 1.0/np.sqrt(1.0+(freqs/limit)**4)
        output[start:start+frame] += np.fft.irfft(np.fft.rfft(padded[start:start+frame]*window)*mask, frame)
        weight[start:start+frame] += window
    return f32(output[:count]/np.maximum(weight[:count], 1e-6))


def sweep_bandpass(signal, rate, centre, width=2.5, frame=1024):
    """Time-varying bandpass; `width` is the ratio between edges."""
    count = signal.size
    if count < frame*2:
        middle = float(np.mean(centre))
        return bandpass(signal, rate, middle/width, middle*width)
    centre = np.broadcast_to(np.asarray(centre, dtype=np.float64), (count,))
    hop = frame//2
    window = f32(np.hanning(frame+1)[:-1])
    padded = np.concatenate([signal, np.zeros(frame, dtype=np.float32)])
    output = np.zeros(count+frame)
    weight = np.zeros(count+frame)
    freqs = np.maximum(np.fft.rfftfreq(frame, 1.0/rate), 1e-3)
    for start in range(0, count, hop):
        middle = float(np.clip(centre[min(start+hop, count-1)], 30.0, rate*0.45))
        mask = 1.0/np.sqrt(1.0+(freqs/(middle*width))**4)/np.sqrt(1.0+(middle/width/freqs)**4)
        output[start:start+frame] += np.fft.irfft(np.fft.rfft(padded[start:start+frame]*window)*mask, frame)
        weight[start:start+frame] += window
    return f32(output[:count]/np.maximum(weight[:count], 1e-6))


def convolve(signal, impulse):
    size = signal.size+impulse.size-1
    length = 1 << int(np.ceil(np.log2(max(size, 2))))
    return f32(np.fft.irfft(np.fft.rfft(signal, length)*np.fft.rfft(impulse, length), length)[:size])


def sparse(rng, count, positions, impulse, amplitudes=None):
    """Convolve an impulse with a sparse set of trigger positions."""
    triggers = np.zeros(max(count, 1), dtype=np.float32)
    positions = np.clip(np.asarray(positions, dtype=np.int64), 0, max(count-1, 0))
    if positions.size:
        values = rng.uniform(0.45, 1.0, positions.size) if amplitudes is None else np.asarray(amplitudes, dtype=np.float64)
        np.add.at(triggers, positions, values.astype(np.float32))
    return convolve(triggers, impulse)[:count]


def poisson_positions(rng, count, rate, events_per_second):
    average = max(events_per_second, 0.05)
    expected = max(int(count/rate*average), 1)
    return rng.integers(0, max(count, 1), expected)


def periodic_positions(count, rate, period, jitter=0.0, rng=None):
    step = max(period*rate, 1.0)
    positions = np.arange(0.0, max(count, 1), step)
    if jitter and rng is not None:
        positions = positions+rng.uniform(-jitter, jitter, positions.size)*step
    return np.clip(positions, 0, max(count-1, 0)).astype(np.int64)


def gate(count, rate, period, duty=0.5, softness=400.0):
    ticks = np.arange(max(count, 1))/rate
    return lowpass(f32((ticks % max(period, 1e-3)) < max(period, 1e-3)*duty), rate, softness)


def reverb(signal, rate, seconds=1.1, mix=0.2, rng=None, damping=5200.0):
    if mix <= 0.0 or signal.size < 16: return signal
    rng = rng or generator(1)
    length = max(int(seconds*rate), 16)
    tail = white(rng, length)*exp_decay(length, rate, seconds/4.5)
    tail[:int(0.004*rate)] *= np.linspace(0.0, 1.0, int(0.004*rate), dtype=np.float32)
    wet = convolve(signal, lowpass(tail, rate, damping))[:signal.size]
    peak = float(np.max(np.abs(wet)))
    if peak > 1e-9:
        wet = wet*(float(np.max(np.abs(signal)))/peak)
    return f32(signal*(1.0-mix)+wet*mix)


def ring_modulate(signal, rate, frequency, amount=0.3):
    carrier = osc(np.full(signal.size, float(frequency), dtype=np.float64), rate, 'sine')
    return f32(signal*(1.0-amount)+signal*carrier*amount)


def saturate(signal, drive=3.0):
    """Soft clipping; raises density without the hard edges of digital clipping."""
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak < 1e-9: return signal
    return f32(np.tanh(signal/peak*max(drive, 1e-3))/np.tanh(max(drive, 1e-3))*peak)


def fade(signal, rate, seconds=0.006):
    ramp = min(max(int(seconds*rate), 1), max(signal.size//2, 1))
    signal = signal.copy()
    signal[:ramp] *= np.linspace(0.0, 1.0, ramp, dtype=np.float32)
    signal[-ramp:] *= np.linspace(1.0, 0.0, ramp, dtype=np.float32)
    return signal


def normalize(signal, peak_dbfs):
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak < 1e-9: return signal
    return f32(signal*(10.0**(float(peak_dbfs)/20.0)/peak))


def place(target, block, start):
    start = max(int(start), 0)
    usable = min(block.size, target.size-start)
    if usable > 0:
        target[start:start+usable] += block[:usable]
    return target


def measure(signal):
    if not signal.size: return {'peak_dbfs': -200.0, 'rms_dbfs': -200.0}
    peak = float(np.max(np.abs(signal)))
    rms = float(np.sqrt(np.mean(np.square(signal.astype(np.float64)))))
    to_db = lambda value: round(20.0*np.log10(value), 3) if value > 1e-10 else -200.0
    return {'peak_dbfs': to_db(peak), 'rms_dbfs': to_db(rms)}
