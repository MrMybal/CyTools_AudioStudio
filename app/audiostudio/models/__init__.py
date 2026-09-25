"""Model catalogue, installation state, download/verify/remove.

The catalogue (app/models/catalog.json + piper-voices.json) is the declaration; this
module decides what is really installed by checking every declared file (presence and
size; SHA-256 on demand). Downloads go through the SDK DownloadManager (resume,
verification, shared cache). A gated source raises structured states instead of
guessing; tokens come from the OS keyring only and never enter argv, jobs or logs.
"""
import hashlib
import re
import json
from pathlib import Path
import shutil
import time
import uuid

from ..paths import APP, ROOT, MODELS, SETTINGS, DOWNLOADS

CATALOG_PATH = APP / 'models' / 'catalog.json'
PIPER_PATH = APP / 'models' / 'piper-voices.json'
STATE_DIR = SETTINGS / 'install-state'
KEYRING_SERVICE = 'CyTools_AudioStudio'
_cache = {}


def voice_model_id(voice_key):
    """Schema-safe model id of a Piper voice (ids are ASCII: 'tugão' -> 'tugao')."""
    import unicodedata
    ascii_key = unicodedata.normalize('NFKD', voice_key).encode('ascii', 'ignore').decode('ascii')
    return 'piper.' + re.sub(r'[^A-Za-z0-9_.-]', '_', ascii_key)


def _read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def catalog():
    """All models: catalogue entries plus one entry per Piper voice (id 'piper:<key>')."""
    key = (CATALOG_PATH.stat().st_mtime_ns, PIPER_PATH.stat().st_mtime_ns)
    if _cache.get('key') == key:
        return _cache['models']
    models = {}
    for item in _read(CATALOG_PATH)['models']:
        models[item['id']] = item
    voices = _read(PIPER_PATH)
    for voice_key, voice in voices.get('voices', voices).items():
        if not isinstance(voice, dict) or 'files' not in voice:
            continue
        files = [{'path': f['path'], 'size': int(f['size']), 'sha256': None, 'md5': f.get('md5'), 'remotePath': f.get('remotePath'), 'sizeCheckOnly': True}
                 for f in voice['files']]
        model_id = voice_model_id(voice_key)
        models[model_id] = {
            'id': model_id, 'backend': 'piper', 'family': 'voice', 'kind': 'voice',
            'name': voice.get('name', voice_key), 'variant': voice.get('quality', ''),
            'directory': voice.get('directory', 'data/models/piper/' + voice_key),
            'source': voice.get('source', {}), 'files': files, 'downloadBytes': sum(f['size'] for f in files),
            'license': voice.get('license', {'name': 'See MODEL_CARD', 'requiresAcceptance': True}),
            'legacy': voice.get('legacy'), 'resources': {'vramBytes': None, 'ramBytes': 1024 ** 3},
            'default': voice_key == 'fr_FR-siwis-medium', 'language': voice.get('language', {}), 'quality': voice.get('quality', ''),
            'numSpeakers': int(voice.get('num_speakers', 1)), 'speakerIdMap': voice.get('speaker_id_map', {}), 'aliases': voice.get('aliases', []),
            'voiceKey': voice_key,
        }
    _cache.update(key=key, models=models)
    return models


def get(model_id):
    item = catalog().get(model_id)
    if item is None:
        raise KeyError('Unknown model: ' + str(model_id))
    return item


def by_backend(backend_id):
    return [m for m in catalog().values() if m['backend'] == backend_id]


def directory(model):
    return ROOT / model['directory']


def state_path(model_id):
    return STATE_DIR / (model_id.replace(':', '_').replace('/', '_') + '.json')


def read_state(model_id):
    try:
        return _read(state_path(model_id))
    except (OSError, ValueError):
        return {}


def write_state(model_id, **fields):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    value = {**read_state(model_id), **fields, 'updatedAt': time.time()}
    temp = state_path(model_id).with_suffix('.tmp' + uuid.uuid4().hex[:6])
    temp.write_text(json.dumps(value, indent=2), 'utf-8')
    temp.replace(state_path(model_id))
    return value


def missing_files(model, hash_check=False):
    """Files absent or of the wrong size (or wrong hash when hash_check)."""
    root = directory(model)
    problems = []
    for entry in model['files']:
        path = root / entry['path']
        if not path.is_file():
            problems.append({'path': entry['path'], 'reason': 'missing'})
            continue
        if entry.get('presenceOnly'):
            continue
        size = path.stat().st_size
        if int(entry['size']) != size:
            problems.append({'path': entry['path'], 'reason': 'size', 'expected': int(entry['size']), 'actual': size})
            continue
        if hash_check:
            if entry.get('sha256'):
                if sha256(path) != entry['sha256']:
                    problems.append({'path': entry['path'], 'reason': 'sha256'})
            elif entry.get('md5'):
                if md5(path) != entry['md5']:
                    problems.append({'path': entry['path'], 'reason': 'md5'})
    return problems


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def md5(path):
    digest = hashlib.md5()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def present_bytes(model):
    root = directory(model)
    total = 0
    for entry in model['files']:
        path = root / entry['path']
        if path.is_file():
            total += path.stat().st_size
        part = root / (entry['path'] + '.part')
        if part.is_file():
            total += part.stat().st_size
    return total


