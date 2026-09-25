"""Merge app/locales/audiostudio.fr.json into the facade catalogue app/locales/ui.json.

audiostudio.fr.json is a flat {"English source": "Traduction"} file maintained by hand.
ui.json is what ui_common.tr() reads: {"key": {"en": ..., "fr": ...}}. Entries already
present (the SDK scaffold, or an earlier merge) are preserved untouched; new English
sources are appended, and, like the scaffold, the French text is also registered as a
key so that an already-translated label resolves to the same entry.

Protocol state codes (NotInstalled, AccessRequired...) are displayed through tr(); their
"en" text is made readable here so the English interface never shows a CamelCase code.

Usage: python app/scripts/merge_locales.py [--check]
  --check   only report what would change; exit 1 when ui.json is not up to date.
"""
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
CATALOG = APP / 'locales' / 'ui.json'
SOURCE = APP / 'locales' / 'audiostudio.fr.json'

READABLE_EN = {
    'NotInstalled': 'Not installed',
    'AccessRequired': 'Access required',
    'LicenseAcceptanceRequired': 'Licence acceptance required',
}


def load(path):
    return json.loads(path.read_text('utf-8-sig'))


def merge(catalog, source):
    """Returns (catalog, added_keys, kept_keys, alias_keys)."""
    added, kept, aliases = [], [], []
    for key, french in source.items():
        if not isinstance(key, str) or not isinstance(french, str) or not key:
            continue
        if key in catalog:
            kept.append(key)
            entry = catalog[key]
        else:
            entry = {'en': READABLE_EN.get(key, key), 'fr': french}
            catalog[key] = entry
            added.append(key)
        # Scaffold convention: the French text is also a key of the same entry.
        if french and french not in catalog:
            catalog[french] = dict(entry)
            aliases.append(french)
    return catalog, added, kept, aliases


def save(catalog):
    text = json.dumps(catalog, ensure_ascii=False, indent=2)
    with open(CATALOG, 'w', encoding='utf-8', newline='\r\n') as handle:
        handle.write(text + '\n')


def main(argv):
    check = '--check' in argv
    catalog = load(CATALOG)
    source = load(SOURCE)
    before = len(catalog)
    catalog, added, kept, aliases = merge(catalog, source)
    print(f'source strings: {len(source)}')
    print(f'already present (preserved): {len(kept)}')
    print(f'new English keys: {len(added)}')
    print(f'new French aliases: {len(aliases)}')
    print(f'catalogue: {before} -> {len(catalog)} entries')
    if check:
        if added or aliases:
            print('ui.json is not up to date; run without --check to merge')
            return 1
        print('ui.json is up to date')
        return 0
    if added or aliases:
        save(catalog)
        print('written ' + str(CATALOG))
    else:
        print('nothing to do')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
