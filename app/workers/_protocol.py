"""Worker-side half of the JSON-lines protocol (see audiostudio/engines/workerhost.py).

A worker script defines handlers and calls ``serve(handlers)``. Handlers receive
``(request, reporter)`` and return a JSON-serialisable result, or raise ``WorkerError``
for expected failures. ``reporter.progress(percent, step, message)`` and
``reporter.log(message, level)`` stream events while the request runs.

``sys.stdout`` is redirected to stderr before any heavy import so that library noise
never corrupts the protocol; only this module writes to the real stdout.
"""
import json
import os
import sys
import threading
import traceback

PROTOCOL = sys.stdout
sys.stdout = sys.stderr
_write_lock = threading.Lock()


class WorkerError(Exception):
    def __init__(self, code, message, details=None, recoverable=False):
        super().__init__(message)
        self.code = code
        self.details = details
        self.recoverable = recoverable


def emit(message):
    with _write_lock:
        try:
            PROTOCOL.write(json.dumps(message, ensure_ascii=False, allow_nan=False) + '\n')
            PROTOCOL.flush()
        except (OSError, ValueError):
            pass


class Reporter:
    def __init__(self, request_id):
        self.request_id = request_id
        self._last = None

    def progress(self, percent, step='', message='', **extra):
        percent = max(0.0, min(100.0, float(percent)))
        key = (round(percent, 1), step, message)
        if key == self._last:
            return
        self._last = key
        payload = {'id': self.request_id, 'event': 'progress', 'percent': percent}
        if step:
            payload['step'] = str(step)
        if message:
            payload['message'] = str(message)
        payload.update({k: v for k, v in extra.items() if isinstance(v, (int, float, str, bool))})
        emit(payload)

    def log(self, message, level='Info'):
        emit({'id': self.request_id, 'event': 'log', 'level': level, 'message': str(message)[:16000]})

    def resident(self, **info):
        emit({'id': self.request_id, 'event': 'resident', 'resident': info})


def classify(exc):
    """Map common Python/library exceptions to CyTools error codes."""
    text = str(exc)
    lowered = text.lower()
    if isinstance(exc, WorkerError):
        return exc.code, text, exc.details, exc.recoverable
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return 'MissingDependency', text, None, True
    if isinstance(exc, FileNotFoundError):
        return 'MissingModel', text, None, True
    if 'out of memory' in lowered or 'cuda error' in lowered and 'memory' in lowered:
        return 'InsufficientVRAM', text, None, True
    if isinstance(exc, PermissionError):
        return 'AccessDenied', text, None, False
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return 'InvalidParameters', text, None, False
    return 'InferenceFailed', text, None, False


def serve(handlers, on_start=None):
    """Main loop: reads requests from stdin until EOF or a shutdown request."""
    if on_start:
        try:
            on_start()
        except Exception as exc:
            emit({'event': 'fatal', 'message': str(exc)})
            raise
    emit({'event': 'ready', 'pid': os.getpid(), 'python': sys.version.split()[0]})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            emit({'event': 'log', 'level': 'Warning', 'message': 'Ignored malformed request line'})
            continue
        request_id = str(request.get('id', ''))
        op = request.get('op', '')
        if op == 'shutdown':
            emit({'id': request_id, 'ok': True, 'result': {'shutdown': True}})
            break
        handler = handlers.get(op)
        reporter = Reporter(request_id)
        if handler is None:
            emit({'id': request_id, 'ok': False, 'code': 'InvalidParameters', 'message': 'Unknown worker operation: ' + str(op)})
            continue
        try:
            result = handler(request, reporter)
            json.dumps(result, allow_nan=False)
            emit({'id': request_id, 'ok': True, 'result': result})
        except Exception as exc:  # every failure becomes a protocol error, the process stays alive
            code, message, details, recoverable = classify(exc)
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()
            emit({'id': request_id, 'ok': False, 'code': code, 'message': message, 'details': details, 'recoverable': recoverable,
                  'traceback': traceback.format_exc()[-4000:]})
    return 0


def inside(workspace, path):
    """Ensure an output path is inside the job workspace; returns the resolved path."""
    from pathlib import Path
    workspace = Path(workspace).resolve()
    target = (workspace / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if not target.is_relative_to(workspace):
        raise WorkerError('AccessDenied', 'Output path escapes the job workspace')
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def memory_report():
    info = {}
    try:
        import psutil
        process = psutil.Process()
        memory = process.memory_info()
        info['workerMemoryBytes'] = int(getattr(memory, 'peak_wset', memory.rss))
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            info['vramPeakBytes'] = int(torch.cuda.max_memory_reserved())
            info['vramAllocatedBytes'] = int(torch.cuda.memory_allocated())
            info['gpuName'] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    return info
