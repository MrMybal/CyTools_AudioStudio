"""End-to-end operation tests through the Core runtime, on a temporary data directory (run from the app directory).

Everything the Tool would write under data/ (inputs, logs, workflows, presets, plugin cache, install state)
is redirected to the temporary directory for the duration of the class, so no file is left behind.
"""
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
import psutil

from tests._fixtures import APP, tone, write_wav, CYDAW_PLUGIN, cydaw_available, piper_available, rms_db, PIPER_VOICE, PIPER_MODEL_ID
from cytools_core import CyToolError, load_manifest, validate_manifest
import audiostudio.paths as paths
from audiostudio import models, audio_io
from audiostudio.operations import common, processing
from audiostudio.voice import presets
from audiostudio.dsp import effects
from audiostudio.workflow import model as workflow_model
from tool import create_runtime

RATE = 48000


def effect(effect_id, params=None, **fields):
    return {'kind': 'effect', 'effect': effect_id, 'params': params or {}, **fields}


def delay_workflow(name='Delay', max_seconds=3.0):
    return workflow_model.new_workflow(name, nodes=[effect('delay', {'delay_seconds': 0.2, 'feedback': 0.5, 'mix': 0.5})], tail={'max_seconds': max_seconds})


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = cls.root = Path(cls.workdir.name).resolve()          # long names: the SDK resolves paths too
        cls.patches = [
            mock.patch.object(paths, 'INPUTS', root / 'inputs'),
            mock.patch.object(common, 'LOGS', root / 'logs'),
            mock.patch.object(common, 'WORKFLOWS', root / 'workflows'),
            mock.patch.object(processing, 'WORKFLOWS', root / 'workflows'),
            mock.patch.object(common, 'PLUGIN_CACHE', root / 'settings' / 'plugins'),
            mock.patch.object(presets, 'FOLDER', root / 'presets' / 'voices'),
            mock.patch.object(models, 'STATE_DIR', root / 'settings' / 'install-state'),
        ]
        for patch in cls.patches:
            patch.start()
        (root / 'workflows').mkdir(parents=True)
        cls.runtime = create_runtime(str(root / 'jobs')).start()
        # The runtime reserves against the memory free when it starts: another application holding
        # the machine's RAM makes every job refused (InsufficientRAM). That is the scheduler being
        # honest, not a failure of these tests.
        free = cls.runtime.ledger.capacity.get('ramBytes', 0)
        if free < 2 * 1024 ** 3:
            cls.runtime.close()
            raise unittest.SkipTest(f'only {free / 1e9:.1f} GB of RAM available to the runtime; close the other applications to run the runtime tests')
        # Alice holds every permission an operation declares (install_model needs "network"); Bob holds none.
        permissions = sorted({p for op in cls.runtime.descriptor['operations'] for p in op.get('permissions', [])})
        cls.alice = cls.runtime.authenticate(cls.runtime.create_client('Alice', permissions)['token'])
        cls.bob = cls.runtime.authenticate(cls.runtime.create_client('Bob')['token'])
        cls.session = cls.runtime.create_session(cls.alice)['sessionId']
        cls.audio = tone(1.0, RATE, 2)
        cls.tone_path = write_wav(root / 'fixtures' / 'tone.wav', cls.audio, RATE)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.runtime.close()
        finally:
            for patch in cls.patches:
                patch.stop()
            cls.workdir.cleanup()

    # ------------------------------------------------------------------ helpers
    def run_op(self, operation, parameters, *, backend_id='', timeout=240, principal=None, session=None):
        principal = principal or self.alice
        job = self.runtime.submit(principal, session or self.session, operation, parameters, backend_id=backend_id)
        return self.runtime.wait(principal, job['jobId'], timeout=timeout)

    def completed(self, operation, parameters, **fields):
        job = self.run_op(operation, parameters, **fields)
        self.assertEqual(job['state'], 'Completed', job.get('error'))
        return job['outputs']

    def failed(self, operation, parameters, code, **fields):
        job = self.run_op(operation, parameters, **fields)
        self.assertEqual(job['state'], 'Failed', job.get('outputs'))
        self.assertEqual(job['error']['code'], code, job['error'])
        return job

    def save_workflow(self, name, document=None):
        return self.completed('save_workflow', {'name': name, 'workflow': document or delay_workflow(name), 'overwrite': True})

    # ------------------------------------------------------------------ contract
    def test_manifest_and_handlers(self):
        descriptor = load_manifest(APP / 'CyTool.json')
        validate_manifest(descriptor)
        ids = {op['id'] for op in descriptor['operations']}
        self.assertGreaterEqual(len(ids), 30)
        missing = ids - set(self.runtime._handlers)
        self.assertEqual(missing, set())
        for operation_id in ids:
            self.assertEqual(self.runtime.operation(operation_id)['id'], operation_id)
        self.assertIn('installation_storage_status', self.runtime._handlers)   # added by the SDK's shared installation
        with self.assertRaises(CyToolError) as ctx:
            self.runtime.operation('no_such_operation')
        self.assertEqual(ctx.exception.code, 'UnknownOperation')
        self.assertEqual(self.runtime.status()['toolId'], 'cy.tool.audiostudio')
        self.assertTrue(self.runtime.status()['acceptingJobs'])
        storage = self.completed('installation_storage_status', {})
        self.assertIn('components', storage)
        self.assertIn('downloadMode', storage)

    def test_runtime_status_counts_the_worker_processes(self):
        """SDK 0.10: GetRuntimeStatus observes the Tool's worker hosts, and CanRun reports the concurrency wait."""
        self.completed('convert_audio', {'input': str(self.tone_path), 'output_format': 'wav'})   # starts the DSP worker
        status = self.runtime.status()
        self.assertGreaterEqual(status['runningWorkers'], 1)
        self.assertEqual(status['unknownWorkers'], 0)
        verdict = self.runtime.can_run('list_effects', {})
        self.assertTrue(verdict['canRun'], verdict)
        self.assertIs(verdict['waitingForConcurrency'], False)

    def test_invalid_parameters_are_refused_before_a_job_exists(self):
        before = len(self.runtime.list_jobs(self.alice))
        cases = [
            ('generate_sfx', {'prompt': 'rain', 'variations': 99}, 'sfx_procedural'),
            ('generate_sfx', {'variations': 1}, 'sfx_procedural'),                        # missing required prompt
            ('generate_sfx', {'prompt': ''}, 'sfx_procedural'),                            # minLength
            ('convert_audio', {'input': str(self.tone_path), 'output_format': 'xyz'}, ''),   # wrong enum
            ('process_audio', {'input': str(self.tone_path), 'bogus': 1}, ''),           # additionalProperties
            ('process_audio', {'input': str(self.tone_path), 'tail': {'max_seconds': 1e9}}, ''),
            ('voice_piper', {'text': 'x', 'speaker': -1}, 'piper'),
            ('save_voice_preset', {'name': 'x', 'backend': 'espeak', 'parameters': {}}, ''),
        ]
        for operation, parameters, backend in cases:
            with self.subTest(operation=operation, parameters=parameters):
                with self.assertRaises(CyToolError) as ctx:
                    self.runtime.submit(self.alice, self.session, operation, parameters, backend_id=backend)
                self.assertEqual(ctx.exception.code, 'InvalidParameters')
        with self.assertRaises(CyToolError) as ctx:
            self.runtime.submit(self.alice, self.session, 'generate_sfx', {'prompt': 'rain'})     # two backends: choose one
        self.assertEqual(ctx.exception.code, 'UnsupportedBackend')
        with self.assertRaises(CyToolError) as ctx:
            self.runtime.submit(self.alice, self.session, 'generate_sfx', {'prompt': 'rain'}, backend_id='piper')
        self.assertEqual(ctx.exception.code, 'UnsupportedBackend')
        with self.assertRaises(CyToolError):
            self.runtime.submit(self.alice, self.session, 'no_such_operation', {})
        self.assertEqual(len(self.runtime.list_jobs(self.alice)), before)

    def test_two_clients_are_isolated(self):
        job = self.run_op('list_effects', {})
        self.assertEqual(job['state'], 'Completed')
        self.assertEqual(self.runtime.list_jobs(self.bob), [])
        self.assertIn(job['jobId'], [j['jobId'] for j in self.runtime.list_jobs(self.alice)])
        for call in (lambda: self.runtime.get_job(self.bob, job['jobId']), lambda: self.runtime.cancel(self.bob, job['jobId']),
                     lambda: self.runtime.submit(self.bob, self.session, 'list_effects', {})):
            with self.assertRaises(CyToolError) as ctx:
                call()
            self.assertEqual(ctx.exception.code, 'AccessDenied')
        bob_session = self.runtime.create_session(self.bob)['sessionId']
        bob_job = self.run_op('list_effects', {}, principal=self.bob, session=bob_session)
        self.assertEqual(bob_job['state'], 'Completed')
        self.assertEqual([j['jobId'] for j in self.runtime.list_jobs(self.bob)], [bob_job['jobId']])
        self.assertNotIn(bob_job['jobId'], [j['jobId'] for j in self.runtime.list_jobs(self.alice)])
        self.runtime.finish_task(self.bob, bob_session)

    # ------------------------------------------------------------------ processing
    def test_process_audio_with_delay_tail(self):
        job = self.run_op('process_audio', {'input': str(self.tone_path), 'workflow': delay_workflow(), 'output_name': 'with tail'})
        self.assertEqual(job['state'], 'Completed', job.get('error'))
        outputs = job['outputs']
        self.assertGreater(outputs['report']['tailSeconds'], 0.2)
        self.assertGreater(outputs['durationSeconds'], 1.0)
        self.assertEqual((outputs['sampleRate'], outputs['channels'], outputs['mimeType']), (RATE, 2, 'audio/wav'))
        target = Path(outputs['file'])
        self.assertTrue(target.is_file())
        self.assertEqual(target.name, 'with tail.wav')
        self.assertTrue(target.is_relative_to(Path(job['workspace'])))
        self.assertEqual(outputs['sizeBytes'], target.stat().st_size)
        self.assertEqual(job['progress']['percent'], 100)
        # Tail override disables the extension: the output keeps the input length.
        outputs = self.completed('process_audio', {'input': str(self.tone_path), 'workflow': delay_workflow(), 'tail': {'enabled': False}, 'output_format': 'flac'})
        self.assertAlmostEqual(outputs['durationSeconds'], 1.0)
        self.assertEqual(outputs['report']['tailSeconds'], 0.0)
        self.assertTrue(outputs['file'].endswith('_processed.flac'))
        self.assertEqual(outputs['mimeType'], 'audio/flac')
        # The input copy imported by the Task lives under the redirected inputs root, never data/inputs.
        imported = Path(outputs['report']['input']).resolve()
        self.assertTrue(imported.is_relative_to(self.root / 'inputs'), imported)
        self.assertFalse(imported.is_relative_to(paths.DATA.resolve()))

    def test_process_audio_with_selection(self):
        workflow = workflow_model.new_workflow('Gain', nodes=[effect('gain', {'gain_db': -20.0})])
        outputs = self.completed('process_audio', {'input': str(self.tone_path), 'workflow': workflow, 'selection_start': 0.0, 'selection_end': 0.5, 'subtype': 'FLOAT'})
        self.assertEqual(outputs['report']['selection'], [0.0, 0.5])
        rendered, rate = audio_io.load(outputs['file'])
        self.assertEqual(rendered.shape, self.audio.shape)
        self.assertAlmostEqual(rms_db(rendered[:, :24000]) - rms_db(self.audio[:, :24000]), -20.0, delta=0.1)
        self.assertTrue(np.allclose(rendered[:, 24000:], self.audio[:, 24000:], atol=1e-6))
        # selection_end -1 means "to the end of the file".
        outputs = self.completed('process_audio', {'input': str(self.tone_path), 'workflow': workflow, 'selection_start': 0.5, 'subtype': 'FLOAT'})
        self.assertEqual(outputs['report']['selection'], [0.5, 1.0])

    def test_process_audio_error_paths(self):
        self.failed('process_audio', {'input': str(self.tone_path)}, 'InvalidParameters')                        # no workflow at all
        self.failed('process_audio', {'input': str(self.tone_path), 'workflow_name': 'no-such-workflow'}, 'MissingInput')
        self.failed('process_audio', {'input': str(self.tone_path), 'workflow': {'format': 'x'}}, 'InvalidParameters')
        self.failed('process_audio', {'input': str(self.root / 'missing.wav'), 'workflow': delay_workflow()}, 'MissingInput')
        text = self.root / 'fixtures' / 'notes.txt'
        text.write_text('not audio', encoding='utf-8')
        self.failed('process_audio', {'input': str(text), 'workflow': delay_workflow()}, 'InvalidInput')
        self.assertEqual(self.runtime.status()['runningJobs'], 0)

    def test_batch_process_continue_on_error(self):
        corrupt = self.root / 'fixtures' / 'bad.wav'
        corrupt.write_text('this is not a wav file', encoding='utf-8')
        outputs = self.completed('batch_process', {'inputs': [str(self.tone_path), str(corrupt)], 'workflow': delay_workflow(), 'suffix': '_batch'})
        self.assertEqual(outputs['count'], 1)
        self.assertEqual(len(outputs['results']), 1)
        self.assertTrue(outputs['results'][0]['file'].endswith('tone_batch.wav'))
        self.assertTrue(Path(outputs['results'][0]['file']).is_file())
        self.assertGreater(outputs['results'][0]['report']['tailSeconds'], 0.0)
        self.assertEqual(len(outputs['failed']), 1)
        self.assertTrue(outputs['failed'][0]['input'].endswith('bad.wav'))
        self.assertTrue(outputs['failed'][0]['code'])
        self.failed('batch_process', {'inputs': [str(corrupt), str(self.tone_path)], 'workflow': delay_workflow(), 'continue_on_error': False}, outputs['failed'][0]['code'])
        # A file that does not exist is refused by the SDK's automatic import before the handler runs:
        # continue_on_error cannot skip it, the whole job fails with MissingInput.
        self.failed('batch_process', {'inputs': [str(self.tone_path), str(self.root / 'nope.wav')], 'workflow': delay_workflow()}, 'MissingInput')

    def test_convert_audio(self):
        outputs = self.completed('convert_audio', {'input': str(self.tone_path), 'output_format': 'flac', 'subtype': 'PCM_16', 'samplerate': 22050, 'channels': 1})
        self.assertTrue(outputs['file'].endswith('tone.flac'))
        self.assertEqual((outputs['sampleRate'], outputs['channels'], outputs['mimeType']), (22050, 1, 'audio/flac'))
        self.assertAlmostEqual(outputs['durationSeconds'], 1.0, places=3)
        info = audio_io.probe(outputs['file'])
        self.assertEqual((info.format, info.subtype, info.frames), ('FLAC', 'PCM_16', 22050))
        wav = self.completed('convert_audio', {'input': str(self.tone_path), 'output_format': 'wav', 'subtype': 'FLOAT', 'samplerate': 96000})
        self.assertEqual((wav['sampleRate'], wav['channels'], wav['mimeType']), (96000, 2, 'audio/wav'))
        self.assertEqual(audio_io.probe(wav['file']).subtype, 'FLOAT')

    def test_convert_and_process_to_lossy_formats_known_bug(self):
        """Known bug: the schema says subtype is ignored for lossy formats, but the default subtype PCM_24 is
        forwarded to audio_io.save, which refuses it ("Subtype PCM_24 is not valid for mp3"). MP3/OGG/AAC output
        through convert_audio, process_audio and batch_process therefore fails with InvalidParameters."""
        for fmt in ('mp3', 'ogg', 'aac'):
            with self.subTest(format=fmt):
                converted = self.completed('convert_audio', {'input': str(self.tone_path), 'output_format': fmt, 'bitrate_kbps': 128})
                self.assertTrue(Path(converted['file']).is_file())
        processed = self.completed('process_audio', {'input': str(self.tone_path), 'workflow': delay_workflow(), 'output_format': 'mp3'})
        self.assertEqual(processed['mimeType'], 'audio/mpeg')

    def test_analyze_audio_and_list_effects(self):
        stats = self.completed('analyze_audio', {'input': str(self.tone_path)})
        for key in ('peakDbfs', 'rmsDbfs', 'integratedLufs', 'truePeakDbtp', 'leadingSeconds', 'trailingSeconds', 'clippedSamples', 'dcOffset', 'info'):
            self.assertIn(key, stats)
        self.assertAlmostEqual(stats['durationSeconds'], 1.0)
        self.assertAlmostEqual(stats['peakDbfs'], 20 * np.log10(0.5), delta=0.05)
        self.assertEqual(stats['info']['channels'], 2)
        listed = self.completed('list_effects', {})
        self.assertEqual(listed['count'], len(effects.REGISTRY))
        self.assertEqual({e['id'] for e in listed['effects']}, set(effects.REGISTRY))

    def test_workflows_save_list_get(self):
        name = 'unit-save-chain'
        saved = self.save_workflow(name)
        self.assertEqual(saved['name'], name)
        self.assertEqual(saved['summary'], 'delay')
        self.assertEqual(Path(saved['path']), self.root / 'workflows' / (name + '.json'))
        self.assertTrue(Path(saved['path']).is_file())
        listed = self.completed('list_workflows', {})
        self.assertEqual(listed['directory'], str(self.root / 'workflows'))
        self.assertIn(name, [w['name'] for w in listed['workflows']])
        fetched = self.completed('get_workflow', {'name': name})
        self.assertEqual(fetched['summary'], 'delay')
        self.assertEqual(fetched['workflow']['nodes'][0]['effect'], 'delay')
        self.assertEqual(fetched['workflow']['tail']['max_seconds'], 3.0)
        self.failed('save_workflow', {'name': name, 'workflow': delay_workflow()}, 'AlreadyExists')
        self.failed('save_workflow', {'name': 'bad', 'workflow': {'format': 'nope'}}, 'InvalidParameters')
        self.failed('get_workflow', {'name': 'unknown-workflow'}, 'MissingInput')
        # A saved workflow can drive process_audio by name.
        outputs = self.completed('process_audio', {'input': str(self.tone_path), 'workflow_name': name})
        self.assertGreater(outputs['report']['tailSeconds'], 0.0)
        self.assertFalse((paths.DATA / 'workflows' / (name + '.json')).exists())     # never written to the real data folder

    # ------------------------------------------------------------------ generation
    def test_generate_sfx_procedural(self):
        outputs = self.completed('generate_sfx', {'prompt': 'explosion', 'variations': 2, 'duration_seconds': 1.0, 'seed': 3}, backend_id='sfx_procedural')
        self.assertEqual((outputs['backend'], outputs['engine'], outputs['sampleRate']), ('sfx_procedural', 'procedural-dsp', 44100))
        self.assertEqual(len(outputs['variations']), 2)
        self.assertEqual([v['seed'] for v in outputs['variations']], [3, 4])
        for item in outputs['variations']:
            self.assertTrue(Path(item['file']).is_file())
            self.assertAlmostEqual(item['durationSeconds'], 1.0, delta=0.05)
            self.assertLessEqual(item['peakDbfs'], -0.9)
            self.assertEqual(item.get('processedFile', ''), '')          # schema default; only set after a post workflow
        self.assertTrue(outputs['recipe']['layers'])
        self.assertEqual(outputs['recipe']['layers'][0]['archetype'], 'explosion')
        self.assertIsInstance(outputs['warnings'], list)
        self.assertTrue(Path(outputs['report']['file']).is_file())
        self.assertFalse(Path(outputs['report']['file']).read_text('utf-8').find('"layers"') < 0)
        ignored = self.completed('generate_sfx', {'prompt': 'rain', 'duration_seconds': 0.5, 'steps': 30}, backend_id='sfx_procedural')
        self.assertIn('steps is ignored by the procedural backend', ignored['warnings'])

    def test_generate_sfx_with_post_workflow(self):
        self.save_workflow('unit-post-delay')
        outputs = self.completed('generate_sfx', {'prompt': 'door', 'duration_seconds': 0.5, 'post_workflow': 'unit-post-delay'}, backend_id='sfx_procedural')
        item = outputs['variations'][0]
        self.assertTrue(Path(item['processedFile']).is_file())
        self.assertTrue(item['processedFile'].endswith('_processed.wav'))
        self.assertGreater(audio_io.probe(item['processedFile']).duration, audio_io.probe(item['file']).duration)
        self.failed('generate_sfx', {'prompt': 'door', 'duration_seconds': 0.5, 'post_workflow': 'no-such-workflow'}, 'MissingInput', backend_id='sfx_procedural')

    def test_preview_recipe_and_list_sfx_types(self):
        recipe = self.completed('preview_sfx_recipe', {'prompt': 'pluie', 'seed': 5})
        self.assertTrue(recipe['layers'])
        self.assertEqual(recipe['layers'][0]['archetype'], 'rain')
        self.assertEqual(recipe['seed'], 5)
        types = self.completed('list_sfx_types', {})
        self.assertEqual(len(types['types']), 36)
        rain = self.completed('list_sfx_types', {'language': 'fr', 'query': 'pluie'})
        self.assertEqual([t['id'] for t in rain['types']], ['rain'])

    # ------------------------------------------------------------------ voices
    def test_voice_presets_operations(self):
        saved = self.completed('save_voice_preset', {'name': 'Unit piper', 'backend': 'piper', 'parameters': {'voice': PIPER_VOICE, 'length_scale': 1.1, 'text': 'ignored'}, 'notes': 'n'})
        preset_id = saved['id']
        self.assertTrue(preset_id.startswith('unit-piper-'))
        self.assertEqual(Path(saved['path']).parent, self.root / 'presets' / 'voices')
        self.assertEqual(saved['preset']['parameters'], {'voice': PIPER_VOICE, 'length_scale': 1.1})
        self.assertEqual(saved['preset']['operationId'], 'voice_piper')
        listed = self.completed('list_voice_presets', {})
        self.assertIn(preset_id, [p['id'] for p in listed['presets']])
        voices = self.completed('list_voices', {'backend': 'piper', 'language': 'fr'})
        self.assertIn(PIPER_VOICE, [v['key'] for v in voices['piper']['voices']])
        self.assertTrue(all(v['language'].startswith('fr') for v in voices['piper']['voices']))
        self.assertIn(preset_id, [p['id'] for p in voices['presets']])
        self.assertEqual(self.completed('delete_voice_preset', {'preset': preset_id}), {'deleted': True})
        self.assertNotIn(preset_id, [p['id'] for p in self.completed('list_voice_presets', {})['presets']])
        self.failed('delete_voice_preset', {'preset': preset_id}, 'MissingInput')
        self.failed('generate_voice', {'preset': 'no-such-preset', 'text': 'x'}, 'MissingInput')
        self.assertFalse((paths.PRESETS / 'voices' / (preset_id + '.json')).exists())

    def test_voice_piper_unknown_voice_is_invalid(self):
        self.failed('voice_piper', {'text': 'Bonjour', 'voice': 'xx_XX-nobody-low'}, 'InvalidParameters', backend_id='piper')

    @unittest.skipUnless(piper_available(), 'Piper voice fr_FR-siwis-medium or its engine is not installed')
    def test_voice_piper_real_synthesis(self):
        job = self.run_op('voice_piper', {'text': 'Bonjour, ceci est un test de synthèse vocale.', 'voice': PIPER_VOICE, 'threads': 2}, backend_id='piper')
        self.assertEqual(job['state'], 'Completed', job.get('error'))
        outputs = job['outputs']
        self.assertTrue(Path(outputs['file']).is_file())
        self.assertGreater(outputs['durationSeconds'], 0.5)
        self.assertEqual((outputs['sampleRate'], outputs['channels'], outputs['mimeType']), (22050, 1, 'audio/wav'))
        self.assertEqual((outputs['backend'], outputs['model']), ('piper', PIPER_MODEL_ID))
        self.assertGreater(outputs['generationSeconds'], 0.0)
        self.assertEqual(outputs['processedFile'], '')
        self.assertEqual(outputs['preset']['backend'], 'piper')
        self.assertNotIn('text', outputs['preset']['parameters'])
        self.assertEqual(outputs['preset']['parameters']['voice'], PIPER_VOICE)
        self.assertTrue(Path(outputs['report']['file']).is_file())
        audio, rate = audio_io.load(outputs['file'])
        self.assertGreater(rms_db(audio), -40.0)

    @unittest.skipUnless(piper_available(), 'Piper voice fr_FR-siwis-medium or its engine is not installed')
    def test_generate_voice_from_saved_piper_preset(self):
        self.save_workflow('unit-voice-post')
        saved = self.completed('save_voice_preset', {'name': 'Preset voice', 'backend': 'piper', 'parameters': {'voice': PIPER_VOICE, 'length_scale': 1.2}, 'post_workflow': 'unit-voice-post'})
        outputs = self.completed('generate_voice', {'preset': saved['id'], 'text': 'Deuxième phrase de test.'})
        self.assertEqual(outputs['preset']['id'], saved['id'])
        self.assertEqual(outputs['preset']['name'], 'Preset voice')
        self.assertEqual(outputs['preset']['parameters']['length_scale'], 1.2)
        self.assertTrue(Path(outputs['file']).is_file())
        self.assertTrue(Path(outputs['processedFile']).is_file())          # post workflow from the preset
        self.assertGreater(audio_io.probe(outputs['processedFile']).duration, outputs['durationSeconds'])
        self.assertEqual(outputs['warnings'], [])
        plain = self.completed('generate_voice', {'preset': saved['id'], 'text': 'Sans traitement.', 'post_workflow': ''})
        self.assertEqual(plain['processedFile'], '')
        self.completed('delete_voice_preset', {'preset': saved['id']})

    # ------------------------------------------------------------------ cancellation
    def test_cancel_running_job_releases_worker_and_reservations(self):
        self.completed('release_workers', {})
        source = write_wav(self.root / 'fixtures' / 'long.wav', tone(20.0, RATE, 2), RATE)
        workflow = workflow_model.new_workflow('Heavy', nodes=[effect('time_stretch', {'stretch_factor': 0.5}), effect('pitch_shift', {'semitones': 3.0}), effect('reverb')],
                                               tail={'max_seconds': 2.0})
        job = self.runtime.submit(self.alice, self.session, 'process_audio', {'input': str(source), 'workflow': workflow})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = self.runtime.get_job(self.alice, job['jobId'])['state']
            if state not in ('Queued', 'Preparing'):
                break
            time.sleep(0.02)
        self.assertEqual(state, 'Running')
        self.assertEqual(self.runtime.status()['runningJobs'], 1)
        self.runtime.cancel(self.alice, job['jobId'])
        final = self.runtime.wait(self.alice, job['jobId'], timeout=90)
        self.assertEqual(final['state'], 'Cancelled', final.get('error'))
        self.assertEqual(final['error']['code'], 'Cancelled')
        self.assertIsNone(final['outputs'])
        status = self.runtime.status()
        self.assertEqual(status['runningJobs'], 0)
        self.assertEqual(status['queuedJobs'], 0)
        self.assertEqual(status['runningWorkers'], 0)
        self.assertEqual(status['resources']['reservations'], {})
        dsp = self.runtime.services.pool.hosts['dsp']
        self.assertFalse(dsp.health()['alive'])
        for recorded in final.get('artifactProcesses', []):
            alive = psutil.pid_exists(recorded['pid']) and psutil.Process(recorded['pid']).create_time() == recorded['created'] and psutil.Process(recorded['pid']).is_running()
            self.assertFalse(alive, 'worker process survived the cancellation')
        # Cancelling a finished job is a no-op; the runtime keeps working with a fresh worker.
        self.assertEqual(self.runtime.cancel(self.alice, job['jobId'])['state'], 'Cancelled')
        self.assertAlmostEqual(self.completed('analyze_audio', {'input': str(self.tone_path)})['durationSeconds'], 1.0)
        self.assertTrue(dsp.health()['alive'])

    # ------------------------------------------------------------------ models, engines, plugins
    def test_models_engines_and_release(self):
        # install_model declares the "network" permission: a client without it is refused before any job exists.
        bob_session = self.runtime.create_session(self.bob)['sessionId']
        with self.assertRaises(CyToolError) as ctx:
            self.runtime.submit(self.bob, bob_session, 'install_model', {'model': PIPER_MODEL_ID})
        self.assertEqual(ctx.exception.code, 'AccessDenied')
        self.runtime.finish_task(self.bob, bob_session)
        self.failed('install_model', {'model': 'no.such.model'}, 'InvalidParameters')
        self.failed('verify_model', {'model': 'no.such.model'}, 'InvalidParameters')
        self.failed('remove_model', {'model': 'no.such.model'}, 'InvalidParameters')
        listed = self.completed('list_models', {})
        self.assertEqual(listed['count'], len(listed['models']))
        self.assertGreaterEqual(listed['count'], 9)
        for item in listed['models']:
            self.assertIn(item['state'], ('Installed', 'NotInstalled', 'Partial', 'Downloading', 'Verifying', 'Interrupted', 'Failed', 'AccessRequired', 'LicenseAcceptanceRequired', 'Cancelled'))
            self.assertIsInstance(item['presentBytes'], int)
        self.assertEqual({'piper', 'torch'} - set(listed['engines']), set())
        only = self.completed('list_models', {'backend': 'qwen3tts'})
        self.assertEqual(len(only['models']), 5)
        engines = self.completed('engine_status', {})
        self.assertEqual({'piper', 'torch'} - set(engines['engines']), set())
        self.assertEqual(set(engines['backends']), {'sfx_procedural', 'audioldm', 'acestep', 'piper', 'qwen3tts', 'fishspeech', 'llm', 'whisper', 'matchering'})
        self.assertIn('workers', engines)
        diagnosed = self.completed('diagnose_backend', {'backend': 'sfx_procedural'})
        self.assertEqual(diagnosed['worker'], {'engine': 'procedural-dsp'})
        self.assertEqual(diagnosed['engine'], '')
        released = self.completed('release_workers', {})
        self.assertIn('sfx_procedural', released['stopped'])
        self.assertFalse(any(h['alive'] for h in released['workers'].values()))
        self.assertEqual(self.runtime.status()['runningWorkers'], 0)

    @unittest.skipUnless(cydaw_available(), 'CyDAW Test Gain.vst3 is not built on this machine')
    def test_scan_and_describe_plugins(self):
        scanned = self.completed('scan_plugins', {'directories': [str(CYDAW_PLUGIN.parent)]})
        self.assertGreaterEqual(scanned['count'], 1)
        self.assertIn('CyDAW Test Gain', [p.get('name') for p in scanned['plugins']])
        listed = self.completed('list_plugins', {})
        self.assertIn('CyDAW Test Gain', [p.get('name') for p in listed['plugins']])
        self.assertTrue((self.root / 'settings' / 'plugins' / 'vst3-catalogue.json').is_file())
        described = self.completed('describe_plugin', {'plugin': str(CYDAW_PLUGIN)})
        self.assertIn('gain_x', described['parameters'])
        self.failed('describe_plugin', {'plugin': str(self.root / 'missing.vst3')}, 'MissingInput')
        workflow = workflow_model.new_workflow('VST', nodes=[{'kind': 'vst3', 'plugin': str(CYDAW_PLUGIN), 'params': {'gain_x': 0.25}}])
        outputs = self.completed('process_audio', {'input': str(self.tone_path), 'workflow': workflow, 'subtype': 'FLOAT'})
        rendered, _ = audio_io.load(outputs['file'])
        self.assertAlmostEqual(rms_db(rendered) - rms_db(self.audio), 20 * np.log10(0.25), delta=0.2)

    def test_jsfx_operations_use_real_worker_and_import_external_source(self):
        from audiostudio.plugins.native import worker_executable
        from tests.test_plugin_formats import SOURCE
        try:
            worker_executable()
        except RuntimeError as exc:
            self.skipTest(str(exc))
        original = self.root / 'fixtures' / 'external.jsfx'
        original.write_text(SOURCE, 'utf-8')
        read = self.completed('read_jsfx', {'script': str(original)})
        self.assertEqual(read['source'], SOURCE)
        self.assertNotEqual(Path(read['path']), original)
        checked = self.completed('validate_jsfx', {'source': SOURCE})
        self.assertTrue(checked['valid'])
        import uuid
        name = 'AudioStudio-Test-' + uuid.uuid4().hex
        saved = self.completed('save_jsfx', {'name': name, 'source': SOURCE})
        target = Path(saved['path'])
        try:
            self.assertEqual(target.read_text('utf-8'), SOURCE)
            self.assertEqual(self.completed('describe_plugin', {'plugin': str(target)})['format'], 'JSFX')
        finally:
            target.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
