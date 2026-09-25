"""Build app/models/catalog.json and app/models/piper-voices.json.

The unified catalogue of CyTools_AudioStudio is generated, never edited by hand.
Sources (all read-only):

  audioldm   app/audiostudio/backends/_reference/audiogen_config.py  (parsed with ast,
             the module is not imported because it pulls in the old tool's UI helpers)
  acestep    app/audiostudio/backends/_reference/acestep_model_catalog.json
  fishspeech app/audiostudio/backends/_reference/fishspeech_model_catalog.json
  qwen3tts   <legacy>/CyTools_Qwen3-TTS/data/models/<variant>/source.json
             (the pinned Hugging Face API listing written by the old tool; when the
             old tool is absent the entry already present in catalog.json is kept)
  piper      app/audiostudio/backends/_reference/piper_voices.json

Usage:
  python app/scripts/build_model_catalog.py                 # regenerate both files
  python app/scripts/build_model_catalog.py --verify        # regenerate, then check the
                                                            # listed files against the
                                                            # weights still installed in
                                                            # the old tools
  python app/scripts/build_model_catalog.py --verify-only   # check without rewriting
  python app/scripts/build_model_catalog.py --legacy-root <folder holding the former Tools>
"""
import argparse
import ast
import datetime as dt
import json
import sys
from pathlib import Path, PurePosixPath

APP = Path(__file__).resolve().parents[1]
REFERENCE = APP / 'audiostudio' / 'backends' / '_reference'
OUTPUT = APP / 'models'
DEFAULT_LEGACY_ROOT = APP.parents[1]      # the folder holding the Tools, when this one sits beside the former ones

GIB = 1024 ** 3
GB = 10 ** 9

# Piper: the pinned revision of rhasspy/piper-voices used by CyTools_Piper_TTS
# (app/config.py of that tool; only the model-side module is mirrored in _reference).
PIPER_REPOSITORY = 'rhasspy/piper-voices'
PIPER_REVISION = 'c10ece1aade47bb51c153c893d14e5bf8e5b7117'
PIPER_BASE_URL = f'https://huggingface.co/{PIPER_REPOSITORY}/resolve/{PIPER_REVISION}/'

QWEN_VARIANTS = ['0.6B-Base', '0.6B-CustomVoice', '1.7B-Base', '1.7B-CustomVoice', '1.7B-VoiceDesign']

