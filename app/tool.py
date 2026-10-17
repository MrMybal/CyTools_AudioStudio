"""CyTools_AudioStudio entry point: one runtime for the ImGui interface, the CLI and MCP.

    runtime/python/Scripts/python.exe app/tool.py describe
    runtime/python/Scripts/python.exe app/tool.py invoke process_audio --params-file params.json
    runtime/python/Scripts/python.exe app/tool.py --data-dir data/jobs-mcp mcp
"""
import sys
from installation_ui import configure as configure_storage
configure_storage()
from pathlib import Path  # noqa: E402

APP = Path(__file__).resolve().parent
ROOT = APP.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from cytools_core import Runtime, load_manifest  # noqa: E402
from cytools_core.transports.cli import run_cli  # noqa: E402

INPUT_FIELDS = {
    'read_jsfx': ['script'],
    'process_audio': ['input'], 'batch_process': ['inputs.*'], 'convert_audio': ['input'], 'analyze_audio': ['input'],
    'generate_music': ['reference_audio'], 'remix_music': ['source_audio'], 'repaint_music': ['source_audio'],
    'voice_qwen3tts': ['reference_audio'], 'transcribe_audio': ['input'], 'master_audio': ['input', 'reference'], 'voice_fishspeech': ['references.*.audio'],
    'batch_session': ['inputs.*'], 'edit_session': ['actions.*.file'],
}


def create_runtime(data_dir, **options):
    from audiostudio.paths import ensure_data_layout, INPUTS
    ensure_data_layout()
    descriptor = load_manifest(APP / 'CyTool.json')
    runtime = Runtime(descriptor, data_dir, **options)
    runtime.configure_inputs(INPUTS, max_bytes=8 * 1024 ** 3, fields=INPUT_FIELDS)
    from audiostudio.operations import register_all
    runtime.services = register_all(runtime)
    from cytools_core.shared_installation import register_operations
    register_operations(runtime, ROOT)
    return runtime


if __name__ == '__main__':
    if sys.stdout:
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr:
        sys.stderr.reconfigure(encoding='utf-8')
    argv = sys.argv[1:]
    if '--data-dir' not in argv:
        argv = ['--data-dir', str(ROOT / 'data' / 'jobs'), *argv]
    raise SystemExit(run_cli(create_runtime, argv))
