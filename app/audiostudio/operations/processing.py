"""Processing operations: workflows, batch, conversion, analysis, effects and VST3 catalogue."""
import json
from pathlib import Path

from cytools_core import CyToolError

from ..paths import WORKFLOWS, default_vst3_directories
from ..dsp import effects
from ..workflow import model as workflow_model
from ..vst import host as vst_host
from .common import (GiB, MiB, require_file, output_path, resolve_workflow, apply_tail_override, describe_file, safe_name,
                     workflow_path, plugin_cache_dir)

SUFFIX = {'wav': '.wav', 'flac': '.flac', 'mp3': '.mp3', 'ogg': '.ogg', 'aac': '.m4a'}


def _render_one(services, context, source, document, parameters, name, progress_offset=0.0, progress_scale=1.0):
    fmt = parameters.get('output_format', 'wav')
    target = output_path(context, name, SUFFIX[fmt])
    selection = None
    if float(parameters.get('selection_start', -1)) >= 0 or float(parameters.get('selection_end', -1)) >= 0:
        selection = [max(0.0, float(parameters.get('selection_start', -1))), float(parameters.get('selection_end', -1))]
        if selection[1] < 0:
            from .. import audio_io
            selection[1] = audio_io.probe(source).duration
    payload = {'input': str(source), 'output': str(target), 'workflow': document, 'format': fmt, 'subtype': parameters.get('subtype'),
               'bitrate_kbps': int(parameters.get('bitrate_kbps', 192)), 'selection': selection}
    report = services.run_dsp(context, 'render', payload, progress_offset=progress_offset, progress_scale=progress_scale)
    result = describe_file(target)
    result['report'] = report
    return result