def status(model_id):
    """Never trusts folder presence: Installed only when every declared file checks out."""
    model = get(model_id)
    problems = missing_files(model)
    state = read_state(model_id)
    if not problems:
        result = 'Installed'
    else:
        recorded = state.get('state', '')
        if recorded in ('Downloading', 'Verifying') and time.time() - state.get('updatedAt', 0) > 30:
            recorded = 'Interrupted'
        if recorded in ('Downloading', 'Verifying', 'Interrupted', 'Failed', 'AccessRequired', 'LicenseAcceptanceRequired', 'Cancelled'):
            result = recorded
        else:
            result = 'Partial' if len(problems) < len(model['files']) else 'NotInstalled'
    present = present_bytes(model)
    return {'id': model_id, 'backend': model['backend'], 'family': model['family'], 'name': model['name'], 'variant': model.get('variant', ''),
            'state': result, 'installed': result == 'Installed', 'directory': str(directory(model)), 'downloadBytes': int(model.get('downloadBytes', 0)),
            'presentBytes': present, 'missing': len(problems), 'problems': problems[:20], 'license': model.get('license', {}),
            'source': model.get('source', {}), 'default': bool(model.get('default')), 'resources': model.get('resources', {}),
            'message': state.get('message', ''), 'error': state.get('error', ''), 'progress': state.get('progress')}


def status_all(backend_id=None, include_voices=False):
    items = []
    for model_id, model in catalog().items():
        if backend_id and model['backend'] != backend_id:
            continue
        if not include_voices and model['backend'] == 'piper' and not model.get('default') and not directory(model).exists():
            continue
        items.append(status(model_id))
    return items


def installed_default(backend_id):
    """The default installed model of a backend, or the first installed one, or None."""
    candidates = [m for m in by_backend(backend_id) if not missing_files(m)]
    if not candidates:
        return None
    candidates.sort(key=lambda m: (not m.get('default'), m['id']))
    return candidates[0]


def require_installed(model_id):
    from cytools_core import CyToolError
    info = status(model_id)
    if not info['installed']:
        raise CyToolError('MissingModel', f'Model "{model_id}" is not installed ({info["state"]}). Install it from the Models screen or with install_model.',
                          recoverable=True, details={'modelId': model_id, 'state': info['state'], 'missing': info['missing']})
    return get(model_id)


# ----------------------------------------------------------------------------- credentials

def token():
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, 'huggingface') or ''
    except Exception:
        return ''


def store_token(value):
    import keyring
    if value:
        keyring.set_password(KEYRING_SERVICE, 'huggingface', value)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, 'huggingface')
        except Exception:
            pass


# ----------------------------------------------------------------------------- install / verify / remove

def file_url(model, entry):
    source = model.get('source', {})
    if entry.get('url'):
        return entry['url']
    if source.get('baseUrl'):
        return source['baseUrl'].rstrip('/') + '/' + (entry.get('remotePath') or entry['path'])
    return f"https://huggingface.co/{source['repository']}/resolve/{source['revision']}/{entry.get('remotePath') or entry['path']}"


