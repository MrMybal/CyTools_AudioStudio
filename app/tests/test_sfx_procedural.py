"""Unit tests for audiostudio.backends.sfx_procedural (run from the app directory)."""
import unittest

import numpy as np

from audiostudio.backends import sfx_procedural as sfx

RATE = 22050


class _Cancelled(Exception):
    pass


class _CancelAfter:
    """Cancellation token whose check() raises after `allowed` calls."""

    def __init__(self, allowed):
        self.allowed = allowed
        self.calls = 0

    def check(self):
        self.calls += 1
        if self.calls > self.allowed:
            raise _Cancelled()


class CatalogueTests(unittest.TestCase):
    def test_catalogue_completeness(self):
        entries = sfx.catalogue()
        self.assertEqual(len(entries), 36)
        self.assertEqual(len(sfx.ARCHETYPES), 36)
        self.assertEqual({entry['kind'] for entry in entries}, {'oneshot', 'continuous', 'rhythmic'})
        self.assertEqual([entry['id'] for entry in entries], sorted(entry['id'] for entry in entries))
        for entry in entries:
            self.assertTrue(entry['keywords'])
            self.assertGreater(entry['natural_duration_seconds'], 0.0)
            self.assertTrue(entry['description'])

    def test_catalogue_keyword_count(self):
        # 366 EN/FR selector words as exposed by catalogue() (per-archetype distinct sets).
        self.assertEqual(sum(len(entry['keywords']) for entry in sfx.catalogue()), 366)

    def test_catalogue_language_and_query(self):
        rain_fr = [entry for entry in sfx.catalogue('fr') if entry['id'] == 'rain'][0]
        self.assertIn('pluie', rain_fr['keywords'])
        self.assertNotIn('rain', rain_fr['keywords'])
        rain_en = [entry for entry in sfx.catalogue('en') if entry['id'] == 'rain'][0]
        self.assertIn('rain', rain_en['keywords'])
        self.assertNotIn('pluie', rain_en['keywords'])
        found = sfx.catalogue(query='pluie')
        self.assertEqual([entry['id'] for entry in found], ['rain'])


class RecipeTests(unittest.TestCase):
    def test_explosion_first(self):
        recipe = sfx.build_recipe('explosion', seed=0, sample_rate=RATE)
        self.assertEqual(recipe['layers'][0]['archetype'], 'explosion')
        self.assertEqual(recipe['warnings'], [])

    def test_french_rain(self):
        recipe = sfx.build_recipe('pluie', seed=0, sample_rate=RATE)
        self.assertEqual(recipe['layers'][0]['archetype'], 'rain')
        self.assertEqual(recipe['layers'][0]['kind'], 'continuous')

    def test_unknown_words_fall_back_to_texture(self):
        recipe = sfx.build_recipe('zorglub blipflop', seed=0, sample_rate=RATE)
        self.assertEqual([layer['archetype'] for layer in recipe['layers']], ['texture'])
        self.assertEqual(len(recipe['warnings']), 1)
        self.assertIn('neutral texture', recipe['warnings'][0])
        self.assertEqual(recipe['unrecognized_words'], ['zorglub', 'blipflop'])

    def test_modifiers_change_recipe(self):
        plain = sfx.build_recipe('explosion', seed=0, sample_rate=RATE)
        modified = sfx.build_recipe('slow deep explosion', seed=0, sample_rate=RATE)
        # 'deep' -> pitch x0.6, 'slow' -> rate x0.5 (original modifier table).
        self.assertAlmostEqual(modified['modifiers']['pitch'], 0.6)
        self.assertAlmostEqual(modified['modifiers']['rate'], 0.5)
        self.assertLess(modified['modifiers']['pitch'], plain['modifiers']['pitch'])
        long_one = sfx.build_recipe('long explosion', seed=0, sample_rate=RATE)
        self.assertAlmostEqual(long_one['modifiers']['duration'], 2.0)
        self.assertGreater(long_one['duration_seconds'], plain['duration_seconds'])

    def test_recipe_format(self):
        recipe = sfx.build_recipe('three loud coins', seed=5, sample_rate=RATE, peak_dbfs=-3.0)
        for key in ('prompt', 'normalized_prompt', 'seed', 'sample_rate', 'duration_seconds',
                    'natural_duration_seconds', 'target_peak_dbfs', 'layers', 'modifiers',
                    'unrecognized_words', 'warnings'):
            self.assertIn(key, recipe)
        self.assertEqual(recipe['seed'], 5)
        self.assertEqual(recipe['sample_rate'], RATE)
        self.assertEqual(recipe['modifiers']['repeats'], 3)
        self.assertEqual(recipe['modifiers']['drive'], 1.0)
        self.assertEqual(recipe['target_peak_dbfs'], -3.0)
        self.assertEqual(recipe['layers'][0]['archetype'], 'coin')
        import json
        json.dumps(recipe)  # must be JSON-serialisable


