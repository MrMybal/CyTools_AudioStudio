"""Shared services for the handlers: worker pool, backend selection, post workflows, outputs."""
import json
from pathlib import Path
import re
import shutil
import threading

from cytools_core import CyToolError

from ..paths import APP, ROOT, DATA, LOGS, WORKFLOWS, PLUGIN_CACHE, base_python
from ..engines import registry as engines
from ..engines.workerhost import WorkerHost, WorkerPool
from ..backends import registry as backends
from ..workflow import model as workflow_model

MiB = 1024 ** 2
GiB = 1024 ** 3
AUDIO_SUFFIXES = ('.wav', '.flac', '.ogg', '.oga', '.opus', '.aiff', '.aif', '.mp3', '.m4a', '.aac', '.wma', '.mp4', '.mkv', '.webm', '.mov', '.caf', '.w64')


class Services:
    def __init__(self, runtime):
        self.runtime = runtime
        self.pool = WorkerPool(runtime)
        self.lock = threading.RLock()

    # ------------------------------------------------------------- workers
    def host(self, backend_id):
        backend = backends.get(backend_id)

        def factory():
            if backend.engine:
                info = engines.require(backend.engine)
                python = Path(info['python'])
                env = engines.worker_environment(backend.engine)
            else:
                python = base_python()
                env = engines.base_environment()
            return WorkerHost(backend_id, [python, backend.worker_script()], cwd=APP, env=env, log_path=LOGS / f'worker-{backend_id}.log',
                              idle_seconds=backend.idle_seconds, startup_timeout=300)
        return self.pool.get(backend_id, factory)

    def dsp(self):
        def factory():
            return WorkerHost('dsp', [base_python(), APP / 'workers' / 'dsp_worker.py'], cwd=APP, log_path=LOGS / 'worker-dsp.log', idle_seconds=600)
        return self.pool.get('dsp', factory)

    def run(self, context, backend_id, op, payload, *, timeout=None, progress_offset=0.0, progress_scale=1.0):
        backend = backends.get(backend_id)
        host = self.host(backend_id)
        if backend.resident_gpu:
            self.pool.make_exclusive(backend_id)
        payload = dict(payload)
        payload.setdefault('workspace', str(context.workspace))
        return host.run_job(context, op, payload, timeout=timeout, progress_offset=progress_offset, progress_scale=progress_scale)

    def run_dsp(self, context, op, payload, *, progress_offset=0.0, progress_scale=1.0):
        payload = dict(payload)
        payload.setdefault('workspace', str(context.workspace))
        return self.dsp().run_job(context, op, payload, progress_offset=progress_offset, progress_scale=progress_scale)


def selected_backend(context, default=''):
    """The backendId chosen for this job (the JobContext has no accessor for it)."""
    try:
        with context.runtime._cv:
            return context.runtime._jobs[context.job_id].get('backendId') or default
    except Exception:
        return default


def require_file(path, field='input'):
    if not path:
        raise CyToolError('MissingInput', f'Parameter "{field}" is required')
    candidate = Path(path)
    if not candidate.is_file():
        raise CyToolError('MissingInput', f'File not found for "{field}": {path}', recoverable=True)
    if candidate.suffix.lower() not in AUDIO_SUFFIXES:
        raise CyToolError('InvalidInput', f'Unsupported audio extension for "{field}": {candidate.suffix}')
    return candidate


def safe_name(name, fallback='output'):
    cleaned = re.sub(r'[^A-Za-z0-9._ -]+', '_', str(name or '')).strip(' ._')
    return cleaned[:120] or fallback


def output_path(context, name, suffix):
    return context.path('outputs/' + safe_name(name) + suffix)


def resolve_workflow(parameters, field_doc='workflow', field_name='workflow_name', required=False):
    """Inline workflow document or a saved workflow name; validated, never executed here."""
    document = parameters.get(field_doc)
    name = (parameters.get(field_name) or '').strip()
    if document:
        try:
            return workflow_model.validate(document)
        except workflow_model.WorkflowError as exc:
            raise CyToolError('InvalidParameters', 'Invalid workflow: ' + str(exc))
    if name:
        return load_workflow(name)
    if required:
        raise CyToolError('InvalidParameters', 'Provide a workflow document or a workflow_name')
    return None


def workflow_path(name):
    candidate = Path(name)
    if candidate.suffix.lower() == '.json' and candidate.is_file():
        return candidate
    return WORKFLOWS / (workflow_model.safe_name(name) + '.json')


def load_workflow(name):
    path = workflow_path(name)
    if not path.is_file():
        raise CyToolError('MissingInput', f'Unknown workflow "{name}" (see list_workflows)', recoverable=True)
    try:
        return workflow_model.load(path)
    except workflow_model.WorkflowError as exc:
        raise CyToolError('InvalidParameters', f'Workflow "{name}" is invalid: {exc}')


def apply_tail_override(document, tail):
    if tail:
        document = dict(document)
        document['tail'] = workflow_model.normalize_tail({**document.get('tail', {}), **tail})
    return document


def post_process(services, context, file, workflow_name, *, progress_offset=90.0, progress_scale=0.1, suffix='_processed'):
    """Apply a saved workflow to a generated file inside the job workspace."""
    if not workflow_name:
        return None
    document = load_workflow(workflow_name)
    source = Path(file)
    target = context.path('outputs/' + source.stem + suffix + source.suffix)
    result = services.run_dsp(context, 'render', {'input': str(source), 'output': str(target), 'workflow': document, 'format': source.suffix.lstrip('.').lower() if source.suffix.lower() in ('.wav', '.flac', '.mp3', '.ogg') else 'wav'},
                              progress_offset=progress_offset, progress_scale=progress_scale)
    return {'file': str(target), 'report': result}


def mime_for(path):
    suffix = Path(path).suffix.lower()
    return {'.wav': 'audio/wav', '.flac': 'audio/flac', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.aiff': 'audio/aiff'}.get(suffix, 'application/octet-stream')


def describe_file(path):
    from .. import audio_io
    info = audio_io.probe(path)
    return {'file': str(path), 'mimeType': mime_for(path), 'sampleRate': info.samplerate, 'channels': info.channels,
            'durationSeconds': info.duration, 'sizeBytes': Path(path).stat().st_size}


def write_report(context, name, payload):
    path = context.path('outputs/' + name)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), 'utf-8')
    return str(path)


def copy_into_workspace(context, source, name):
    """Snapshot an external file into the job (worker reads only job-owned files)."""
    source = Path(source)
    target = context.path('inputs/' + name + source.suffix.lower())
    shutil.copy2(source, target)
    return target


def plugin_cache_dir():
    PLUGIN_CACHE.mkdir(parents=True, exist_ok=True)
    return PLUGIN_CACHE
