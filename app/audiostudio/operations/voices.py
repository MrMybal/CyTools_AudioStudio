"""Voice operations: Piper, Qwen3-TTS, Fish Speech, presets and the voice catalogue."""
from pathlib import Path

from cytools_core import CyToolError

from .. import models as model_catalog
from ..voice import presets as voice_presets
from ..voice.annotations import build_plan, AnnotationError
from .common import GiB, MiB, require_file, post_process, describe_file, write_report, copy_into_workspace

QWEN_MODE_SUFFIX = {'custom': 'CustomVoice', 'clone': 'Base', 'design': 'VoiceDesign'}


def _finish_voice(services, context, parameters, backend, model_id, result, preset_params, started_progress=90.0):
    file = result['file']
    info = describe_file(file)
    processed = None
    post = parameters.get('post_workflow') or ''
    if post:
        processed = post_process(services, context, file, post, progress_offset=started_progress, progress_scale=(100 - started_progress) / 100.0)
    preset = voice_presets.build(parameters.get('preset_name') or f'{backend} voice', backend, preset_params, model_id=model_id, post_workflow=post)
    preset.pop('id', None)
    report_file = write_report(context, 'generation.json', {'backend': backend, 'model': model_id, 'parameters': parameters, 'result': result, 'preset': preset})
    context.progress(100, currentStep='Done')
    return {**info, 'backend': backend, 'model': model_id, 'processedFile': processed['file'] if processed else '',
            'generationSeconds': float(result.get('generationSeconds') or result.get('elapsedSeconds') or 0.0), 'preset': preset,
            'warnings': list(result.get('warnings', [])), 'segments': result.get('segments', []), 'chunks': result.get('chunks', []), 'report': {'file': report_file}}