class RenderTests(unittest.TestCase):
    def test_every_archetype_renders(self):
        for key, spec in sfx.ARCHETYPES.items():
            with self.subTest(archetype=key):
                # The first English keyword selects its archetype ('chime' itself is a bell word).
                recipe = sfx.build_recipe(spec[4][0], seed=1, sample_rate=RATE, duration_seconds=0.5)
                self.assertEqual(recipe['layers'][0]['archetype'], key)
                audio = sfx.render(recipe)
                self.assertEqual(audio.dtype, np.float32)
                self.assertEqual(audio.ndim, 2)
                self.assertEqual(audio.shape[0], 1)
                self.assertEqual(audio.shape[1], int(round(0.5*RATE)))
                self.assertTrue(np.isfinite(audio).all())
                self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)
                self.assertGreater(float(np.max(np.abs(audio))), 0.0)

    def test_determinism(self):
        first = sfx.render(sfx.build_recipe('thunder in a cave', seed=42, sample_rate=RATE, duration_seconds=0.6))
        second = sfx.render(sfx.build_recipe('thunder in a cave', seed=42, sample_rate=RATE, duration_seconds=0.6))
        self.assertTrue(np.array_equal(first, second))
        other = sfx.render(sfx.build_recipe('thunder in a cave', seed=43, sample_rate=RATE, duration_seconds=0.6))
        self.assertFalse(np.array_equal(first, other))

    def test_cancellation_stops_render(self):
        recipe = sfx.build_recipe('explosion thunder impact', seed=0, sample_rate=RATE, duration_seconds=0.5)
        self.assertEqual(len(recipe['layers']), 3)
        token = _CancelAfter(allowed=1)
        with self.assertRaises(_Cancelled):
            sfx.render(recipe, cancellation=token)
        self.assertEqual(token.calls, 2)

    def test_progress_callback(self):
        recipe = sfx.build_recipe('explosion thunder', seed=0, sample_rate=RATE, duration_seconds=0.5)
        seen = []
        sfx.render(recipe, progress=lambda fraction, message: seen.append((fraction, message)))
        self.assertEqual([fraction for fraction, _ in seen], [0.5, 1.0])
        self.assertIn('explosion', seen[0][1])


class GenerateTests(unittest.TestCase):
    def test_variations(self):
        seen = []
        takes = sfx.generate('laser', seed=10, sample_rate=RATE, duration_seconds=0.3, variations=3,
                             progress=lambda fraction, message: seen.append(fraction))
        self.assertEqual(len(takes), 3)
        self.assertEqual([take['seed'] for take in takes], [10, 11, 12])
        self.assertEqual([take['recipe']['seed'] for take in takes], [10, 11, 12])
        for take in takes:
            self.assertEqual(take['audio'].shape, (1, int(round(0.3*RATE))))
            self.assertEqual(take['audio'].dtype, np.float32)
        self.assertFalse(np.array_equal(takes[0]['audio'], takes[1]['audio']))
        self.assertEqual(seen[-1], 1.0)
        self.assertEqual(seen, sorted(seen))

    def test_variation_matches_direct_render(self):
        take = sfx.generate('bell', seed=3, sample_rate=RATE, duration_seconds=0.4, variations=2)[1]
        direct = sfx.render(sfx.build_recipe('bell', seed=4, sample_rate=RATE, duration_seconds=0.4))
        self.assertTrue(np.array_equal(take['audio'], direct))

    def test_variations_range(self):
        with self.assertRaises(ValueError):
            sfx.generate('bell', variations=0)
        with self.assertRaises(ValueError):
            sfx.generate('bell', variations=5)

    def test_generate_cancellation(self):
        token = _CancelAfter(allowed=0)
        with self.assertRaises(_Cancelled):
            sfx.generate('bell', sample_rate=RATE, duration_seconds=0.3, cancellation=token)


if __name__ == '__main__':
    unittest.main()