def register(runtime, services):
    def process_audio(context, parameters):
        source = require_file(parameters.get('input'))
        document = resolve_workflow(parameters, required=True)
        document = apply_tail_override(document, parameters.get('tail'))
        name = parameters.get('output_name') or (source.stem + '_processed')
        context.progress(1, currentStep='Starting', stepCount=1, currentStepIndex=1)
        result = _render_one(services, context, source, document, parameters, name)
        context.progress(100, currentStep='Done')
        return result

    def batch_process(context, parameters):
        document = resolve_workflow(parameters, required=True)
        document = apply_tail_override(document, parameters.get('tail'))
        inputs = parameters['inputs']
        results, failed = [], []
        for index, item in enumerate(inputs):
            context.cancellation.check()
            context.progress(index * 100.0 / len(inputs), currentStep=f'File {index + 1}/{len(inputs)}', currentStepIndex=index + 1, stepCount=len(inputs), currentFile=str(item))
            try:
                source = require_file(item, f'inputs[{index}]')
                name = source.stem + parameters.get('suffix', '_processed')
                results.append(_render_one(services, context, source, document, parameters, name, progress_offset=index * 100.0 / len(inputs), progress_scale=1.0 / len(inputs)))
            except CyToolError as exc:
                if exc.code in ('Cancelled', 'Timeout'):
                    raise
                if not parameters.get('continue_on_error', True):
                    raise
                failed.append({'input': str(item), 'code': exc.code, 'message': str(exc)})
        context.progress(100, currentStep='Done')
        return {'results': results, 'failed': failed, 'count': len(results)}

    def convert_audio(context, parameters):
        source = require_file(parameters.get('input'))
        fmt = parameters.get('output_format', 'wav')
        target = output_path(context, source.stem, SUFFIX[fmt])
        payload = {'input': str(source), 'output': str(target), 'format': fmt, 'subtype': parameters.get('subtype'), 'bitrate_kbps': int(parameters.get('bitrate_kbps', 192)),
                   'samplerate': int(parameters.get('samplerate', 0)) or None, 'channels': int(parameters.get('channels', 0)) or None}
        report = services.run_dsp(context, 'convert', payload)
        result = describe_file(target)
        result['report'] = report
        return result

    def analyze_audio(context, parameters):
        source = require_file(parameters.get('input'))
        return services.run_dsp(context, 'analyze', {'input': str(source)})

    def render_session(context, parameters):
        """Mix an editor session folder (inserts, automation, master, tail) to a file."""
        session = Path(str(parameters.get('session', '')))
        index = session if session.is_file() else session / 'session.json'
        if not index.is_file():
            raise CyToolError('MissingInput', 'Session not found: ' + str(session))
        fmt = parameters.get('output_format', 'wav')
        target = output_path(context, index.parent.name or 'session', SUFFIX[fmt])
        payload = {'session': str(index), 'output': str(target), 'format': fmt, 'subtype': parameters.get('subtype'),
                   'bitrate_kbps': int(parameters.get('bitrate_kbps', 192)), 'tail': parameters.get('tail'), 'selection': parameters.get('selection')}
        report = services.run_dsp(context, 'render_session', payload)
        result = describe_file(target)
        result['report'] = report
        return result

    def _session_folder(name):
        """Absolute path as given, otherwise a folder under data/sessions."""
        from ..paths import SESSIONS
        path = Path(str(name))
        return path if path.is_absolute() else SESSIONS / safe_name(str(name), 'session')

    def edit_session(context, parameters):
        """Scripted session editing (add / replace / remove tracks, inserts, master, tail), save and optional render."""
        session = parameters.get('session')
        if session:
            source = Path(str(session))
            index = source if source.is_file() else source / 'session.json'
            if not index.is_file():
                raise CyToolError('MissingInput', 'Session not found: ' + str(session))
            session = str(index)
        fmt = parameters.get('output_format', 'wav')
        payload = {'session': session, 'samplerate': int(parameters.get('samplerate', 48000) or 48000), 'actions': parameters.get('actions') or [],
                   'save_as': str(_session_folder(parameters['save_as'])) if parameters.get('save_as') else None,
                   'render': bool(parameters.get('render', False)), 'output': str(output_path(context, 'session-render', SUFFIX[fmt])),
                   'format': fmt, 'subtype': parameters.get('subtype'), 'bitrate_kbps': int(parameters.get('bitrate_kbps', 192)),
                   'tail': parameters.get('tail'), 'selection': parameters.get('selection')}
        report = services.run_dsp(context, 'edit_session', payload)
        if report.get('file'):
            report.update({k: v for k, v in describe_file(Path(report['file'])).items() if k not in report})
        return report

    def batch_session(context, parameters):
        """Render a session once per input sound placed in a slot track (batch of sounds through one project)."""
        source = Path(str(parameters.get('session', '')))
        index = source if source.is_file() else source / 'session.json'
        if not index.is_file():
            raise CyToolError('MissingInput', 'Session not found: ' + str(source))
        fmt = parameters.get('output_format', 'wav')
        target = context.workspace / 'outputs' / 'batch'
        payload = {'session': str(index), 'inputs': [str(require_file(item, f'inputs[{i}]')) for i, item in enumerate(parameters['inputs'])],
                   'slot': parameters.get('slot') or {}, 'output_dir': str(target), 'suffix': parameters.get('suffix', '') or '',
                   'format': fmt, 'subtype': parameters.get('subtype'), 'bitrate_kbps': int(parameters.get('bitrate_kbps', 192)),
                   'tail': parameters.get('tail'), 'selection': parameters.get('selection')}
        report = services.run_dsp(context, 'batch_session', payload)
        folder = parameters.get('output_dir')
        if folder:
            # The worker only writes inside the job workspace; copy the renders to the requested folder afterwards.
            import shutil
            destination = Path(str(folder))
            destination.mkdir(parents=True, exist_ok=True)
            for item in report.get('results', []):
                copied = destination / Path(item['file']).name
                shutil.copy2(item['file'], copied)
                item['workspaceFile'] = item['file']
                item['file'] = str(copied)
            report['outputDir'] = str(destination)
        return report

    def list_effects(context, parameters):
        return {'effects': effects.catalogue(), 'count': len(effects.REGISTRY)}

    def list_workflows(context, parameters):
        return {'workflows': workflow_model.list_workflows(WORKFLOWS), 'directory': str(WORKFLOWS)}

    def get_workflow(context, parameters):
        from .common import load_workflow
        document = load_workflow(parameters['name'])
        return {'workflow': document, 'summary': workflow_model.summary(document)}

    def save_workflow(context, parameters):
        try:
            document = workflow_model.validate(parameters['workflow'])
        except workflow_model.WorkflowError as exc:
            raise CyToolError('InvalidParameters', 'Invalid workflow: ' + str(exc))
        document['name'] = parameters['name']
        target = workflow_path(parameters['name'])
        if target.exists() and not parameters.get('overwrite'):
            raise CyToolError('AlreadyExists', f'Workflow "{parameters["name"]}" exists; set overwrite to replace it', recoverable=True)
        workflow_model.save(target, document)
        return {'path': str(target), 'name': document['name'], 'summary': workflow_model.summary(document)}

    def scan_plugins(context, parameters):
        directories = [str(d) for d in default_vst3_directories()] + [d for d in parameters.get('directories', []) if d]
        settings = _plugin_settings()
        directories += [d for d in settings.get('directories', []) if d not in directories]
        return services.run_dsp(context, 'scan', {'directories': directories, 'cache_dir': str(plugin_cache_dir()), 'force': bool(parameters.get('force'))})

    def list_plugins(context, parameters):
        cache = vst_host.read_cache(plugin_cache_dir())
        plugins = sorted(cache.get('plugins', {}).values(), key=lambda p: (p.get('name') or Path(p.get('path', '')).stem).lower())
        return {'plugins': plugins, 'count': len(plugins), 'directories': [str(d) for d in default_vst3_directories()] + _plugin_settings().get('directories', [])}

    def describe_plugin(context, parameters):
        plugin = parameters['plugin']
        if not Path(plugin).exists():
            raise CyToolError('MissingInput', 'Plugin not found: ' + plugin, recoverable=True)
        return services.run_dsp(context, 'describe', {'plugin': plugin})

    def master_audio(context, parameters):
        from .common import post_process
        source = require_file(parameters.get('input'))
        mode = parameters.get('mode', 'loudness')
        reference = parameters.get('reference') or ''
        if mode == 'reference':
            if not reference:
                raise CyToolError('InvalidParameters', 'Mode reference needs a reference recording')
            reference = str(require_file(reference, 'reference'))
        fmt = parameters.get('output_format', 'wav')
        target = output_path(context, source.stem + '_mastered', SUFFIX[fmt])
        context.progress(1, currentStep='Starting')
        payload = {'input': str(source), 'reference': reference, 'mode': mode, 'target_lufs': float(parameters.get('target_lufs', -14.0)),
                   'ceiling_db': float(parameters.get('ceiling_db', -1.0)), 'output': str(target), 'format': fmt, 'subtype': parameters.get('subtype'),
                   'bitrate_kbps': int(parameters.get('bitrate_kbps', 192))}
        report = services.run_dsp(context, 'master', payload, progress_scale=0.9)
        result = describe_file(target)
        post = parameters.get('post_workflow') or ''
        if post:
            processed = post_process(services, context, str(target), post)
            result['processedFile'] = processed['file']
        result['report'] = report
        context.progress(100, currentStep='Done')
        return result

    def estimate_process(parameters, backend, model):
        try:
            from .. import audio_io
            source = parameters.get('input')
            duration = audio_io.probe(source).duration if source and Path(source).is_file() else 60.0
        except Exception:
            duration = 60.0
        # float32 stereo at 48 kHz, tail extension, a few working copies.
        ram = int(min(24 * GiB, 512 * MiB + (duration + 20) * 48000 * 2 * 4 * 6))
        return {'ramBytes': ram, 'cpuThreads': 4, 'diskBytes': int(duration * 48000 * 2 * 4 + 32 * MiB)}

    runtime.register('process_audio', process_audio, estimate=estimate_process)
    runtime.register('master_audio', master_audio, estimate=estimate_process)
    runtime.register('batch_process', batch_process)
    runtime.register('convert_audio', convert_audio, estimate=estimate_process)
    runtime.register('analyze_audio', analyze_audio, estimate=estimate_process)
    runtime.register('render_session', render_session)
    runtime.register('edit_session', edit_session)
    runtime.register('batch_session', batch_session)
    runtime.register('list_effects', list_effects)
    runtime.register('list_workflows', list_workflows)
    runtime.register('get_workflow', get_workflow)
    runtime.register('save_workflow', save_workflow)
    runtime.register('scan_plugins', scan_plugins)
    runtime.register('list_plugins', list_plugins)
    runtime.register('describe_plugin', describe_plugin)


def _plugin_settings():
    from ..paths import SETTINGS
    path = SETTINGS / 'plugins.json'
    try:
        value = json.loads(path.read_text('utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}
