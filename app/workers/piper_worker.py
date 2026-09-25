"""Piper worker (engine 'piper', CPU). Keeps the last voices loaded between requests.

synthesize {"model": "<path to voice .onnx>", "text": "...", "speaker": 0, "length_scale": 1.0, "noise_scale": 0.667,
            "noise_w_scale": 0.8, "volume": 1.0, "normalize": true, "threads": 2, "output": "<wav path>", "workspace": "..."}
"""
import json
from pathlib import Path
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers._protocol import serve, WorkerError, inside  # noqa: E402

_voices = {}


def _voice(model_path, threads):
    from piper import PiperVoice
    from piper.config import PiperConfig
    import onnxruntime as ort
    key = (str(model_path), int(threads))
    if key in _voices:
        return _voices[key]
    model = Path(model_path)
    config_path = Path(str(model) + '.json')
    if not model.is_file() or not config_path.is_file():
        raise WorkerError('MissingModel', 'Piper voice files not found: ' + str(model), recoverable=True)
    config = json.loads(config_path.read_text('utf-8'))
    options = ort.SessionOptions()
    options.intra_op_num_threads = int(threads)
    options.inter_op_num_threads = 1
    voice = PiperVoice(config=PiperConfig.from_dict(config), session=ort.InferenceSession(str(model), sess_options=options, providers=['CPUExecutionProvider']))
    voice.use_tashkeel = False
    if len(_voices) >= 3:
        _voices.clear()
    _voices[key] = voice
    return voice


def synthesize(request, reporter):
    from piper import SynthesisConfig
    started = time.monotonic()
    reporter.progress(5, step='Loading voice')
    voice = _voice(request['model'], request.get('threads', 2))
    speaker = int(request.get('speaker', 0))
    if speaker >= voice.config.num_speakers:
        raise WorkerError('InvalidParameters', f'Speaker index {speaker} is out of range for this voice ({voice.config.num_speakers} speakers)')
    settings = SynthesisConfig(speaker_id=speaker, length_scale=float(request.get('length_scale', 1.0)), noise_scale=float(request.get('noise_scale', 0.667)),
                               noise_w_scale=float(request.get('noise_w_scale', 0.8)), volume=float(request.get('volume', 1.0)),
                               normalize_audio=bool(request.get('normalize', True)))
    workspace = request.get('workspace')
    output = inside(workspace, request['output']) if workspace else Path(request['output'])
    reporter.progress(15, step='Synthesising')
    with wave.open(str(output), 'wb') as handle:
        voice.synthesize_wav(request['text'], handle, syn_config=settings)
    with wave.open(str(output), 'rb') as handle:
        frames, rate = handle.getnframes(), handle.getframerate()
    if frames <= 0:
        raise WorkerError('InferenceFailed', 'No audio produced')
    reporter.progress(100, step='Done')
    return {'file': str(output), 'sampleRate': rate, 'durationSeconds': frames / rate, 'channels': 1,
            'elapsedSeconds': round(time.monotonic() - started, 3), 'numSpeakers': int(voice.config.num_speakers)}


def diagnose(request, reporter):
    import importlib.metadata
    import onnxruntime
    return {'piperVersion': importlib.metadata.version('piper-tts'), 'onnxVersion': onnxruntime.__version__,
            'providers': onnxruntime.get_available_providers(), 'loadedVoices': len(_voices)}


def unload(request, reporter):
    _voices.clear()
    return {'unloaded': True}


HANDLERS = {'synthesize': synthesize, 'diagnose': diagnose, 'status': diagnose, 'unload': unload}

if __name__ == '__main__':
    raise SystemExit(serve(HANDLERS))
