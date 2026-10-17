"""Mixing graph of the editor: clips -> track inserts -> volume/pan automation -> master inserts.

One ``Renderer`` owns the processor instances (native effects and VST3 plugins) of every
insert node, so their state carries from block to block. The player keeps one for real-time
playback; ``Document.mixdown`` creates a fresh one for exports, so an export never disturbs
what is being played. Each node keeps a tap (the last frames in and out, peak levels) and its
meters for the interfaces. A processor that raises is bypassed and reported, never fatal for
the audio thread.
"""
import time

import numpy as np

from ..dsp import effects
from ..dsp import processors as P

TAP_FRAMES = 8192


class Tap:
    """Recent audio around one node (stereo rings) and peak levels, for scopes and meters."""

    def __init__(self, frames=TAP_FRAMES):
        self.frames = frames
        self.input = np.zeros((2, frames), np.float32)
        self.output = np.zeros((2, frames), np.float32)
        self.position = 0
        self.in_peak = (0.0, 0.0)
        self.out_peak = (0.0, 0.0)
        self.updated = 0.0

    def push(self, block_in, block_out):
        n = min(block_in.shape[1], self.frames)
        block_in, block_out = P.as_stereo(block_in)[:, -n:], P.as_stereo(block_out)[:, -n:]
        index = (self.position + np.arange(n)) % self.frames
        self.input[:, index] = block_in
        self.output[:, index] = block_out
        self.position = int((self.position + n) % self.frames)
        self.in_peak = (float(np.abs(block_in[0]).max()) if n else 0.0, float(np.abs(block_in[1]).max()) if n else 0.0)
        self.out_peak = (float(np.abs(block_out[0]).max()) if n else 0.0, float(np.abs(block_out[1]).max()) if n else 0.0)
        self.updated = time.monotonic()

    def recent(self, which='output', frames=2048):
        """The last ``frames`` frames in time order, (2, frames)."""
        ring = self.output if which == 'output' else self.input
        frames = min(frames, self.frames)
        index = (self.position - frames + np.arange(frames)) % self.frames
        return ring[:, index]


