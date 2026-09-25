"""Move model weights from the five superseded Tools into CyTools_AudioStudio.

    python app/scripts/migrate_legacy.py --plan      # show what would move
    python app/scripts/migrate_legacy.py --apply     # move (same drive: instant renames)

The user decided that the old Tools (AudioGen, ACE-Step 1.5, FishSpeech S2 Pro, Piper TTS,
Qwen3-TTS) are superseded and that their weights move directly, without copies. Every
move is recorded in data/reports/migration-legacy.json so it can be reversed by hand
(``--undo`` replays the receipt backwards). Nothing is deleted; the old Tool folders
keep their code and environments. After moving, every catalogue file is checked for
presence and size.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
TOOLS = ROOT.parent
sys.path.insert(0, str(APP))
from audiostudio import models as model_catalog  # noqa: E402

RECEIPT = ROOT / 'data' / 'reports' / 'migration-legacy.json'

EXTRA_MOVES = [
    # (old tool, relative source, relative destination in AudioStudio)
    ('CyTools_ACE-Step1.5', 'data/cache/acestep', 'data/cache/acestep'),
    ('CyTools_ACE-Step1.5', 'data/inputs/folk60.flac', 'data/inputs/examples/folk60.flac'),
    ('CyTools_ACE-Step1.5', 'data/inputs/synthwave30.flac', 'data/inputs/examples/synthwave30.flac'),
]


def plan():
    moves = []
    for model in model_catalog.catalog().values():
        legacy = model.get('legacy') or {}
        if not legacy.get('tool') or not legacy.get('path'):
            continue
        source = TOOLS / legacy['tool'] / legacy['path']
        destination = ROOT / model['directory']
        if model['backend'] == 'acestep':
            # ACE-Step components are four sibling folders plus a marker: move each one.
            for component in sorted(source.iterdir()) if source.is_dir() else []:
                if component.name.startswith('.'):
                    continue
                moves.append({'model': model['id'], 'source': str(component), 'destination': str(destination / component.name)})
            continue
        moves.append({'model': model['id'], 'source': str(source), 'destination': str(destination)})
    for tool, relative, target in EXTRA_MOVES:
        moves.append({'model': '', 'source': str(TOOLS / tool / relative), 'destination': str(ROOT / target)})
    result = []
    seen = set()
    for move in moves:
        key = move['source'].lower()
        if key in seen:
            continue
        seen.add(key)
        source, destination = Path(move['source']), Path(move['destination'])
        move['exists'] = source.exists()
        move['destinationExists'] = destination.exists()
        move['action'] = 'move' if source.exists() and not destination.exists() else 'skip'
        if destination.exists() and source.exists():
            move['action'] = 'conflict'
        result.append(move)
    return result


def apply(moves):
    done = []
    for move in moves:
        if move['action'] != 'move':
            continue
        source, destination = Path(move['source']), Path(move['destination'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            source.rename(destination)
            method = 'rename'
        except OSError:
            shutil.move(str(source), str(destination))
            method = 'shutil.move'
        done.append({**move, 'method': method, 'movedAt': time.time()})
        print('moved', source, '->', destination)
    return done


def verify():
    report = {}
    for model in model_catalog.catalog().values():
        if model.get('legacy') and Path(model['directory']).parts:
            info = model_catalog.status(model['id'])
            if info['state'] != 'NotInstalled' or model_catalog.directory(model).exists():
                report[model['id']] = {'state': info['state'], 'missing': info['missing'], 'problems': info['problems'][:5]}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--undo', action='store_true')
    args = parser.parse_args()
    if args.undo:
        receipt = json.loads(RECEIPT.read_text('utf-8'))
        for move in reversed(receipt.get('moves', [])):
            source, destination = Path(move['destination']), Path(move['source'])
            if source.exists() and not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.rename(destination)
                print('restored', destination)
        return 0
    moves = plan()
    for move in moves:
        print(f"{move['action']:9} {move['model'] or '-':30} {move['source']} -> {move['destination']}")
    if not args.apply:
        return 0
    if any(m['action'] == 'conflict' for m in moves):
        print('Conflicts found (destination already exists); resolve them before applying.')
        return 2
    done = apply(moves)
    verification = verify()
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(RECEIPT.read_text('utf-8')) if RECEIPT.exists() else {'moves': []}
    previous['moves'].extend(done)
    previous['verification'] = verification
    previous['updatedAt'] = time.time()
    RECEIPT.write_text(json.dumps(previous, indent=2, ensure_ascii=False), 'utf-8')
    print(json.dumps(verification, indent=2))
    return 0 if all(v['missing'] == 0 for v in verification.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
