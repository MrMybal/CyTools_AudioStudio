"""Run an operator-configured local Whisper ZML launcher inside the Whisper worker."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from workers._protocol import WorkerError


CONFIG_ENV = 'CYTOOLS_WHISPER_ZML_CONFIG'
PLATFORMS = {'cpu': 'cpu', 'cuda': 'iree_cuda'}


def load_config():
    filename = os.environ.get(CONFIG_ENV)
    if not filename:
        raise WorkerError('MissingDependency', f'Set {CONFIG_ENV} to a Whisper ZML configuration file', recoverable=True)
    path = Path(filename)
    try:
        if not path.is_absolute():
            raise ValueError('Use an absolute configuration path')
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(config, dict):
            raise ValueError('Expected a JSON object')
        for key in ('launcher', 'probe', 'weights'):
            target = Path(config[key])
            if not target.is_absolute():
                raise ValueError(f'{key} must be an absolute path')
            config[key] = target
        for key in ('launcher', 'probe'):
            if not config[key].is_file():
                raise ValueError(f'{key} is missing at {config[key]}')
        for part in ('encoder.safetensors', 'decoder.safetensors'):
            if not (config['weights'] / part).is_file():
                raise ValueError(f'{part} is missing in {config["weights"]}; prepare the local Whisper checkpoint')
        if 'expected_cuda_device' in config and not isinstance(config['expected_cuda_device'], str):
            raise ValueError('expected_cuda_device must be a device name or substring')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise WorkerError('MissingDependency', f'Invalid {CONFIG_ENV}: {exc}', recoverable=True) from exc
    return config


def audio_path(source, work):
    import soundfile as sf

    try:
        sf.info(source)
    except sf.LibsndfileError:
        from audiostudio import audio_io

        audio, rate = audio_io.load(source)
        converted = work / 'input.wav'
        sf.write(converted, audio.T, rate, subtype='FLOAT')
        return converted
    return source


def transcribe(request, reporter):
    config = load_config()
    device = request.get('device', 'cuda')
    if device not in PLATFORMS:
        raise WorkerError('InvalidParameters', 'Whisper ZML accepts CPU or CUDA')
    reporter.progress(15, step='Reading audio')
    with TemporaryDirectory(prefix='whisper-zml-', dir=request['workspace']) as folder:
        work = Path(folder)
        source = audio_path(Path(request['input']), work)
        cmd = [sys.executable, '-B', config['launcher'], '--audio', source,
               '--model', request['model_dir'], '--weights', config['weights'], '--probe', config['probe'],
               '--profile', 'large_v3_turbo', '--language', request.get('language') or 'auto',
               '--backend', device, '--workspace', work, '--max-new-tokens', '256']
        expected = 'cpu:0' if device == 'cpu' else config.get('expected_cuda_device')
        if expected:
            cmd.extend(('--expected-device', expected))
        env = os.environ.copy()
        env.update({name: str(work) for name in ('TMP', 'TEMP', 'TMPDIR')})
        env['PYTHONIOENCODING'] = 'utf-8'
        reporter.progress(30, step='Transcribing with Whisper ZML')
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.stderr.strip():
        reporter.log(result.stderr.strip()[-8000:], level='Warning' if result.returncode else 'Info')
    if result.returncode:
        raise WorkerError('InferenceFailed', f'Whisper ZML exited with status {result.returncode}', recoverable=True,
                          details={'device': device, 'diagnostics': result.stderr.strip()[-8000:]})
    try:
        report = json.loads(result.stdout)
        placement = report['placement']
        if (placement['backend'], placement['pjrt'], placement['shards']) != (device, PLATFORMS[device], 1):
            raise ValueError('Unexpected ZML platform or shard count')
        if expected and expected.casefold() not in placement['device'].casefold():
            raise ValueError(f'Unexpected ZML device {placement["device"]}')
        if report['complete'] is not True:
            raise ValueError('Whisper ZML reached its per-window token limit')
        return {'text': report['text'], 'segments': report['segments'] if request.get('timestamps', True) else [],
                'durationSeconds': report['duration'], 'language': report['language'], 'runtime': 'zml',
                'placement': placement}
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkerError('InferenceFailed', f'Invalid Whisper ZML result: {exc}', recoverable=True) from exc
