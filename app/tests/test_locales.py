"""Every visible English string of the ImGui interface must have a French entry in ui.json.

Runs without ImGui: the GUI sources are parsed with ``ast``, the effect registry is
imported directly (numpy only), and the catalogue is read as plain JSON.

    python -m unittest app.tests.test_locales -v        (from the Tool root)
    python -m unittest tests.test_locales -v            (from app/)
"""
import ast
import json
from pathlib import Path
import re
import sys
import unittest

APP = Path(__file__).resolve().parents[1]
GUI = APP / 'gui'
CATALOG = APP / 'locales' / 'ui.json'
MANIFEST = APP / 'CyTool.json'

# ImGui calls whose first argument is a visible label (the facade list plus the plain
# text calls used through the native module in gui/*.py).
LABEL_CALLS = {'button', 'small_button', 'checkbox', 'radio_button', 'input_text', 'input_text_multiline',
               'input_int', 'input_float', 'input_double', 'slider_int', 'slider_float', 'drag_int', 'drag_float',
               'combo', 'begin_combo', 'selectable', 'collapsing_header', 'tree_node', 'tree_node_ex',
               'begin_tab_item', 'menu_item', 'begin_menu',
               'text', 'text_wrapped', 'text_disabled', 'text_unformatted', 'bullet_text', 'separator_text', 'set_tooltip'}
PROGRESS_OVERLAY_INDEX = 2   # progress_bar(fraction, size, overlay)
# EditorPanel helpers: name -> (index of the label argument, index of the tooltip argument)
TOOLBAR_CALLS = {'_button': (0, 1), '_check': (0, 2), '_combo': (None, 4)}

# Protocol state codes shown through tr() in gui/models_panel.py (STATE_COLOUR keys).
MODEL_STATES = ('Installed', 'Downloading', 'Verifying', 'Partial', 'Interrupted', 'Failed',
                'AccessRequired', 'LicenseAcceptanceRequired', 'Cancelled', 'NotInstalled')


def visible_part(text):
    """The part of a label that ImGui draws ('##' and '###' suffixes are identity only)."""
    return text.partition('##')[0]


def is_translatable(text):
    """False for empty strings, hidden-id labels, punctuation, format specs and identifiers."""
    if not text or text.startswith('##'):
        return False
    visible = visible_part(text)
    if not visible or len(visible) < 2:
        return False
    if '%' in visible and re.fullmatch(r'[%\w.\-+ :]*', visible) and re.search(r'%[\d.]*[dfsx]', visible):
        return False
    if not re.search(r'[A-Za-z]', visible):
        return False
    if re.fullmatch(r'[a-z0-9_]+', visible):       # cuda, wav, flac, mono...: protocol values
        return False
    return True


