"""Standalone application identity and portable icon assets."""
from pathlib import Path
import sys


def configure(application_id):
    from imgui_bundle import hello_imgui
    hello_imgui.set_assets_folder(str(Path(__file__).resolve().parent / 'assets'))
    if sys.platform == 'win32':
        import ctypes
        identify = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        identify.argtypes = [ctypes.c_wchar_p]
        identify.restype = ctypes.c_long
        result = identify(application_id)
        if result < 0:
            print(f'Could not set application identity: HRESULT {result}', file=sys.stderr)
