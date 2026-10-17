"""DSP worker: renders workflows, hosts VST3 plugins, analyses files.

Runs with the base interpreter (runtime/python). Kept alive between requests so that
VST3 plugins stay loaded. A plugin crash kills only this process: the host reports
WorkerCrashed and the interface stays up.

Operations:
  render   {"input": path, "output": path, "workflow": {...}, "format": "wav", "subtype": "PCM_24", "bitrate_kbps": 192,
            "selection": [start_seconds, end_seconds] | null, "workspace": path}
  render_buffer {"input": raw .npy path, "samplerate": n, "output": .npy path, "workflow": {...}}
  scan     {"directories": [...], "plugins": [...], "cache_dir": path}
  describe {"plugin": path, "plugin_name": ""}
  editor   {"plugin": path, "params": {...}, "state": "..."}   opens the native editor window (blocking)
  analyze  {"input": path}
  convert  {"input": path, "output": path, "format": .., "subtype": .., "bitrate_kbps": .., "samplerate": .., "channels": ..}
  render_session {"session": folder or session.json, "output": path, "format": .., "subtype": .., "tail": {...}, "selection": [a, b] | null}
  edit_session   {"session": ..|null, "actions": [...], "save_as": folder, "render": bool, "output": path, ...}   (see audiostudio.editor.batch)
  batch_session  {"session": .., "inputs": [...], "slot": {...}, "output_dir": folder, "suffix": "", "format": ..}
"""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers._protocol import serve, WorkerError, inside  # noqa: E402

import numpy as np  # noqa: E402

_cache = None


def _plugin_cache():
    global _cache
    if _cache is None:
        from audiostudio.workflow.engine import PluginCache
        _cache = PluginCache()
    return _cache


def _progress_adapter(reporter, label='Rendering', scale=94.0):
    def progress(fraction, message=''):
        # The engine reports 1.0 when the chain is done; encoding follows, so keep it below 100.
        reporter.progress(1.0 + fraction * scale, step=label, message=message)
    return progress


def render(request, reporter):
    from audiostudio import audio_io
    from audiostudio.workflow import engine
    source = Path(request['input'])
    if not source.is_file():
        raise WorkerError('MissingInput', 'Input file not found: ' + str(source))
    workspace = request.get('workspace')
    output = inside(workspace, request['output']) if workspace else Path(request['output'])
    reporter.progress(1, step='Decoding', message=source.name)
    audio, rate = audio_io.load(source)
    selection = request.get('selection')
    prefix = suffix = None
    if selection:
        start = max(0, int(round(float(selection[0]) * rate)))
        end = min(audio.shape[1], int(round(float(selection[1]) * rate)))
        if end <= start:
            raise WorkerError('InvalidParameters', 'Selection end must be after its start')
        prefix, suffix = audio[:, :start], audio[:, end:]
        audio = audio[:, start:end]
    result = engine.render(audio, rate, request['workflow'], progress=_progress_adapter(reporter), plugin_cache=_plugin_cache())
    rendered = result.audio
    if selection:
        # A longer result (tail) overlaps the audio that follows the selection.
        extra = rendered.shape[1] - audio.shape[1]
        if extra > 0 and suffix.shape[1] > 0:
            overlap = min(extra, suffix.shape[1])
            suffix = suffix.copy()
            suffix[:, :overlap] += rendered[:, audio.shape[1]:audio.shape[1] + overlap]
            rendered = rendered[:, :audio.shape[1] + max(0, extra - overlap)] if extra > overlap else rendered[:, :audio.shape[1]]
        if rendered.shape[0] != prefix.shape[0]:
            rendered = np.repeat(np.mean(rendered, axis=0, keepdims=True), prefix.shape[0], axis=0)
        rendered = np.concatenate([prefix, rendered, suffix], axis=1)
    reporter.progress(96, step='Encoding', message=output.name)
    written = audio_io.save(output, rendered, result.samplerate, fmt=request.get('format'), subtype=request.get('subtype'),
                            bitrate_kbps=int(request.get('bitrate_kbps', 192)))
    report = result.report()
    report.update({'file': str(written), 'sizeBytes': written.stat().st_size, 'input': str(source), 'selection': selection})
    reporter.progress(100, step='Done')
    return report


