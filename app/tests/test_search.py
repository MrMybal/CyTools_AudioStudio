"""Text search of the effect and plugin pickers (pure functions, no ImGui)."""
import unittest

from gui import search
from audiostudio.dsp import effects


class SearchTests(unittest.TestCase):
    def test_fold_and_matches(self):
        self.assertEqual(search.fold('Réverbération Élargisseur'), 'reverberation elargisseur')
        self.assertTrue(search.matches('reverb plaque', 'Réverbération (hall / plaque / pièce)'))
        self.assertTrue(search.matches('', 'anything'))
        self.assertFalse(search.matches('reverb delay', 'Reverb only'))
        self.assertEqual(search.filter_indices('comp', ['Compressor', 'EQ', 'Multiband compressor']), [0, 2])

    def test_effect_haystacks_cover_names_ids_categories_and_help(self):
        spec = effects.REGISTRY['ir_reverb']
        french = {'Reverb (hall / plate / room)': 'Réverbération (hall / plaque / pièce)', 'Space': 'Espace'}
        haystack = search.effect_haystack(spec, lambda text: french.get(text, text))
        for query in ('hall plate', 'reverberation plaque', 'ir reverb', 'espace', 'convolution'):
            self.assertTrue(search.matches(query, haystack), query)
        specs = list(effects.REGISTRY.values())
        found = [specs[i].id for i in search.filter_indices('vocod', [search.effect_haystack(s) for s in specs])]
        self.assertEqual(found, ['vocoder'])
        self.assertIn('CyDAW', search.plugin_haystack({'name': 'CyDAW Test Gain', 'manufacturer': 'CyDAW'}))


if __name__ == '__main__':
    unittest.main()
