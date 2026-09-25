"""Sound-effect and music generation operations."""
import random
from pathlib import Path

from cytools_core import CyToolError

from ..paths import DATA
from .. import models as model_catalog
from .common import GiB, MiB, selected_backend, require_file, post_process, describe_file, write_report, copy_into_workspace

DEFAULT_SFX_STEPS = 20


def register(runtime, services):
    # ------------------------------------------------------------------ SFX
    def generate_sfx(context, parameters):
        backend = selected_backend(context)
        if backend not in ('sfx_procedural', 'audioldm'):
            raise CyToolError('UnsupportedBackend', 'generate_sfx needs backendId sfx_procedural or audioldm')
        variations = int(parameters.get('variations', 1))
        outputs = [str(context.path(f'outputs/sound_{index + 1:02d}.wav')) for index in range(variations)]
        warnings = []
        context.progress(1, currentStep='Starting', stepCount=2, currentStepIndex=1)
        if backend == 'sfx_procedural':
            for key in ('negative_prompt', 'steps', 'guidance_scale'):
                if parameters.get(key) not in (None, '', DEFAULT_SFX_STEPS if key == 'steps' else 2.5 if key == 'guidance_scale' else ''):
                    warnings.append(f'{key} is ignored by the procedural backend')
            payload = {'prompt': parameters['prompt'], 'seed': int(parameters.get('seed', 0)), 'sample_rate': int(parameters.get('sample_rate', 44100)),
                       'duration_seconds': parameters.get('duration_seconds'), 'peak_dbfs': float(parameters.get('peak_dbfs', -1.0)),
                       'bit_depth': int(parameters.get('bit_depth', 16)), 'output_files': outputs}
            result = services.run(context, 'sfx_procedural', 'generate', payload, progress_scale=0.9)
            engine = 'procedural-dsp'
        else:
            model = model_catalog.installed_default('audioldm')
            if model is None:
                raise CyToolError('MissingModel', 'AudioLDM weights are not installed (see list_models / install_model)', recoverable=True)
            duration = parameters.get('duration_seconds') or 5.0
            if int(parameters.get('sample_rate', 44100)) != 16000:
                warnings.append('AudioLDM generates at 16 kHz; the output is resampled to the requested rate')
            if duration > 15:
                warnings.append('AudioLDM tends to loop beyond 15 seconds')
            payload = {'model_dir': str(model_catalog.directory(model)), 'prompt': parameters['prompt'], 'negative_prompt': parameters.get('negative_prompt', ''),
                       'steps': int(parameters.get('steps', DEFAULT_SFX_STEPS)), 'guidance_scale': float(parameters.get('guidance_scale', 2.5)), 'duration_seconds': float(duration),
                       'seed': int(parameters.get('seed', 0)), 'device': parameters.get('device', 'cuda'), 'cpu_threads': 8, 'output_files': outputs,
                       'sample_rate': int(parameters.get('sample_rate', 44100)), 'peak_dbfs': float(parameters.get('peak_dbfs', -1.0)), 'bit_depth': int(parameters.get('bit_depth', 16))}
            result = services.run(context, 'audioldm', 'generate', payload, progress_scale=0.9)
            engine = 'audioldm'
            if result.get('vramPeakBytes') is not None:
                try:
                    context.observe_resources({'ramBytes': int(result.get('workerMemoryBytes', 0)), 'vramBytes': {'0': int(result.get('vramPeakBytes', 0))}})
                except Exception:
                    pass
        post = parameters.get('post_workflow') or ''
        for index, item in enumerate(result['variations']):
            if post:
                processed = post_process(services, context, item['file'], post, progress_offset=90 + index * 10.0 / max(1, variations), progress_scale=0.1 / max(1, variations))
                item['processedFile'] = processed['file']
        warnings += list(result.get('warnings', []))
        report = {'backend': backend, 'engine': engine, 'parameters': parameters, 'variations': result['variations'], 'warnings': warnings,
                  'timings': result.get('timings'), 'recipe': result.get('recipe')}
        report_file = write_report(context, 'generation.json', report)
        context.progress(100, currentStep='Done', stepCount=2, currentStepIndex=2)
        return {'variations': result['variations'], 'backend': backend, 'engine': engine, 'sampleRate': int(parameters.get('sample_rate', 44100)),
                'recipe': result.get('recipe'), 'warnings': warnings, 'report': {'file': report_file, 'timings': result.get('timings')}}

    def preview_sfx_recipe(context, parameters):
        return services.run(context, 'sfx_procedural', 'preview', dict(parameters))

    def list_sfx_types(context, parameters):
        return services.run(context, 'sfx_procedural', 'catalogue', dict(parameters))

    def estimate_sfx(parameters, backend, model):
        backend_id = (backend or {}).get('id', 'sfx_procedural')
        seconds = float(parameters.get('duration_seconds') or 5.0)
        variations = int(parameters.get('variations', 1))
        if backend_id == 'audioldm':
            load = variations * seconds / 5.0
            if parameters.get('device', 'cuda') == 'cuda':
                return {'ramBytes': int(3 * GiB + 0.25 * GiB * load), 'vramBytes': {'auto': int(2.5 * GiB + 0.4 * GiB * load)}, 'cpuThreads': 4, 'diskBytes': 64 * MiB}
            return {'ramBytes': int(4 * GiB + 0.5 * GiB * load), 'vramBytes': {}, 'cpuThreads': 8, 'diskBytes': 64 * MiB}
        return {'ramBytes': int(256 * MiB + seconds * 48000 * 4 * 24 * 3 * variations), 'vramBytes': {}, 'cpuThreads': 2, 'diskBytes': int(seconds * 48000 * 3 * variations + 8 * MiB)}

    runtime.register('generate_sfx', generate_sfx, estimate=estimate_sfx)
    runtime.register('preview_sfx_recipe', preview_sfx_recipe)
    runtime.register('list_sfx_types', list_sfx_types)

    # ------------------------------------------------------------------ music (ACE-Step)
    def acestep_base(context):
        model = model_catalog.installed_default('acestep')
        if model is None:
            raise CyToolError('MissingModel', 'ACE-Step 1.5 checkpoints are not installed (see list_models / install_model)', recoverable=True)
        gpus = [g for g in services.runtime.system.get('gpus', []) if 'CUDA' in g.get('computeBackends', [])]
        if not gpus:
            raise CyToolError('UnsupportedGPU', 'ACE-Step requires an NVIDIA CUDA GPU', recoverable=True)
        total = int(gpus[0].get('vramTotalBytes') or gpus[0].get('memoryTotalBytes') or 0)
        return {'checkpoints_dir': str(model_catalog.directory(model)), 'cache_dir': str(DATA / 'cache' / 'acestep'), 'device_index': gpus[0].get('index', 0),
                'offload_to_cpu': bool(total and total < 20 * GiB)}

    def seeds_for(parameters):
        count = int(parameters.get('track_count', 1))
        seed = parameters.get('seed')
        if seed is None:
            rng = random.SystemRandom()
            return [rng.randrange(0, 2 ** 31) for _ in range(count)]
        return [(int(seed) + n) % (2 ** 31) for n in range(count)]

    def music_request(parameters, task, **extra):
        request = {'task_type': task, 'caption': parameters['caption'], 'lyrics': parameters.get('lyrics', ''), 'instrumental': bool(parameters.get('instrumental', False)),
                   'language': parameters.get('language', 'unknown'), 'bpm': parameters.get('bpm'), 'keyscale': parameters.get('keyscale', ''),
                   'time_signature': parameters.get('time_signature', ''), 'steps': int(parameters.get('steps', 8)), 'seeds': seeds_for(parameters),
                   'output_format': parameters.get('output_format', 'flac'), 'output_dir': 'outputs', 'plan_with_lm': False, 'creativity': 0.85, 'nucleus': 0.9,
                   'duration_seconds': -1.0, 'reference_audio': None, 'source_audio': None, 'audio_strength': 0.0, 'repaint_start': 0.0, 'repaint_end': -1.0,
                   'repaint_mode': 'balanced', 'repaint_strength': 0.5}
        request.update(extra)
        return request

    def finish_music(context, parameters, result, request, backend='acestep'):
        post = parameters.get('post_workflow') or ''
        for index, track in enumerate(result['tracks']):
            if post:
                processed = post_process(services, context, track['file'], post, progress_offset=90 + index * 10.0 / max(1, len(result['tracks'])), progress_scale=0.1 / max(1, len(result['tracks'])))
                track['processedFile'] = processed['file']
        if result.get('vramPeakBytes') is not None:
            try:
                context.observe_resources({'ramBytes': int(result.get('workerMemoryBytes', 0)), 'vramBytes': {'0': int(result.get('vramPeakBytes', 0))}})
            except Exception:
                pass
        report = {'backend': backend, 'parameters': parameters, 'request': {k: v for k, v in request.items() if k not in ('checkpoints_dir',)}, 'result': result}
        report_file = write_report(context, 'generation.json', report)
        context.progress(100, currentStep='Done')
        return {**result, 'report': {'file': report_file}}

    def generate_music(context, parameters):
        base = acestep_base(context)
        reference = parameters.get('reference_audio') or ''
        extra = {'duration_seconds': float(parameters.get('duration_seconds', 60.0)), 'plan_with_lm': bool(parameters.get('plan_with_lm', True)),
                 'creativity': float(parameters.get('creativity', 0.85)), 'nucleus': float(parameters.get('nucleus', 0.9))}
        if reference:
            source = require_file(reference, 'reference_audio')
            extra['reference_audio'] = str(copy_into_workspace(context, source, 'reference'))
            extra['audio_strength'] = float(parameters.get('reference_strength', 0.2))
        request = music_request(parameters, 'text2music', **extra)
        context.progress(1, currentStep='Starting')
        result = services.run(context, 'acestep', 'generate', {**base, **request}, progress_scale=0.9)
        return finish_music(context, parameters, result, request)

    def remix_music(context, parameters):
        base = acestep_base(context)
        source = require_file(parameters.get('source_audio'), 'source_audio')
        request = music_request(parameters, 'cover', source_audio=str(copy_into_workspace(context, source, 'source')), audio_strength=float(parameters.get('similarity', 0.6)))
        context.progress(1, currentStep='Starting')
        result = services.run(context, 'acestep', 'generate', {**base, **request}, progress_scale=0.9)
        return finish_music(context, parameters, result, request)

    def repaint_music(context, parameters):
        base = acestep_base(context)
        source = require_file(parameters.get('source_audio'), 'source_audio')
        start, end = float(parameters.get('start_seconds', 0.0)), float(parameters.get('end_seconds', -1.0))
        if end != -1.0 and end <= start:
            raise CyToolError('InvalidParameters', 'end_seconds must be greater than start_seconds (or -1 for the end of the file)')
        request = music_request(parameters, 'repaint', source_audio=str(copy_into_workspace(context, source, 'source')), repaint_start=start, repaint_end=end,
                                repaint_mode=parameters.get('repaint_mode', 'balanced'), repaint_strength=float(parameters.get('repaint_strength', 0.5)))
        context.progress(1, currentStep='Starting')
        result = services.run(context, 'acestep', 'generate', {**base, **request}, progress_scale=0.9)
        return finish_music(context, parameters, result, request)

    def write_lyrics(context, parameters):
        base = acestep_base(context)
        payload = {**base, 'mode': parameters.get('mode', 'create'), 'idea': parameters.get('idea', ''), 'caption': parameters.get('caption', ''), 'lyrics': parameters.get('lyrics', ''),
                   'instrumental': bool(parameters.get('instrumental', False)), 'language': parameters.get('language', 'unknown'), 'bpm': parameters.get('bpm'),
                   'duration_seconds': parameters.get('duration_seconds'), 'keyscale': parameters.get('keyscale', ''), 'time_signature': parameters.get('time_signature', ''),
                   'creativity': float(parameters.get('creativity', 0.85)), 'nucleus': float(parameters.get('nucleus', 0.9))}
        if payload['mode'] == 'create' and not payload['idea'].strip():
            raise CyToolError('InvalidParameters', 'Mode create needs an idea')
        if payload['mode'] == 'format' and not (payload['caption'].strip() or payload['lyrics'].strip()):
            raise CyToolError('InvalidParameters', 'Mode format needs a caption or lyrics')
        context.progress(1, currentStep='Starting')
        result = services.run(context, 'acestep', 'lyrics', payload, progress_scale=0.95)
        report_file = write_report(context, 'lyrics.json', {'parameters': parameters, 'result': result})
        context.progress(100, currentStep='Done')
        return {**result, 'report': {'file': report_file}}

    def estimate_music(parameters, backend, model):
        tracks = int(parameters.get('track_count', 1))
        duration = float(parameters.get('duration_seconds', 60.0) or 60.0)
        plan = bool(parameters.get('plan_with_lm', False)) and 'duration_seconds' in parameters
        vram = (9.5 * GiB) + (6.5 * GiB if plan else 0) + 4 * MiB * duration * tracks
        ram = (12.5 if plan else 6.5) * GiB
        return {'ramBytes': int(ram), 'vramBytes': {'auto': int(min(vram, 23 * GiB))}, 'cpuThreads': 4,
                'diskBytes': int({'flac': 130000, 'wav': 384000, 'mp3': 16000}.get(parameters.get('output_format', 'flac'), 130000) * duration * tracks + 64 * MiB),
                'durationSeconds': 60 + 20 * tracks}

    def estimate_lyrics(parameters, backend, model):
        return {'ramBytes': int(12 * GiB), 'vramBytes': {'auto': int(10 * GiB)}, 'cpuThreads': 4, 'diskBytes': 8 * MiB, 'durationSeconds': 45}

    runtime.register('generate_music', generate_music, estimate=estimate_music)
    runtime.register('remix_music', remix_music, estimate=estimate_music)
    runtime.register('repaint_music', repaint_music, estimate=estimate_music)
    runtime.register('write_lyrics', write_lyrics, estimate=estimate_lyrics)
