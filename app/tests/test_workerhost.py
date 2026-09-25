"""WorkerHost / WorkerPool with a fake protocol worker, then the real DSP worker (run from the app directory)."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

import numpy as np
import psutil

from tests._fixtures import APP, tone, write_wav, CYDAW_PLUGIN, cydaw_available, rms_db
from cytools_core import CyToolError, CancellationToken
from audiostudio import audio_io
from audiostudio.engines import registry as engines
from audiostudio.engines.workerhost import WorkerHost, WorkerPool
from audiostudio.workflow import model as workflow_model

FAKE_WORKER = '''
import os, sys, time
sys.path.insert(0, {app!r})
from workers import _protocol
from workers._protocol import serve, WorkerError


def echo(request, reporter):
    return {{'echo': request.get('value'), 'pid': os.getpid()}}


def progress(request, reporter):
    for index in range(3):
        reporter.progress(index * 40, step='step%d' % index, message='m%d' % index, etaSeconds=3 - index)
    reporter.progress(80, step='step2', message='m2')          # duplicate of the last key is not re-emitted
    reporter.log('hello from worker', 'Warning')
    reporter.resident(gpu=True, models=['fake'])
    return {{'done': True}}


def fail(request, reporter):
    raise WorkerError('CustomFailure', 'boom', details={{'k': 1}}, recoverable=True)


def value_error(request, reporter):
    raise ValueError('bad value')


def crash(request, reporter):
    os._exit(3)


def sleep(request, reporter):
    time.sleep(float(request.get('seconds', 5)))
    return {{'slept': True}}


def noise(request, reporter):
    _protocol.PROTOCOL.write('garbage line\\n')
    _protocol.PROTOCOL.flush()
    print('a print goes to stderr, not to the protocol')
    return {{'ok': 1}}


def nan(request, reporter):
    return {{'value': float('nan')}}


raise SystemExit(serve({{'echo': echo, 'progress': progress, 'fail': fail, 'value_error': value_error, 'crash': crash,
                         'sleep': sleep, 'noise': noise, 'nan': nan}}))
'''

EXIT_WORKER = 'import sys\nsys.exit(2)\n'


class FakeContext:
    """Minimal JobContext stand-in for WorkerHost.run_job."""

    def __init__(self):
        self.cancellation = CancellationToken()
        self.progress_calls = []
        self.logs = []
        self.runtime = None
        self.job_id = 'job-1'

    def progress(self, percent, **fields):
        self.cancellation.check()
        self.progress_calls.append((percent, fields))

    def log(self, message, level='Info'):
        self.logs.append((message, level))


def wait_until(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class FakeWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.script = Path(cls.workdir.name) / 'fake_worker.py'
        cls.script.write_text(FAKE_WORKER.format(app=str(APP)), encoding='utf-8')
        cls.exit_script = Path(cls.workdir.name) / 'exit_worker.py'
        cls.exit_script.write_text(EXIT_WORKER, encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.workdir.cleanup()

    def host(self, script=None, idle_seconds=0, **fields):
        host = WorkerHost('fake', [sys.executable, script or self.script], cwd=APP, env=engines.base_environment(),
                          log_path=Path(self.workdir.name) / 'logs' / 'fake.log', idle_seconds=idle_seconds, startup_timeout=60, **fields)
        self.addCleanup(host.stop)
        return host

    def test_handshake_and_health(self):
        host = self.host()
        self.assertEqual(host.health()['state'], 'Stopped')
        self.assertFalse(host.health()['alive'])
        host.start()
        health = host.health()
        self.assertTrue(health['alive'])
        self.assertEqual(health['state'], 'Idle')
        self.assertIsInstance(health['pid'], int)
        self.assertTrue(psutil.pid_exists(health['pid']))
        self.assertFalse(health['heartbeatSupported'])
        pid = health['pid']
        host.start()                                    # idempotent while alive
        self.assertEqual(host.health()['pid'], pid)
        self.assertTrue((Path(self.workdir.name) / 'logs' / 'fake.log').is_file())

    def test_request_result_progress_logs_resident(self):
        host = self.host()
        self.assertEqual(host.request('echo', {'value': 'x'})['echo'], 'x')
        # With a venv trampoline (uv) the interpreter is a child of the spawned process; both are in the tree.
        tree = [host.health()['pid']] + [c.pid for c in psutil.Process(host.health()['pid']).children(recursive=True)]
        self.assertIn(host.request('echo', {'value': 'x'})['pid'], tree)
        events, logs = [], []
        result = host.request('progress', {}, progress=events.append, log=lambda message, level: logs.append((message, level)))
        self.assertEqual(result, {'done': True})
        self.assertEqual([e['percent'] for e in events], [0.0, 40.0, 80.0])
        self.assertEqual([e['step'] for e in events], ['step0', 'step1', 'step2'])
        self.assertEqual([e['message'] for e in events], ['m0', 'm1', 'm2'])
        self.assertEqual([e['etaSeconds'] for e in events], [3, 2, 1])
        self.assertEqual(logs, [('hello from worker', 'Warning')])
        self.assertEqual(host.resident, {'gpu': True, 'models': ['fake']})
        self.assertEqual(host.health()['resident'], {'gpu': True, 'models': ['fake']})
        self.assertEqual(host.health()['state'], 'Idle')

    def test_error_codes(self):
        host = self.host()
        with self.assertRaises(CyToolError) as ctx:
            host.request('fail', {})
        self.assertEqual(ctx.exception.code, 'CustomFailure')
        self.assertEqual(str(ctx.exception), 'boom')
        self.assertEqual(ctx.exception.details, {'k': 1})
        self.assertTrue(ctx.exception.recoverable)
        with self.assertRaises(CyToolError) as ctx:
            host.request('value_error', {})
        self.assertEqual(ctx.exception.code, 'InvalidParameters')
        with self.assertRaises(CyToolError) as ctx:
            host.request('nan', {})
        self.assertEqual(ctx.exception.code, 'InvalidParameters')     # non-finite result refused by the protocol
        with self.assertRaises(CyToolError) as ctx:
            host.request('no_such_op', {})
        self.assertEqual(ctx.exception.code, 'InvalidParameters')
        self.assertIn('Unknown worker operation', str(ctx.exception))
        self.assertTrue(host.health()['alive'])                    # errors keep the process alive
        self.assertEqual(host.request('echo', {'value': 1})['echo'], 1)

    def test_non_json_output_becomes_log(self):
        host = self.host()
        logs = []
        self.assertEqual(host.request('noise', {}, log=lambda message, level: logs.append((message, level))), {'ok': 1})
        self.assertEqual(logs, [('Non-JSON worker output: garbage line', 'Warning')])

    def test_crash_then_automatic_restart(self):
        host = self.host()
        pid = host.request('echo', {})['pid']
        with self.assertRaises(CyToolError) as ctx:
            host.request('crash', {})
        self.assertEqual(ctx.exception.code, 'WorkerCrashed')
        self.assertIn('exited unexpectedly', str(ctx.exception))
        self.assertIn('log', ctx.exception.details)
        self.assertFalse(host.health()['alive'])
        self.assertEqual(host.health()['state'], 'Stopped')
        self.assertNotEqual(host.request('echo', {})['pid'], pid)      # a new process serves the next request
        self.assertTrue(host.health()['alive'])

    def test_startup_failures(self):
        with self.assertRaises(CyToolError) as ctx:
            self.host(script=self.exit_script).start()
        self.assertEqual(ctx.exception.code, 'WorkerCrashed')
        broken = WorkerHost('broken', ['no-such-executable-cytools-test'], idle_seconds=0)
        with self.assertRaises(CyToolError) as ctx:
            broken.start()
        self.assertEqual(ctx.exception.code, 'MissingRuntime')
        self.assertEqual(broken.state, 'Failed')

    def test_cancellation_kills_process(self):
        host = self.host()
        host.start()
        pid = host.health()['pid']
        process = psutil.Process(pid)
        tree = [process] + process.children(recursive=True)
        polls = {'n': 0}

        def cancelled():
            polls['n'] += 1
            return polls['n'] >= 3
        started = time.monotonic()
        with self.assertRaises(CyToolError) as ctx:
            host.request('sleep', {'seconds': 30}, cancelled=cancelled)
        self.assertEqual(ctx.exception.code, 'Cancelled')
        self.assertLess(time.monotonic() - started, 15.0)
        for item in tree:                                   # the whole process tree is gone, not only the launcher
            self.assertFalse(item.is_running() and item.status() != psutil.STATUS_ZOMBIE, item)
        self.assertFalse(host.health()['alive'])
        self.assertIsNone(host.process)

    def test_timeout_kills_process(self):
        host = self.host()
        host.start()
        process = psutil.Process(host.health()['pid'])
        with self.assertRaises(CyToolError) as ctx:
            host.request('sleep', {'seconds': 30}, timeout=0.5)
        self.assertEqual(ctx.exception.code, 'Timeout')
        self.assertFalse(process.is_running() and process.status() != psutil.STATUS_ZOMBIE)
        self.assertFalse(host.health()['alive'])

    def test_busy_rejects_concurrent_request(self):
        host = self.host()
        host.start()
        outcome = {}

        def slow():
            outcome['result'] = host.request('sleep', {'seconds': 1.5})
        thread = threading.Thread(target=slow)
        thread.start()
        self.assertTrue(wait_until(lambda: host.busy, 5.0))
        self.assertEqual(host.health()['state'], 'Busy')
        with self.assertRaises(CyToolError) as ctx:
            host.request('echo', {})
        self.assertEqual(ctx.exception.code, 'Busy')
        thread.join(10)
        self.assertEqual(outcome['result'], {'slept': True})
        self.assertFalse(host.busy)

    def test_idle_unload_stops_process(self):
        host = self.host(idle_seconds=1)
        host.request('echo', {})
        pid = host.health()['pid']
        self.assertTrue(host.health()['alive'])
        # The idle loop polls every 5 seconds.
        self.assertTrue(wait_until(lambda: not host.health()['alive'], 15.0))
        self.assertFalse(psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE)
        self.assertEqual(host.state, 'Stopped')
        self.assertEqual(host.request('echo', {'value': 2})['echo'], 2)      # transparently restarted

    def test_stop_release_and_health(self):
        host = self.host()
        host.start()
        pid = host.health()['pid']
        host.stop()
        self.assertFalse(host.health()['alive'])
        self.assertEqual(host.health()['state'], 'Stopped')
        self.assertIsNone(host.health()['pid'])
        self.assertTrue(wait_until(lambda: not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE, 5.0))
        host.stop()                                     # idempotent
        host.start()
        host.release('Temporary')
        self.assertTrue(host.health()['alive'])
        host.release('Job')
        self.assertTrue(host.health()['alive'])
        host.release('Model')
        self.assertFalse(host.health()['alive'])
        with self.assertRaises(CyToolError) as ctx:
            host.release('Bogus')
        self.assertEqual(ctx.exception.code, 'InvalidParameters')
        host.start()
        host.kill()
        self.assertFalse(host.health()['alive'])
        self.assertEqual(host.resident, {})

    def test_run_job_forwards_progress_and_cancellation(self):
        host = self.host()
        context = FakeContext()
        result = host.run_job(context, 'progress', {}, progress_offset=50.0, progress_scale=0.5)
        self.assertEqual(result, {'done': True})
        self.assertEqual([p for p, _ in context.progress_calls], [50.0, 70.0, 90.0])
        self.assertEqual(context.progress_calls[1][1], {'currentStep': 'step1', 'statusMessage': 'm1', 'etaSeconds': 2.0})
        self.assertEqual(context.logs, [('hello from worker', 'Warning')])
        cancelling = FakeContext()
        threading.Timer(0.5, cancelling.cancellation.cancel).start()
        with self.assertRaises(CyToolError) as ctx:
            host.run_job(cancelling, 'sleep', {'seconds': 30})
        self.assertEqual(ctx.exception.code, 'Cancelled')
        self.assertFalse(host.health()['alive'])
        already = FakeContext()
        already.cancellation.cancel()
        with self.assertRaises(CyToolError) as ctx:
            host.run_job(already, 'echo', {})
        self.assertEqual(ctx.exception.code, 'Cancelled')

    def test_worker_pool(self):
        registered = {}

        class FakeRuntime:
            def register_worker(self, worker_id, worker):
                registered[worker_id] = worker
        pool = WorkerPool(FakeRuntime())
        made = {'n': 0}

        def factory():
            made['n'] += 1
            return self.host()
        first = pool.get('fake', factory)
        self.assertIs(pool.get('fake', factory), first)
        self.assertEqual(made['n'], 1)
        self.assertEqual(list(registered), ['worker-fake'])
        second = pool.get('other', lambda: self.host())
        second.start()
        second.resident = {'gpu': True}
        first.start()
        pool.make_exclusive('fake')
        self.assertFalse(second.health()['alive'])          # the other GPU-holding worker was stopped
        self.assertTrue(first.health()['alive'])
        status = pool.status()
        self.assertEqual(set(status), {'fake', 'other'})
        self.assertTrue(status['fake']['alive'])
        pool.stop_all()
        self.assertFalse(any(h['alive'] for h in pool.status().values()))


class DspWorkerTests(unittest.TestCase):
    """The real dsp_worker.py through WorkerHost, with the interpreter running the tests."""

    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.root = Path(cls.workdir.name).resolve()
        cls.host = WorkerHost('dsp', [sys.executable, APP / 'workers' / 'dsp_worker.py'], cwd=APP, env=engines.base_environment(),
                              log_path=cls.root / 'logs' / 'dsp.log', idle_seconds=0, startup_timeout=180)
        cls.audio = tone(1.0, 48000, 2)
        cls.source = write_wav(cls.root / 'tone.wav', cls.audio, 48000)

    @classmethod
    def tearDownClass(cls):
        cls.host.stop()
        cls.workdir.cleanup()

    def test_render_workflow_with_tail(self):
        workflow = workflow_model.new_workflow('Delay', nodes=[{'kind': 'effect', 'effect': 'delay', 'params': {'delay_seconds': 0.2, 'feedback': 0.5, 'mix': 0.5}}], tail={'max_seconds': 3.0})
        events = []
        output = self.root / 'out' / 'rendered.wav'
        report = self.host.request('render', {'input': str(self.source), 'output': 'out/rendered.wav', 'workflow': workflow, 'format': 'wav', 'subtype': 'PCM_24',
                                              'workspace': str(self.root)}, progress=events.append)
        self.assertTrue(output.is_file())
        self.assertEqual(Path(report['file']).resolve(), output.resolve())      # 8.3 short names differ on Windows
        self.assertGreater(report['tailSeconds'], 0.2)
        self.assertEqual(report['originalFrames'], 48000)
        self.assertGreater(report['frames'], 48000)
        self.assertEqual(report['sizeBytes'], output.stat().st_size)
        self.assertIsNone(report['selection'])
        self.assertEqual(audio_io.probe(output).subtype, 'PCM_24')
        percents = [e['percent'] for e in events]
        self.assertEqual(percents[-1], 100.0)
        steps = [e.get('step') for e in events]
        for step in ('Decoding', 'Rendering', 'Encoding', 'Done'):
            self.assertIn(step, steps)
        with self.assertRaises(CyToolError) as ctx:
            self.host.request('render', {'input': str(self.source), 'output': '../escape.wav', 'workflow': workflow, 'workspace': str(self.root)})
        self.assertEqual(ctx.exception.code, 'AccessDenied')

    def test_render_progress_is_monotonic_known_bug(self):
        """Known bug: dsp_worker.render reports 1 % (Decoding), then the engine's 0..100 % (ending with 100 % 'done'),
        then 96 % (Encoding) and 100 % again, so the job progress goes backwards twice."""
        events = []
        workflow = workflow_model.new_workflow('Gain', nodes=[{'kind': 'effect', 'effect': 'gain'}], tail={'max_seconds': 0.2})
        self.host.request('render', {'input': str(self.source), 'output': str(self.root / 'mono.wav'), 'workflow': workflow, 'format': 'wav'}, progress=events.append)
        percents = [e['percent'] for e in events]
        self.assertEqual(percents, sorted(percents), percents)

    def test_render_selection_overlaps_following_audio(self):
        workflow = workflow_model.new_workflow('Gain', nodes=[{'kind': 'effect', 'effect': 'gain', 'params': {'gain_db': -20.0}}])
        output = self.root / 'selected.wav'
        report = self.host.request('render', {'input': str(self.source), 'output': str(output), 'workflow': workflow, 'format': 'wav', 'subtype': 'FLOAT', 'selection': [0.0, 0.5]})
        self.assertEqual(report['selection'], [0.0, 0.5])
        rendered, rate = audio_io.load(output)
        self.assertEqual(rendered.shape, self.audio.shape)
        self.assertAlmostEqual(rms_db(rendered[:, :24000]) - rms_db(self.audio[:, :24000]), -20.0, delta=0.1)
        self.assertTrue(np.allclose(rendered[:, 24000:], self.audio[:, 24000:], atol=1e-6))
        with self.assertRaises(CyToolError) as ctx:
            self.host.request('render', {'input': str(self.source), 'output': str(output), 'workflow': workflow, 'selection': [0.5, 0.2]})
        self.assertEqual(ctx.exception.code, 'InvalidParameters')

    def test_render_buffer(self):
        source = self.root / 'buffer.npy'
        np.save(str(source), self.audio)
        workflow = workflow_model.new_workflow('Invert', nodes=[{'kind': 'effect', 'effect': 'invert'}])
        report = self.host.request('render_buffer', {'input': str(source), 'samplerate': 48000, 'output': str(self.root / 'buffer_out.npy'), 'workflow': workflow})
        result = np.load(report['file'])
        self.assertEqual(result.shape, self.audio.shape)
        self.assertTrue(np.allclose(result, -self.audio, atol=1e-6))

    @unittest.skipUnless(cydaw_available(), 'CyDAW Test Gain.vst3 is not built on this machine')
    def test_scan_and_describe_plugin(self):
        cache_dir = self.root / 'plugin-cache'
        result = self.host.request('scan', {'directories': [str(CYDAW_PLUGIN.parent)], 'cache_dir': str(cache_dir)})
        self.assertGreaterEqual(result['count'], 1)
        self.assertEqual(result['failures'], [])
        plugin = next(p for p in result['plugins'] if p.get('name') == 'CyDAW Test Gain')
        self.assertEqual(plugin['state'], 'ok')
        self.assertIn('gain_x', plugin['parameters'])
        self.assertTrue(plugin['isEffect'])
        self.assertTrue((cache_dir / 'vst3-catalogue.json').is_file())
        again = self.host.request('scan', {'directories': [str(CYDAW_PLUGIN.parent)], 'cache_dir': str(cache_dir)})
        self.assertEqual(again['count'], result['count'])          # served from the cache
        self.assertEqual(self.host.request('scan', {'directories': [str(self.root / 'no-plugins')]})['count'], 0)
        description = self.host.request('describe', {'plugin': str(CYDAW_PLUGIN)})
        self.assertEqual(description['name'], 'CyDAW Test Gain')
        self.assertEqual(description['parameters']['gain_x']['type'], 'float')
        with self.assertRaises(CyToolError):
            self.host.request('describe', {'plugin': str(self.root / 'missing.vst3')})
        # A VST3 node rendered by the worker.
        workflow = workflow_model.new_workflow('VST', nodes=[{'kind': 'vst3', 'plugin': str(CYDAW_PLUGIN), 'params': {'gain_x': 0.5}}], tail={'max_seconds': 0.5})
        output = self.root / 'vst.wav'
        self.host.request('render', {'input': str(self.source), 'output': str(output), 'workflow': workflow, 'format': 'wav', 'subtype': 'FLOAT'})
        rendered, _ = audio_io.load(output)
        self.assertAlmostEqual(rms_db(rendered) - rms_db(self.audio), 20 * np.log10(0.5), delta=0.2)
        self.assertGreaterEqual(self.host.request('status', {})['pluginsLoaded'], 1)

    def test_analyze(self):
        stats = self.host.request('analyze', {'input': str(self.source)})
        for key in ('peakDbfs', 'rmsDbfs', 'integratedLufs', 'truePeakDbtp', 'leadingSeconds', 'trailingSeconds', 'clippedSamples', 'info'):
            self.assertIn(key, stats)
        self.assertEqual(stats['info']['samplerate'], 48000)
        self.assertAlmostEqual(stats['durationSeconds'], 1.0)
        self.assertAlmostEqual(stats['peakDbfs'], 20 * np.log10(0.5), delta=0.05)

    def test_convert(self):
        output = self.root / 'converted.flac'
        result = self.host.request('convert', {'input': str(self.source), 'output': str(output), 'format': 'flac', 'subtype': 'PCM_16', 'samplerate': 22050, 'channels': 1})
        self.assertEqual((result['samplerate'], result['channels']), (22050, 1))
        self.assertAlmostEqual(result['durationSeconds'], 1.0, places=3)
        info = audio_io.probe(output)
        self.assertEqual((info.format, info.samplerate, info.channels, info.frames), ('FLAC', 22050, 1, 22050))
        stereo = self.host.request('convert', {'input': str(output), 'output': str(self.root / 'stereo.wav'), 'format': 'wav', 'channels': 2})
        self.assertEqual(stereo['channels'], 2)

    def test_missing_input_error_path(self):
        missing = str(self.root / 'does-not-exist.wav')
        for op, payload in (('render', {'input': missing, 'output': str(self.root / 'x.wav'), 'workflow': workflow_model.new_workflow('E')}),
                            ('analyze', {'input': missing}), ('convert', {'input': missing, 'output': str(self.root / 'y.wav'), 'format': 'wav'})):
            with self.subTest(op=op):
                with self.assertRaises(CyToolError) as ctx:
                    self.host.request(op, payload)
                self.assertEqual(ctx.exception.code, 'MissingInput')
        self.assertTrue(self.host.health()['alive'])
        status = self.host.request('status', {})
        self.assertIn('pedalboard', status)


if __name__ == '__main__':
    unittest.main()
