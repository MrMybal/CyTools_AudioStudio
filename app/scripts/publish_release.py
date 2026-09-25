"""Publish the built assets as a GitHub release (tag v<version>) of the repository in release.json.

    set GITHUB_TOKEN=<a token with "contents: write" on the repository>     (PowerShell: $env:GITHUB_TOKEN = '...')
    runtime/python/Scripts/python.exe app/scripts/publish_release.py [--notes FILE] [--draft] [--prerelease]

The token is read from the environment only; it is never written to a file, a log or the job
history. Run app/scripts/build_release.py first: the assets of runtime/build/release/v<version>
are uploaded (cytools-app.zip, its .sha256, the portable build, the launcher, SHA256SUMS.txt).
The tag must already exist on the remote (git push origin v<version>) or is created from the
current commit of the default branch by GitHub when it does not.
"""
import argparse
import json
import mimetypes
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
API = 'https://api.github.com'


def request(method, url, token, data=None, content_type='application/json'):
    headers = {'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + token, 'User-Agent': 'CyTools-AudioStudio-release',
               'X-GitHub-Api-Version': '2022-11-28'}
    if data is not None:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:500]
        raise SystemExit(f'GitHub API {method} {url} -> HTTP {exc.code}: {detail}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--notes', help='Markdown file with the release notes')
    parser.add_argument('--draft', action='store_true')
    parser.add_argument('--prerelease', action='store_true')
    parser.add_argument('--assets', help='folder of the built assets (default runtime/build/release/v<version>)')
    args = parser.parse_args()
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    if not token:
        raise SystemExit('GITHUB_TOKEN is not set (a fine-grained token with contents: write on the repository).')
    release = json.loads((APP / 'release.json').read_text('utf-8-sig'))
    repository, version = release['repository'], release['version']
    tag = 'v' + version
    folder = Path(args.assets) if args.assets else ROOT / 'runtime' / 'build' / 'release' / tag
    assets = sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
    if not assets:
        raise SystemExit('No assets in ' + str(folder) + ': run app/scripts/build_release.py first.')
    notes = Path(args.notes).read_text('utf-8') if args.notes else f'CyTools_AudioStudio {version}. See README.md; the portable build needs no installed Python.'
    existing = None
    try:
        existing = request('GET', f'{API}/repos/{repository}/releases/tags/{tag}', token)
    except SystemExit:
        existing = None
    if existing:
        print('release exists:', existing['html_url'])
        created = existing
    else:
        payload = {'tag_name': tag, 'name': f'CyTools_AudioStudio {version}', 'body': notes, 'draft': bool(args.draft), 'prerelease': bool(args.prerelease), 'generate_release_notes': False}
        created = request('POST', f'{API}/repos/{repository}/releases', token, json.dumps(payload).encode('utf-8'))
        print('release created:', created['html_url'])
    present = {asset['name'] for asset in created.get('assets', [])}
    upload_base = created['upload_url'].split('{')[0]
    for asset in assets:
        if asset.name in present:
            print('already uploaded:', asset.name)
            continue
        content_type = mimetypes.guess_type(asset.name)[0] or 'application/octet-stream'
        print(f'uploading {asset.name} ({asset.stat().st_size / 1e6:.1f} MB)...', flush=True)
        request('POST', f'{upload_base}?name={asset.name}', token, asset.read_bytes(), content_type)
    print('done:', created['html_url'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
