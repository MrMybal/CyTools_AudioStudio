"""Speech annotations and voice presets (run from the app directory)."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from tests._fixtures import tone, write_wav
from audiostudio.voice import annotations, presets


class AnnotationTests(unittest.TestCase):
    def test_tags_never_reach_text(self):
        plan = annotations.build_plan('Hello [tone: cheerful] world [pause: 500ms] end [ton: reset] again.')
        texts = [item['text'] for item in plan if 'text' in item]
        self.assertEqual(texts, ['Hello', 'world', 'end', 'again.'])
        for text in texts:
            self.assertNotIn('[', text)
            self.assertNotIn(']', text)
        self.assertEqual([item.get('pauseSeconds') for item in plan if 'pauseSeconds' in item], [0.5])
        self.assertEqual(annotations.strip_tags('Hello [tone: cheerful] world [pause: 500ms] end'), 'Hello world end')

    def test_tone_persistence_and_reset(self):
        plan = annotations.build_plan('A. [tone: whisper] B. C. [tone: NEUTRAL] D. [ton: excité] E.', delivery='segments', base_instruction='Base')
        self.assertEqual([(i['text'], i['direction']) for i in plan], [('A.', ''), ('B.', 'whisper'), ('C.', 'whisper'), ('D.', ''), ('E.', 'excité')])
        self.assertEqual(plan[0]['instruction'], 'Base')
        self.assertTrue(plan[1]['instruction'].startswith('Base\n'))
        self.assertIn('whisper', plan[1]['instruction'])
        without_base = annotations.build_plan('[tone: soft] X', base_instruction='')
        self.assertFalse(without_base[0]['instruction'].startswith('\n'))
        self.assertIn('soft', without_base[0]['instruction'])
        disabled = annotations.build_plan('A [tone: x] B', enabled=False)
        self.assertEqual(disabled, [{'text': 'A [tone: x] B', 'instruction': '', 'direction': ''}])

    def test_exact_pause_samples_through_render_plan(self):
        rate = 16000
        plan = annotations.build_plan('[pause: 250ms] first [pause: 1s] second [pause: 0,5s] third')
        self.assertEqual([i.get('pauseSeconds') for i in plan if 'pauseSeconds' in i], [0.25, 1.0, 0.5])
        emitted = []

        def synthesize(item):
            return np.full(100, 0.1, np.float32), rate

        used = annotations.render_plan(plan, synthesize, lambda audio, r, item: emitted.append((len(audio), r, 'pauseSeconds' in item)))
        self.assertEqual(used, rate)
        self.assertEqual(emitted, [(4000, rate, True), (100, rate, False), (16000, rate, True), (100, rate, False), (8000, rate, True), (100, rate, False)])
        # A rate change between passages or invalid audio is refused.
        rates = iter([16000, 22050])
        with self.assertRaises(RuntimeError):
            annotations.render_plan(annotations.build_plan('a. b.', delivery='segments'), lambda item: (np.ones(10, np.float32), next(rates)), lambda *a: None)
        with self.assertRaises(RuntimeError):
            annotations.render_plan(annotations.build_plan('a'), lambda item: (np.array([np.nan], np.float32), rate), lambda *a: None)
        stereo = []
        annotations.render_plan(annotations.build_plan('a'), lambda item: (np.ones((2, 10), np.float32), rate), lambda audio, r, item: stereo.append(audio.shape))
        self.assertEqual(stereo, [(10,)])

    def test_invalid_tag_matrix(self):
        invalid = {
            'pause without unit': 'x [pause: 5] y',
            'pause too long': 'x [pause: 11s] y',
            'pause total too long': 'x ' + '[pause: 10s] ' * 7 + 'y',
            'pause garbage': 'x [pause: soon] y',
            'empty tone': 'x [tone: ] y',
            'unclosed tag': 'x [tone: soft y',
            'tone too long': 'x [tone: ' + 'a' * 257 + '] y',
            'nested bracket': 'x [tone: a [b] y',
            'only annotations': '[pause: 1s]',
            'only tone': '[tone: soft]',
            'empty text': '',
        }
        for label, text in invalid.items():
            with self.subTest(case=label):
                with self.assertRaises(annotations.AnnotationError):
                    annotations.build_plan(text)
        self.assertTrue(issubclass(annotations.AnnotationError, ValueError))
        # Legal edge cases.
        self.assertEqual(annotations.build_plan('x [pause: 10s] y')[1]['pauseSeconds'], 10.0)
        self.assertEqual(len(annotations.build_plan('x [pause: 0ms] y')), 2)           # zero pause dropped
        self.assertEqual(annotations.build_plan('x [ TONE : Loud ] y')[1]['direction'], 'Loud')
        self.assertEqual(annotations.build_plan('x [tone: ' + 'a' * 256 + '] y')[1]['direction'], 'a' * 256)

    def test_segments_paragraphs_and_limits(self):
        text = 'One. Two! Three?\nFour;  Five'
        self.assertEqual([i['text'] for i in annotations.build_plan(text, delivery='segments')], ['One.', 'Two!', 'Three?', 'Four;', 'Five'])
        self.assertEqual([i['text'] for i in annotations.build_plan('Para one.\nstill one.\n\n  \nPara two.', delivery='paragraphs')], ['Para one.\nstill one.', 'Para two.'])
        self.assertEqual([i['text'] for i in annotations.build_plan(text, delivery='complete')], [text])
        self.assertEqual(annotations.split_delivery('  ', 'segments'), [])
        many = ' '.join(f'S{i}.' for i in range(annotations.MAX_SEGMENTS))
        self.assertEqual(len(annotations.build_plan(many, delivery='segments')), annotations.MAX_SEGMENTS)
        with self.assertRaises(annotations.AnnotationError):
            annotations.build_plan(many + ' extra.', delivery='segments')


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.workdir.name) / 'voices'
        self.patch = mock.patch.object(presets, 'FOLDER', self.folder)
        self.patch.start()
        self.reference = write_wav(Path(self.workdir.name) / 'ref.wav', tone(0.2, 22050, 1), 22050)

    def tearDown(self):
        self.patch.stop()
        self.workdir.cleanup()

    def test_build(self):
        preset = presets.build('Narrateur FR', 'piper', {'voice': 'fr_FR-siwis-medium', 'text': 'spoken', 'post_workflow': 'x', 'length_scale': 1.1},
                               post_workflow='polish', notes='n' * 3000)
        self.assertEqual(preset['format'], presets.FORMAT)
        self.assertEqual(preset['operationId'], 'voice_piper')
        self.assertTrue(preset['id'].startswith('narrateur-fr-'))
        self.assertEqual(preset['parameters'], {'voice': 'fr_FR-siwis-medium', 'length_scale': 1.1})
        self.assertEqual(preset['postWorkflow'], 'polish')
        self.assertEqual(len(preset['notes']), 2000)
        self.assertEqual(preset['references'], [])
        with self.assertRaises(presets.PresetError):
            presets.build('x', 'espeak', {})
        clone = presets.build('Clone', 'qwen3tts', {'mode': 'clone', 'reference_audio': str(self.reference), 'model': '1.7B-Base'}, preset_id='fixed-id')
        self.assertEqual(clone['id'], 'fixed-id')
        self.assertEqual(clone['modelId'], '1.7B-Base')
        self.assertEqual(len(clone['references']), 1)
        self.assertEqual(clone['references'][0]['field'], 'reference_audio')
        self.assertEqual(clone['references'][0]['size'], self.reference.stat().st_size)
        self.assertEqual(len(clone['references'][0]['sha256']), 64)
        fish = presets.build('Dialogue', 'fishspeech', {'turns': [{'text': 'a'}], 'references': [{'audio': str(self.reference), 'text': 't'}, {'audio': 'missing.wav', 'text': 'm'}]})
        self.assertNotIn('turns', fish['parameters'])
        self.assertEqual([r['field'] for r in fish['references']], ['references[0].audio'])
        self.assertEqual(presets.slug('  Élan Vital! 2024 '), 'lan-vital-2024')
        self.assertEqual(presets.slug('***'), 'voice')

    def test_save_load_list_delete(self):
        preset = presets.build('Voix test', 'piper', {'voice': 'fr_FR-siwis-medium'}, notes='note')
        path = presets.save(preset)
        self.assertEqual(path, self.folder / (preset['id'] + '.json'))
        self.assertEqual([p.name for p in self.folder.iterdir()], [preset['id'] + '.json'])   # no temp file left
        loaded = presets.load(preset['id'])
        self.assertEqual(loaded['name'], 'Voix test')
        self.assertEqual(loaded['parameters'], {'voice': 'fr_FR-siwis-medium'})
        self.assertEqual(presets.load(str(path))['id'], preset['id'])       # a path is accepted too
        listed = presets.list_all()
        self.assertEqual(len(listed), 1)
        self.assertEqual((listed[0]['id'], listed[0]['backend'], listed[0]['notes'], listed[0]['references']), (preset['id'], 'piper', 'note', 0))
        (self.folder / 'corrupt.json').write_text('{"format": "nope"}', encoding='utf-8')
        listed = presets.list_all()
        self.assertEqual(len(listed), 2)
        self.assertIn('error', next(e for e in listed if e['id'] == 'corrupt'))
        with self.assertRaises(presets.PresetError):
            presets.load('does-not-exist')
        with self.assertRaises(presets.PresetError):
            presets.load(str(self.folder / 'corrupt.json'))
        self.assertTrue(presets.delete(preset['id']))
        self.assertFalse(path.exists())
        with self.assertRaises(presets.PresetError):
            presets.delete(preset['id'])
        with self.assertRaises(presets.PresetError):
            presets.validate({'format': presets.FORMAT, 'schemaVersion': 99, 'backend': 'piper', 'parameters': {}})
        with self.assertRaises(presets.PresetError):
            presets.validate({'format': presets.FORMAT, 'schemaVersion': 1, 'backend': 'piper', 'parameters': []})
        self.assertEqual(presets.path_for('../evil/id').name, '.._evil_id.json')

    def test_check_references_detects_changes(self):
        preset = presets.build('Clone', 'qwen3tts', {'mode': 'clone', 'reference_audio': str(self.reference)})
        self.assertEqual(presets.check_references(preset), [])
        write_wav(self.reference, tone(0.2, 22050, 1, frequency=880.0), 22050)      # same size, different content
        warnings = presets.check_references(preset)
        self.assertEqual(len(warnings), 1)
        self.assertIn('changed', warnings[0])
        self.reference.unlink()
        warnings = presets.check_references(preset)
        self.assertEqual(len(warnings), 1)
        self.assertIn('missing', warnings[0])

    def test_parameters_for(self):
        piper = presets.build('P', 'piper', {'voice': 'fr_FR-siwis-medium', 'length_scale': 1.2})
        params = presets.parameters_for(piper, text='Bonjour', overrides={'seed': None, 'post_workflow': 'chain'})
        self.assertEqual(params, {'voice': 'fr_FR-siwis-medium', 'length_scale': 1.2, 'text': 'Bonjour', 'post_workflow': 'chain'})
        self.assertEqual(piper['parameters'], {'voice': 'fr_FR-siwis-medium', 'length_scale': 1.2})   # preset untouched
        with self.assertRaises(presets.PresetError):
            presets.parameters_for(piper)
        qwen = presets.build('Q', 'qwen3tts', {'mode': 'custom', 'speaker': 'Ryan', 'instruction': 'calm'})
        self.assertEqual(presets.parameters_for(qwen, text='Hi')['text'], 'Hi')
        self.assertEqual(presets.parameters_for(qwen, text='Hi', overrides={'seed': 7})['seed'], 7)
        fish = presets.build('F', 'fishspeech', {'expression': 'whisper', 'temperature': 0.7})
        params = presets.parameters_for(fish, text='Hello')
        self.assertEqual(params['turns'], [{'speaker': 0, 'text': 'Hello', 'expression': 'whisper'}])
        self.assertNotIn('expression', params)
        self.assertEqual(params['temperature'], 0.7)
        turns = [{'speaker': 1, 'text': 'A'}]
        self.assertEqual(presets.parameters_for(fish, turns=turns)['turns'], turns)
        with self.assertRaises(presets.PresetError):
            presets.parameters_for(fish)


if __name__ == '__main__':
    unittest.main()