def render_buffer(request, reporter):
    """Editor path: raw float32 buffers exchanged as .npy files (no encoding loss)."""
    from audiostudio.workflow import engine
    source = Path(request['input'])
    audio = np.load(str(source), mmap_mode=None)
    rate = int(request['samplerate'])
    result = engine.render(audio, rate, request['workflow'], progress=_progress_adapter(reporter), plugin_cache=_plugin_cache())
    output = Path(request['output'])
    output.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(output), np.ascontiguousarray(result.audio, dtype=np.float32))
    report = result.report()
    report['file'] = str(output)
    return report


def scan(request, reporter):
    from audiostudio.vst import host
    directories = request.get('directories') or []
    explicit = [Path(p) for p in request.get('plugins') or []]
    bundles = host.find_bundles(directories) + [p for p in explicit if p.exists()]
    cache_dir = request.get('cache_dir')
    cache = host.read_cache(cache_dir) if cache_dir else {'version': host.CACHE_VERSION, 'plugins': {}}
    results, failures = [], []
    total = max(1, len(bundles))
    for index, bundle in enumerate(bundles):
        reporter.progress(index * 100.0 / total, step='Scanning plugins', message=bundle.name)
        key = str(host.bundle_path(bundle)).lower()
        try:
            signature = host.cache_key(bundle)
        except OSError as exc:
            failures.append({'path': str(bundle), 'error': str(exc)})
            continue
        cached = cache['plugins'].get(key)
        if cached and cached.get('signature') == signature and not request.get('force'):
            reused = [v for k, v in cache['plugins'].items() if (k == key or k.startswith(key + '|')) and v.get('signature') == signature]
            results.extend(reused)
            failures.extend({'path': v['path'], 'error': v.get('error', 'Previous scan failed')} for v in reused if v.get('state') != 'ok')
            continue
        for stale in [k for k in cache['plugins'] if k.startswith(key + '|')]:
            del cache['plugins'][stale]
        # Mark as pending first: if the plugin crashes this process, the host sees which one.
        cache['plugins'][key] = {'path': str(bundle), 'signature': signature, 'state': 'scanning'}
        if cache_dir:
            host.write_cache(cache_dir, cache)
        try:
            names = host.plugin_names(bundle)
            if not names:
                raise ValueError('No plugin found')
            descriptions = [host.describe(bundle, name) for name in names]
            for info in descriptions[:-1]:
                info.update({'signature': signature, 'state': 'ok', 'scannedAt': time.time()})
                cache['plugins'][key + '|' + (info.get('pluginId') or info['name'])] = info
                results.append(info)
            info = descriptions[-1]
            info.update({'signature': signature, 'state': 'ok', 'scannedAt': time.time()})
        except Exception as exc:
            info = {'path': str(bundle), 'signature': signature, 'state': 'failed', 'error': str(exc)[:500], 'scannedAt': time.time()}
            failures.append({'path': str(bundle), 'error': str(exc)[:500]})
        cache['plugins'][key] = info
        results.append(info)
        if cache_dir:
            host.write_cache(cache_dir, cache)
    reporter.progress(100, step='Scan complete')
    return {'plugins': results, 'failures': failures, 'directories': [str(d) for d in directories], 'count': len(results)}


def describe(request, reporter):
    from audiostudio.vst import host
    return host.describe(request['plugin'], request.get('plugin_name') or None)


def editor(request, reporter):
    """Open the plugin's native window; returns the state when the window is closed."""
    from audiostudio.vst import host
    native = host.plugin_format(request['plugin']) != 'vst3'
    plugin = host.load(request['plugin'], request.get('plugin_name') or None) if native else _plugin_cache().get(request['plugin'], request.get('plugin_name') or None)
    try:
        host.apply_settings(plugin, request.get('params'), request.get('state'))
        reporter.progress(10, step='Plugin window open', message='Close the plugin window to continue')
        try:
            plugin.show_editor()
        except Exception as exc:
            raise WorkerError('EditorUnavailable', 'This plugin cannot show an editor here: ' + str(exc))
        snapshot = host.capture(plugin)
        reporter.progress(100, step='Editor closed')
        return snapshot
    finally:
        if native:
            plugin.close()