def install(model_id, *, accept_license=False, repair=False, cancellation=None, progress=None, log=None):
    """Download missing files with resume; verify; write the Installed state.

    progress(done_bytes, total_bytes, current_file) ; cancellation has .check().
    Raises CyToolError with LicenseAcceptanceRequired / AccessRequired / InsufficientDisk / Cancelled.
    """
    from cytools_core import CyToolError
    from cytools_core.downloads import DownloadManager
    model = get(model_id)
    license_info = model.get('license', {})
    if license_info.get('requiresAcceptance') and not accept_license and missing_files(model):
        write_state(model_id, state='LicenseAcceptanceRequired', message='Accept the licence on the official page and tick the acceptance box')
        raise CyToolError('LicenseAcceptanceRequired', f'The licence of {model["name"]} must be accepted personally before download',
                          recoverable=True, details={'modelId': model_id, 'licenseUrl': license_info.get('url', ''), 'license': license_info.get('name', '')})
    root = directory(model)
    root.mkdir(parents=True, exist_ok=True)
    problems = missing_files(model, hash_check=repair)
    if not problems and not repair:
        write_state(model_id, state='Installed', message='')
        return {'modelId': model_id, 'state': 'Installed', 'downloaded': 0}
    todo = {p['path'] for p in problems}
    needed = sum(int(e['size']) for e in model['files'] if e['path'] in todo)
    free = shutil.disk_usage(str(root)).free
    if free < needed * 1.05 + 512 * 1024 ** 2:
        write_state(model_id, state='Failed', error='Insufficient disk space')
        raise CyToolError('InsufficientDisk', f'{needed / 1e9:.2f} GB needed, {free / 1e9:.2f} GB free', recoverable=True)
    headers = {}
    auth = token()
    source_host = 'huggingface.co' in json.dumps(model.get('source', {}))
    if auth and source_host:
        headers['Authorization'] = 'Bearer ' + auth
    write_state(model_id, state='Downloading', message='', error='')
    done = 0
    downloaded = 0
    managers = {}
    for entry in model['files']:
        if entry['path'] not in todo:
            done += int(entry['size'])
            continue
        if cancellation:
            cancellation.check()
        target = root / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and repair:
            target.unlink()
        manager = managers.get(target.parent)
        if manager is None:
            manager = managers[target.parent] = DownloadManager(target.parent, timeout=120)
        url = file_url(model, entry)
        if log:
            log('Downloading ' + entry['path'])
        started_file = done

        def report(received, total, _base=started_file, _name=entry['path']):
            write_state(model_id, state='Downloading', progress={'doneBytes': _base + received, 'totalBytes': int(model.get('downloadBytes', 0)), 'file': _name})
            if progress:
                progress(_base + received, int(model.get('downloadBytes', 0)), _name)
        try:
            manager.download(target.name, url, sha256=entry.get('sha256') or None, size=int(entry['size']), headers=headers,
                             license_accepted=True, cancellation=cancellation, progress=report, revision=model.get('source', {}).get('revision'))
        except CyToolError as exc:
            code = getattr(exc, 'code', '')
            if code in ('AuthenticationRequired', 'AccessRequired', 'AccessDenied'):
                write_state(model_id, state='AccessRequired', error=str(exc), message='Sign in to Hugging Face and accept the model conditions on its page')
                raise CyToolError('AccessRequired', f'Access to {model["name"]} was refused (401/403). Sign in and accept the conditions on {model.get("source", {}).get("url", "")}',
                                  recoverable=True, details={'modelId': model_id, 'url': model.get('source', {}).get('url', '')}) from exc
            if code == 'Cancelled':
                write_state(model_id, state='Cancelled', message='Partial files are kept; Resume continues where it stopped')
                raise
            write_state(model_id, state='Failed', error=str(exc))
            raise
        except Exception as exc:
            write_state(model_id, state='Failed', error=str(exc))
            raise CyToolError('DownloadFailed', str(exc), recoverable=True) from exc
        if entry.get('md5') and md5(target) != entry['md5']:
            target.unlink(missing_ok=True)
            write_state(model_id, state='Failed', error='MD5 mismatch for ' + entry['path'])
            raise CyToolError('IntegrityFailure', 'MD5 mismatch for ' + entry['path'], recoverable=True)
        done += int(entry['size'])
        downloaded += int(entry['size'])
    write_state(model_id, state='Verifying')
    remaining = missing_files(model, hash_check=False)
    if remaining:
        write_state(model_id, state='Failed', error='Files still missing after download: ' + ', '.join(p['path'] for p in remaining[:5]))
        raise CyToolError('IntegrityFailure', 'Verification failed after download', recoverable=True, details={'problems': remaining[:20]})
    write_state(model_id, state='Installed', message='', error='', progress=None, verifiedAt=time.time(), licenseAccepted=bool(accept_license))
    return {'modelId': model_id, 'state': 'Installed', 'downloaded': downloaded}


def verify(model_id, hash_check=True):
    model = get(model_id)
    problems = missing_files(model, hash_check=hash_check)
    write_state(model_id, state='Installed' if not problems else 'Partial', verifiedAt=time.time(), error='' if not problems else 'Verification found problems')
    return {'modelId': model_id, 'ok': not problems, 'problems': problems}


def remove(model_id):
    from cytools_core import CyToolError
    model = get(model_id)
    root = directory(model).resolve()
    if not root.is_relative_to(MODELS.resolve()):
        raise CyToolError('AccessDenied', 'Refusing to delete outside data/models')
    freed = 0
    if root.exists():
        for path in root.rglob('*'):
            if path.is_file():
                freed += path.stat().st_size
        shutil.rmtree(root)
    write_state(model_id, state='NotInstalled', message='', error='', progress=None)
    return {'modelId': model_id, 'freedBytes': freed}


def manifest_models(backend_id):
    """Model descriptors for CyTool.json backends[].models (no weights, no secrets)."""
    entries = []
    for model in by_backend(backend_id):
        if backend_id == 'piper' and not model.get('default') and not directory(model).exists():
            continue  # 177 voices would bloat the manifest; the catalogue op lists them all
        resources = {'ramBytes': int(model.get('resources', {}).get('ramBytes') or 0)}
        if model.get('resources', {}).get('vramBytes'):
            resources['vramBytes'] = {'auto': int(model['resources']['vramBytes'])}
        entries.append({'id': model['id'], 'name': model['name'], 'version': str(model.get('source', {}).get('revision', ''))[:12] or '1',
                        'source': model.get('source', {}).get('url', '') or model.get('source', {}).get('repository', ''),
                        'license': model.get('license', {}).get('name', 'Not declared'), 'licenseUrl': model.get('license', {}).get('url', ''),
                        'location': 'Local', 'runsLocally': True, 'installed': not missing_files(model),
                        'downloadSize': int(model.get('downloadBytes', 0)), 'installedSize': int(model.get('downloadBytes', 0)),
                        'resourceRequirements': resources})
    return entries
