"""Render a workflow over a buffer: effects, VST3 plugins and model nodes in order.

``render(audio, samplerate, workflow, progress=None, cancel=None, model_runner=None)``
returns ``RenderResult``. Tail rendering appends silence before the chain and trims
the silent remainder afterwards, so decays are preserved (see dsp.tail).

Model nodes are delegated to ``model_runner(node, audio, samplerate, report)``: the
worker that runs a workflow decides how a model is executed (usually another engine
process). Without a runner, a model node raises ``UnsupportedNode``.
"""
from dataclasses import dataclass, field
import time
import numpy as np

from ..dsp import effects
from ..dsp.tail import TailSettings, extend, trim, measure_tail
from . import model as workflow_model


class UnsupportedNode(RuntimeError):
    pass


class RenderCancelled(RuntimeError):
    pass


@dataclass
class RenderResult:
    audio: np.ndarray
    samplerate: int
    original_frames: int
    tail_seconds: float = 0.0
    nodes: list = field(default_factory=list)
    seconds: float = 0.0

    def report(self):
        return {'samplerate': self.samplerate, 'frames': int(self.audio.shape[1]), 'channels': int(self.audio.shape[0]),
                'originalFrames': self.original_frames, 'durationSeconds': float(self.audio.shape[1]) / float(self.samplerate),
                'tailSeconds': self.tail_seconds, 'nodes': self.nodes, 'renderSeconds': round(self.seconds, 3)}


def _check(cancel):
    if cancel is not None and cancel():
        raise RenderCancelled('Render cancelled')


def _mix(dry, wet, mix):
    if mix >= 1.0:
        return wet
    if wet.shape != dry.shape:
        return wet
    return (dry * (1.0 - mix) + wet * mix).astype(np.float32)


class PluginCache:
    """Loaded VST3 instances reused across nodes and calls inside one worker."""

    def __init__(self):
        self.plugins = {}

    def get(self, path, plugin_name=None):
        from ..vst import host
        key = (str(host.loadable_path(path)).lower(), plugin_name or '')
        if key not in self.plugins:
            self.plugins[key] = host.load(path, plugin_name)
        return self.plugins[key]


def render(audio, samplerate, workflow, progress=None, cancel=None, model_runner=None, plugin_cache=None):
    started = time.monotonic()
    document = workflow_model.validate(workflow)
    tail = TailSettings.from_dict(document['tail'])
    audio = np.ascontiguousarray(np.asarray(audio, dtype=np.float32))
    if audio.ndim == 1:
        audio = audio[np.newaxis, :]
    original_frames = int(audio.shape[1])
    rate = int(samplerate)
    nodes = [n for n in document['nodes'] if n.get('enabled', True)]
    reports = []
    # A length-changing node (time stretch, trim) breaks the "original length" reference:
    # the tail extension is added only when at least one stateful node exists.
    stateful = any(n['kind'] == 'vst3' or (n['kind'] == 'effect' and effects.get(n['effect']).build is not None) for n in nodes)
    current = extend(audio, rate, tail) if stateful else audio
    cache = plugin_cache or PluginCache()
    total = max(1, len(nodes))
    for index, node in enumerate(nodes):
        _check(cancel)
        label = node.get('label') or node.get('effect') or node.get('pluginName') or node.get('model') or node['kind']
        if progress:
            progress(index / total, f'{label} ({index + 1}/{total})')
        node_started = time.monotonic()
        dry = current
        if node['kind'] == 'effect':
            spec = effects.get(node['effect'])
            values = spec.normalize(node.get('params'))
            if spec.apply is not None:
                current = spec.apply(current, rate, values)
                if node['effect'] == 'resample':
                    ratio = int(values['target_rate']) / rate
                    original_frames = int(round(original_frames * ratio))
                    rate = int(values['target_rate'])
                elif spec.changes_length and current.shape[1] != dry.shape[1]:
                    # Keep the original/extension proportion for trimming.
                    original_frames = min(current.shape[1], int(round(original_frames * current.shape[1] / max(1, dry.shape[1]))))
            else:
                plugin = spec.build(values)
                current = np.ascontiguousarray(plugin(current, float(rate), reset=True).astype(np.float32))
        elif node['kind'] == 'vst3':
            from ..vst import host
            plugin = cache.get(node['plugin'], node.get('pluginName') or None)
            host.apply_settings(plugin, node.get('params'), node.get('state'))
            current = host.process(plugin, current, rate, reset=True)
        elif node['kind'] == 'model':
            if model_runner is None:
                raise UnsupportedNode('Model nodes need a model runner: ' + node['model'])
            current, rate_after = model_runner(node, current, rate, lambda fraction, text='': progress((index + fraction) / total, text) if progress else None)
            if rate_after and int(rate_after) != rate:
                original_frames = int(round(original_frames * int(rate_after) / rate))
                rate = int(rate_after)
        if current.shape[1] == dry.shape[1] and current.shape[0] == dry.shape[0]:
            current = _mix(dry, current, float(node.get('mix', 1.0)))
        current = np.nan_to_num(current, nan=0.0, posinf=1.0, neginf=-1.0)
        reports.append({'id': node['id'], 'kind': node['kind'], 'label': label, 'seconds': round(time.monotonic() - node_started, 3),
                        'frames': int(current.shape[1]), 'channels': int(current.shape[0])})
    _check(cancel)
    tail_seconds = 0.0
    if stateful:
        tail_seconds = measure_tail(current, rate, original_frames, tail.threshold_db)
        current = trim(current, rate, tail, original_frames)
    if progress:
        progress(1.0, 'done')
    return RenderResult(np.ascontiguousarray(current), rate, original_frames, round(tail_seconds, 3), reports, time.monotonic() - started)


def render_file(source, destination, workflow, fmt=None, subtype=None, bitrate_kbps=192, progress=None, cancel=None, model_runner=None):
    """Convenience: decode, render, encode. Returns (RenderResult, written path)."""
    from .. import audio_io
    audio, rate = audio_io.load(source)
    result = render(audio, rate, workflow, progress=progress, cancel=cancel, model_runner=model_runner)
    written = audio_io.save(destination, result.audio, result.samplerate, fmt=fmt, subtype=subtype, bitrate_kbps=bitrate_kbps)
    return result, written
