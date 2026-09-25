"""Models, engines, diagnostics and worker release."""
import json
import os
from pathlib import Path
import subprocess
import sys

from cytools_core import CyToolError

from ..paths import APP, ROOT, LOGS, base_python
from .. import models as model_catalog
from ..engines import registry as engines
from ..backends import registry as backends
from .common import GiB, MiB


def register(runtime, services):
    def list_models(context, parameters):
        items = model_catalog.status_all(parameters.get('backend') or None, include_voices=bool(parameters.get('include_voices')))
        return {'models': items, 'count': len(items), 'engines': engines.status_all()}

    def install_model(context, parameters):
        model_id = parameters['model']
        try:
            model_catalog.get(model_id)
        except KeyError:
            raise CyToolError('InvalidParameters', f'Unknown model "{model_id}" (see list_models)')
        total = int(model_catalog.get(model_id).get('downloadBytes', 0)) or 1

        def progress(done, size, name):
            context.progress(min(99.0, 100.0 * done / max(size, 1)), currentStep='Downloading', currentFile=name, statusMessage=f'{done / 1e9:.2f} / {size / 1e9:.2f} GB')
        context.progress(0, currentStep='Checking files')
        result = model_catalog.install(model_id, accept_license=bool(parameters.get('accept_license')), repair=bool(parameters.get('repair')),
                                       cancellation=context.cancellation, progress=progress, log=lambda m: context.log(m))
        context.progress(100, currentStep='Installed')
        return result

    def verify_model(context, parameters):
        try:
            model_catalog.get(parameters['model'])
        except KeyError:
            raise CyToolError('InvalidParameters', 'Unknown model')
        context.progress(5, currentStep='Hashing files')
        result = model_catalog.verify(parameters['model'])
        context.progress(100, currentStep='Done')
        return result

    def remove_model(context, parameters):
        try:
            model_catalog.get(parameters['model'])
        except KeyError:
            raise CyToolError('InvalidParameters', 'Unknown model')
        return model_catalog.remove(parameters['model'])

    def engine_status(context, parameters):
        return {'engines': engines.status_all(), 'workers': services.pool.status(), 'backends': {b.id: {'engine': b.engine, 'family': b.family, 'label': b.label} for b in backends.BACKENDS.values()}}

    def install_engine(context, parameters):
        name = parameters['engine']
        log_path = context.path('logs/install-engine.log')
        command = [str(base_python()), str(APP / 'setup_engine.py'), name] + (['--cpu-only'] if parameters.get('cpu_only') else [])
        context.log('Running ' + ' '.join(command))
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0
        with open(log_path, 'w', encoding='utf-8', errors='replace') as handle:
            process = subprocess.Popen(command, cwd=str(ROOT), stdout=handle, stderr=subprocess.STDOUT, creationflags=flags)
            try:
                while process.poll() is None:
                    try:
                        context.cancellation.sleep(1.0)
                    except CyToolError:
                        _terminate(process)
                        raise
                    try:
                        tail = log_path.read_text('utf-8', errors='replace').strip().splitlines()
                        context.progress(50, currentStep='Installing ' + name, statusMessage=(tail[-1] if tail else '')[:300])
                    except OSError:
                        pass
            finally:
                if process.poll() is None:
                    _terminate(process)
        if process.returncode != 0:
            tail = log_path.read_text('utf-8', errors='replace')[-4000:]
            raise CyToolError('InstallFailed', f'Engine installation failed (exit {process.returncode}); see {log_path}', details={'log': tail}, recoverable=True)
        context.progress(100, currentStep='Installed')
        return {'engine': name, 'status': engines.status(name), 'log': str(log_path)}

    def diagnose_backend(context, parameters):
        backend = backends.get(parameters['backend'])
        info = {'backend': backend.id, 'engine': backend.engine, 'engineStatus': engines.status(backend.engine) if backend.engine else None,
                'models': [model_catalog.status(m['id']) for m in model_catalog.by_backend(backend.id)][:8]}
        op = {'sfx_procedural': 'status', 'acestep': 'inspect'}.get(backend.id, 'diagnose')
        payload = {}
        if backend.id == 'acestep':
            model = model_catalog.installed_default('acestep')
            if model is not None:
                payload = {'checkpoints_dir': str(model_catalog.directory(model)), 'cache_dir': str(ROOT / 'data' / 'cache' / 'acestep'), 'device_index': 0}
            else:
                info['worker'] = {'skipped': 'checkpoints not installed'}
                return info
        info['worker'] = services.run(context, backend.id, op, payload)
        return info

    def release_workers(context, parameters):
        before = services.pool.status()
        services.pool.stop_all()
        return {'stopped': [name for name, health in before.items() if health.get('alive')], 'workers': services.pool.status()}

    runtime.register('list_models', list_models)
    runtime.register('install_model', install_model)
    runtime.register('verify_model', verify_model)
    runtime.register('remove_model', remove_model)
    runtime.register('engine_status', engine_status)
    runtime.register('install_engine', install_engine)
    runtime.register('diagnose_backend', diagnose_backend)
    runtime.register('release_workers', release_workers)


def _terminate(process):
    try:
        import psutil
        parent = psutil.Process(process.pid)
        for child in parent.children(recursive=True):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        psutil.wait_procs([parent], timeout=5)
        if process.poll() is None:
            process.kill()
    except Exception:
        process.kill()
    process.wait()
