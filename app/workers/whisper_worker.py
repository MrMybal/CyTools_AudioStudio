"""Whisper worker (engine 'torch'): speech recognition with timestamps. Model stays resident.

transcribe {"model_dir": "<dir>", "input": "<audio>", "language": "" (auto) | "fr" | ..., "device": "cuda|cpu",
            "timestamps": true, "workspace": "..."}
"""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers._protocol import serve, WorkerError, memory_report  # noqa: E402

_state = {}


def _load(model_dir, device, reporter):
    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
    key = (str(model_dir), device)
    if _state.get('key') == key:
        return _state['pipe']
    unload({}, reporter)
    if device == 'cuda' and not torch.cuda.is_available():
        raise WorkerError('MissingDependency', 'CUDA is not available; choose the CPU device', recoverable=True)
    if not Path(model_dir, 'config.json').is_file():
        raise WorkerError('MissingModel', 'Whisper weights not found: ' + str(model_dir), recoverable=True)
    reporter.progress(5, step='Loading Whisper')
    dtype = torch.float16 if device == 'cuda' else torch.float32
    model = AutoModelForSpeechSeq2Seq.from_pretrained(str(model_dir), dtype=dtype, low_cpu_mem_usage=True, use_safetensors=True, local_files_only=True).to(device)
    processor = AutoProcessor.from_pretrained(str(model_dir), local_files_only=True)
    pipe = pipeline('automatic-speech-recognition', model=model, tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor,
                    dtype=dtype, device=device)
    _state.update(key=key, pipe=pipe)
    reporter.resident(model=str(model_dir), gpu=device == 'cuda')
    return pipe


def unload(request, reporter):
    _state.clear()
    try:
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    reporter.resident()
    return {'unloaded': True}


def transcribe(request, reporter):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    started = time.monotonic()
    source = Path(request['input'])
    if not source.is_file():
        raise WorkerError('MissingInput', 'Audio not found: ' + str(source))
    pipe = _load(request['model_dir'], request.get('device', 'cuda'), reporter)
    reporter.progress(20, step='Reading audio')
    try:
        audio, rate = sf.read(str(source), dtype='float32', always_2d=True)
    except Exception:
        import av
        with av.open(str(source)) as container:
            stream = next(s for s in container.streams if s.type == 'audio')
            frames = [f.to_ndarray().astype(np.float32) for f in container.decode(stream)]
            rate = stream.codec_context.sample_rate
        audio = np.concatenate(frames, axis=1).T
    mono = audio.mean(axis=1)
    if rate != 16000:
        from math import gcd
        g = gcd(int(rate), 16000)
        mono = resample_poly(mono, 16000 // g, int(rate) // g).astype(np.float32)
    duration = len(mono) / 16000.0
    reporter.progress(35, step='Transcribing', message=f'{duration:.1f} s')
    kwargs = {'return_timestamps': bool(request.get('timestamps', True))}
    generate = {'task': 'transcribe'}
    if request.get('language'):
        generate['language'] = request['language']
    kwargs['generate_kwargs'] = generate
    if duration > 30:
        kwargs['chunk_length_s'] = 30
        kwargs['batch_size'] = 8
    result = pipe({'raw': mono, 'sampling_rate': 16000}, **kwargs)
    chunks = []
    for chunk in result.get('chunks') or []:
        stamp = chunk.get('timestamp') or (None, None)
        chunks.append({'start': stamp[0], 'end': stamp[1], 'text': chunk.get('text', '').strip()})
    reporter.progress(100, step='Done')
    return {'text': (result.get('text') or '').strip(), 'segments': chunks, 'durationSeconds': duration,
            'seconds': round(time.monotonic() - started, 3), **memory_report()}


def diagnose(request, reporter):
    import torch
    import transformers
    return {'torch': torch.__version__, 'transformers': transformers.__version__, 'cuda': torch.cuda.is_available(), 'resident': _state.get('key', ('',))[0]}


HANDLERS = {'transcribe': transcribe, 'unload': unload, 'diagnose': diagnose, 'status': diagnose}

if __name__ == '__main__':
    raise SystemExit(serve(HANDLERS))
