"""AudioLDM worker (engine 'torch'). Keeps the pipeline resident between requests.

generate {"model_dir": "<dir>", "prompt": "...", "negative_prompt": "", "steps": 20, "guidance_scale": 2.5,
          "duration_seconds": 5.0, "seed": 0, "device": "cuda|cpu", "cpu_threads": 4, "output_files": [...],
          "sample_rate": 44100, "peak_dbfs": -1.0, "bit_depth": 16, "workspace": "..."}
"""
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers._protocol import serve, WorkerError, inside, memory_report  # noqa: E402

NATIVE_SAMPLE_RATE = 16000
_pipeline = None
_pipeline_key = None


def _load(model_dir, device, reporter):
    global _pipeline, _pipeline_key
    import torch
    from diffusers import AudioLDMPipeline
    key = (str(model_dir), device)
    if _pipeline is not None and _pipeline_key == key:
        return _pipeline
    unload({}, reporter)
    if device == 'cuda' and not torch.cuda.is_available():
        raise WorkerError('MissingDependency', 'CUDA is not available in the engine; choose the CPU device', recoverable=True)
    if not Path(model_dir, 'model_index.json').is_file():
        raise WorkerError('MissingModel', 'AudioLDM weights not found: ' + str(model_dir), recoverable=True)
    reporter.progress(3, step='Loading AudioLDM')
    pipeline = AudioLDMPipeline.from_pretrained(str(model_dir), torch_dtype=torch.float32, local_files_only=True).to(device)
    pipeline.set_progress_bar_config(disable=True)
    _pipeline, _pipeline_key = pipeline, key
    reporter.resident(model=str(model_dir), gpu=device == 'cuda')
    return pipeline


def unload(request, reporter):
    global _pipeline, _pipeline_key
    _pipeline = None
    _pipeline_key = None
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


def _resample(values, source_rate, target_rate):
    import numpy as np
    from scipy.signal import resample_poly
    if int(source_rate) == int(target_rate):
        return values.astype(np.float32)
    divisor = math.gcd(int(source_rate), int(target_rate))
    return resample_poly(values, target_rate // divisor, source_rate // divisor).astype(np.float32)


def generate(request, reporter):
    import numpy as np
    import soundfile as sf
    import torch
    started = time.monotonic()
    device = request.get('device', 'cuda')
    pipeline = _load(request['model_dir'], device, reporter)
    loaded = time.monotonic()
    workspace = request.get('workspace')
    targets = [inside(workspace, p) if workspace else Path(p) for p in request['output_files']]
    torch.set_num_threads(max(int(request.get('cpu_threads', 4)), 1))
    seed = int(request.get('seed', 0))
    torch.manual_seed(seed)
    generator = torch.Generator(device=device).manual_seed(seed)
    steps = int(request.get('steps', 20))
    duration = float(request.get('duration_seconds', 5.0))

    def callback(step, timestep, latents):
        reporter.progress(10 + 80 * (step + 1) / max(1, steps), step='Diffusion', message=f'step {step + 1}/{steps}')

    reporter.progress(10, step='Diffusion')
    result = pipeline(prompt=request['prompt'], negative_prompt=request.get('negative_prompt') or None, num_inference_steps=steps,
                      guidance_scale=float(request.get('guidance_scale', 2.5)), audio_length_in_s=duration,
                      num_waveforms_per_prompt=len(targets), generator=generator, callback=callback, callback_steps=1)
    waveforms = np.asarray(result.audios, dtype=np.float32)
    if waveforms.ndim == 1:
        waveforms = waveforms[None, :]
    if not np.isfinite(waveforms).all():
        raise WorkerError('InferenceFailed', 'The pipeline produced non-finite samples')
    inferred = time.monotonic()
    rate = int(request.get('sample_rate', 44100))
    wanted = int(round(duration * rate))
    ceiling = 10.0 ** (float(request.get('peak_dbfs', -1.0)) / 20.0)
    subtype = 'PCM_24' if int(request.get('bit_depth', 16)) == 24 else 'PCM_16'
    produced = []
    for index, path in enumerate(targets):
        values = _resample(waveforms[min(index, waveforms.shape[0] - 1)], NATIVE_SAMPLE_RATE, rate)
        if values.size < wanted:
            values = np.pad(values, (0, wanted - values.size))
        values = values[:wanted]
        peak = float(np.max(np.abs(values)))
        if peak > 1e-9:
            values = values * (ceiling / peak)
        sf.write(str(path), values, rate, subtype=subtype)
        rms = float(np.sqrt(np.mean(np.square(values.astype(np.float64)))))
        produced.append({'file': str(path), 'seed': seed + index, 'durationSeconds': round(values.size / rate, 4),
                         'peakDbfs': round(20.0 * math.log10(max(float(np.max(np.abs(values))), 1e-10)), 3),
                         'rmsDbfs': round(20.0 * math.log10(max(rms, 1e-10)), 3), 'sizeBytes': path.stat().st_size})
    reporter.progress(100, step='Done')
    return {'variations': produced, 'engine': 'audioldm', 'device': device, 'nativeSampleRate': NATIVE_SAMPLE_RATE, 'precision': 'float32',
            'torch': torch.__version__, 'timings': {'loadSeconds': round(loaded - started, 3), 'inferenceSeconds': round(inferred - loaded, 3),
                                                    'totalSeconds': round(time.monotonic() - started, 3)}, **memory_report()}


def diagnose(request, reporter):
    import torch
    import diffusers
    return {'torch': torch.__version__, 'diffusers': diffusers.__version__, 'cuda': torch.cuda.is_available(),
            'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else '', 'resident': _pipeline_key[0] if _pipeline_key else ''}


HANDLERS = {'generate': generate, 'unload': unload, 'diagnose': diagnose, 'status': diagnose}

if __name__ == '__main__':
    raise SystemExit(serve(HANDLERS))
