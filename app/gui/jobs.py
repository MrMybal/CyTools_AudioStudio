"""Job submission and polling for the interface. The UI never schedules work itself."""
import time

from cytools_core import CyToolError


class Jobs:
    TERMINAL = ('Completed', 'Failed', 'Cancelled')

    def __init__(self, runtime, actor, session):
        self.runtime, self.actor, self.session = runtime, actor, session
        self.active = {}          # job_id -> {'operation', 'callback', 'label', 'job'}
        self.history = []         # last finished jobs (most recent first)
        self.message = ''
        self.error = ''
        self.last_poll = 0.0

    def submit(self, operation, parameters, callback=None, label='', backend_id='', model_id='', priority='Normal'):
        try:
            job = self.runtime.submit(self.actor, self.session, operation, parameters, backend_id=backend_id, model_id=model_id, priority=priority)
        except CyToolError as exc:
            self.error = f'{operation}: {exc.code}: {exc}'
            return None
        except Exception as exc:
            self.error = f'{operation}: {exc}'
            return None
        self.active[job['jobId']] = {'operation': operation, 'callback': callback, 'label': label or operation, 'job': job, 'started': time.time()}
        self.error = ''
        self.message = 'Submitted ' + (label or operation)
        return job

    def poll(self):
        now = time.monotonic()
        if now - self.last_poll < 0.15:
            return
        self.last_poll = now
        for job_id in list(self.active):
            entry = self.active[job_id]
            try:
                job = self.runtime.get_job(self.actor, job_id)
            except Exception as exc:
                self.error = str(exc)
                continue
            entry['job'] = job
            if job['state'] in self.TERMINAL:
                self.active.pop(job_id, None)
                self.history.insert(0, entry)
                del self.history[20:]
                if job['state'] == 'Failed':
                    error = job.get('error') or {}
                    self.error = f"{entry['label']}: {error.get('code', 'Failed')}: {error.get('message', '')}"
                elif job['state'] == 'Cancelled':
                    self.message = entry['label'] + ' cancelled'
                else:
                    self.message = entry['label'] + ' completed'
                if entry['callback']:
                    try:
                        entry['callback'](job)
                    except Exception as exc:
                        self.error = f"{entry['label']}: {exc}"

    def cancel(self, job_id):
        try:
            self.runtime.cancel(self.actor, job_id)
        except Exception as exc:
            self.error = str(exc)

    def cancel_all(self):
        for job_id in list(self.active):
            self.cancel(job_id)

    def running(self, *operations):
        return [e['job'] for e in self.active.values() if not operations or e['operation'] in operations]

    def is_running(self, *operations):
        return bool(self.running(*operations))

    def progress_text(self, job):
        progress = job.get('progress') or {}
        parts = [job.get('state', '')]
        if progress.get('currentStep'):
            parts.append(str(progress['currentStep']))
        if progress.get('statusMessage'):
            parts.append(str(progress['statusMessage']))
        return ' - '.join(parts)

    def run_sync(self, operation, parameters, timeout=120, backend_id='', model_id=''):
        """Blocking helper for quick catalogue calls (lists, presets); not for generation."""
        job = self.runtime.submit(self.actor, self.session, operation, parameters, backend_id=backend_id, model_id=model_id)
        result = self.runtime.wait(self.actor, job['jobId'], timeout=timeout)
        if result['state'] != 'Completed':
            error = result.get('error') or {}
            raise CyToolError(error.get('code', 'Failed'), error.get('message', operation + ' failed'))
        return result['outputs']
