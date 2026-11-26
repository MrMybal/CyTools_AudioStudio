"""Use the locally configured Qwen3-TTS ZML bridge within a worker job."""

import json
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import wave

from workers._protocol import WorkerError


CONFIG_ENV = 'CYTOOLS_QWEN3_TTS_ZML_CONFIG'


def runtime(request):
    selected = request.get('runtime', 'auto')
    if selected == 'auto':
        return 'zml' if os.environ.get(CONFIG_ENV) else 'torch'
    if selected not in ('zml', 'torch'):
        raise WorkerError('InvalidParameters', 'Expected auto, torch or zml for Qwen3-TTS runtime')
    return selected


def load():
    try:
        path = Path(os.environ[CONFIG_ENV])
        if not path.is_absolute():
            raise ValueError('Use an absolute configuration path')
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        entry = Path(config['bridge'])
        if not entry.is_absolute() or not entry.is_file():
            raise ValueError('bridge must name an existing absolute cytools_bridge.py')
        synthesize = runpy.run_path(str(entry))['synthesize']
        if not callable(synthesize):
            raise ValueError('Invalid Qwen3-TTS ZML bridge entry point')
        return config, synthesize
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        raise WorkerError('MissingDependency', f'Invalid {CONFIG_ENV}: {exc}', recoverable=True) from exc


def render(session, request, item):
    import soundfile as sf

    config, synthesize = session
    try:
        with TemporaryDirectory(prefix='qwen-zml-', dir=request['workspace']) as folder:
            output = Path(folder) / 'speech.wav'
            synthesize(config, request, item, output)
            return sf.read(output, dtype='float32')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, wave.Error) as exc:
        raise WorkerError('InferenceFailed', str(exc), recoverable=True) from exc