LICENSES = {
    'cc-by-nc-sa-4.0': {
        'name': 'CC-BY-NC-SA-4.0',
        'url': 'https://creativecommons.org/licenses/by-nc-sa/4.0/',
        'requiresAcceptance': True,
        'commercialUse': 'forbidden',
        'notes': 'Non-commercial, share-alike. Public repository, no account needed; the '
                 'user must still read and accept the licence before the download starts.',
    },
    'mit': {
        'name': 'MIT',
        'url': 'https://huggingface.co/ACE-Step/Ace-Step1.5',
        'requiresAcceptance': False,
        'commercialUse': 'allowed',
        'notes': 'MIT as declared on the model card of the pinned revision.',
    },
    'fish-audio-research': {
        'name': 'Fish Audio Research License',
        'url': 'https://huggingface.co/fishaudio/s2-pro/blob/1de9996b6be38b745688de084d87a5633f714e4e/LICENSE.md',
        'requiresAcceptance': True,
        'commercialUse': 'forbidden',
        'notes': 'Research / non-commercial; commercial use needs a separate agreement with '
                 'Fish Audio. The user must accept the licence personally in the interface. '
                 'A Hugging Face token is only a fallback when the server answers 401/403; '
                 'it never appears in argv, jobs or logs.',
    },
    'apache-2.0': {
        'name': 'Apache-2.0',
        'url': 'https://www.apache.org/licenses/LICENSE-2.0',
        'requiresAcceptance': False,
        'commercialUse': 'allowed',
        'notes': 'Public repository, Apache-2.0 as declared in the pinned listing.',
    },
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def module_constants(path, names):
    """Top-level literal assignments of a module, without importing it."""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in names:
                found[name] = ast.literal_eval(node.value)
    missing = set(names) - set(found)
    if missing:
        raise SystemExit(f'{path}: literal constants not found: {sorted(missing)}')
    return found


def file_entry(path, size, sha256, size_check_only=None, **extra):
    entry = {'path': str(PurePosixPath(path)), 'size': int(size), 'sha256': sha256,
             'sizeCheckOnly': (sha256 is None) if size_check_only is None else size_check_only}
    entry.update(extra)
    return entry


def model_entry(*, id, backend, family, name, variant, directory, repository, revision, gated,
                files, license, legacy_tool, legacy_path, vram, ram, default, notes):
    if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise SystemExit(f'{id}: revision is not a 40-hex commit: {revision!r}')
    return {
        'id': id, 'backend': backend, 'family': family, 'name': name, 'variant': variant,
        'directory': directory,
        'source': {'kind': 'huggingface', 'repository': repository, 'revision': revision,
                   'gated': bool(gated), 'url': 'https://huggingface.co/' + repository},
        'files': files,
        'downloadBytes': sum(f['size'] for f in files),
        'license': dict(LICENSES[license]),
        'legacy': {'tool': legacy_tool, 'path': legacy_path},
        'resources': {'vramBytes': vram, 'ramBytes': ram},
        'default': bool(default),
        'notes': notes,
    }


# --------------------------------------------------------------------------- sources

def audioldm():
    c = module_constants(REFERENCE / 'audiogen_config.py', ['MODEL_ID', 'REVISION', 'LICENSE', 'FILES'])
    files = []
    for component, table in c['FILES'].items():
        for filename, (size, sha) in table.items():
            files.append(file_entry(f'{component}/{filename}' if component else filename, size, sha))
    files.sort(key=lambda f: f['path'])
    return model_entry(
        id='audioldm-s-full-v2', backend='audioldm', family='sfx', name='AudioLDM-S Full v2',
        variant='', directory='data/models/audioldm/' + c['REVISION'],
        repository=c['MODEL_ID'], revision=c['REVISION'], gated=False, files=files,
        license=c['LICENSE'], legacy_tool='CyTools_AudioGen',
        legacy_path='data/models/audioldm/' + c['REVISION'],
        vram=int(2.7 * GB), ram=int(3.5 * GB), default=True,
        notes='Diffusers pipeline (text-to-audio, 16 kHz). Only the LFS weights carry an upstream '
              'SHA-256; the small JSON/text files are checked by exact size. Resources are the '
              'peaks measured by CyTools_AudioGen (decimal GB).')


def acestep():
    src = read_json(REFERENCE / 'acestep_model_catalog.json')
    files = []
    for f in src['files']:
        if f['path'].endswith('.py'):
            # Upstream rewrites these remote-code files without bumping the revision, so
            # their size drifts (observed: 217 B vs 13130 B, 111091 B vs 96036 B).
            files.append(file_entry(f['path'], f['sizeBytes'], None, size_check_only=False, presenceOnly=True))
        else:
            files.append(file_entry(f['path'], f['sizeBytes'], f.get('sha256')))
    files.sort(key=lambda f: f['path'])
    if sum(f['size'] for f in files) != src['downloadSize']:
        raise SystemExit('acestep: downloadSize does not match the file table')
    entry = model_entry(
        id='acestep-1.5', backend='acestep', family='music', name='ACE-Step 1.5', variant='',
        directory='data/models/acestep', repository=src['repo'], revision=src['revision'],
        gated=False, files=files, license=src['license'].lower(),
        legacy_tool='CyTools_ACE-Step1.5', legacy_path='data/models',
        vram=16 * GIB, ram=int(12.5 * GIB), default=True,
        notes='Four components stored flat inside the directory: ' + ', '.join(src['components']) +
              '. VRAM is the peak with the 5 Hz language-model planner (about 10 GiB without it); '
              'RAM is the peak working set with the planner. The two .py files are presence-only.')
    entry['components'] = list(src['components'])
    return entry


def fishspeech():
    src = read_json(REFERENCE / 'fishspeech_model_catalog.json')
    files = sorted((file_entry(f['name'], f['size'], f['sha256']) for f in src['files']), key=lambda f: f['path'])
    return model_entry(
        id='fishspeech-s2-pro', backend='fishspeech', family='voice', name='Fish Speech S2 Pro',
        variant='', directory='data/models/fishspeech/s2-pro', repository=src['repository'],
        revision=src['revision'], gated=False, files=files, license='fish-audio-research',
        legacy_tool='CyTools_FishSpeechS2Pro', legacy_path='data/models/s2-pro',
        vram=20 * GIB, ram=16 * GIB, default=False,
        notes='Text-to-speech with voice cloning (two safetensors shards + codec.pth). Every file '
              'carries an upstream SHA-256. The repository answered public resolve URLs without a '
              'token when the old tool installed it; the licence still requires personal acceptance. '
              'VRAM is the value declared by CyTools_FishSpeechS2Pro, not a measured peak.')


def qwen3tts(legacy_root, previous):
    entries = []
    for key in QWEN_VARIANTS:
        size, kind = key.split('-', 1)
        model_id = 'qwen3tts-' + key
        source = legacy_root / 'CyTools_Qwen3-TTS' / 'data' / 'models' / key / 'source.json'
        if source.is_file():
            src = read_json(source)
            files = []
            for f in src['files']:
                extra = {} if f.get('sha256') else {'gitBlobSha1': f.get('blob')}
                files.append(file_entry(f['path'], f['size'], f.get('sha256'), **extra))
            files.sort(key=lambda f: f['path'])
            if sum(f['size'] for f in files) != src['sizeBytes']:
                raise SystemExit(f'{model_id}: sizeBytes does not match the file table')
            repository, revision, license_key = src['repository'], src['revision'], src['license'].lower()
        elif model_id in previous:
            print(f'warning: {source} absent, keeping the previous catalogue entry for {model_id}', file=sys.stderr)
            old = previous[model_id]
            files, repository, revision = old['files'], old['source']['repository'], old['source']['revision']
            license_key = old['license']['name'].lower()
        else:
            raise SystemExit(f'{model_id}: {source} missing and no previous entry to keep')
        big = size == '1.7B'
        entries.append(model_entry(
            id=model_id, backend='qwen3tts', family='voice',
            name=f'Qwen3-TTS 12Hz {size} {kind}', variant=key,
            directory='data/models/qwen3tts/' + key, repository=repository, revision=revision,
            gated=False, files=files, license=license_key,
            legacy_tool='CyTools_Qwen3-TTS', legacy_path='data/models/' + key,
            vram=(8 if big else 5) * GIB, ram=(10 if big else 6) * GIB,
            default=(key == '1.7B-CustomVoice'),
            notes={'CustomVoice': 'Preset speakers with instruction control.',
                   'Base': 'Voice cloning from a reference recording.',
                   'VoiceDesign': 'Voice described in natural language.'}[kind] +
                  ' Files listed from the pinned Hugging Face API listing: LFS files carry an '
                  'upstream SHA-256, the others a git blob SHA-1 (gitBlobSha1) and are size-checked.'))
    return entries


def piper_voices():
    src = read_json(REFERENCE / 'piper_voices.json')
    voices = {}
    for key, voice in src.items():
        files = []
        for remote, meta in voice['files'].items():
            files.append({'remotePath': remote, 'path': PurePosixPath(remote).name,
                          'size': int(meta['size_bytes']), 'md5': meta['md5_digest']})
        files.sort(key=lambda f: f['path'])
        voices[key] = {
            'key': voice.get('key', key), 'name': voice['name'], 'language': voice['language'],
            'quality': voice['quality'], 'num_speakers': voice['num_speakers'],
            'speaker_id_map': voice['speaker_id_map'], 'aliases': voice.get('aliases', []),
            'directory': 'data/models/piper/' + key,
            'files': files,
            'downloadBytes': sum(f['size'] for f in files),
            'source': {'kind': 'huggingface', 'repository': PIPER_REPOSITORY,
                       'revision': PIPER_REVISION, 'baseUrl': PIPER_BASE_URL},
            'license': {'name': 'MIT (see MODEL_CARD)', 'requiresAcceptance': True, 'commercialUse': 'unknown'},
            'legacy': {'tool': 'CyTools_Piper_TTS', 'path': 'data/models/' + key},
        }
    return voices


# --------------------------------------------------------------------------- build

def build(legacy_root):
    previous = {}
    if (OUTPUT / 'catalog.json').is_file():
        previous = {m['id']: m for m in read_json(OUTPUT / 'catalog.json').get('models', [])}
    models = [audioldm(), acestep(), fishspeech()] + qwen3tts(legacy_root, previous)
    ids = [m['id'] for m in models]
    if len(ids) != len(set(ids)):
        raise SystemExit('duplicate model ids')
    for family in ('sfx', 'music', 'voice'):
        if sum(1 for m in models if m['family'] == family and m['default']) != 1:
            raise SystemExit(f'family {family} must have exactly one default')
    catalog = {'schemaVersion': 1,
               'generatedAt': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
               'models': models}
    voices = {'schemaVersion': 1, 'generatedAt': catalog['generatedAt'],
              'source': {'kind': 'huggingface', 'repository': PIPER_REPOSITORY,
                         'revision': PIPER_REVISION, 'baseUrl': PIPER_BASE_URL},
              'voices': piper_voices()}
    return catalog, voices


# --------------------------------------------------------------------------- verify

def check_files(directory, files):
    """Return (mismatches, presence-only drift notes) for one installed directory."""
    mismatches, drift = [], []
    for f in files:
        path = directory / f['path']
        if not path.is_file():
            mismatches.append(f"missing {f['path']}")
            continue
        actual = path.stat().st_size
        if actual != f['size']:
            if f.get('presenceOnly'):
                drift.append(f"{f['path']} size {actual} (catalogue {f['size']}, presence-only)")
            else:
                mismatches.append(f"{f['path']} size {actual} != {f['size']}")
    return mismatches, drift


def cross_check_receipts(model, directory):
    """Compare the catalogue hashes with the receipts the old tools wrote after download."""
    notes = []
    hashes = {f['path']: f['sha256'] for f in model['files'] if f['sha256']}
    receipt = {}
    if model['backend'] == 'audioldm' and (directory / 'verified.json').is_file():
        r = read_json(directory / 'verified.json')
        receipt = r.get('sha256', {})
        if r.get('revision') != model['source']['revision']:
            notes.append('verified.json revision differs')
    elif model['backend'] == 'acestep' and (directory / 'cytools-acestep15-installed.json').is_file():
        r = read_json(directory / 'cytools-acestep15-installed.json')
        receipt = r.get('sha256', {})
        if r.get('revision') != model['source']['revision']:
            notes.append('marker revision differs')
    elif model['backend'] == 'fishspeech' and (directory / 'installed.json').is_file():
        if read_json(directory / 'installed.json').get('revision') != model['source']['revision']:
            notes.append('installed.json revision differs')
    elif model['backend'] == 'qwen3tts' and (directory / 'installed.json').is_file():
        r = read_json(directory / 'installed.json')
        receipt = {f['path']: f['sha256'] for f in r.get('files', []) if f.get('sha256')}
        if r.get('revision') != model['source']['revision']:
            notes.append('installed.json revision differs')
    for path, digest in hashes.items():
        if path in receipt and receipt[path] != digest:
            notes.append(f'sha256 of {path} differs from the receipt')
    # per-file receipts written by the SDK download manager (<file>.installed.json)
    for path, digest in hashes.items():
        side = directory / (path + '.installed.json')
        if side.is_file():
            actual = read_json(side).get('actualSha256')
            if actual and actual != digest:
                notes.append(f'actualSha256 of {path} differs from the download receipt')
    return notes


def verify(catalog, voices, legacy_root):
    rows, problems = [], 0
    for model in catalog['models']:
        directory = legacy_root / model['legacy']['tool'] / model['legacy']['path']
        present = directory.is_dir()
        mismatches, drift, receipts = [], [], []
        if present:
            mismatches, drift = check_files(directory, model['files'])
            receipts = cross_check_receipts(model, directory)
        problems += len(mismatches) + len(receipts)
        rows.append((model['id'], len(model['files']), model['downloadBytes'] / GB, present, mismatches, drift + receipts))
    for key, voice in voices['voices'].items():
        directory = legacy_root / voice['legacy']['tool'] / voice['legacy']['path']
        if not directory.is_dir():
            continue
        mismatches, drift = check_files(directory, voice['files'])
        notes = []
        receipt = directory / 'verified.json'
        if receipt.is_file() and read_json(receipt).get('revision') != PIPER_REVISION:
            notes.append('verified.json revision differs')
        problems += len(mismatches) + len(notes)
        rows.append(('piper:' + key, len(voice['files']), voice['downloadBytes'] / GB, True, mismatches, notes))

    header = f"{'id':<28} {'files':>5} {'download GB':>12} {'legacy':>7}  mismatches"
    print(header)
    print('-' * len(header))
    for id_, count, gb, present, mismatches, notes in rows:
        print(f"{id_:<28} {count:>5} {gb:>12.3f} {'yes' if present else 'no':>7}  {len(mismatches)}")
        for m in mismatches:
            print(f"    MISMATCH {m}")
        for n in notes:
            print(f"    note     {n}")
    missing_voices = sum(1 for v in voices['voices'].values()
                         if not (legacy_root / v['legacy']['tool'] / v['legacy']['path']).is_dir())
    print(f"\n{len(catalog['models'])} models, {len(voices['voices'])} Piper voices "
          f"({missing_voices} voices not installed in the legacy tool, skipped); "
          f"{problems} problem(s).")
    return problems == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--legacy-root', type=Path, default=DEFAULT_LEGACY_ROOT,
                        help='folder that contains the old tools (default: %(default)s)')
    parser.add_argument('--verify', action='store_true', help='check the files against the legacy weights after writing')
    parser.add_argument('--verify-only', action='store_true', help='only check the catalogue already on disk')
    args = parser.parse_args(argv)
    legacy_root = args.legacy_root.resolve()

    if args.verify_only:
        catalog, voices = read_json(OUTPUT / 'catalog.json'), read_json(OUTPUT / 'piper-voices.json')
    else:
        catalog, voices = build(legacy_root)
        # Entries added after the migration (text assistant, Whisper...) are not produced by this
        # generator: keep them from the catalogue on disk.
        generated = {m['id'] for m in catalog['models']}
        previous = read_json(OUTPUT / 'catalog.json') if (OUTPUT / 'catalog.json').is_file() else {'models': []}
        catalog['models'] += [m for m in previous.get('models', []) if m['id'] not in generated]
        write_json(OUTPUT / 'catalog.json', catalog)
        write_json(OUTPUT / 'piper-voices.json', voices)
        print(f"wrote {OUTPUT / 'catalog.json'} ({len(catalog['models'])} models)")
        print(f"wrote {OUTPUT / 'piper-voices.json'} ({len(voices['voices'])} voices)")
    if args.verify or args.verify_only:
        return 0 if verify(catalog, voices, legacy_root) else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
