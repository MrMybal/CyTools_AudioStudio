"""Staged GitHub updates, outside the job runtime and outside the UI thread.

Three streams stay distinct:
  * application : releases of this Tool's own GitHub repository (release.json 'repository', editable in the Updates tab)
  * engine      : pinned upstream sources in runtime/sources (git, exact revisions, from app/engines.json)
  * weights     : the model catalogue, handled by install_model only
Updates are staged under runtime/updates, verified (identity, ABI, content, confinement), activated
while nothing runs, and keep a backup for rollback. data/ is never part of a replacement.

    python app/maintenance.py tool-check|tool-fetch|tool-rollback|engine-check|engine-fetch|engine-apply|engine-rollback|auto-check|auto-download
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parent
ROOT = APP.parent
RUNTIME = ROOT / 'runtime'
SETTINGS = ROOT / 'data' / 'settings'
LOGS = ROOT / 'data' / 'logs'
UPDATES = RUNTIME / 'updates'
BACKUPS = RUNTIME / 'backups'
SOURCES = RUNTIME / 'sources'
TOOL_ID = 'cy.tool.audiostudio'
MAX_ARCHIVE_BYTES = 256 * 1024 ** 2
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
REPOSITORY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9_.-]+')


def say(text):
    print(text, flush=True)


def read_json(path):
    try:
        return json.loads(Path(path).read_text('utf-8-sig'))
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), 'utf-8')
    temp.replace(path)


def runtime_python():
    candidate = RUNTIME / 'python' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return str(candidate if candidate.exists() else sys.executable)


def engine_sources():
    spec = read_json(APP / 'engines.json')
    result = {}
    for engine in spec.get('engines', {}).values():
        result.update(engine.get('sources', {}))
    return result


def default_repository():
    """Repository shipped in release.json (the application's own GitHub project); may be empty."""
    return str(read_json(APP / 'release.json').get('repository', '') or '')


def update_settings():
    values = read_json(SETTINGS / 'updates.json')
    if not values.get('tool_repository') and default_repository():
        values['tool_repository'] = default_repository()
    return values


def save_update_settings(values):
    current = update_settings()
    if values.get('tool_repository'):
        values['tool_repository'] = repository(values['tool_repository'])
    current.update(values)
    write_json(SETTINGS / 'updates.json', current)
    return current


def repository(value):
    value = str(value).strip().removeprefix('https://github.com/').removesuffix('.git').rstrip('/')
    if not REPOSITORY.fullmatch(value) or value.split('/')[-1] in ('.', '..'):
        raise ValueError('Use a GitHub repository written owner/name')
    return value


def github(path):
    request = urllib.request.Request('https://api.github.com/' + path, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'CyTools-AudioStudio-Updater'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError({404: 'Repository or release not found on GitHub.', 403: 'GitHub rate limit reached for anonymous requests; retry later.'}
                           .get(error.code, 'GitHub answered HTTP ' + str(error.code))) from error
    except urllib.error.URLError as error:
        raise RuntimeError('Network unavailable: ' + str(error.reason)) from error


def ensure_idle():
    """Never replace the application or an engine while a worker of this Tool is alive."""
    import psutil
    markers = [str(APP / 'workers'), str(APP / 'gui' / 'main.py'), str(APP / 'desktop.py')]
    for process in psutil.process_iter(['pid', 'cmdline']):
        try:
            if process.pid == os.getpid():
                continue
            line = ' '.join(process.info['cmdline'] or [])
            if any(marker in line for marker in markers):
                raise RuntimeError('AudioStudio or one of its workers is running. Close the application first.')
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def normalise(tag):
    return str(tag).lstrip('vV').strip()


# -- application -----------------------------------------------------------------------------
def check_tool():
    configured = update_settings().get('tool_repository', '')
    if not configured:
        raise RuntimeError('No GitHub repository is configured for this application. Enter yours in the Updates tab; none is invented.')
    repo = repository(configured)
    release = github('repos/' + repo + '/releases/latest')
    local = read_json(APP / 'release.json').get('version', '0.0.0')
    state = {'repository': repo, 'available': release['tag_name'], 'installed': local, 'url': release['html_url'], 'assets': release.get('assets', []),
             'update_available': normalise(release['tag_name']) != normalise(local), 'checkedAt': time.time()}
    write_json(SETTINGS / 'tool-update.json', state)
    say(('New application release: ' if state['update_available'] else 'Application is up to date: ') + state['available'])
    return state


def safe_extract(archive, destination):
    """Reject traversal, absolute paths, drive letters, symlinks and oversized archives."""
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as bundle:
        if sum(info.file_size for info in bundle.infolist()) > MAX_ARCHIVE_BYTES:
            raise ValueError('Archive too large for an application update.')
        for info in bundle.infolist():
            name = info.filename
            if name.startswith('/') or '\\' in name or ':' in name or '..' in Path(name).parts:
                raise ValueError('Unsafe path in archive: ' + name)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Symbolic links are not allowed in a release.')
            if not (destination / name).resolve().is_relative_to(destination):
                raise ValueError('Archive entry escapes the staging folder: ' + name)
        bundle.extractall(destination)


def verify_candidate(candidate):
    """Identity, ABI and minimum content of a staged application, before it may become pending."""
    from cytools_core import load_manifest
    manifest = load_manifest(candidate / 'CyTool.json')
    if manifest['id'] != TOOL_ID:
        raise ValueError('This release belongs to another Tool: ' + manifest['id'])
    release, local = read_json(candidate / 'release.json'), read_json(APP / 'release.json')
    if release.get('runtime_abi') != local.get('runtime_abi'):
        raise ValueError(f"This release needs another runtime ({release.get('runtime_abi')}); a full installation is required.")
    for required in ('gui/main.py', 'tool.py', 'desktop.py', 'maintenance.py', 'engines.json', 'workers/dsp_worker.py', 'audiostudio/__init__.py'):
        if not (candidate / required).is_file():
            raise ValueError('Release is incomplete: ' + required + ' is missing.')
    if (candidate.parent / 'data').exists() or (candidate / 'data').exists():
        raise ValueError('A release must not contain a data folder.')
    return release.get('version') or manifest['version']


def stage_archive(archive, digest):
    stage = UPDATES / 'tool' / digest.lower()
    if (stage / 'unpacked').exists():
        shutil.rmtree(stage / 'unpacked')
    safe_extract(archive, stage / 'unpacked')
    candidate = stage / 'unpacked' / 'app'
    version = verify_candidate(candidate)
    write_json(SETTINGS / 'tool-pending.json', {'app': str(candidate.relative_to(ROOT)).replace('\\', '/'), 'version': version})
    say('Release verified. It will be activated at the next start; data/ is preserved.')
    return version


def fetch_tool():
    from cytools_core.downloads import DownloadManager
    state = check_tool()
    if not state['update_available']:
        say('Nothing to download.')
        return
    assets = {asset['name']: asset for asset in state['assets']}
    name = 'cytools-app.zip'
    if name not in assets or name + '.sha256' not in assets:
        raise RuntimeError('The release must provide cytools-app.zip and cytools-app.zip.sha256 (see app/Docs/Updates.md).')

    def url_of(asset):
        url = asset['browser_download_url']
        if not url.startswith('https://github.com/' + state['repository'] + '/releases/download/'):
            raise ValueError('Unexpected release URL.')
        return url
    with urllib.request.urlopen(url_of(assets[name + '.sha256']), timeout=30) as response:
        digest = response.read(1024).decode('ascii', 'replace').split()[0]
    if not re.fullmatch('[a-fA-F0-9]{64}', digest):
        raise ValueError('Invalid release checksum.')
    stage = UPDATES / 'tool' / digest.lower()
    stage.mkdir(parents=True, exist_ok=True)
    DownloadManager(stage).download(name, url_of(assets[name]), sha256=digest.lower(), size=assets[name].get('size'))
    stage_archive(stage / name, digest)


def apply_pending():
    """Swap app/ at startup only (called by runtime/bootstrap.py before the interface is imported)."""
    pending = read_json(SETTINGS / 'tool-pending.json')
    if not pending:
        return None
    ensure_idle()
    source = (ROOT / pending['app']).resolve()
    if not source.is_relative_to(UPDATES.resolve()) or not (source / 'CyTool.json').is_file():
        raise ValueError('Staged application is invalid.')
    verify_candidate(source)
    backup = BACKUPS / 'app' / ('app-' + read_json(APP / 'release.json').get('version', 'unknown') + '-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.parent.mkdir(parents=True, exist_ok=True)
    APP.rename(backup)
    try:
        source.rename(APP)
    except Exception:
        backup.rename(APP)
        raise
    write_json(SETTINGS / 'tool-previous.json', {'app': str(backup.relative_to(ROOT)).replace('\\', '/'), 'version': read_json(backup / 'release.json').get('version', '')})
    (SETTINGS / 'tool-pending.json').unlink()
    return pending.get('version', '')


def rollback_tool():
    previous = read_json(SETTINGS / 'tool-previous.json')
    if not previous or not (ROOT / previous['app'] / 'CyTool.json').is_file():
        raise RuntimeError('No previous application is available.')
    staged = UPDATES / 'tool' / 'rollback' / 'unpacked' / 'app'
    if staged.exists():
        shutil.rmtree(staged.parents[1])
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / previous['app'], staged)
    write_json(SETTINGS / 'tool-pending.json', {'app': str(staged.relative_to(ROOT)).replace('\\', '/'), 'version': previous.get('version', '')})
    say('The previous application will be restored at the next start.')


# -- engine sources ----------------------------------------------------------------------------
def git(*arguments, cwd=None):
    executable = shutil.which('git')
    if not executable:
        raise RuntimeError('git is required for engine updates.')
    result = subprocess.run([executable, *arguments], cwd=cwd, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=900)
    if result.returncode:
        raise RuntimeError('git ' + ' '.join(arguments[:2]) + ' failed: ' + result.stderr.strip()[-400:])
    return result.stdout.strip()


def active_revision(name):
    folder = SOURCES / name
    try:
        return git('-C', str(folder), 'rev-parse', 'HEAD') if (folder / '.git').is_dir() else ''
    except RuntimeError:
        return ''


def check_engine():
    spec = engine_sources()
    state = read_json(SETTINGS / 'engine-update.json')
    for name, source in spec.items():
        head = git('ls-remote', source['repository'], 'HEAD').split()[0]
        if not re.fullmatch('[0-9a-f]{40}', head):
            raise RuntimeError('Unexpected answer from ' + source['repository'])
        state[name] = {**state.get(name, {}), 'available': head, 'checkedAt': time.time()}
        say(f"{name}: active {active_revision(name)[:12] or '-'}, newest upstream {head[:12]}")
    write_json(SETTINGS / 'engine-update.json', state)
    return state


def fetch_engine():
    """Clone the newest upstream revision next to the active one; nothing active is touched."""
    spec = engine_sources()
    state = check_engine()
    for name, source in spec.items():
        revision = state[name]['available']
        if revision == active_revision(name):
            say(name + ': already at the newest revision')
            continue
        stage = UPDATES / 'engine' / name / revision
        if not (stage / source['requiredFile']).is_file():
            if stage.exists():
                shutil.rmtree(stage)
            stage.parent.mkdir(parents=True, exist_ok=True)
            git('clone', '--no-checkout', '--filter=blob:none', source['repository'], str(stage))
            git('-C', str(stage), 'checkout', '--detach', revision)
        if not (stage / source['requiredFile']).is_file():
            raise RuntimeError(name + ': the file used by the worker no longer exists upstream; update refused.')
        subprocess.run([runtime_python(), '-m', 'py_compile', str(stage / source['requiredFile'])], check=True, creationflags=NO_WINDOW)
        state[name]['staged'] = revision
        say(f'{name}: revision {revision[:12]} staged (not active). Activate only after reading the upstream changes.')
    write_json(SETTINGS / 'engine-update.json', state)


def apply_engine():
    ensure_idle()
    state = read_json(SETTINGS / 'engine-update.json')
    previous = read_json(SETTINGS / 'engine-previous.json')
    for name, entry in state.items():
        revision = entry.get('staged')
        if not revision:
            continue
        stage, target = UPDATES / 'engine' / name / revision, SOURCES / name
        backup = BACKUPS / 'sources' / f'{name}-{active_revision(name)[:12]}-{time.strftime("%Y%m%d-%H%M%S")}'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.rename(backup)
            previous[name] = str(backup.relative_to(ROOT)).replace('\\', '/')
        stage.rename(target)
        entry.pop('staged')
        say(f'{name}: revision {revision[:12]} activated (previous kept for rollback)')
    write_json(SETTINGS / 'engine-update.json', state)
    write_json(SETTINGS / 'engine-previous.json', previous)
    say('Run a real generation to validate; roll back if the worker no longer loads. The pinned revision in engines.json is unchanged: setup_engine.py would restore it.')


def rollback_engine():
    ensure_idle()
    previous = read_json(SETTINGS / 'engine-previous.json')
    if not previous:
        raise RuntimeError('No previous engine source is recorded.')
    for name, relative in list(previous.items()):
        backup, target = ROOT / relative, SOURCES / name
        if not backup.is_dir():
            continue
        parked = BACKUPS / 'sources' / f'{name}-replaced-{time.strftime("%Y%m%d-%H%M%S")}'
        if target.exists():
            target.rename(parked)
        backup.rename(target)
        previous.pop(name)
        say(name + ': previous revision restored')
    write_json(SETTINGS / 'engine-previous.json', previous)


def update_state():
    spec = engine_sources()
    recorded = read_json(SETTINGS / 'engine-update.json')
    return {'application': {'installed': read_json(APP / 'release.json').get('version', '?'), 'pending': read_json(SETTINGS / 'tool-pending.json').get('version'),
                            'available': read_json(SETTINGS / 'tool-update.json').get('available'), 'previous': read_json(SETTINGS / 'tool-previous.json').get('version')},
            'engine': {name: {'pinned': source['revision'], 'active': active_revision(name), **{k: v for k, v in recorded.get(name, {}).items() if k in ('available', 'staged')}}
                       for name, source in spec.items()},
            'enginePrevious': read_json(SETTINGS / 'engine-previous.json')}


class Task:
    """Non-blocking maintenance process for the interface."""

    def __init__(self):
        self.process, self.status, self.action, self.handle = None, '', '', None
        self.log = LOGS / 'maintenance.log'

    @property
    def busy(self):
        return self.process is not None and self.process.poll() is None

    def start(self, action):
        if self.busy:
            return False
        self.log.parent.mkdir(parents=True, exist_ok=True)
        if self.handle:
            self.handle.close()
        self.handle = self.log.open('w', encoding='utf-8')
        self.process = subprocess.Popen([runtime_python(), str(APP / 'maintenance.py'), action], stdin=subprocess.DEVNULL, stdout=self.handle, stderr=self.handle,
                                        text=True, encoding='utf-8', cwd=str(ROOT), creationflags=NO_WINDOW)
        self.action, self.status = action, 'Running: ' + action
        return True

    def poll(self):
        if self.process and self.process.poll() is not None:
            self.status = ('Finished: ' if self.process.returncode == 0 else 'Failed: ') + self.action
            self.process = None
            if self.handle:
                self.handle.close()
                self.handle = None
        try:
            return self.log.read_text(encoding='utf-8', errors='replace')[-6000:]
        except OSError:
            return ''

    def cancel(self):
        if not self.busy:
            return
        import psutil
        try:
            family = psutil.Process(self.process.pid).children(recursive=True) + [psutil.Process(self.process.pid)]
        except psutil.NoSuchProcess:
            family = []
        for member in family:
            try:
                member.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(family, timeout=10)
        for member in alive:
            try:
                member.kill()
            except psutil.NoSuchProcess:
                pass
        self.process.wait(timeout=10)
        self.process = None
        if self.handle:
            self.handle.close()
            self.handle = None
        self.status = 'Cancelled: ' + self.action + ' (staged files are kept)'


ACTIONS = {'tool-check': check_tool, 'tool-fetch': fetch_tool, 'tool-rollback': rollback_tool,
           'engine-check': check_engine, 'engine-fetch': fetch_engine, 'engine-apply': apply_engine, 'engine-rollback': rollback_engine}


def main():
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action in ('auto-check', 'auto-download'):
        check_engine()
        if update_settings().get('tool_repository'):
            (fetch_tool if action == 'auto-download' else check_tool)()
        return
    if action not in ACTIONS:
        raise SystemExit('Usage: maintenance.py ' + '|'.join(ACTIONS))
    ACTIONS[action]()


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        main()
    except Exception as exception:
        say(type(exception).__name__ + ': ' + str(exception))
        raise SystemExit(1)