def register(runtime, services):
    def voice_piper(context, parameters):
        key = parameters.get('voice') or 'fr_FR-siwis-medium'
        model_id = model_catalog.voice_model_id(key)
        try:
            model = model_catalog.require_installed(model_id)
        except KeyError:
            raise CyToolError('InvalidParameters', f'Unknown Piper voice "{key}" (see list_voices)')
        onnx = next((f['path'] for f in model['files'] if f['path'].endswith('.onnx')), None)
        payload = {'model': str(model_catalog.directory(model) / onnx), 'text': parameters['text'], 'speaker': int(parameters.get('speaker', 0)),
                   'length_scale': float(parameters.get('length_scale', 1.0)), 'noise_scale': float(parameters.get('noise_scale', 0.667)),
                   'noise_w_scale': float(parameters.get('noise_w_scale', 0.8)), 'volume': float(parameters.get('volume', 1.0)),
                   'normalize': bool(parameters.get('normalize', True)), 'threads': int(parameters.get('threads', 2)), 'output': 'outputs/speech.wav'}
        context.progress(1, currentStep='Starting')
        result = services.run(context, 'piper', 'synthesize', payload, progress_scale=0.9)
        return _finish_voice(services, context, parameters, 'piper', model_id, result, {k: v for k, v in parameters.items() if k != 'text'})

    def voice_qwen3tts(context, parameters):
        mode = parameters.get('mode', 'custom')
        variant = parameters.get('model', '1.7B-CustomVoice')
        if not variant.endswith(QWEN_MODE_SUFFIX[mode]):
            raise CyToolError('InvalidParameters', f'Mode {mode} requires a {QWEN_MODE_SUFFIX[mode]} model (got {variant})')
        if mode == 'design' and not (parameters.get('instruction') or '').strip():
            raise CyToolError('InvalidParameters', 'Voice design needs an instruction describing the voice')
        if mode == 'custom' and variant.startswith('0.6B') and (parameters.get('instruction') or '').strip():
            raise CyToolError('InvalidParameters', 'Delivery instructions need the 1.7B CustomVoice model')
        if parameters.get('text_annotations') and not (mode == 'custom' and variant == '1.7B-CustomVoice'):
            raise CyToolError('InvalidParameters', 'Text annotations require the 1.7B CustomVoice model in custom mode')
        try:
            build_plan(parameters['text'], enabled=bool(parameters.get('text_annotations')), delivery=parameters.get('delivery', 'paragraphs'), base_instruction=parameters.get('instruction', '') or '')
        except AnnotationError as exc:
            raise CyToolError('InvalidParameters', str(exc))
        model_id = 'qwen3tts-' + variant
        model = model_catalog.require_installed(model_id)
        reference = ''
        if mode == 'clone':
            source = require_file(parameters.get('reference_audio'), 'reference_audio')
            if not parameters.get('x_vector_only') and not (parameters.get('reference_text') or '').strip():
                raise CyToolError('InvalidParameters', 'Cloning needs the transcription of the reference, or x_vector_only')
            reference = str(copy_into_workspace(context, source, 'reference'))
        payload = {'model_path': str(model_catalog.directory(model)), 'model': variant, 'mode': mode, 'text': parameters['text'], 'language': parameters.get('language', 'French'),
                   'speaker': parameters.get('speaker', 'Ryan'), 'instruction': parameters.get('instruction', ''), 'reference_audio': reference,
                   'reference_text': parameters.get('reference_text', ''), 'x_vector_only': bool(parameters.get('x_vector_only', False)),
                   'device': parameters.get('device', 'cuda'), 'delivery': parameters.get('delivery', 'paragraphs'), 'temperature': float(parameters.get('temperature', 0.9)),
                   'top_k': int(parameters.get('top_k', 50)), 'top_p': float(parameters.get('top_p', 1.0)), 'repetition_penalty': float(parameters.get('repetition_penalty', 1.05)),
                   'max_new_tokens': int(parameters.get('max_new_tokens', 2048)), 'seed': int(parameters.get('seed', 42)),
                   'text_annotations': bool(parameters.get('text_annotations', False)), 'output_dir': 'outputs'}
        context.progress(1, currentStep='Starting')
        result = services.run(context, 'qwen3tts', 'synthesize', payload, progress_scale=0.9)
        _observe(context, result)
        return _finish_voice(services, context, parameters, 'qwen3tts', model_id, result, {k: v for k, v in parameters.items() if k != 'text'})

    def voice_fishspeech(context, parameters):
        model = model_catalog.require_installed('fishspeech-s2-pro')
        references = []
        for index, item in enumerate(parameters.get('references', []) or []):
            source = require_file(item.get('audio'), f'references[{index}].audio')
            references.append({'audio': str(copy_into_workspace(context, source, f'reference-{index}')), 'text': item['text']})
        turns = parameters['turns']
        if references:
            for turn in turns:
                if int(turn.get('speaker', 0)) >= len(references):
                    raise CyToolError('InvalidParameters', f'Turn speaker {turn.get("speaker", 0)} has no reference; provide references in speaker order')
        payload = {'model_dir': str(model_catalog.directory(model)), 'turns': turns, 'references': references, 'temperature': float(parameters.get('temperature', 0.8)),
                   'top_p': float(parameters.get('top_p', 0.8)), 'top_k': int(parameters.get('top_k', 30)), 'seed': int(parameters.get('seed', 42)),
                   'max_new_tokens': int(parameters.get('max_new_tokens', 1024)), 'chunk_length': int(parameters.get('chunk_length', 200)), 'gpu_index': 0,
                   'precision': parameters.get('precision', 'bfloat16'), 'output': 'outputs/speech.wav'}
        context.progress(1, currentStep='Starting')
        result = services.run(context, 'fishspeech', 'synthesize', payload, progress_scale=0.9)
        _observe(context, result)
        return _finish_voice(services, context, parameters, 'fishspeech', 'fishspeech-s2-pro', result, {k: v for k, v in parameters.items() if k != 'turns'})

    HANDLERS = {'piper': voice_piper, 'qwen3tts': voice_qwen3tts, 'fishspeech': voice_fishspeech}

    def generate_voice(context, parameters):
        try:
            preset = voice_presets.load(parameters['preset'])
        except voice_presets.PresetError as exc:
            raise CyToolError('MissingInput', str(exc), recoverable=True)
        warnings = voice_presets.check_references(preset)
        overrides = {}
        if parameters.get('seed') is not None:
            overrides['seed'] = int(parameters['seed'])
        post = parameters.get('post_workflow')
        overrides['post_workflow'] = preset.get('postWorkflow', '') if post is None else post
        try:
            params = voice_presets.parameters_for(preset, text=parameters['text'], overrides=overrides)
        except voice_presets.PresetError as exc:
            raise CyToolError('InvalidParameters', str(exc))
        params['preset_name'] = preset['name']
        from cytools_core import validate_parameters
        operation = runtime.operation(preset['operationId'])
        params = validate_parameters({k: v for k, v in params.items() if k != 'preset_name'}, operation['inputSchema'])
        params['preset_name'] = preset['name']
        for warning in warnings:
            context.log(warning, level='Warning')
        result = HANDLERS[preset['backend']](context, params)
        result['warnings'] = warnings + list(result.get('warnings', []))
        result['preset']['id'] = preset['id']
        return result

    def list_voices(context, parameters):
        which = parameters.get('backend', 'all')
        language = (parameters.get('language') or '').lower()
        result = {}
        if which in ('all', 'piper'):
            voices = []
            for model in model_catalog.by_backend('piper'):
                lang = model.get('language', {})
                code = str(lang.get('code', ''))
                if language and not (code.lower().startswith(language) or str(lang.get('family', '')).lower() == language):
                    continue
                installed = not model_catalog.missing_files(model)
                if parameters.get('installed_only') and not installed:
                    continue
                voices.append({'key': model['voiceKey'], 'modelId': model['id'], 'name': model['name'], 'language': code, 'languageName': lang.get('name_english', ''),
                               'quality': model.get('quality', ''), 'numSpeakers': model.get('numSpeakers', 1), 'speakerIdMap': model.get('speakerIdMap', {}),
                               'installed': installed, 'downloadBytes': model.get('downloadBytes', 0)})
            result['piper'] = {'voices': voices, 'count': len(voices), 'installed': sum(1 for v in voices if v['installed'])}
        if which in ('all', 'qwen3tts'):
            variants = {m['variant'] or m['id']: model_catalog.status(m['id'])['installed'] for m in model_catalog.by_backend('qwen3tts')}
            result['qwen3tts'] = {'speakers': ['Ryan', 'Aiden', 'Vivian', 'Serena', 'Uncle_Fu', 'Dylan', 'Eric', 'Ono_Anna', 'Sohee'],
                                  'modes': {'custom': 'preset speaker + instruction (CustomVoice)', 'clone': 'reference recording (Base)', 'design': 'voice description (VoiceDesign)'},
                                  'languages': ['Auto', 'French', 'English', 'Chinese', 'Japanese', 'Korean', 'German', 'Russian', 'Portuguese', 'Spanish', 'Italian'],
                                  'models': variants, 'annotations': '[tone: ...] and [pause: 500ms] with 1.7B-CustomVoice'}
        if which in ('all', 'fishspeech'):
            result['fishspeech'] = {'installed': model_catalog.status('fishspeech-s2-pro')['installed'], 'speakers': '0-4 per turn, mapped to references',
                                    'expressions': 'free natural-language expression per turn (whisper, excited, ...)', 'cloning': '0.1-30 s reference with transcription'}
        result['presets'] = voice_presets.list_all()
        return result

    def save_voice_preset(context, parameters):
        try:
            preset = voice_presets.build(parameters['name'], parameters['backend'], parameters['parameters'], post_workflow=parameters.get('post_workflow', ''),
                                         notes=parameters.get('notes', ''), preset_id=parameters.get('preset_id', ''))
            path = voice_presets.save(preset)
        except voice_presets.PresetError as exc:
            raise CyToolError('InvalidParameters', str(exc))
        return {'id': preset['id'], 'path': str(path), 'preset': preset}

    def list_voice_presets(context, parameters):
        return {'presets': voice_presets.list_all()}

    def delete_voice_preset(context, parameters):
        try:
            voice_presets.delete(parameters['preset'])
        except voice_presets.PresetError as exc:
            raise CyToolError('MissingInput', str(exc), recoverable=True)
        return {'deleted': True}

    def estimate_qwen(parameters, backend, model):
        big = str(parameters.get('model', '1.7B-CustomVoice')).startswith('1.7B')
        if parameters.get('device', 'cuda') == 'cuda':
            return {'ramBytes': int((10 if big else 6) * GiB), 'vramBytes': {'auto': int((8 if big else 5) * GiB)}, 'cpuThreads': 4, 'diskBytes': 512 * MiB}
        return {'ramBytes': int((14 if big else 8) * GiB), 'vramBytes': {}, 'cpuThreads': 8, 'diskBytes': 512 * MiB}

    def estimate_fish(parameters, backend, model):
        return {'ramBytes': int(16 * GiB), 'vramBytes': {'auto': int(20 * GiB)}, 'cpuThreads': 4, 'diskBytes': 512 * MiB}

    def estimate_piper(parameters, backend, model):
        return {'ramBytes': int(1 * GiB), 'vramBytes': {}, 'cpuThreads': int(parameters.get('threads', 2)), 'diskBytes': int(max(16 * MiB, len(parameters.get('text', '')) * 30000))}

    def estimate_preset(parameters, backend, model):
        try:
            preset = voice_presets.load(parameters['preset'])
        except Exception:
            return {'ramBytes': int(2 * GiB), 'vramBytes': {}, 'cpuThreads': 2, 'diskBytes': 64 * MiB}
        merged = {**preset['parameters'], 'text': parameters.get('text', '')}
        return {'piper': estimate_piper, 'qwen3tts': estimate_qwen, 'fishspeech': estimate_fish}[preset['backend']](merged, backend, model)

    def prepare_tts_text(context, parameters):
        from ..voice import prepare
        target = parameters.get('target', 'qwen3tts')
        style = parameters.get('style', '') or ''
        fallback = prepare.heuristic(parameters['text'], target, style, int(parameters.get('pause_ms', 500)))
        if parameters.get('method', 'heuristic') != 'llm':
            return fallback
        model = model_catalog.installed_default('llm')
        if model is None:
            return {**fallback, 'fallbackReason': 'The text assistant model is not installed (see list_models: llm-qwen3-1.7b)'}
        context.progress(1, currentStep='Starting')
        base = {'model_path': str(model_catalog.directory(model)), 'max_new_tokens': int(parameters.get('max_new_tokens', 1024)), 'temperature': 0.0,
                'device': parameters.get('device', 'cuda')}
        if target == 'qwen3tts':
            # Small models stop after the first paragraph: annotate paragraph by paragraph and join with pauses.
            paragraphs = prepare.paragraphs_of(parameters['text'])
            annotated, raws, fallbacks = [], [], 0
            for index, paragraph in enumerate(paragraphs):
                context.cancellation.check()
                result = services.run(context, 'llm', 'chat', {**base, 'system': prepare.SYSTEM_QWEN_PARAGRAPH,
                                                                'user': prepare.user_prompt(paragraph, target, style, parameters.get('language', ''))},
                                      progress_offset=index * 90.0 / max(1, len(paragraphs)), progress_scale=0.9 / max(1, len(paragraphs)))
                raws.append(result.get('text', ''))
                valid = prepare.validate_paragraph(result.get('text', ''), paragraph)
                if valid is None:
                    fallbacks += 1
                    valid = paragraph
                annotated.append(valid)
            _observe(context, result if paragraphs else {})
            pause = f"[pause: {int(parameters.get('pause_ms', 500))}ms]"
            text = ('\n\n' + pause + '\n\n').join(annotated)
            if style and not text.lstrip().lower().startswith('[tone'):
                text = f'[tone: {style}]\n' + text
            context.progress(100, currentStep='Done')
            return {'target': target, 'text': text, 'method': 'llm' if fallbacks < len(paragraphs) else 'heuristic', 'textAnnotations': True,
                    'fallbackReason': f'{fallbacks} paragraph(s) kept verbatim because the assistant changed their words' if fallbacks else '', 'raw': '\n---\n'.join(raws)[:4000]}
        result = services.run(context, 'llm', 'chat', {**base, 'system': prepare.system_prompt(target),
                                                        'user': prepare.user_prompt(parameters['text'], target, style, parameters.get('language', ''))}, progress_scale=0.95)
        _observe(context, result)
        validated = prepare.validate_llm_output(result.get('text', ''), parameters['text'], target, style)
        context.progress(100, currentStep='Done')
        if validated is None:
            return {**fallback, 'fallbackReason': 'The assistant output did not keep the source words or its markup was invalid', 'raw': result.get('text', '')[:4000]}
        return {**validated, 'raw': result.get('text', '')[:4000]}

    def estimate_prepare(parameters, backend, model):
        if parameters.get('method', 'heuristic') != 'llm':
            return {'ramBytes': 256 * MiB, 'vramBytes': {}, 'cpuThreads': 1, 'diskBytes': 1 * MiB}
        if parameters.get('device', 'cuda') == 'cuda':
            return {'ramBytes': int(9 * GiB), 'vramBytes': {'auto': int(5 * GiB)}, 'cpuThreads': 4, 'diskBytes': 8 * MiB}
        return {'ramBytes': int(12 * GiB), 'vramBytes': {}, 'cpuThreads': 8, 'diskBytes': 8 * MiB}

    def transcribe_audio(context, parameters):
        source = require_file(parameters.get('input'))
        model = model_catalog.installed_default('whisper')
        if model is None:
            raise CyToolError('MissingModel', 'Whisper is not installed (Models tab, or install_model whisper-large-v3-turbo)', recoverable=True,
                              details={'modelId': 'whisper-large-v3-turbo'})
        context.progress(1, currentStep='Starting')
        result = services.run(context, 'whisper', 'transcribe', {'model_dir': str(model_catalog.directory(model)), 'input': str(source),
                                                                  'language': parameters.get('language', ''), 'device': parameters.get('device', 'cuda'),
                                                                  'timestamps': True}, progress_scale=0.98)
        _observe(context, result)
        context.progress(100, currentStep='Done')
        return {'text': result['text'], 'segments': result.get('segments', []), 'durationSeconds': result.get('durationSeconds', 0.0),
                'language': parameters.get('language', '') or 'auto', 'seconds': result.get('seconds', 0.0)}

    def estimate_transcribe(parameters, backend, model):
        if parameters.get('device', 'cuda') == 'cuda':
            return {'ramBytes': int(4 * GiB), 'vramBytes': {'auto': int(3 * GiB)}, 'cpuThreads': 4, 'diskBytes': 8 * MiB}
        return {'ramBytes': int(6 * GiB), 'vramBytes': {}, 'cpuThreads': 8, 'diskBytes': 8 * MiB}

    runtime.register('transcribe_audio', transcribe_audio, estimate=estimate_transcribe)
    runtime.register('prepare_tts_text', prepare_tts_text, estimate=estimate_prepare)
    runtime.register('voice_piper', voice_piper, estimate=estimate_piper)
    runtime.register('voice_qwen3tts', voice_qwen3tts, estimate=estimate_qwen)
    runtime.register('voice_fishspeech', voice_fishspeech, estimate=estimate_fish)
    runtime.register('generate_voice', generate_voice, estimate=estimate_preset)
    runtime.register('list_voices', list_voices)
    runtime.register('save_voice_preset', save_voice_preset)
    runtime.register('list_voice_presets', list_voice_presets)
    runtime.register('delete_voice_preset', delete_voice_preset)


def _observe(context, result):
    if result.get('vramPeakBytes') is not None:
        try:
            context.observe_resources({'ramBytes': int(result.get('workerMemoryBytes', 0)), 'vramBytes': {'0': int(result.get('vramPeakBytes', 0))}})
        except Exception:
            pass