def _string_literal(node):
    """A str constant, or the left part of 'literal' + expr (e.g. tr('Cancel') + '##id')."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _string_literal(node.left)
    return None


def _call_name(node):
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def gui_strings():
    """{string: {'file:call', ...}} for every literal passed to tr() or a label widget in gui/*.py."""
    found = {}

    def add(text, where):
        if text is not None:
            found.setdefault(text, set()).add(where)

    for path in sorted(GUI.glob('*.py')):
        tree = ast.parse(path.read_text('utf-8-sig'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and path.name == 'main.py':
                # TABS = ('Editor', ...) are passed to the facade's begin_tab_item by variable.
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if 'TABS' in targets and isinstance(node.value, (ast.Tuple, ast.List)):
                    for element in node.value.elts:
                        add(_string_literal(element), path.name + ':TABS')
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = _call_name(node)
            if name == 'tr':
                add(_string_literal(node.args[0]), path.name + ':tr')
            elif name in LABEL_CALLS:
                add(_string_literal(node.args[0]), path.name + ':' + name)
            if name in TOOLBAR_CALLS:
                # editor toolbar helpers: label (button / checkbox) and tooltip, both shown through tr()
                label_index, tip_index = TOOLBAR_CALLS[name]
                for index in (label_index, tip_index):
                    if index is not None and len(node.args) > index:
                        add(_string_literal(node.args[index]), path.name + ':' + name)
            elif name == 'progress_bar' and len(node.args) > PROGRESS_OVERLAY_INDEX:
                add(_string_literal(node.args[PROGRESS_OVERLAY_INDEX]), path.name + ':progress_bar')
    return found


def effect_strings():
    """Names, categories, parameter labels and help texts of every registered effect."""
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    from audiostudio.dsp import effects
    found = set()
    for spec in effects.REGISTRY.values():
        found.update({spec.name, spec.category})
        if spec.help:
            found.add(spec.help)
        for param in spec.params:
            found.add(param.label)
            if param.help:
                found.add(param.help)
    return found


def model_messages():
    """message='...' literals of write_state() calls in audiostudio/models/__init__.py."""
    source = APP / 'audiostudio' / 'models' / '__init__.py'
    tree = ast.parse(source.read_text('utf-8-sig'), filename=str(source))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == 'write_state':
            for keyword in node.keywords:
                if keyword.arg == 'message':
                    text = _string_literal(keyword.value)
                    if text:
                        found.add(text)
    return found


class LocaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG.read_text('utf-8-sig'))
        cls.manifest = json.loads(MANIFEST.read_text('utf-8-sig'))

    def french(self, text):
        entry = self.catalog.get(text)
        if not isinstance(entry, dict):
            return None
        value = entry.get('fr')
        return value if isinstance(value, str) and value.strip() else None

    def assert_all_translated(self, strings, origin):
        missing = sorted(text for text in strings if is_translatable(text) and self.french(visible_part(text)) is None)
        self.assertFalse(missing, f'{len(missing)} {origin} string(s) without a French entry in ui.json:\n  ' + '\n  '.join(repr(m) for m in missing))

    def test_gui_literals_have_french(self):
        strings = gui_strings()
        self.assertGreater(len(strings), 150, 'the GUI extractor found suspiciously few strings')
        self.assert_all_translated(strings, 'GUI')

    def test_tab_names_have_french(self):
        strings = gui_strings()
        tabs = [text for text, places in strings.items() if 'main.py:TABS' in places]
        self.assertEqual(sorted(tabs), sorted(['Editor', 'Generate', 'Workflows', 'Plugins', 'Models', 'Updates']))
        self.assert_all_translated(tabs, 'tab')

    def test_effect_catalogue_has_french(self):
        strings = effect_strings()
        self.assertGreater(len(strings), 80)
        self.assert_all_translated(strings, 'effect')

    def test_model_states_have_readable_english_and_french(self):
        self.assert_all_translated(MODEL_STATES, 'model state')
        for state in MODEL_STATES:
            english = self.catalog[state]['en']
            self.assertNotRegex(english, r'[a-z][A-Z]', f'{state!r}: English display text is still a CamelCase code ({english!r})')

    def test_model_messages_have_french(self):
        strings = model_messages()
        self.assertGreaterEqual(len(strings), 3)
        self.assert_all_translated(strings, 'model message')

    def test_operation_ids_are_not_catalogue_keys(self):
        # Operation ids are protocol values: tr() must never rewrite them (Options combo, logs).
        operations = [operation['id'] for operation in self.manifest.get('operations', [])]
        self.assertTrue(operations)
        leaked = [operation for operation in operations if operation in self.catalog]
        self.assertFalse(leaked, 'operation ids present as catalogue keys: ' + ', '.join(leaked))

    def test_catalogue_entries_are_well_formed(self):
        for key, entry in self.catalog.items():
            self.assertIsInstance(entry, dict, key)
            self.assertIn('en', entry, key)
            self.assertIn('fr', entry, key)
            self.assertTrue(entry['en'].strip() and entry['fr'].strip(), key)

    def test_source_file_is_merged(self):
        source = json.loads((APP / 'locales' / 'audiostudio.fr.json').read_text('utf-8-sig'))
        unmerged = [key for key, value in source.items() if key not in self.catalog or value not in self.catalog]
        self.assertFalse(unmerged, 'run app/scripts/merge_locales.py; unmerged: ' + ', '.join(repr(k) for k in unmerged[:10]))


if __name__ == '__main__':
    unittest.main()