def validate_jsfx(request, reporter):
    from audiostudio.plugins.scripts import validate_source
    return validate_source(request['source'], request.get('directory') or None)


def save_jsfx(request, reporter):
    from audiostudio.plugins.scripts import save_source
    return save_source(request['name'], request['source'], request.get('overwrite', False))


def analyze(request, reporter):
    from audiostudio import audio_io
    from audiostudio.dsp import analysis
    source = Path(request['input'])
    if not source.is_file():
        raise WorkerError('MissingInput', 'Input file not found: ' + str(source))
    info = audio_io.probe(source).as_dict()
    audio, rate = audio_io.load(source)
    stats = analysis.statistics(audio, rate)
    stats.update(analysis.leading_trailing_silence(audio, rate))
    stats['info'] = info
    return stats


def convert(request, reporter):
    from audiostudio import audio_io
    source = Path(request['input'])
    if not source.is_file():
        raise WorkerError('MissingInput', 'Input file not found: ' + str(source))
    workspace = request.get('workspace')
    output = inside(workspace, request['output']) if workspace else Path(request['output'])
    audio, rate = audio_io.load(source)
    target_rate = int(request.get('samplerate') or rate)
    if target_rate != rate:
        audio = audio_io.resample(audio, rate, target_rate)
        rate = target_rate
    channels = request.get('channels')
    if channels == 1 and audio.shape[0] > 1:
        audio = np.mean(audio, axis=0, keepdims=True)
    elif channels == 2 and audio.shape[0] == 1:
        audio = np.repeat(audio, 2, axis=0)
    written = audio_io.save(output, audio, rate, fmt=request.get('format'), subtype=request.get('subtype'), bitrate_kbps=int(request.get('bitrate_kbps', 192)))
    return {'file': str(written), 'sizeBytes': written.stat().st_size, 'samplerate': rate, 'channels': int(audio.shape[0]),
            'durationSeconds': float(audio.shape[1]) / rate}


def master(request, reporter):
    """Reference mastering with Matchering, or loudness normalisation with a true-peak limiter."""
    from audiostudio import audio_io
    from audiostudio.dsp import effects, analysis
    source = Path(request['input'])
    if not source.is_file():
        raise WorkerError('MissingInput', 'Input file not found: ' + str(source))
    workspace = request.get('workspace')
    output = inside(workspace, request['output']) if workspace else Path(request['output'])
    mode = request.get('mode', 'loudness')
    reporter.progress(2, step='Decoding')
    audio, rate = audio_io.load(source)
    before = analysis.statistics(audio, rate)
    if mode == 'reference':
        import matchering as mg
        import tempfile
        reference = Path(request.get('reference') or '')
        if not reference.is_file():
            raise WorkerError('MissingInput', 'Reference recording not found: ' + str(reference))
        reporter.progress(10, step='Matching the reference', message=reference.name)
        with tempfile.TemporaryDirectory(prefix='master-') as temp:
            target_wav = Path(temp) / 'target.wav'
            reference_wav = Path(temp) / 'reference.wav'
            result_wav = Path(temp) / 'result.wav'
            audio_io.save(target_wav, audio if audio.shape[0] == 2 else np.repeat(audio[:1], 2, axis=0), rate, fmt='wav', subtype='FLOAT')
            ref_audio, ref_rate = audio_io.load(reference)
            audio_io.save(reference_wav, ref_audio if ref_audio.shape[0] == 2 else np.repeat(ref_audio[:1], 2, axis=0), ref_rate, fmt='wav', subtype='FLOAT')
            mg.log(lambda text: reporter.log(str(text)))
            mg.process(target=str(target_wav), reference=str(reference_wav), results=[mg.pcm24(str(result_wav))])
            mastered, rate = audio_io.load(result_wav)
        method = 'matchering'
    else:
        reporter.progress(10, step='Measuring loudness')
        mastered = effects.apply_effect('loudness', audio, rate, {'target_lufs': float(request.get('target_lufs', -14.0)), 'true_peak_limit': True,
                                                                   'ceiling_db': float(request.get('ceiling_db', -1.0))})
        method = 'loudness'
    ceiling = float(request.get('ceiling_db', -1.0))
    peak = float(np.max(np.abs(mastered))) if mastered.size else 0.0
    if peak > 10 ** (ceiling / 20):
        mastered = effects.apply_effect('limiter', mastered, rate, {'threshold_db': ceiling, 'release_ms': 50.0})
    reporter.progress(90, step='Encoding')
    written = audio_io.save(output, mastered, rate, fmt=request.get('format'), subtype=request.get('subtype'), bitrate_kbps=int(request.get('bitrate_kbps', 192)))
    after = analysis.statistics(mastered, rate)
    reporter.progress(100, step='Done')
    return {'file': str(written), 'method': method, 'before': {k: before.get(k) for k in ('integratedLufs', 'truePeakDbtp', 'peakDbfs', 'rmsDbfs')},
            'after': {k: after.get(k) for k in ('integratedLufs', 'truePeakDbtp', 'peakDbfs', 'rmsDbfs')}, 'samplerate': rate, 'sizeBytes': written.stat().st_size}