class Renderer:
    def __init__(self, document, plugin_loader=None, live=False):
        self.document = document
        self.live = live          # the player's renderer also runs the Effect... dialog's audition insert
        self.processors = {}      # node id -> {'signature', 'processor', 'params'}
        self.taps = {}            # node id -> Tap
        self.errors = {}          # node id -> message
        self.track_peaks = {}     # track id -> (left, right)
        self.master_peak = (0.0, 0.0)
        self.master_rms = 0.0
        self.plugin_loader = plugin_loader or self._load_plugin
        self.plugins = {}         # loaded VST3 instances by (path, name)
        self.latency = {}         # node id -> frames

    # ------------------------------------------------------------------ processors
    @staticmethod
    def _load_plugin(path, name):
        from ..vst import host
        return host.load(path, name or None)

    def _signature(self, node):
        if node['kind'] == 'effect':
            return ('effect', node.get('effect'), self.document.samplerate)
        if node['kind'] == 'vst3':
            return ('vst3', str(node.get('plugin', '')).lower(), node.get('pluginName', ''), self.document.samplerate)
        return ('unsupported', node['kind'])

    def processor_for(self, node):
        """The processor of a node, built or updated to the node's current parameters."""
        signature = self._signature(node)
        entry = self.processors.get(node['id'])
        if entry is None or entry['signature'] != signature:
            processor = self._build(node)
            entry = {'signature': signature, 'processor': processor, 'params': dict(node.get('params') or {}), 'state': node.get('state', '')}
            self.processors[node['id']] = entry
            return processor
        processor = entry['processor']
        if processor is None:
            return None
        params = node.get('params') or {}
        if params != entry['params'] or (node['kind'] == 'vst3' and node.get('state', '') != entry.get('state', '')):
            try:
                if node['kind'] == 'vst3' and node.get('state', '') != entry.get('state', ''):
                    processor.restore_state(node.get('state', ''))
                processor.set_params(params)
            except Exception as exc:
                self.errors[node['id']] = str(exc)
            entry['params'] = dict(params)
            entry['state'] = node.get('state', '')
        return processor

    def _build(self, node):
        try:
            if node['kind'] == 'effect':
                processor = effects.make_processor(node['effect'], node.get('params') or {}, self.document.samplerate)
                if processor is None:
                    self.errors[node['id']] = 'This effect works on whole files only (use it on a selection)'
                return processor
            if node['kind'] == 'vst3':
                key = (str(node.get('plugin', '')).lower(), node.get('pluginName', '') or '')
                plugin = self.plugins.get(key)
                if plugin is None:
                    plugin = self.plugin_loader(node['plugin'], node.get('pluginName', ''))
                    self.plugins[key] = plugin
                processor = P.VST3Processor(plugin, node.get('params') or {}, self.document.samplerate, state=node.get('state', ''))
                self.errors.pop(node['id'], None)
                return processor
        except Exception as exc:
            self.errors[node['id']] = str(exc)
        return None

    def reset(self):
        for entry in self.processors.values():
            if entry['processor'] is not None:
                try:
                    entry['processor'].reset()
                except Exception:
                    pass
        for tap in self.taps.values():
            tap.__init__(tap.frames)

    def forget(self, node_id):
        self.processors.pop(node_id, None)
        self.taps.pop(node_id, None)
        self.errors.pop(node_id, None)

    def prune(self):
        """Drop processors of nodes that no longer exist in the document."""
        alive = {n['id'] for t in self.document.tracks for n in t.inserts} | {n['id'] for n in self.document.master.inserts}
        for node_id in list(self.processors):
            if node_id not in alive:
                self.forget(node_id)

    def tap(self, node_id):
        tap = self.taps.get(node_id)
        if tap is None:
            tap = self.taps[node_id] = Tap()
        return tap

    def meters(self, node_id):
        entry = self.processors.get(node_id)
        processor = entry['processor'] if entry else None
        return dict(getattr(processor, 'meters', {}) or {}) if processor is not None else {}

    def processor(self, node_id):
        entry = self.processors.get(node_id)
        return entry['processor'] if entry else None

    # ------------------------------------------------------------------ automation
    def _node_params(self, owner, node, seconds):
        """(parameters, automated): the node's parameters with the active lanes applied at ``seconds``."""
        params = node.get('params') or {}
        prefix = node['id'] + '.'
        lanes = [lane for key, lane in owner.automation.items() if key.startswith(prefix) and lane.active]
        if not lanes:
            return params, False
        merged = dict(params)
        for lane in lanes:
            key = lane.key[len(prefix):]
            value = lane.value_at(seconds, merged.get(key, 0.0))
            current = merged.get(key)
            if isinstance(current, bool):
                value = value >= 0.5
            elif isinstance(current, int) and not isinstance(current, bool):
                value = int(round(value))
            merged[key] = value
        return merged, True

    def _gain_pan(self, owner, start, frames, ignore_pan=False):
        """Per-frame stereo gains from volume/pan (automated or static; None when nothing is automated)."""
        doc = self.document
        gain_lane = owner.automation.get('gain_db')
        pan_lane = owner.automation.get('pan')
        mute_lane = owner.automation.get('mute')
        static = not ((gain_lane and gain_lane.active) or (pan_lane and pan_lane.active) or (mute_lane and mute_lane.active))
        if static:
            return None
        times = (start + np.arange(frames)) / float(doc.samplerate)
        gain_db = gain_lane.values(times, owner.gain_db) if (gain_lane and gain_lane.active) else np.full(frames, float(owner.gain_db))
        pan = pan_lane.values(times, getattr(owner, 'pan', 0.0)) if (pan_lane and pan_lane.active) else np.full(frames, float(getattr(owner, 'pan', 0.0)))
        if ignore_pan:
            pan = np.zeros(frames)
        base = 10.0 ** (gain_db / 20.0)
        if mute_lane and mute_lane.active:
            base = base * (mute_lane.values(times, 0.0) < 0.5)
        angle = (np.clip(pan, -1.0, 1.0) + 1.0) * 0.25 * np.pi
        return (np.cos(angle) * np.sqrt(2.0) * base).astype(np.float32), (np.sin(angle) * np.sqrt(2.0) * base).astype(np.float32)

    # ------------------------------------------------------------------ blocks
    def clip_block(self, track, start, frames):
        """Stereo block of the clips of a track for document frames [start, start + frames), with their
        fades (overlapping clips are summed). The second value is False when no clip is in the range."""
        out = np.zeros((2, frames), np.float32)
        stop = start + frames
        audible = False
        for clip in track.clips:
            a, b = max(start, clip.offset), min(stop, clip.end)
            if b <= a:
                continue
            local_a, local_b = a - clip.offset, b - clip.offset
            block = clip.view()[:, local_a:local_b]
            envelope = self.document._fade_gain(clip, local_a, local_b)
            if envelope is not None:
                block = block * envelope
            if clip.channels == 1:
                out[:, a - start:b - start] += block[0]
            else:
                out[:, a - start:b - start] += block[:2]
            audible = True
        return out, audible

    def sidechain_block(self, track_id, start, frames):
        track = self.document.track(track_id)
        if track is None:
            return None
        block, _ = self.clip_block(track, start, frames)
        return block

    def run_chain(self, owner, nodes, block, start, frames):
        seconds = start / float(self.document.samplerate)
        for node in nodes:
            if not node.get('enabled', True) or (node.get('_preview') and not self.live):
                continue
            processor = self.processor_for(node)
            if processor is None:
                continue
            params, automated = self._node_params(owner, node, seconds)
            if automated:
                try:
                    processor.set_params(params)
                except Exception as exc:
                    self.errors[node['id']] = str(exc)
            sidechain = None
            if node.get('sidechain'):
                sidechain = self.sidechain_block(node['sidechain'], start, frames)
            dry = block
            try:
                wet = processor.process(block, sidechain=sidechain)
                if wet is None or wet.shape[1] != frames:
                    raise ValueError('processor returned %s frames for %s' % (None if wet is None else wet.shape[1], frames))
                wet = P.as_stereo(np.asarray(wet, dtype=np.float32))
                self.errors.pop(node['id'], None)
            except Exception as exc:
                self.errors[node['id']] = str(exc)
                wet = dry
            mix = float(node.get('mix', 1.0))
            if mix < 1.0:
                wet = P.mix_dry_wet(dry, wet, mix).astype(np.float32)
            self.tap(node['id']).push(dry, wet)
            self.latency[node['id']] = int(getattr(processor, 'latency_frames', 0) or 0)
            block = wet
        return block

    def render(self, start, frames, channels=2):
        """Mix every audible track through its inserts, then the master chain; (channels, frames)."""
        doc = self.document
        out = np.zeros((2, frames), np.float32)
        if frames <= 0:
            return out[:channels]
        soloed = any(t.solo for t in doc.tracks)
        mono = channels == 1                      # a mono mixdown applies the gain only, no pan law
        for track in doc.tracks:
            if track.mute or (soloed and not track.solo):
                self.track_peaks[track.id] = (0.0, 0.0)
                continue
            block, audible = self.clip_block(track, start, frames)
            if not audible and not track.inserts:
                self.track_peaks[track.id] = (0.0, 0.0)
                continue
            if track.inserts and (self.live or any(not n.get('_preview') for n in track.inserts)):
                block = self.run_chain(track, track.inserts, block, start, frames)
            gains = self._gain_pan(track, start, frames, ignore_pan=mono)
            if gains is None:
                left, right = (P.db_to_gain(track.gain_db),) * 2 if mono else track.stereo_gains()
                block = np.stack([block[0] * left, block[1] * right]).astype(np.float32)
            else:
                block = np.stack([block[0] * gains[0], block[1] * gains[1]]).astype(np.float32)
            self.track_peaks[track.id] = (float(np.abs(block[0]).max()), float(np.abs(block[1]).max()))
            out += block
        master = doc.master
        if master.inserts:
            out = self.run_chain(master, master.inserts, out, start, frames)
        gains = self._gain_pan(master, start, frames)
        if master.mute:
            out[:] = 0.0
        elif gains is None:
            out *= np.float32(P.db_to_gain(master.gain_db))
        else:
            out = np.stack([out[0] * gains[0], out[1] * gains[1]]).astype(np.float32)
        out = np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=-1.0)
        self.master_peak = (float(np.abs(out[0]).max()), float(np.abs(out[1]).max()))
        self.master_rms = float(np.sqrt(np.mean(out ** 2)))
        if channels == 1:
            return np.mean(out, axis=0, keepdims=True)
        return out

    # ------------------------------------------------------------------ offline
    def render_range(self, start, stop, channels=2, block=4096, tail=None, progress=None):
        """Render [start, stop) frames, then keep rendering silence while stateful inserts ring out."""
        doc = self.document
        self.reset()
        parts = []
        position = start
        total = max(1, stop - start)
        while position < stop:
            count = min(block, stop - position)
            parts.append(self.render(position, count, channels))
            position += count
            if progress:
                progress(min(1.0, (position - start) / total))
        rendered = np.concatenate(parts, axis=1) if parts else np.zeros((channels, 0), np.float32)
        settings = tail if tail is not None else doc.tail
        if settings.get('enabled', True) and doc.has_stateful_inserts():
            threshold = P.db_to_gain(float(settings.get('threshold_db', -60.0)))
            max_frames = int(float(settings.get('max_seconds', 10.0)) * doc.samplerate)
            hold = int(float(settings.get('hold_seconds', 0.1)) * doc.samplerate)
            extra = []
            added = 0
            quiet = 0
            while added < max_frames:
                chunk = self.render(position, block, channels)
                extra.append(chunk)
                added += block
                position += block
                if float(np.abs(chunk).max()) < threshold:
                    quiet += block
                    if quiet >= hold:
                        break
                else:
                    quiet = 0
            if extra:
                tail_audio = np.concatenate(extra, axis=1)
                envelope = np.abs(tail_audio).max(axis=0)
                loud = np.nonzero(envelope >= threshold)[0]
                keep = int(loud[-1]) + 1 + hold if loud.size else 0
                if keep > 0:
                    rendered = np.concatenate([rendered, tail_audio[:, :min(keep, tail_audio.shape[1])]], axis=1)
        return np.ascontiguousarray(rendered)
