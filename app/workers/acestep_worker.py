"""ACE-Step 1.5 worker (engine 'torch', CUDA only). Keeps the DiT stack and the planning LM resident.

Requests carry: "checkpoints_dir" (folder holding acestep-v15-turbo, vae, Qwen3-Embedding-0.6B, acestep-5Hz-lm-1.7B),
"cache_dir" (data/cache/acestep), "device_index", "offload_to_cpu" and the operation payload:
  inspect  {}
  lyrics   {"mode": "create|format", "idea", "caption", "lyrics", "instrumental", "language", "bpm", "duration_seconds",
            "keyscale", "time_signature", "creativity", "nucleus"}
  generate {"task_type": "text2music|cover|repaint", "caption", "lyrics", "instrumental", "language", "bpm", "keyscale",
            "time_signature", "duration_seconds", "steps", "seeds": [...], "plan_with_lm", "creativity", "nucleus",
            "reference_audio", "source_audio", "audio_strength", "repaint_start", "repaint_end", "repaint_mode",
            "repaint_strength", "output_format", "output_dir", "workspace"}
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers._protocol import serve, WorkerError, inside, memory_report  # noqa: E402

DIT_MODEL = 'acestep-v15-turbo'
LM_MODEL = 'acestep-5Hz-lm-1.7B'
_state = {'configured': None, 'dit': None, 'llm': None}


def configure(request):
    """Everything the upstream package reads from the environment, set once per checkpoints dir."""
    checkpoints = str(request['checkpoints_dir'])
    if _state['configured'] == checkpoints:
        return
    os.environ['ACESTEP_DISABLE_TQDM'] = '1'
    os.environ['ACESTEP_CHECKPOINTS_DIR'] = checkpoints
    cache = Path(request.get('cache_dir') or Path(checkpoints).parent.parent / 'cache' / 'acestep')
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['ACESTEP_PROJECT_ROOT'] = str(cache)
    os.environ['CUDA_DEVICE_ORDER'] = 'PCI_BUS_ID'
    if request.get('device_index') is not None:
        os.environ['CUDA_VISIBLE_DEVICES'] = str(request['device_index'])
    _state['configured'] = checkpoints


def _require_cuda():
    import torch
    if not torch.cuda.is_available():
        raise WorkerError('MissingDependency', 'ACE-Step requires an NVIDIA CUDA GPU', recoverable=True)


def _load_dit(request, reporter):
    if _state['dit'] is not None:
        return _state['dit']
    from acestep.handler import AceStepHandler
    checkpoints = Path(request['checkpoints_dir'])
    if not (checkpoints / DIT_MODEL / 'config.json').is_file():
        raise WorkerError('MissingModel', 'ACE-Step checkpoints not found in ' + str(checkpoints), recoverable=True)
    reporter.progress(4, step='Loading models', message='ACE-Step DiT, VAE and text encoder')
    dit = AceStepHandler()
    message, success = dit.initialize_service(project_root=str(checkpoints.parent), config_path=DIT_MODEL, device='cuda',
                                              use_flash_attention=False, compile_model=False, offload_to_cpu=bool(request.get('offload_to_cpu', False)),
                                              offload_dit_to_cpu=False, quantization=None, use_mlx_dit=False)
    if not success:
        raise WorkerError('BackendUnavailable', 'ACE-Step did not initialize: ' + str(message))
    _state['dit'] = dit
    reporter.resident(model=str(checkpoints), gpu=True)
    return dit


def _load_llm(request, reporter):
    if _state['llm'] is not None:
        return _state['llm']
    from acestep.llm_inference import LLMHandler
    reporter.progress(12, step='Loading models', message='5Hz planning language model')
    handler = LLMHandler()
    message, success = handler.initialize(checkpoint_dir=str(request['checkpoints_dir']), lm_model_path=LM_MODEL, backend='pt',
                                          device='cuda', offload_to_cpu=False, dtype=None)
    if not success or not handler.llm_initialized:
        raise WorkerError('BackendUnavailable', 'The 5Hz language model did not initialize: ' + str(message))
    _state['llm'] = handler
    reporter.resident(model=str(request['checkpoints_dir']), gpu=True, llm=True)
    return handler


def _null_llm():
    from acestep.llm_inference import LLMHandler
    return LLMHandler()


def unload(request, reporter):
    _state['dit'] = None
    _state['llm'] = None
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


def inspect(request, reporter):
    configure(request)
    import torch
    import transformers
    import diffusers
    devices = []
    if torch.cuda.is_available():
        for index in range(torch.cuda.device_count()):
            properties = torch.cuda.get_device_properties(index)
            free, total = torch.cuda.mem_get_info(index)
            devices.append({'index': index, 'name': properties.name, 'capability': f'{properties.major}.{properties.minor}',
                            'vramTotalBytes': int(total), 'vramFreeBytes': int(free)})
    modules = {}
    for name in ('acestep.handler', 'acestep.inference', 'acestep.llm_inference'):
        try:
            __import__(name)
            modules[name] = 'OK'
        except Exception as exc:
            modules[name] = f'{type(exc).__name__}: {exc}'
    return {'python': sys.version.split()[0], 'torch': torch.__version__, 'torchCuda': torch.version.cuda or '', 'transformers': transformers.__version__,
            'diffusers': diffusers.__version__, 'cuda': bool(torch.cuda.is_available()),
            'bfloat16': bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported()), 'devices': devices, 'upstreamModules': modules,
            'resident': {'dit': _state['dit'] is not None, 'llm': _state['llm'] is not None}, **memory_report()}


def lyrics(request, reporter):
    configure(request)
    _require_cuda()
    from acestep.inference import create_sample, format_sample
    started = time.monotonic()
    handler = _load_llm(request, reporter)
    loaded = time.monotonic()
    reporter.progress(30, step='Generating', message='Writing lyrics and metadata')
    language = None if request.get('language', 'unknown') == 'unknown' else request['language']
    if request.get('mode', 'create') == 'create':
        result = create_sample(llm_handler=handler, query=request.get('idea', ''), instrumental=bool(request.get('instrumental', False)),
                               vocal_language=language, temperature=float(request.get('creativity', 0.85)), top_k=None, top_p=float(request.get('nucleus', 0.9)))
    else:
        metadata = {key: value for key, value in (('bpm', request.get('bpm')), ('duration', request.get('duration_seconds')),
                                                  ('keyscale', request.get('keyscale')), ('timesignature', request.get('time_signature')),
                                                  ('language', language)) if value}
        result = format_sample(llm_handler=handler, caption=request.get('caption', ''), lyrics=request.get('lyrics', ''), user_metadata=metadata or None,
                               temperature=float(request.get('creativity', 0.85)), top_k=None, top_p=float(request.get('nucleus', 0.9)))
    if not result.success:
        raise WorkerError('InferenceFailed', result.error or result.status_message or 'Lyric generation failed')
    reporter.progress(100, step='Done')
    return {'caption': result.caption or '', 'lyrics': result.lyrics or '',
            'metadata': {'bpm': result.bpm, 'durationSeconds': result.duration, 'keyscale': result.keyscale or '',
                         'timeSignature': result.timesignature or '', 'language': result.language or 'unknown',
                         'instrumental': bool(getattr(result, 'instrumental', False))},
            'statusMessage': result.status_message or '', 'lmModel': LM_MODEL,
            'timings': {'loadSeconds': round(loaded - started, 3), 'totalSeconds': round(time.monotonic() - started, 3)}, **memory_report()}


def generate(request, reporter):
    configure(request)
    _require_cuda()
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    started = time.monotonic()
    dit = _load_dit(request, reporter)
    plan = bool(request.get('plan_with_lm', False))
    language_model = _load_llm(request, reporter) if plan else _null_llm()
    loaded = time.monotonic()
    seeds = [int(s) for s in request['seeds']]
    workspace = request.get('workspace')
    output_dir = inside(workspace, request['output_dir']) if workspace else Path(request['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)
    params = GenerationParams(
        task_type=request['task_type'], caption=request.get('caption', ''), lyrics=request.get('lyrics', ''),
        instrumental=bool(request.get('instrumental', False)), vocal_language=request.get('language', 'unknown'),
        bpm=request.get('bpm'), keyscale=request.get('keyscale', ''), timesignature=request.get('time_signature', ''),
        duration=float(request.get('duration_seconds', -1.0)), inference_steps=int(request.get('steps', 8)), seed=seeds[0],
        thinking=plan, lm_temperature=float(request.get('creativity', 0.85)), lm_top_p=float(request.get('nucleus', 0.9)),
        use_cot_metas=plan, use_cot_caption=plan, use_cot_language=plan,
        reference_audio=request.get('reference_audio') or None, src_audio=request.get('source_audio') or None,
        audio_cover_strength=float(request.get('audio_strength', 0.0) or 0.0),
        repainting_start=float(request.get('repaint_start', 0.0) or 0.0), repainting_end=float(request.get('repaint_end', -1.0) if request.get('repaint_end') is not None else -1.0),
        repaint_mode=request.get('repaint_mode', 'balanced'), repaint_strength=float(request.get('repaint_strength', 0.5) or 0.5),
    )
    config = GenerationConfig(batch_size=len(seeds), use_random_seed=False, seeds=list(seeds), audio_format=request.get('output_format', 'flac'), allow_lm_batch=False)

    def report(ratio, desc=''):
        reporter.progress(20 + 76 * max(0.0, min(1.0, float(ratio))), step='Generating', message=str(desc)[:160])

    reporter.progress(20, step='Generating', message='Preparing conditioning')
    result = generate_music(dit, language_model, params, config, save_dir=str(output_dir), progress=report)
    if not result.success:
        raise WorkerError('InferenceFailed', result.error or result.status_message or 'Generation failed')
    tracks = _describe_tracks(result, seeds)
    if not tracks:
        raise WorkerError('InvalidOutput', 'Generation returned no audio file')
    reporter.progress(100, step='Done')
    return {'tracks': tracks, 'captionUsed': params.caption, 'lyricsUsed': params.lyrics, 'metadata': _lm_metadata(result),
            'taskType': request['task_type'], 'stepsUsed': params.inference_steps, 'sampleRate': tracks[0]['sampleRate'],
            'outputFormat': request.get('output_format', 'flac'), 'ditModel': DIT_MODEL, 'lmModel': LM_MODEL if plan else '',
            'statusMessage': result.status_message or '',
            'timings': {'loadSeconds': round(loaded - started, 3), 'generateSeconds': round(time.monotonic() - loaded, 3),
                        'totalSeconds': round(time.monotonic() - started, 3)}, **memory_report()}


def _describe_tracks(result, seeds):
    import soundfile as sf
    tracks = []
    for index, audio in enumerate(result.audios):
        path = audio.get('path') or ''
        if not path or not Path(path).is_file():
            continue
        with sf.SoundFile(path) as handle:
            duration, channels, rate = handle.frames / handle.samplerate, handle.channels, handle.samplerate
        tracks.append({'file': str(Path(path).resolve()), 'seed': int(seeds[index]) if index < len(seeds) else int(seeds[0]),
                       'durationSeconds': float(duration), 'channels': int(channels), 'sampleRate': int(audio.get('sample_rate') or rate),
                       'sizeBytes': int(Path(path).stat().st_size)})
    return tracks


def _lm_metadata(result):
    raw = (result.extra_outputs or {}).get('lm_metadata') or {}
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict):
        raw = {}

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    bpm = number(raw.get('bpm'))
    return {'bpm': int(bpm) if bpm else None, 'durationSeconds': number(raw.get('duration')), 'keyscale': str(raw.get('keyscale') or ''),
            'timeSignature': str(raw.get('timesignature') or ''), 'language': str(raw.get('language') or raw.get('vocal_language') or 'unknown')}


HANDLERS = {'inspect': inspect, 'lyrics': lyrics, 'generate': generate, 'unload': unload, 'status': inspect}

if __name__ == '__main__':
    raise SystemExit(serve(HANDLERS))
