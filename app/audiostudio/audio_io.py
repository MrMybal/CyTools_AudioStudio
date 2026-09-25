"""Audio file decoding/encoding.

Buffers are float32 numpy arrays shaped (channels, frames), values in [-1, 1].
Priority: libsndfile (soundfile) for WAV/FLAC/OGG/AIFF/MP3 decoding and lossless
encoding, pedalboard for MP3 encoding, PyAV for AAC/M4A/WMA/Opus and anything else.
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np

READ_SUFFIXES = ('.wav', '.flac', '.ogg', '.oga', '.opus', '.aiff', '.aif', '.mp3', '.m4a', '.aac', '.wma', '.mp4', '.mkv', '.webm', '.mov', '.caf', '.w64', '.rf64')
WRITE_FORMATS = {
    'wav': {'suffix': '.wav', 'subtypes': ['PCM_16', 'PCM_24', 'PCM_32', 'FLOAT'], 'lossy': False},
    'flac': {'suffix': '.flac', 'subtypes': ['PCM_16', 'PCM_24'], 'lossy': False},
    'ogg': {'suffix': '.ogg', 'subtypes': ['VORBIS'], 'lossy': True},
    'aiff': {'suffix': '.aiff', 'subtypes': ['PCM_16', 'PCM_24', 'PCM_32', 'FLOAT'], 'lossy': False},
    'mp3': {'suffix': '.mp3', 'subtypes': ['MPEG_LAYER_III'], 'lossy': True},
    'aac': {'suffix': '.m4a', 'subtypes': ['AAC'], 'lossy': True},
}
LOSSY_BITRATES = (64, 96, 128, 160, 192, 256, 320)


@dataclass
class AudioInfo:
    path: str
    samplerate: int
    channels: int
    frames: int
    duration: float
    format: str
    subtype: str

    def as_dict(self):
        return self.__dict__.copy()


def _as_planar(data):
    """soundfile returns (frames, channels); convert to (channels, frames) float32 contiguous."""
    array = np.asarray(data, dtype=np.float32)
    if array.ndim == 1:
        array = array[np.newaxis, :]
    else:
        array = array.T
    return np.ascontiguousarray(array)


def probe(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    try:
        import soundfile as sf
        info = sf.info(str(path))
        return AudioInfo(str(path), int(info.samplerate), int(info.channels), int(info.frames),
                         float(info.frames) / float(info.samplerate) if info.samplerate else 0.0,
                         str(info.format), str(info.subtype))
    except Exception:
        pass
    import av
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == 'audio'), None)
        if stream is None:
            raise ValueError('No audio stream in ' + str(path))
        rate = int(stream.codec_context.sample_rate or 0)
        channels = int(getattr(stream.codec_context, 'channels', 0) or getattr(stream.layout, 'nb_channels', 0) or 0)
        duration = float(stream.duration * stream.time_base) if stream.duration else float(container.duration / 1_000_000) if container.duration else 0.0
        return AudioInfo(str(path), rate, channels, int(duration * rate), duration, str(stream.codec_context.name), '')


def load(path, samplerate=None, mono=False, dtype=np.float32):
    """Decode a whole file. Returns (audio[channels, frames], samplerate)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    audio, rate = None, None
    try:
        import soundfile as sf
        data, rate = sf.read(str(path), dtype='float32', always_2d=True)
        audio = _as_planar(data)
    except Exception:
        audio = None
    if audio is None:
        audio, rate = _load_with_av(path)
    if mono and audio.shape[0] > 1:
        audio = np.mean(audio, axis=0, keepdims=True)
    if samplerate and int(samplerate) != int(rate):
        audio = resample(audio, rate, int(samplerate))
        rate = int(samplerate)
    return np.ascontiguousarray(audio.astype(dtype, copy=False)), int(rate)


def _load_with_av(path):
    import av
    frames = []
    rate = None
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == 'audio'), None)
        if stream is None:
            raise ValueError('No audio stream in ' + str(path))
        resampler = None
        for frame in container.decode(stream):
            if rate is None:
                rate = int(frame.sample_rate)
                resampler = av.AudioResampler(format='fltp', layout=frame.layout.name, rate=rate)
            for converted in resampler.resample(frame):
                frames.append(converted.to_ndarray().astype(np.float32))
        if resampler is not None:
            for converted in resampler.resample(None):
                frames.append(converted.to_ndarray().astype(np.float32))
    if not frames:
        raise ValueError('Empty audio stream in ' + str(path))
    audio = np.concatenate(frames, axis=1)
    return np.ascontiguousarray(audio), int(rate)


def resample(audio, source_rate, target_rate):
    if int(source_rate) == int(target_rate):
        return audio
    # Polyphase resampling gives an exact length change (pedalboard's Resample keeps the host rate).
    from scipy.signal import resample_poly
    from math import gcd
    factor = gcd(int(source_rate), int(target_rate))
    up, down = int(target_rate) // factor, int(source_rate) // factor
    return np.ascontiguousarray(resample_poly(audio, up, down, axis=1).astype(np.float32))


def save(path, audio, samplerate, fmt=None, subtype=None, bitrate_kbps=192):
    """Encode a buffer. Returns the written path. Format is inferred from the suffix when omitted."""
    path = Path(path)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[np.newaxis, :]
    if fmt is None:
        fmt = next((k for k, v in WRITE_FORMATS.items() if v['suffix'] == path.suffix.lower()), None)
        if fmt is None and path.suffix.lower() in ('.aif',):
            fmt = 'aiff'
        if fmt is None:
            raise ValueError('Unsupported output format: ' + path.suffix)
    spec = WRITE_FORMATS[fmt]
    if spec['lossy'] or not subtype:
        # Lossy encoders have a single sample format; a PCM subtype chosen for WAV/FLAC is ignored.
        subtype = spec['subtypes'][0]
    if subtype not in spec['subtypes']:
        raise ValueError(f'Subtype {subtype} is not valid for {fmt}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt in ('wav', 'flac', 'ogg', 'aiff'):
        import soundfile as sf
        sf.write(str(path), np.ascontiguousarray(audio.T), int(samplerate), format=fmt.upper(), subtype=subtype)
    elif fmt == 'mp3':
        from pedalboard.io import AudioFile
        with AudioFile(str(path), 'w', samplerate=float(samplerate), num_channels=int(audio.shape[0]), quality=int(bitrate_kbps)) as handle:
            handle.write(audio)
    elif fmt == 'aac':
        _save_with_av(path, audio, samplerate, 'aac', bitrate_kbps)
    return path


def _save_with_av(path, audio, samplerate, codec, bitrate_kbps):
    import av
    layout = 'mono' if audio.shape[0] == 1 else 'stereo' if audio.shape[0] == 2 else None
    if layout is None:
        raise ValueError('AAC export supports mono or stereo only')
    with av.open(str(path), 'w') as container:
        stream = container.add_stream(codec, rate=int(samplerate))
        stream.bit_rate = int(bitrate_kbps) * 1000
        stream.layout = layout
        stream.format = 'fltp'
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(audio), format='fltp', layout=layout)
        frame.sample_rate = int(samplerate)
        frame.pts = 0
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def peak_dbfs(audio):
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    return 20.0 * np.log10(peak) if peak > 0 else -np.inf


def rms_dbfs(audio):
    if not audio.size:
        return -np.inf
    value = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    return 20.0 * np.log10(value) if value > 0 else -np.inf