def render_session(request, reporter):
    """Mix an editor session (tracks, inserts, automation, master bus) to a file, tail included."""
    from audiostudio import audio_io
    from audiostudio.editor.document import Document
    source = Path(request['session'])
    index = source if source.is_file() else source / 'session.json'
    if not index.is_file():
        raise WorkerError('MissingInput', 'Session not found: ' + str(source))
    workspace = request.get('workspace')
    output = inside(workspace, request['output']) if workspace else Path(request['output'])
    reporter.progress(1, step='Loading session', message=index.parent.name)
    document = Document.load_session(index)
    tail = request.get('tail')
    if tail:
        document.tail.update({k: tail[k] for k in ('enabled', 'threshold_db', 'max_seconds', 'hold_seconds') if k in tail})
    selection = request.get('selection')
    started = time.monotonic()

    def progress(fraction):
        reporter.progress(2 + fraction * 90.0, step='Rendering', message='%d %%' % int(fraction * 100))
    if selection:
        audio = document.mixdown(float(selection[0]), float(selection[1]), progress=progress)
        original = float(selection[1]) - float(selection[0])
    else:
        audio = document.mixdown(progress=progress)
        original = document.duration
    reporter.progress(95, step='Encoding', message=output.name)
    written = audio_io.save(output, audio, document.samplerate, fmt=request.get('format'), subtype=request.get('subtype'),
                            bitrate_kbps=int(request.get('bitrate_kbps', 192)))
    inserts = sum(len(t.inserts) for t in document.tracks) + len(document.master.inserts)
    lanes = sum(len(t.automation) for t in document.tracks) + len(document.master.automation)
    reporter.progress(100, step='Done')
    return {'file': str(written), 'sizeBytes': written.stat().st_size, 'samplerate': document.samplerate, 'channels': int(audio.shape[0]),
            'durationSeconds': float(audio.shape[1]) / document.samplerate, 'tailSeconds': round(max(0.0, audio.shape[1] / document.samplerate - original), 3),
            'tracks': len(document.tracks), 'inserts': inserts, 'automationLanes': lanes, 'renderSeconds': round(time.monotonic() - started, 3),
            'session': str(index)}


