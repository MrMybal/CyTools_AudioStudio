"""Persistent worker processes with a JSON-lines protocol.

The SDK ``ProcessWorker`` is one-shot (one JSON in, one JSON out) and cannot report
progress; loading a multi-gigabyte model for every job would also be too slow. This
host keeps a worker alive between jobs, forwards its progress and log events to the
job context, kills it on cancellation (so the reservation is released only after the
process is really gone) and unloads it after an idle delay. It registers with the
Core runtime through the same ``stop``/``release``/``health`` contract as ProcessWorker.

Protocol (one JSON object per line, UTF-8):
  worker -> host   {"event": "ready", "pid": 123}
  host   -> worker {"id": "...", "op": "generate", ...payload}
  worker -> host   {"id": "...", "event": "progress", "percent": 42, "step": "Decoding"}
  worker -> host   {"id": "...", "event": "log", "level": "Info", "message": "..."}
  worker -> host   {"id": "...", "ok": true, "result": {...}}
  worker -> host   {"id": "...", "ok": false, "code": "InferenceFailed", "message": "...", "details": {...}}
Anything a worker prints outside this protocol must go to stderr (the worker module
swaps sys.stdout for that reason). stderr is appended to a per-engine log file.

This is a generic extension candidate for the SDK (persistent workers with handshake,
progress and idle unload are listed as extension points in ImplementationStatus.md).
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

from cytools_core import CyToolError

try:
    import psutil
except ImportError:  # psutil is a Core dependency; keep a soft fallback for tests
    psutil = None


class WorkerHost:
    def __init__(self, name, command, *, cwd=None, env=None, log_path=None, idle_seconds=300, startup_timeout=240):
        self.name = name
        self.command = [str(c) for c in command]
        self.cwd = str(cwd) if cwd else None
        self.env = env
        self.log_path = Path(log_path) if log_path else None
        self.idle_seconds = idle_seconds
        self.startup_timeout = startup_timeout
        self.process = None
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.busy = False
        self.last_used = time.monotonic()
        self.resident = {}          # what the worker reports as loaded (model ids, vram)
        self.state = 'Stopped'
        self._reader = None
        self._idle_thread = None
        self._stderr_handle = None

    # ----------------------------------------------------------------- lifecycle
    def start(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            self.queue = queue.Queue()
            stderr = subprocess.DEVNULL
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                self._stderr_handle = open(self.log_path, 'a', encoding='utf-8', errors='replace')
                self._stderr_handle.write(f'\n=== worker {self.name} started {time.strftime("%Y-%m-%d %H:%M:%S")} ===\n')
                self._stderr_handle.flush()
                stderr = self._stderr_handle
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0
            try:
                self.process = subprocess.Popen(self.command, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=stderr, text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=flags)
            except OSError as exc:
                self.state = 'Failed'
                raise CyToolError('MissingRuntime', f'Cannot start worker {self.name}: {exc}') from exc
            self.state = 'Starting'
            self._reader = threading.Thread(target=self._read_loop, args=(self.process,), daemon=True, name='worker-' + self.name)
            self._reader.start()
            deadline = time.monotonic() + self.startup_timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.stop()
                    raise CyToolError('Timeout', f'Worker {self.name} did not answer the handshake within {self.startup_timeout}s',
                                      details={'log': str(self.log_path) if self.log_path else ''})
                try:
                    message = self.queue.get(timeout=min(0.5, remaining))
                except queue.Empty:
                    if self.process.poll() is not None:
                        self.state = 'Failed'
                        raise CyToolError('WorkerCrashed', f'Worker {self.name} exited with code {self.process.returncode} during startup',
                                          details={'log': str(self.log_path) if self.log_path else ''})
                    continue
                if message.get('event') == 'ready':
                    break
                if message.get('event') == 'closed':
                    self.state = 'Failed'
                    raise CyToolError('WorkerCrashed', f'Worker {self.name} closed during startup', details={'log': str(self.log_path) if self.log_path else ''})
            self.state = 'Idle'
            self.last_used = time.monotonic()
            if self._idle_thread is None or not self._idle_thread.is_alive():
                self._idle_thread = threading.Thread(target=self._idle_loop, daemon=True, name='worker-idle-' + self.name)
                self._idle_thread.start()

    def _read_loop(self, process):
        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.queue.put(json.loads(line))
                except ValueError:
                    self.queue.put({'event': 'log', 'level': 'Warning', 'message': 'Non-JSON worker output: ' + line[:500]})
        except (OSError, ValueError):
            pass
        finally:
            self.queue.put({'event': 'closed', 'returncode': process.poll()})

    def _idle_loop(self):
        while True:
            time.sleep(5.0)
            with self.lock:
                if not self.process or self.process.poll() is not None:
                    return
                if not self.busy and self.idle_seconds and time.monotonic() - self.last_used > self.idle_seconds:
                    self._log('idle for %ds, unloading' % self.idle_seconds)
                    self.stop()
                    return

    def _log(self, message):
        if self._stderr_handle:
            try:
                self._stderr_handle.write('[host] ' + message + '\n')
                self._stderr_handle.flush()
            except (OSError, ValueError):
                pass

    def stop(self):
        with self.lock:
            process = self.process
            self.process = None
            self.resident = {}
            self.state = 'Stopped'
            if process is None:
                return
            try:
                if process.stdin:
                    try:
                        process.stdin.write(json.dumps({'id': 'shutdown', 'op': 'shutdown'}) + '\n')
                        process.stdin.flush()
                    except (OSError, ValueError):
                        pass
                    try:
                        process.stdin.close()
                    except (OSError, ValueError):
                        pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._terminate_tree(process)
            finally:
                for stream in (process.stdout,):
                    try:
                        if stream:
                            stream.close()
                    except (OSError, ValueError):
                        pass
                if self._stderr_handle:
                    try:
                        self._stderr_handle.write('=== worker stopped ===\n')
                        self._stderr_handle.close()
                    except (OSError, ValueError):
                        pass
                    self._stderr_handle = None

    def _terminate_tree(self, process):
        if psutil is None:
            process.kill()
            process.wait()
            return
        try:
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            return
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            pass
        _, alive = psutil.wait_procs(children + [parent], timeout=5)
        for item in alive:
            try:
                item.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def kill(self):
        with self.lock:
            process = self.process
            self.process = None
            self.resident = {}
            self.state = 'Stopped'
        if process is not None:
            self._terminate_tree(process)
            if self._stderr_handle:
                try:
                    self._stderr_handle.write('=== worker killed ===\n')
                    self._stderr_handle.close()
                except (OSError, ValueError):
                    pass
                self._stderr_handle = None

    # ----------------------------------------------------------------- SDK worker contract
    def release(self, level):
        if level in ('Model', 'Worker', 'All'):
            self.stop()
        elif level not in ('Temporary', 'Job'):
            raise CyToolError('InvalidParameters', 'Unknown release level')

    def health(self):
        with self.lock:
            alive = bool(self.process and self.process.poll() is None)
            return {'state': 'Busy' if self.busy else ('Idle' if alive else self.state), 'pid': self.process.pid if alive else None,
                    'alive': alive, 'lastResponseMonotonic': self.last_used, 'heartbeatSupported': False, 'resident': dict(self.resident)}

    # ----------------------------------------------------------------- requests
    def request(self, op, payload=None, *, cancelled=None, timeout=None, progress=None, log=None):
        with self.lock:
            if self.busy:
                raise CyToolError('Busy', f'Worker {self.name} is already processing a request')
            self.busy = True
        try:
            self.start()
            request_id = uuid.uuid4().hex
            message = {'id': request_id, 'op': op, **(payload or {})}
            with self.lock:
                self.state = 'Busy'
                try:
                    self.process.stdin.write(json.dumps(message, allow_nan=False) + '\n')
                    self.process.stdin.flush()
                except (OSError, ValueError) as exc:
                    self.kill()
                    raise CyToolError('WorkerCrashed', f'Worker {self.name} refused the request: {exc}')
            return self._wait(request_id, cancelled, timeout, progress, log)
        finally:
            with self.lock:
                self.busy = False
                self.last_used = time.monotonic()
                if self.process and self.process.poll() is None:
                    self.state = 'Idle'

    def _wait(self, request_id, cancelled, timeout, progress, log):
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            if cancelled is not None and cancelled():
                self.kill()
                raise CyToolError('Cancelled', 'Cancelled: worker stopped')
            if deadline and time.monotonic() > deadline:
                self.kill()
                raise CyToolError('Timeout', f'Worker {self.name} exceeded {timeout}s')
            try:
                message = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            event = message.get('event')
            if event == 'closed':
                code = message.get('returncode')
                self.kill()
                raise CyToolError('WorkerCrashed', f'Worker {self.name} exited unexpectedly (code {code})',
                                  details={'log': str(self.log_path) if self.log_path else ''})
            if event == 'progress':
                if progress:
                    try:
                        progress(message)
                    except CyToolError:
                        raise
                    except Exception:
                        pass
                continue
            if event == 'log':
                if log:
                    log(message.get('message', ''), message.get('level', 'Info'))
                continue
            if event == 'resident':
                self.resident = message.get('resident') or {}
                continue
            if message.get('id') != request_id:
                continue
            if message.get('ok'):
                return message.get('result', {})
            details = message.get('details')
            raise CyToolError(message.get('code') or 'InferenceFailed', message.get('message') or 'Worker error',
                              recoverable=bool(message.get('recoverable', False)), details=details if isinstance(details, dict) else {'details': details})

    def run_job(self, context, op, payload=None, *, timeout=None, progress_offset=0.0, progress_scale=1.0):
        """Run a request on behalf of a job: progress, logs, cancellation and pid bookkeeping."""
        context.cancellation.check()
        self.start()
        runtime = getattr(context, 'runtime', None)
        if runtime is not None and self.process is not None and psutil is not None:
            try:
                with runtime._cv:
                    job = runtime._jobs[context.job_id]
                    process = psutil.Process(self.process.pid)
                    job.setdefault('artifactProcesses', []).append({'pid': process.pid, 'created': process.create_time()})
                    runtime._save(job)
            except Exception:
                pass

        def on_progress(message):
            percent = float(message.get('percent', 0.0))
            fields = {}
            for key in ('step', 'currentStep'):
                if message.get(key):
                    fields['currentStep'] = str(message[key])[:200]
            if message.get('message'):
                fields['statusMessage'] = str(message['message'])[:500]
            if message.get('etaSeconds') is not None:
                fields['etaSeconds'] = float(message['etaSeconds'])
            if message.get('currentFile'):
                fields['currentFile'] = str(message['currentFile'])
            context.progress(max(0.0, min(100.0, progress_offset + percent * progress_scale)), **fields)

        def on_log(message, level):
            context.log(message[:16000], level=level if level in ('Info', 'Warning', 'Error', 'Debug') else 'Info')

        return self.request(op, payload, cancelled=_cancel_probe(context.cancellation), timeout=timeout, progress=on_progress, log=on_log)


def _cancel_probe(token):
    event = getattr(token, 'event', None)

    def probe():
        if event is not None and event.is_set():
            return True
        try:
            token.check()
            return False
        except CyToolError:
            return True
        except Exception:
            return True
    return probe


class WorkerPool:
    """One host per worker script; registered with the runtime for release/health."""

    def __init__(self, runtime=None):
        self.runtime = runtime
        self.hosts = {}
        self.lock = threading.RLock()

    def get(self, name, factory):
        with self.lock:
            host = self.hosts.get(name)
            if host is None:
                host = factory()
                self.hosts[name] = host
                if self.runtime is not None:
                    try:
                        self.runtime.register_worker('worker-' + name, host)
                    except Exception:
                        pass
            return host

    def make_exclusive(self, name):
        """Stop the other GPU-holding workers before a heavy job (24 GiB cards are not infinite)."""
        with self.lock:
            for other, host in self.hosts.items():
                if other != name and host.health()['alive'] and host.resident.get('gpu'):
                    host.stop()

    def status(self):
        with self.lock:
            return {name: host.health() for name, host in self.hosts.items()}

    def stop_all(self):
        with self.lock:
            for host in self.hosts.values():
                host.stop()
