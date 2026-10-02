"""Write the LICENCES folder delivered at the root of the product.

    runtime/python/Scripts/python.exe app/scripts/build_licences.py            # writes LICENCES/ and app/LICENSE-CyToolsCore.txt
    runtime/python/Scripts/python.exe app/scripts/build_licences.py --check    # exits 1 when a file is missing or stale

  LICENCES/CyToolsCore-MIT.txt       licence file of the installed cytools-core distribution, unchanged
  LICENCES/LICENSE-CyToolsCore.txt   notice written by the SDK scaffold (also kept as app/LICENSE-CyToolsCore.txt)
  LICENCES/SOURCES.txt               repositories, guides and references of the included components
  LICENCES/ThirdParty-Notices.txt    components of app/licenses.json (the table shown in the Options tab)

The texts come from the SDK that is really installed, never from a copy typed by hand: a build with
another SDK, or with an SDK that is not MIT, stops here. The release builder adds
LICENCES/PythonPackages.txt for the Python it ships (python_packages below).
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import textwrap

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
LICENCES = ROOT / 'LICENCES'
SDK_REPOSITORY = 'https://github.com/MrMybal/CyToolsCore'
SDK_VERSION = '0.10.1'
SDK_REVISION = 'a8d200f2d0baaade1633e0683663b4506c595f74'
SDK_REQUIREMENT = f'cytools-core[mcp] @ git+{SDK_REPOSITORY}.git@{SDK_REVISION}'
UNREAL_SDK_REPOSITORY = 'https://github.com/MrMybal/CyUEMCPSDK'
PRODUCT_REPOSITORY = 'https://github.com/MrMybal/CyTools_AudioStudio'
COPYRIGHT = 'Copyright (c) 2026 Cyberalien'


def sdk_texts():
    """(licence text, scaffold notice) of the installed SDK, after checking what is installed."""
    distribution = importlib.metadata.distribution('cytools-core')
    expression = distribution.metadata.get('License-Expression')
    if distribution.version != SDK_VERSION or expression != 'MIT':
        raise SystemExit(f'cytools-core {SDK_VERSION} (MIT) is required, found {distribution.version} '
                         f'(License-Expression: {expression}). Install: pip install "{SDK_REQUIREMENT}"')
    files = [entry for entry in (distribution.files or []) if entry.name == 'LICENSE' and '.dist-info' in str(entry)]
    if len(files) != 1:
        raise SystemExit('The installed cytools-core distribution does not carry exactly one LICENSE file.')
    licence = distribution.locate_file(files[0]).read_text('utf-8')
    import cytools_core
    notice = (Path(cytools_core.__file__).parent / 'templates' / 'LICENSE-CyToolsCore.txt').read_text('utf-8')
    for text in (licence, notice):
        if COPYRIGHT not in text or 'MIT License' not in text:
            raise SystemExit('The SDK licence text is not the expected MIT text.')
    return licence, notice


def sources_text(version):
    blob = SDK_REPOSITORY + '/blob/main/Docs/'
    return textwrap.dedent(f'''\
        CyTools_AudioStudio {version} - sources and references of the delivered components
        ====================================================================================

        Product
          Licence        GPL-3.0-only, full text in LICENSE at the root of the product
          Source code    {PRODUCT_REPOSITORY}
          Components     LICENCES/ThirdParty-Notices.txt (same list as the Options tab, app/licenses.json)

        CyToolsCore SDK {SDK_VERSION} (runtime, jobs, CLI / JSONL / HTTP / MCP transports, scaffold)
          Licence        MIT, {COPYRIGHT}; full text in LICENCES/CyToolsCore-MIT.txt
          Scaffold       LICENCES/LICENSE-CyToolsCore.txt (also app/LICENSE-CyToolsCore.txt)
          Repository     {SDK_REPOSITORY}
          Revision       {SDK_REVISION}
          Install        pip install "{SDK_REQUIREMENT}"
          Guides         creating a CyTool        {blob}AgentGuide.md
                         standalone delivery      {blob}StandaloneDelivery.md
                         updating a product       {blob}UpdateExistingProducts.md
                         licensing                {blob}Licensing.md
                         copies in this product   app/Docs/
          The MIT licence of the SDK does not change the licence of this product: CyTools_AudioStudio
          stays under the GPL-3.0 because of its own code and of pedalboard / JUCE.

        CyUEMCPSDK (Unreal Engine MCP SDK)
          Repository     {UNREAL_SDK_REPOSITORY}
          Not included: this product has no Unreal Engine plugin and no assistant runtime.

        Python packages of runtime/python
          The portable build lists every installed distribution, its licence and the licence files kept
          inside the archive in LICENCES/PythonPackages.txt. An installation from source installs them
          from PyPI with app/requirements.txt; each package keeps its licence files in
          runtime/python/Lib/site-packages/<name>-<version>.dist-info/.
          CPython itself: runtime/python/LICENSE.txt (portable build), https://docs.python.org/3.11/license.html

        Engines, vendored sources and model weights
          They are not part of this archive. The application downloads them on request (Models tab,
          app/setup_engine.py) from the sources listed in LICENCES/ThirdParty-Notices.txt,
          app/engines.json and app/models/catalog.json; each one keeps its own licence, and a gated or
          non-commercial model is only downloaded after the user accepted its terms.

        A link or the word MIT never replaces a licence text: keep this folder with every copy of the product.
        ''')


def notices_text(version):
    entries = json.loads((APP / 'licenses.json').read_text('utf-8-sig'))
    lines = [f'CyTools_AudioStudio {version} - third-party notices', '=' * 52, '',
             'Components used by the application, with their licence and their source. Generated from',
             'app/licenses.json, the table shown in the Options tab. Full licence texts: LICENSE (product),',
             'LICENCES/CyToolsCore-MIT.txt (SDK), and for each Python package its own .dist-info folder',
             '(indexed in LICENCES/PythonPackages.txt of the portable build).', '']
    for entry in entries:
        lines.append(f"[{entry['kind']}] {entry['name']}")
        lines.append('  Licence: ' + entry['license'])
        if entry.get('url'):
            lines.append('  Source:  ' + entry['url'])
        if entry.get('notes'):
            lines.extend(textwrap.wrap(entry['notes'], 96, initial_indent='  Notes:   ', subsequent_indent='           '))
        lines.append('')
    return '\n'.join(lines)


def documents():
    """{path: text} of every generated file."""
    version = json.loads((APP / 'release.json').read_text('utf-8-sig'))['version']
    licence, notice = sdk_texts()
    return {
        LICENCES / 'CyToolsCore-MIT.txt': licence,
        LICENCES / 'LICENSE-CyToolsCore.txt': notice,
        APP / 'LICENSE-CyToolsCore.txt': notice,
        LICENCES / 'SOURCES.txt': sources_text(version),
        LICENCES / 'ThirdParty-Notices.txt': notices_text(version),
    }


_LIST_PACKAGES = r'''
import importlib.metadata, json, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
rows = []
for dist in importlib.metadata.distributions():
    meta = dist.metadata
    licence = meta.get('License-Expression') or ''
    if not licence:
        licence = '; '.join(c.split(' :: ')[-1] for c in (meta.get_all('Classifier') or []) if c.startswith('License ::'))
    if not licence:
        licence = ' '.join((meta.get('License') or '').split())[:80]
    urls = [meta.get('Home-page') or ''] + [u.split(',', 1)[-1].strip() for u in (meta.get_all('Project-URL') or [])]
    texts = []
    for entry in dist.files or []:
        name = entry.name.upper()
        if '.dist-info' in str(entry) and (name.startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE', 'AUTHORS')) or 'licenses' in entry.parts):
            path = Path(dist.locate_file(entry)).resolve()
            if path.is_file() and path.is_relative_to(root):
                texts.append(path.relative_to(root).as_posix())
    rows.append({'name': meta.get('Name') or '', 'version': dist.version, 'licence': licence or 'see the licence files',
                 'url': next((u for u in urls if u), ''), 'texts': sorted(set(texts))})
print(json.dumps(sorted(rows, key=lambda row: row['name'].lower())))
'''


def python_packages(python, runtime_root, prefix):
    """Index of the distributions installed in another Python (the one that is shipped).

    prefix is the path of runtime_root inside the delivered archive, e.g. 'runtime/python'.
    Returns (text, rows); raises when the shipped SDK is not the MIT one.
    """
    result = subprocess.run([str(python), '-c', _LIST_PACKAGES, str(runtime_root)], capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        raise RuntimeError('cannot list the packages of ' + str(python) + ':\n' + result.stderr)
    rows = json.loads(result.stdout)
    core = [row for row in rows if row['name'].lower().replace('_', '-') == 'cytools-core']
    if len(core) != 1 or core[0]['version'] != SDK_VERSION or core[0]['licence'] != 'MIT' or not core[0]['texts']:
        raise RuntimeError(f'the shipped Python must contain exactly cytools-core {SDK_VERSION} (MIT) with its licence file, found: {core}')
    lines = ['Python packages shipped in ' + prefix, '=' * (27 + len(prefix)), '',
             'One entry per installed distribution: licence declared by the package, project page, and the',
             'licence files kept unchanged inside this archive. CPython itself: ' + prefix + '/LICENSE.txt.', '']
    for row in rows:
        lines.append(f"{row['name']} {row['version']}")
        lines.append('  Licence: ' + row['licence'])
        if row['url']:
            lines.append('  Project: ' + row['url'])
        for text in row['texts']:
            lines.append(f'  Text:    {prefix}/{text}')
        lines.append('')
    return '\n'.join(lines), rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale = []
    for path, text in documents().items():
        if args.check:
            if not path.is_file() or path.read_text('utf-8') != text:
                stale.append(path.relative_to(ROOT).as_posix())
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, 'utf-8', newline='\n')
        print('wrote ' + path.relative_to(ROOT).as_posix())
    if stale:
        print('stale or missing: ' + ', '.join(stale) + '; run app/scripts/build_licences.py')
        return 1
    if args.check:
        print('LICENCES is up to date')
    return 0


if __name__ == '__main__':
    sys.exit(main())