def _write_mix(document, output, request, selection=None, progress=None):
    from audiostudio import audio_io
    if selection:
        audio = document.mixdown(float(selection[0]), float(selection[1]), progress=progress)
        original = float(selection[1]) - float(selection[0])
    else:
        audio = document.mixdown(progress=progress)
        original = document.duration
    written = audio_io.save(output, audio, document.samplerate, fmt=request.get('format'), subtype=request.get('subtype'),
                            bitrate_kbps=int(request.get('bitrate_kbps', 192)))
    return {'file': str(written), 'sizeBytes': written.stat().st_size, 'samplerate': document.samplerate, 'channels': int(audio.shape[0]),
            'durationSeconds': float(audio.shape[1]) / document.samplerate, 'tailSeconds': round(max(0.0, audio.shape[1] / document.samplerate - original), 3)}


def _workflow_loader():
    from audiostudio.operations.common import load_workflow
    return load_workflow


def edit_session(request, reporter):
    """Apply scripted actions to a session (or a new one), save it and optionally render it."""
    from audiostudio.editor import batch
    document = batch.load_or_new(request.get('session'), int(request.get('samplerate') or 48000))
    if request.get('tail'):
        document.tail.update({k: request['tail'][k] for k in ('enabled', 'threshold_db', 'max_seconds', 'hold_seconds') if k in request['tail']})
    reporter.progress(2, step='Editing', message='%d action(s)' % len(request.get('actions') or []))
    try:
        reports = batch.apply_actions(document, request.get('actions') or [], _workflow_loader())
    except batch.BatchError as exc:
        raise WorkerError(exc.code, str(exc))
    result = {'actions': reports, 'session': None, 'document': batch.describe(document)}
    save_as = request.get('save_as')
    if save_as:
        folder = Path(save_as)
        result['session'] = str(document.save_session(folder))
    if request.get('render'):
        workspace = request.get('workspace')
        output = inside(workspace, request['output']) if workspace else Path(request['output'])
        reporter.progress(20, step='Rendering', message=output.name)
        result.update(_write_mix(document, output, request, request.get('selection'), lambda f: reporter.progress(20 + f * 75, step='Rendering')))
    reporter.progress(100, step='Done')
    return result


def batch_session(request, reporter):
    """Render a session once per input sound placed in a slot track."""
    from audiostudio.editor import batch
    document = batch.load_or_new(request.get('session'), int(request.get('samplerate') or 48000))
    if request.get('tail'):
        document.tail.update({k: request['tail'][k] for k in ('enabled', 'threshold_db', 'max_seconds', 'hold_seconds') if k in request['tail']})
    workspace = request.get('workspace')
    folder = inside(workspace, request['output_dir']) if workspace else Path(request['output_dir'])
    folder.mkdir(parents=True, exist_ok=True)
    suffix = request.get('suffix', '') or ''
    extension = {'wav': '.wav', 'flac': '.flac', 'mp3': '.mp3', 'ogg': '.ogg', 'aac': '.m4a'}.get(request.get('format') or 'wav', '.wav')
    inputs = list(request.get('inputs') or [])
    total = max(1, len(inputs))

    def render(document, stem):
        return _write_mix(document, folder / (stem + suffix + extension), request, request.get('selection'))

    def progress(fraction, message=''):
        reporter.progress(1 + fraction * 98, step='Batch', message=message)
    try:
        results, failed = batch.batch_session(document, inputs, request.get('slot'), render, progress=progress, load_workflow=_workflow_loader())
    except batch.BatchError as exc:
        raise WorkerError(exc.code, str(exc))
    reporter.progress(100, step='Done')
    return {'results': results, 'failed': failed, 'count': len(results), 'outputDir': str(folder), 'document': batch.describe(document)}


def status(request, reporter):
    import pedalboard
    return {'pedalboard': pedalboard.__version__, 'pluginsLoaded': len(_cache.plugins) if _cache else 0}


HANDLERS = {'render': render, 'render_buffer': render_buffer, 'scan': scan, 'describe': describe, 'validate_jsfx': validate_jsfx, 'save_jsfx': save_jsfx, 'editor': editor,
            'analyze': analyze, 'convert': convert, 'master': master, 'render_session': render_session, 'edit_session': edit_session,
            'batch_session': batch_session, 'status': status}

if __name__ == '__main__':
    raise SystemExit(serve(HANDLERS))
