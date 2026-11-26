"""Qwen3-TTS worker (engine 'torch'). Keeps one model resident between requests.

synthesize {"model_path": "<dir>", "model": "1.7B-CustomVoice", "mode": "custom|clone|design", "text": "...",
            "language": "French", "speaker": "Ryan", "instruction": "", "reference_audio": "", "reference_text": "",
            "x_vector_only": false, "device": "cuda|cpu", "delivery": "paragraphs|segments|complete",
            "temperature": 0.9, "top_k": 50, "top_p": 1.0, "repetition_penalty": 1.05, "max_new_tokens": 2048,
            "seed": 42, "text_annotations": false, "output_dir": "<dir inside workspace>", "workspace": "..."}
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers._protocol import serve, WorkerError, inside, memory_report  # noqa: E402

_model = None
_model_key = None


def _load(model_path, device, reporter):
    global _model, _model_key
    import torch
    from qwen_tts import Qwen3TTSModel
    key = (str(model_path), device)
    if _model is not None and _model_key == key:
        return _model
    unload({}, reporter)
    if device == 'cuda' and not torch.cuda.is_available():
        raise WorkerError('MissingDependency', 'CUDA is not available in the engine; choose the CPU device', recoverable=True)
    if not Path(model_path, 'config.json').is_file():
        raise WorkerError('MissingModel', 'Qwen3-TTS weights not found: ' + str(model_path), recoverable=True)
    reporter.progress(2, step='Loading model', message=Path(model_path).name)
    torch.set_num_threads(min(8, os.cpu_count() or 4))
    _model = Qwen3TTSModel.from_pretrained(str(model_path), device_map='cuda:0' if device == 'cuda' else 'cpu',
                                           dtype=torch.bfloat16 if device == 'cuda' else torch.float32, attn_implementation='sdpa')
    _model_key = key
    reporter.resident(model=str(model_path), gpu=device == 'cuda')
    return _model


def unload(request, reporter):
    global _model, _model_key
    _model = None
    _model_key = None
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
    import numpy as np
    import soundfile as sf
    import torch
    from audiostudio.voice.annotations import build_plan, render_plan, AnnotationError
    started = time.monotonic()
    device = request.get('device', 'cuda')
    model = _load(request['model_path'], device, reporter)
    torch.manual_seed(int(request.get('seed', 42)))
    mode = request.get('mode', 'custom')
    try:
        plan = build_plan(request['text'], enabled=bool(request.get('text_annotations', False)), delivery=request.get('delivery', 'paragraphs'),
                          base_instruction=request.get('instruction', '') or '')
    except AnnotationError as exc:
        raise WorkerError('InvalidParameters', str(exc))
    common = dict(language=request.get('language', 'Auto'), temperature=float(request.get('temperature', 0.9)), top_k=int(request.get('top_k', 50)),
                  top_p=float(request.get('top_p', 1.0)), repetition_penalty=float(request.get('repetition_penalty', 1.05)),
                  max_new_tokens=int(request.get('max_new_tokens', 2048)), do_sample=True)
    prompt = None
    if mode == 'clone':
        reference = request.get('reference_audio') or ''
        if not Path(reference).is_file():
            raise WorkerError('MissingInput', 'Reference audio not found: ' + reference)
        reporter.progress(4, step='Encoding reference voice')
        prompt = model.create_voice_clone_prompt(ref_audio=reference, ref_text=request.get('reference_text') or None,
                                                 x_vector_only_mode=bool(request.get('x_vector_only', False)))
    workspace = request.get('workspace')
    out_dir = inside(workspace, request['output_dir']) if workspace else Path(request['output_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks, arrays, timeline = [], [], []
    offset = 0
    speech_items = [i for i in plan if 'text' in i]

    def synthesize_item(item):
        reporter.progress(5 + 90 * len(chunks) / max(1, len(plan)), step='Generating passage', message=item['text'][:80])
        if mode == 'custom':
            wavs, rate = model.generate_custom_voice(text=item['text'], speaker=request.get('speaker', 'Ryan'), instruct=item['instruction'], **common)
        elif mode == 'design':
            wavs, rate = model.generate_voice_design(text=item['text'], instruct=item['instruction'], **common)
        else:
            wavs, rate = model.generate_voice_clone(text=item['text'], voice_clone_prompt=prompt, **common)
        return wavs[0], rate

    def emit(audio, rate, item):
        nonlocal offset
        path = out_dir / f'segment-{len(chunks) + 1:04d}.wav'
        sf.write(str(path), audio, rate, subtype='PCM_16')
        timeline.append({**{k: v for k, v in item.items() if k != 'instruction'}, 'startSample': offset, 'sampleCount': int(len(audio)), 'file': str(path)})
        offset += len(audio)
        arrays.append(audio)
        chunks.append(str(path))
        reporter.progress(5 + 90 * len(chunks) / max(1, len(plan)), step='Segment ready', message=f'{len(chunks)}/{len(plan)}', currentFile=str(path))

    rate = render_plan(plan, synthesize_item, emit)
    audio = np.concatenate(arrays)
    output = out_dir / 'speech.wav'
    sf.write(str(output), audio, rate, subtype='PCM_16')
    reporter.progress(100, step='Done')
    return {'file': str(output), 'sampleRate': int(rate), 'durationSeconds': float(len(audio)) / rate, 'channels': 1,
            'chunks': chunks, 'segments': timeline, 'passages': len(speech_items), 'mode': mode, 'model': request.get('model', ''),
            'generationSeconds': round(time.monotonic() - started, 3), **memory_report()}


def diagnose(request, reporter):
    import torch
    import importlib.metadata
    return {'torch': torch.__version__, 'cuda': torch.cuda.is_available(), 'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else '',
            'qwenTts': importlib.metadata.version('qwen-tts'), 'resident': _model_key[0] if _model_key else ''}


HANDLERS = {'synthesize': synthesize, 'unload': unload, 'diagnose': diagnose, 'status': diagnose}

if __name__ == '__main__':
    raise SystemExit(serve(HANDLERS))
