"""Graphical entry point: applies a staged application update, then starts the ImGui interface."""
from pathlib import Path
import runpy
import sys

APP = Path(__file__).resolve().parent
ROOT = APP.parent


def main():
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    try:
        import maintenance
        maintenance.apply_pending()
    except Exception as exc:  # a broken staged update must not prevent the start
        (ROOT / 'data' / 'logs').mkdir(parents=True, exist_ok=True)
        with open(ROOT / 'data' / 'logs' / 'bootstrap.log', 'a', encoding='utf-8') as handle:
            handle.write('apply_pending failed: ' + str(exc) + '\n')
    for name in list(sys.modules):
        if name in ('maintenance',):
            del sys.modules[name]
    runpy.run_path(str(APP / 'gui' / 'main.py'), run_name='__main__')


if __name__ == '__main__':
    main()
