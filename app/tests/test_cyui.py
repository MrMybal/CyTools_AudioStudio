"""CyUI port: colour packing, palettes, theme files and value parsing match the C++ library (run from app/)."""
import tempfile
import unittest
from pathlib import Path

from gui import cyui
from gui.cyui import theme, widgets


class ColourTests(unittest.TestCase):
    def test_rgb_packs_abgr_like_the_cpp_rgb(self):
        self.assertEqual(cyui.rgb(0x112233), 0xFF332211)
        self.assertEqual(cyui.rgb(0xF28A2E, 0.24), (61 << 24) | 0x2E8AF2)            # int(0.24 * 255 + 0.5) = 61
        self.assertEqual(cyui.floats(cyui.rgb(0xFF0000)), (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(cyui.from_floats(1.0, 0.0, 0.0), cyui.rgb(0xFF0000))

    def test_alpha_mix_brighter_darker(self):
        red = cyui.rgb(0xFF0000)
        self.assertEqual(cyui.alpha(red, 0.5) >> 24, 128)
        self.assertEqual(cyui.alpha(red, 2.0) >> 24, 255)
        self.assertEqual(cyui.mix(cyui.rgb(0x000000), cyui.rgb(0xFFFFFF), 0.5) & 0xFFFFFF, 0x808080)
        self.assertEqual(cyui.brighter(red, 1.0), cyui.rgb(0xFFFFFF))
        self.assertEqual(cyui.darker(red, 1.0), cyui.rgb(0x000000))

    def test_contrast_text_and_categorical(self):
        self.assertEqual(cyui.contrast_text(cyui.rgb(0xF0F0F0)), cyui.rgb(0x141414))
        self.assertEqual(cyui.contrast_text(cyui.rgb(0x202020)), cyui.rgb(0xFFFFFF))
        self.assertEqual(cyui.categorical(0), cyui.rgb(0xF0A43A))
        self.assertEqual(cyui.categorical(12), cyui.categorical(0))


class ThemeTests(unittest.TestCase):
    def test_the_five_themes_of_the_library(self):
        self.assertEqual([t.key for t in cyui.THEMES], ['mid-grey', 'light-grey', 'amber-night', 'violet', 'navy'])
        self.assertEqual([t.light for t in cyui.THEMES], [False, True, False, False, False])
        self.assertEqual(theme.MID_GREY.accent, cyui.rgb(0xF28A2E))
        self.assertEqual(theme.NAVY.bg0, cyui.rgb(0x0A0E13))
        self.assertEqual([key for key, _, _ in cyui.PALETTE_FIELDS], theme.palette_field_names())

    def test_text_never_disappears_on_its_ground(self):
        """Primary and secondary text keep a readable contrast on every ground of every theme."""
        def luminance(colour):
            r, g, b, _ = cyui.floats(colour)
            lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

        def ratio(a, b):
            la, lb = sorted((luminance(a), luminance(b)), reverse=True)
            return (la + 0.05) / (lb + 0.05)
        for item in cyui.THEMES:
            p = item.palette
            for ground in ('bg0', 'bg1', 'bg2', 'bg3'):
                self.assertGreater(ratio(p.text, getattr(p, ground)), 4.5, (item.key, ground))
                self.assertGreater(ratio(p.textDim, getattr(p, ground)), 2.3, (item.key, ground))
            self.assertGreater(ratio(p.accentText, p.accent), 1.9, item.key)

    def test_metrics(self):
        self.assertEqual(theme.COMPACT.font_size, 14.0)
        self.assertEqual(theme.COMFORTABLE.font_size, 16.0)
        self.assertEqual(cyui.DENSITIES, ('compact', 'comfortable'))

    def test_theme_files_round_trip_and_read_cydaw_json(self):
        base = theme.MID_GREY
        text = cyui.palette_to_text(theme.VIOLET)
        self.assertIn('accent = #7C5CFF', text)
        self.assertIn('grid = #FFFFFF0A', text)                                            # alpha kept as #RRGGBBAA
        self.assertEqual(cyui.palette_from_text(text, base), theme.VIOLET)
        partial = cyui.palette_from_text('{"accent": "#112233", "unknown": "#ffffff"}', base)
        self.assertEqual(partial.accent, cyui.rgb(0x112233))
        self.assertEqual(partial.bg0, base.bg0)                                            # what the text lacks keeps base
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mine.cytheme'
            cyui.save_palette(path, theme.NAVY)
            self.assertEqual(cyui.load_palette(path, base), theme.NAVY)


class ValueTests(unittest.TestCase):
    def test_typed_numbers(self):
        self.assertEqual(widgets.typed_number('2,5'), 2.5)
        self.assertEqual(widgets.typed_number(' 1.2k '), 1200.0)
        self.assertEqual(widgets.typed_number('-3e2'), -300.0)
        self.assertIsNone(widgets.typed_number('abc'))
        self.assertIsNone(widgets.typed_number(''))

    def test_meter_law(self):
        self.assertEqual(widgets.meter_position(-80.0), 0.0)
        self.assertAlmostEqual(widgets.meter_position(6.0), 1.0)
        self.assertLess(widgets.meter_position(-12.0), widgets.meter_position(-3.0))

    def test_labels(self):
        self.assertEqual(widgets.visible('Play###play'), 'Play')
        self.assertEqual(widgets.visible('##hidden'), '')


if __name__ == '__main__':
    unittest.main()
