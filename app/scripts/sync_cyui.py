"""Sync selected, unchanged CyUI Python files from an exact upstream checkout.
Usage: python app/scripts/sync_cyui.py /path/to/CyUI
The checkout must match the recorded revision; no UI code is patched here.
"""
from pathlib import Path
import hashlib, json, subprocess, sys
app = Path(__file__).resolve().parents[1]
manifest = json.loads((app / 'cyui-source.json').read_text(encoding='utf-8'))
source = Path(sys.argv[1]).resolve()
revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
if revision != manifest['revision']:
    raise SystemExit('Checkout does not match the pinned CyUI revision')
for name, expected in manifest['files'].items():
    data = (source / 'python' / name).read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8')
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit('Modified upstream file: ' + name)
    target = app / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
print('Verified and synced CyUI ' + revision)
