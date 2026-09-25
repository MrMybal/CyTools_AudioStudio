"""Fish Speech S2 Pro worker (engine 'torch', CUDA only). Keeps the model resident.

synthesize {"model_dir": "<dir with model safetensors + codec.pth>", "turns": [{"speaker": 0, "text": "...", "expression": ""}],
            "references": [{"audio": "<wav>", "text": "..."}], "temperature": 0.8, "top_p": 0.8, "top_k": 30, "seed": 42,
            "max_new_tokens": 1024, "chunk_length": 200, "gpu_index": 0, "precision": "bfloat16", "output": "<wav>", "workspace": "..."}
"""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers._protocol import serve, WorkerError, inside, memory_report  # noqa: E402

_state = {}


def _load(model_dir, device, precision_name, reporter):
    import torch
    from fish_speech.models.text2semantic.inference import init_model, load_codec_model
    key = (str(model_dir), device, precision_name)
    if _state.get('key') == key:
        return _state['model'], _state['decode'], _state['codec']
    unload({}, reporter)
    if not torch.cuda.is_available():
        raise WorkerError('MissingDependency', 'Fish Speech requires an NVIDIA CUDA GPU', recoverable=True)
    model_dir = Path(model_dir)
    if not (model_dir / 'codec.pth').is_file():
        raise WorkerError('MissingModel', 'Fish Speech S2 Pro weights not found: ' + str(model_dir), recoverable=True)
    precision = torch.float16 if precision_name == 'float16' else torch.bfloat16
    reporter.progress(5, step='Loading S2 Pro')
    torch.set_num_threads(4)
    with torch.inference_mode():
        model, decode = init_model(model_dir, device, precision, compile=False)
        with torch.device(device):
            model.setup_caches(max_batch_size=1, max_seq_len=model.config.max_seq_len, dtype=precision)
        reporter.progress(20, step='Loading audio codec')
        codec = load_codec_model(model_dir / 'codec.pth', device, precision)
    _state.update(key=key, model=model, decode=decode, codec=codec, device=device)
    reporter.resident(model=str(model_dir), gpu=True)
    return model, decode, codec


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


def synthesize(request, reporter):
    import soundfile as sf
    import torch
    from fish_speech.models.text2semantic.inference import encode_audio, decode_to_audio, generate_long
    started = time.monotonic()
    device = 'cuda:' + str(int(request.get('gpu_index', 0)))
    model, decode, codec = _load(request['model_dir'], device, request.get('precision', 'bfloat16'), reporter)
    seed = int(request.get('seed', 42))
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    references = request.get('references') or []
    turns = request.get('turns') or []
    if not turns:
        raise WorkerError('InvalidParameters', 'At least one turn is required')
    workspace = request.get('workspace')
    output = inside(workspace, request['output']) if workspace else Path(request['output'])
    with torch.inference_mode():
        prompts = []
        for index, reference in enumerate(references):
            audio_path = Path(reference['audio'])
            if not audio_path.is_file():
                raise WorkerError('MissingInput', 'Reference audio not found: ' + str(audio_path))
            info = sf.info(str(audio_path))
            if not 0.1 <= info.duration <= 30:
                raise WorkerError('InvalidParameters', 'Each reference must last between 0.1 and 30 seconds')
            prompts.append(encode_audio(audio_path, codec, device).cpu())
            reporter.progress(25, step='Reference encoded', message=f'{index + 1}/{len(references)}')
        text = '\n'.join(f"<|speaker:{int(t.get('speaker', 0))}|>{('[' + t['expression'] + '] ') if t.get('expression') else ''}{t['text']}" for t in turns)
        codes = []
        reporter.progress(30, step='Generating audio tokens')
        generator = generate_long(model=model, device=device, decode_one_token=decode, text=text, num_samples=1,
                                  max_new_tokens=int(request.get('max_new_tokens', 1024)), top_p=float(request.get('top_p', 0.8)),
                                  top_k=int(request.get('top_k', 30)), temperature=float(request.get('temperature', 0.8)), compile=False,
                                  iterative_prompt=True, chunk_length=int(request.get('chunk_length', 200)),
                                  prompt_text=[r['text'] for r in references] or None, prompt_tokens=prompts or None)
        for response in generator:
            if response.action == 'sample':
                codes.append(response.codes)
                reporter.progress(min(80, 30 + len(codes) * 5), step='Generating audio tokens', message=f'{len(codes)} segment(s)')
            elif response.action != 'next':
                raise WorkerError('InferenceFailed', 'Unexpected engine response')
        if not codes:
            raise WorkerError('InferenceFailed', 'The engine produced no audio tokens')
        reporter.progress(85, step='Decoding audio')
        audio = decode_to_audio(torch.cat(codes, dim=1).to(device), codec).cpu().float().numpy()
    sf.write(str(output), audio, codec.sample_rate, subtype='PCM_16')
    frames = audio.shape[-1] if audio.ndim > 1 else len(audio)
    reporter.progress(100, step='Done')
    return {'file': str(output), 'sampleRate': int(codec.sample_rate), 'durationSeconds': float(frames) / codec.sample_rate,
            'channels': int(audio.shape[0]) if audio.ndim == 2 else 1, 'turns': len(turns), 'references': len(references),
            'generationSeconds': round(time.monotonic() - started, 3), **memory_report()}


def diagnose(request, reporter):
    import torch
    return {'torch': torch.__version__, 'cuda': torch.cuda.is_available(), 'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else '',
            'gpuTotalBytes': torch.cuda.get_device_properties(0).total_memory if torch.cuda.is_available() else 0, 'resident': _state.get('key', ('',))[0]}


HANDLERS = {'synthesize': synthesize, 'unload': unload, 'diagnose': diagnose, 'status': diagnose}

if __name__ == '__main__':
    raise SystemExit(serve(HANDLERS))
