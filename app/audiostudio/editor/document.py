"""Editor document: tracks, selection, undo/redo, edit operations, mixdown, sessions.

Times are seconds in document time; frames are at ``Document.samplerate``. Every edit
goes through ``Document.edit(...)`` which records the previous state of the touched
tracks so it can be undone. Sessions are saved as a folder with a JSON index and one
WAV per track under data/sessions/<name>/.
"""
from dataclasses import dataclass, field
import copy
import json
from pathlib import Path
import shutil
import time
import uuid

import numpy as np

from .peaks import Peaks
from .automation import AutomationLane
from .. import audio_io

SESSION_SCHEMA = 2
DEFAULT_TAIL = {'enabled': True, 'threshold_db': -60.0, 'max_seconds': 10.0, 'hold_seconds': 0.1}

MAX_UNDO = 64
COLOURS = [(0.36, 0.72, 0.95), (0.98, 0.62, 0.2), (0.55, 0.85, 0.5), (0.9, 0.5, 0.8), (0.95, 0.85, 0.35), (0.6, 0.7, 1.0)]


def db_to_gain(db):
    return float(10.0 ** (float(db) / 20.0))


@dataclass
class Track:
    """One clip on its own lane.

    ``audio`` holds every decoded sample. The clip shows the window
    ``audio[:, start:start + length]`` placed at ``offset`` in the document, so trimming a
    clip by its edges never destroys audio and can be dragged back. ``flatten()`` bakes the
    window into ``audio`` and is called before an edit that rewrites samples.
    ``fade_in`` / ``fade_out`` are seconds applied at mix time (non destructive).
    """
    id: str
    name: str
    audio: np.ndarray                       # (channels, frames) float32, complete material
    offset: int = 0                         # start frame in the document
    gain_db: float = 0.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    colour: tuple = (0.36, 0.72, 0.95)
    source: str = ''
    height: float = 110.0
    start: int = 0                          # in-point inside audio
    length: int = -1                        # visible frames; -1 = to the end of audio
    fade_in: float = 0.0                    # seconds
    fade_out: float = 0.0                   # seconds
    inserts: list = field(default_factory=list)        # insert chain: workflow-style nodes (effect / vst3)
    automation: dict = field(default_factory=dict)     # key -> AutomationLane
    automation_view: str = ''                          # lane shown in the timeline ('' = none)
    _peaks: object = field(default=None, repr=False)

    @property
    def total_frames(self):
        return int(self.audio.shape[1])

    @property
    def frames(self):
        """Visible length of the clip."""
        available = max(0, self.total_frames - max(0, self.start))
        return available if self.length < 0 else max(0, min(int(self.length), available))

    @property
    def channels(self):
        return int(self.audio.shape[0])

    @property
    def end(self):
        return self.offset + self.frames

    def view(self):
        """The visible samples of the clip."""
        return self.audio[:, self.start:self.start + self.frames]

    def flatten(self):
        """Bake the trim into the audio so sample edits work on what is visible."""
        if self.start != 0 or self.length >= 0:
            self.audio = np.ascontiguousarray(self.view())
            self.start, self.length = 0, -1
            self.invalidate()
        return self

    def peaks(self):
        if self._peaks is None:
            self._peaks = Peaks(self.audio)
        return self._peaks

    def invalidate(self):
        self._peaks = None

    def snapshot(self):
        return {'audio': self.audio.copy(), 'offset': self.offset, 'gain_db': self.gain_db, 'pan': self.pan, 'mute': self.mute, 'solo': self.solo,
                'name': self.name, 'start': self.start, 'length': self.length, 'fade_in': self.fade_in, 'fade_out': self.fade_out,
                'inserts': copy.deepcopy(self.inserts), 'automation': {k: lane.copy() for k, lane in self.automation.items()}}

    def restore(self, state):
        self.audio = state['audio']
        self.offset, self.gain_db, self.pan, self.mute, self.solo, self.name = state['offset'], state['gain_db'], state['pan'], state['mute'], state['solo'], state['name']
        self.start, self.length = state.get('start', 0), state.get('length', -1)
        self.fade_in, self.fade_out = state.get('fade_in', 0.0), state.get('fade_out', 0.0)
        self.inserts = copy.deepcopy(state.get('inserts', []))
        self.automation = {k: lane.copy() for k, lane in state.get('automation', {}).items()}
        self.invalidate()

    def lane(self, key, create=False):
        lane = self.automation.get(key)
        if lane is None and create:
            lane = self.automation[key] = AutomationLane(key)
        return lane

    def stereo_gains(self):
        angle = (float(self.pan) + 1.0) * 0.25 * np.pi
        base = db_to_gain(self.gain_db)
        return float(np.cos(angle)) * np.sqrt(2.0) * base, float(np.sin(angle)) * np.sqrt(2.0) * base


class MasterBus:
    """The sum of every track: its own insert chain, gain and automation. Not a clip."""

    id = 'master'
    name = 'Master'
    pan = 0.0
    solo = False

    def __init__(self):
        self.gain_db = 0.0
        self.mute = False
        self.inserts = []
        self.automation = {}
        self.automation_view = ''
        self.height = 90.0

    def stereo_gains(self):
        base = db_to_gain(self.gain_db)
        return base, base

    def lane(self, key, create=False):
        lane = self.automation.get(key)
        if lane is None and create:
            lane = self.automation[key] = AutomationLane(key)
        return lane

    def snapshot(self):
        return {'gain_db': self.gain_db, 'mute': self.mute, 'inserts': copy.deepcopy(self.inserts),
                'automation': {k: lane.copy() for k, lane in self.automation.items()}}

    def restore(self, state):
        self.gain_db, self.mute = state['gain_db'], state['mute']
        self.inserts = copy.deepcopy(state['inserts'])
        self.automation = {k: lane.copy() for k, lane in state['automation'].items()}

    def to_dict(self):
        return {'gain_db': self.gain_db, 'mute': self.mute, 'inserts': [{k: v for k, v in n.items() if not k.startswith('_')} for n in self.inserts],
                'height': self.height, 'automation': {k: lane.to_dict() for k, lane in self.automation.items()}, 'automationView': self.automation_view}

    @classmethod
    def from_dict(cls, value):
        master = cls()
        value = value or {}
        master.gain_db = float(value.get('gain_db', 0.0))
        master.mute = bool(value.get('mute', False))
        master.inserts = _load_inserts(value.get('inserts'))
        master.automation = _load_automation(value.get('automation'))
        master.automation_view = str(value.get('automationView', '') or '')
        master.height = float(value.get('height', 90.0))
        return master


def _load_inserts(value):
    from ..workflow import model as workflow_model
    nodes = []
    for node in value or []:
        try:
            clean = workflow_model.normalize_node(node)
            if node.get('sidechain'):
                clean['sidechain'] = str(node['sidechain'])
            nodes.append(clean)
        except Exception:
            continue
    return nodes


def _load_automation(value):
    lanes = {}
    for key, lane in (value or {}).items():
        try:
            lanes[str(key)] = AutomationLane.from_dict({**lane, 'key': key})
        except Exception:
            continue
    return lanes


class Document:
    def __init__(self, samplerate=48000):
        self.samplerate = int(samplerate)
        self.tracks = []
        self.master = MasterBus()
        self.tail = dict(DEFAULT_TAIL)
        self.selection = None          # (start_seconds, end_seconds)
        self.selected_track = 0
        self.cursor = 0.0              # seconds
        self.clipboard = None          # (audio, samplerate)
        self.undo_stack = []
        self.redo_stack = []
        self.name = 'Untitled'
        self.path = None
        self.dirty = False
        self.version = 0

    # ------------------------------------------------------------------ basics
    @property
    def frames(self):
        return max((t.end for t in self.tracks), default=0)

    @property
    def duration(self):
        return self.frames / float(self.samplerate)

    def seconds_to_frame(self, seconds):
        return int(round(float(seconds) * self.samplerate))

    def frame_to_seconds(self, frame):
        return float(frame) / self.samplerate

    def track(self, track_id):
        return next((t for t in self.tracks if t.id == track_id), None)

    def current_track(self):
        if not self.tracks:
            return None
        self.selected_track = max(0, min(self.selected_track, len(self.tracks) - 1))
        return self.tracks[self.selected_track]

    def selection_frames(self, track=None):
        """Selection as (start, stop) frames in document time, or the whole track/document."""
        if self.selection:
            a, b = sorted(self.selection)
            return self.seconds_to_frame(a), self.seconds_to_frame(b)
        if track is not None:
            return track.offset, track.end
        return 0, self.frames

    def touch(self):
        self.dirty = True
        self.version += 1

    # ------------------------------------------------------------------ undo
    def edit(self, label, track_ids=None, structural=False):
        """Record the state of the given tracks (or all when structural) before an edit."""
        ids = [t.id for t in self.tracks] if (structural or track_ids is None) else list(track_ids)
        entry = {'label': label, 'time': time.time(), 'tracks': {tid: self.track(tid).snapshot() for tid in ids if self.track(tid) is not None},
                 'order': [t.id for t in self.tracks], 'structural': structural,
                 'objects': {t.id: t for t in self.tracks} if structural else {}, 'selection': self.selection, 'samplerate': self.samplerate,
                 'master': self.master.snapshot()}
        self.undo_stack.append(entry)
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack.clear()
        self.touch()
        return entry

    def _apply_entry(self, entry):
        current = {'label': entry['label'], 'time': time.time(), 'tracks': {}, 'order': [t.id for t in self.tracks], 'structural': entry['structural'],
                   'objects': {t.id: t for t in self.tracks}, 'selection': self.selection, 'samplerate': self.samplerate, 'master': self.master.snapshot()}
        for tid in entry['tracks']:
            track = self.track(tid) or entry['objects'].get(tid)
            if track is not None:
                current['tracks'][tid] = track.snapshot()
        if entry['structural']:
            self.tracks = [entry['objects'][tid] for tid in entry['order'] if tid in entry['objects']]
            self.samplerate = entry['samplerate']
        for tid, state in entry['tracks'].items():
            track = self.track(tid)
            if track is not None:
                track.restore(state)
        self.selection = entry['selection']
        if entry.get('master') is not None:
            self.master.restore(entry['master'])
        self.touch()
        return current

    def undo(self):
        if not self.undo_stack:
            return None
        entry = self.undo_stack.pop()
        self.redo_stack.append(self._apply_entry(entry))
        return entry['label']

    def redo(self):
        if not self.redo_stack:
            return None
        entry = self.redo_stack.pop()
        self.undo_stack.append(self._apply_entry(entry))
        return entry['label']

    # ------------------------------------------------------------------ tracks
    def add_track(self, audio, name='Track', samplerate=None, offset_seconds=0.0, source='', record=True):
        audio = np.ascontiguousarray(np.asarray(audio, dtype=np.float32))
        if audio.ndim == 1:
            audio = audio[np.newaxis, :]
        if audio.shape[0] > 2:
            audio = audio[:2]
        if samplerate and int(samplerate) != self.samplerate:
            if not self.tracks:
                self.samplerate = int(samplerate)
            else:
                audio = audio_io.resample(audio, int(samplerate), self.samplerate)
        if record:
            self.edit('Add track ' + name, structural=True)
        track = Track(uuid.uuid4().hex[:8], name, audio, self.seconds_to_frame(offset_seconds), colour=COLOURS[len(self.tracks) % len(COLOURS)], source=source)
        self.tracks.append(track)
        self.selected_track = len(self.tracks) - 1
        self.touch()
        return track

    def remove_track(self, track_id):
        track = self.track(track_id)
        if track is None:
            return
        self.edit('Remove track ' + track.name, structural=True)
        self.tracks = [t for t in self.tracks if t.id != track_id]
        self.selected_track = max(0, min(self.selected_track, len(self.tracks) - 1))
        self.touch()

    def move_track(self, track_id, direction):
        index = next((i for i, t in enumerate(self.tracks) if t.id == track_id), None)
        if index is None:
            return
        target = index + direction
        if 0 <= target < len(self.tracks):
            self.edit('Reorder tracks', structural=True)
            self.tracks[index], self.tracks[target] = self.tracks[target], self.tracks[index]
            self.selected_track = target

    def import_file(self, path, offset_seconds=None, name=None):
        audio, rate = audio_io.load(path)
        offset = self.cursor if offset_seconds is None else offset_seconds
        return self.add_track(audio, name or Path(path).stem, samplerate=rate, offset_seconds=offset, source=str(path))

    # ------------------------------------------------------------------ region helpers
    def flatten(self, tracks):
        for track in tracks:
            track.flatten()

    def _region(self, track, start_frame, stop_frame):
        """Clamp a document frame range to the track and return local (a, b)."""
        a = max(0, start_frame - track.offset)
        b = min(track.frames, stop_frame - track.offset)
        return a, max(a, b)

    def _replace(self, track, a, b, block):
        """Replace local frames [a, b) of a track with ``block`` (may change the length)."""
        if block.shape[0] != track.channels:
            block = np.repeat(np.mean(block, axis=0, keepdims=True), track.channels, axis=0) if block.shape[0] != 1 else np.repeat(block, track.channels, axis=0)
        track.audio = np.ascontiguousarray(np.concatenate([track.audio[:, :a], block.astype(np.float32), track.audio[:, b:]], axis=1))
        track.invalidate()

    def targets(self, all_tracks=False):
        if all_tracks:
            return list(self.tracks)
        track = self.current_track()
        return [track] if track is not None else []

    # ------------------------------------------------------------------ editing
    def delete(self, all_tracks=False):
        if not self.selection:
            return False
        start, stop = self.selection_frames()
        tracks = self.targets(all_tracks)
        self.edit('Delete', [t.id for t in tracks])
        self.flatten(tracks)
        for track in tracks:
            a, b = self._region(track, start, stop)
            if b > a:
                self._replace(track, a, b, track.audio[:, :0])
            elif start < track.offset:
                track.offset = max(0, track.offset - (stop - start))
        self.cursor = self.frame_to_seconds(start)
        self.selection = None
        return True

    def silence(self, all_tracks=False):
        if not self.selection:
            return False
        start, stop = self.selection_frames()
        tracks = self.targets(all_tracks)
        self.edit('Silence', [t.id for t in tracks])
        self.flatten(tracks)
        for track in tracks:
            a, b = self._region(track, start, stop)
            if b > a:
                track.audio[:, a:b] = 0.0
                track.invalidate()
        return True

    def trim(self, all_tracks=False):
        """Keep only the selection."""
        if not self.selection:
            return False
        start, stop = self.selection_frames()
        tracks = self.targets(all_tracks)
        self.edit('Trim', [t.id for t in tracks])
        self.flatten(tracks)
        for track in tracks:
            a, b = self._region(track, start, stop)
            track.audio = np.ascontiguousarray(track.audio[:, a:b])
            track.offset = max(track.offset, start)
            track.invalidate()
        return True

    def copy(self):
        track = self.current_track()
        if track is None or not self.selection:
            return False
        start, stop = self.selection_frames()
        a, b = self._region(track, start, stop)
        if b <= a:
            return False
        self.clipboard = (track.view()[:, a:b].copy(), self.samplerate)
        return True

    def cut(self):
        if self.copy():
            return self.delete()
        return False

    def paste(self, insert=True):
        track = self.current_track()
        if self.clipboard is None:
            return False
        block, rate = self.clipboard
        if rate != self.samplerate:
            block = audio_io.resample(block, rate, self.samplerate)
        if track is None:
            self.add_track(block, 'Pasted', offset_seconds=self.cursor)
            return True
        position = self.seconds_to_frame(self.selection[0] if self.selection else self.cursor)
        self.edit('Paste', [track.id])
        track.flatten()
        if self.selection:
            start, stop = self.selection_frames()
            a, b = self._region(track, start, stop)
            self._replace(track, a, b if insert is False else a, block) if insert else self._replace(track, a, b, block)
        else:
            a = max(0, min(track.frames, position - track.offset))
            if position < track.offset:
                track.offset = position
                a = 0
            if insert:
                self._replace(track, a, a, block)
            else:
                b = min(track.frames, a + block.shape[1])
                self._replace(track, a, b, block)
        self.selection = (self.frame_to_seconds(position), self.frame_to_seconds(position + block.shape[1]))
        return True

    def insert_silence(self, seconds, all_tracks=False):
        position = self.seconds_to_frame(self.cursor)
        count = self.seconds_to_frame(seconds)
        tracks = self.targets(all_tracks)
        self.edit('Insert silence', [t.id for t in tracks])
        self.flatten(tracks)
        for track in tracks:
            if position <= track.offset:
                track.offset += count
            elif position < track.end:
                a = position - track.offset
                self._replace(track, a, a, np.zeros((track.channels, count), np.float32))
        return True

    def split(self):
        track = self.current_track()
        if track is None:
            return False
        position = self.seconds_to_frame(self.cursor) - track.offset
        if position <= 0 or position >= track.frames:
            return False
        self.edit('Split', structural=True)
        track.flatten()
        right = Track(uuid.uuid4().hex[:8], track.name + ' (2)', np.ascontiguousarray(track.audio[:, position:]), track.offset + position,
                      track.gain_db, track.pan, track.mute, track.solo, track.colour, track.source, track.height,
                      fade_out=track.fade_out)
        right.inserts, right.automation = self.copy_chain(track)
        track.audio = np.ascontiguousarray(track.audio[:, :position])
        track.fade_out = 0.0
        track.invalidate()
        self.tracks.insert(self.selected_track + 1, right)
        return True

    def resize_clip(self, track, edge, seconds, record=True):
        """Move one edge of a clip. Audio outside the clip is kept and can be dragged back."""
        frame = self.seconds_to_frame(seconds)
        if record:
            self.edit('Resize clip', [track.id])
        if edge == 'left':
            frame = max(0, frame)
            delta = frame - track.offset
            delta = max(-track.start, min(delta, track.frames - 1))
            track.start += delta
            if track.length >= 0:
                track.length = max(1, track.length - delta)
            else:
                track.length = max(1, track.total_frames - track.start)
            track.offset = max(0, track.offset + delta)
        else:
            length = max(1, min(frame - track.offset, track.total_frames - track.start))
            track.length = int(length)
        track.fade_in = min(track.fade_in, self.frame_to_seconds(track.frames))
        track.fade_out = min(track.fade_out, self.frame_to_seconds(track.frames))
        self.touch()
        return track

    def set_fade(self, track, side, seconds, record=True):
        """Fade in/out length of a clip, in seconds (0 removes it)."""
        if record:
            self.edit('Fade ' + side, [track.id])
        value = float(max(0.0, min(seconds, self.frame_to_seconds(track.frames))))
        if side == 'in':
            track.fade_in = min(value, self.frame_to_seconds(track.frames) - track.fade_out)
        else:
            track.fade_out = min(value, self.frame_to_seconds(track.frames) - track.fade_in)
        self.touch()
        return track

    def set_offset(self, track, seconds):
        self.edit('Move track', [track.id])
        track.offset = max(0, self.seconds_to_frame(seconds))

    def apply(self, label, function, all_tracks=False, whole_track=False):
        """Apply ``function(audio, samplerate) -> audio`` to the selection (or whole track).

        A longer result overlaps the following audio (tail), a shorter one shrinks the region."""
        tracks = self.targets(all_tracks)
        if not tracks:
            return False
        self.edit(label, [t.id for t in tracks])
        self.flatten(tracks)
        for track in tracks:
            if self.selection and not whole_track:
                start, stop = self.selection_frames()
                a, b = self._region(track, start, stop)
                if b <= a:
                    continue
            else:
                a, b = 0, track.frames
            block = np.ascontiguousarray(track.audio[:, a:b])
            result = np.asarray(function(block, self.samplerate), dtype=np.float32)
            if result.ndim == 1:
                result = result[np.newaxis, :]
            if result.shape[0] != track.channels:
                result = np.repeat(np.mean(result, axis=0, keepdims=True), track.channels, axis=0)
            extra = result.shape[1] - (b - a)
            if extra > 0:
                # The tail (reverb, delay) is mixed over the audio that follows the region and
                # extends the track when it runs past its end.
                after = track.audio[:, b:].copy()
                overlap = min(extra, after.shape[1])
                after[:, :overlap] += result[:, b - a:b - a + overlap]
                remainder = result[:, b - a + overlap:]
                track.audio = np.ascontiguousarray(np.concatenate([track.audio[:, :a], result[:, :b - a], after, remainder], axis=1))
                track.invalidate()
            else:
                self._replace(track, a, b, result)
        return True

    # ------------------------------------------------------------------ inserts and automation
    def owner(self, owner_id):
        """A track by id, or the master bus for 'master'."""
        return self.master if owner_id == 'master' else self.track(owner_id)

    def _edit_owner(self, label, owner):
        if owner is self.master:
            self.edit(label, [])
        else:
            self.edit(label, [owner.id])

    def add_insert(self, owner, node, index=None):
        """Append (or insert) a workflow-style node to a track or master chain."""
        from ..workflow import model as workflow_model
        clean = workflow_model.normalize_node(node)
        if node.get('sidechain'):
            clean['sidechain'] = str(node['sidechain'])
        if node.get('_description') is not None:
            clean['_description'] = node['_description']
        self._edit_owner('Add insert', owner)
        if index is None or index >= len(owner.inserts):
            owner.inserts.append(clean)
        else:
            owner.inserts.insert(max(0, index), clean)
        self.touch()
        return clean

    def remove_insert(self, owner, node_id):
        index = next((i for i, n in enumerate(owner.inserts) if n['id'] == node_id), None)
        if index is None:
            return False
        self._edit_owner('Remove insert', owner)
        del owner.inserts[index]
        for key in [k for k in owner.automation if k.startswith(node_id + '.')]:
            del owner.automation[key]
        if owner.automation_view.startswith(node_id + '.'):
            owner.automation_view = ''
        self.touch()
        return True

    def move_insert(self, owner, node_id, direction):
        index = next((i for i, n in enumerate(owner.inserts) if n['id'] == node_id), None)
        if index is None:
            return False
        target = index + direction
        if not 0 <= target < len(owner.inserts):
            return False
        self._edit_owner('Reorder inserts', owner)
        owner.inserts[index], owner.inserts[target] = owner.inserts[target], owner.inserts[index]
        self.touch()
        return True

    def insert_node(self, owner, node_id):
        return next((n for n in owner.inserts if n['id'] == node_id), None)

    def copy_chain(self, source):
        """Deep copy of a chain and its lanes with fresh node ids (split, duplicate)."""
        mapping = {}
        inserts = []
        for node in source.inserts:
            clone = copy.deepcopy(node)
            clone['id'] = uuid.uuid4().hex[:8]
            mapping[node['id']] = clone['id']
            inserts.append(clone)
        automation = {}
        for key, lane in source.automation.items():
            head, dot, tail = key.partition('.')
            new_key = (mapping.get(head, head) + dot + tail) if dot else key
            automation[new_key] = AutomationLane(new_key, [list(p) for p in lane.points], lane.enabled)
        return inserts, automation

    def has_stateful_inserts(self):
        from ..dsp import effects
        for owner in list(self.tracks) + [self.master]:
            for node in owner.inserts:
                if not node.get('enabled', True):
                    continue
                if node['kind'] == 'vst3':
                    return True
                spec = effects.REGISTRY.get(node.get('effect')) if node['kind'] == 'effect' else None
                if spec is not None and spec.stateful:
                    return True
        return False

    def automation_range(self, owner, key):
        """(minimum, maximum, default, kind) of a lane key, from the track or the effect parameter."""
        if key == 'gain_db':
            return -48.0, 12.0, float(owner.gain_db), 'float'
        if key == 'pan':
            return -1.0, 1.0, float(getattr(owner, 'pan', 0.0)), 'float'
        if key == 'mute':
            return 0.0, 1.0, 1.0 if owner.mute else 0.0, 'bool'
        node_id, _, param_id = key.partition('.')
        node = self.insert_node(owner, node_id)
        if node is None:
            return 0.0, 1.0, 0.0, 'float'
        if node['kind'] == 'effect':
            from ..dsp import effects
            spec = effects.REGISTRY.get(node['effect'])
            param = next((p for p in spec.params if p.id == param_id), None) if spec else None
            if param is not None:
                current = node.get('params', {}).get(param_id, param.default)
                if param.kind == 'bool':
                    return 0.0, 1.0, 1.0 if current else 0.0, 'bool'
                if param.kind in ('float', 'int'):
                    lo = param.minimum if param.minimum is not None else -100.0
                    hi = param.maximum if param.maximum is not None else 100.0
                    return float(lo), float(hi), float(current), param.kind
        elif node['kind'] == 'vst3':
            description = node.get('_description') or {}
            info = description.get('parameters', {}).get(param_id, {})
            current = node.get('params', {}).get(param_id, info.get('value', 0.0))
            try:
                return float(info.get('minimum', 0.0)), float(info.get('maximum', 1.0)), float(current), 'float'
            except (TypeError, ValueError):
                return 0.0, 1.0, 0.0, 'float'
        return 0.0, 1.0, 0.0, 'float'

    def automatable_keys(self, owner):
        """Lane keys offered for an owner: volume, pan, mute and every automatable insert parameter."""
        keys = [('gain_db', 'Volume'), ('mute', 'Mute')] if owner is self.master else [('gain_db', 'Volume'), ('pan', 'Pan'), ('mute', 'Mute')]
        from ..dsp import effects
        for node in owner.inserts:
            if node['kind'] == 'effect':
                spec = effects.REGISTRY.get(node['effect'])
                if spec is None:
                    continue
                for param in spec.params:
                    if param.automatable and param.kind in ('float', 'int', 'bool'):
                        keys.append((node['id'] + '.' + param.id, spec.name + ': ' + param.label))
            elif node['kind'] == 'vst3':
                description = node.get('_description') or {}
                for param_id, info in list(description.get('parameters', {}).items())[:64]:
                    if info.get('choices'):
                        continue
                    keys.append((node['id'] + '.' + param_id, (node.get('pluginName') or 'VST3') + ': ' + str(info.get('label') or param_id)))
        return keys

    def automation_add(self, owner, key, seconds, value, record=True):
        if record:
            self._edit_owner('Automation point', owner)
        lane = owner.lane(key, create=True)
        index = lane.add_point(seconds, value)
        self.touch()
        return index

    def automation_move(self, owner, key, index, seconds, value):
        lane = owner.lane(key)
        if lane is None:
            return index
        result = lane.move_point(index, seconds, value)
        self.touch()
        return result

    def automation_remove(self, owner, key, index, record=True):
        lane = owner.lane(key)
        if lane is None:
            return False
        if record:
            self._edit_owner('Remove automation point', owner)
        removed = lane.remove_point(index)
        if not lane.points:
            del owner.automation[key]
        self.touch()
        return removed

    def automation_clear(self, owner, key):
        if key in owner.automation:
            self._edit_owner('Clear automation', owner)
            del owner.automation[key]
            self.touch()

    def automation_write(self, owner, key, seconds, value):
        """Live write: replaces points around ``seconds`` (no undo entry per block)."""
        lane = owner.lane(key, create=True)
        lane.write(seconds, value)
        self.version += 1
        self.dirty = True

    # ------------------------------------------------------------------ mix
    def mix_block(self, start_frame, frames, channels=2, renderer=None):
        """Mix all audible tracks into a (channels, frames) block starting at start_frame.

        Without a renderer a throw-away one is used (inserts are then rendered from a cold state)."""
        from .renderer import Renderer
        renderer = renderer or Renderer(self)
        return renderer.render(start_frame, frames, channels)

    def _fade_gain(self, track, local_a, local_b):
        """Fade envelope for frames [local_a, local_b) of a clip, or None when there is no fade."""
        if track.fade_in <= 0 and track.fade_out <= 0:
            return None
        count = local_b - local_a
        if count <= 0:
            return None
        index = np.arange(local_a, local_b, dtype=np.float32)
        gain = np.ones(count, np.float32)
        fade_in = self.seconds_to_frame(track.fade_in)
        fade_out = self.seconds_to_frame(track.fade_out)
        if fade_in > 0:
            gain *= np.clip(index / fade_in, 0.0, 1.0)
        if fade_out > 0:
            gain *= np.clip((track.frames - index) / fade_out, 0.0, 1.0)
        return gain

    def mixdown(self, start_seconds=None, stop_seconds=None, channels=2, tail=None, progress=None):
        """Offline render through a fresh renderer; stateful inserts ring out after the end (tail)."""
        from .renderer import Renderer
        start = 0 if start_seconds is None else self.seconds_to_frame(start_seconds)
        stop = self.frames if stop_seconds is None else self.seconds_to_frame(stop_seconds)
        if stop <= start:
            return np.zeros((channels, 0), np.float32)
        return Renderer(self).render_range(start, stop, channels, tail=tail, progress=progress)

    # ------------------------------------------------------------------ sessions
    def save_session(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        index = {'format': 'cytools-audiostudio-session', 'schemaVersion': SESSION_SCHEMA, 'name': folder.name, 'samplerate': self.samplerate, 'savedAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
                 'cursor': self.cursor, 'selection': list(self.selection) if self.selection else None, 'tracks': [],
                 'master': self.master.to_dict(), 'tail': dict(self.tail)}
        keep = set()
        for order, track in enumerate(self.tracks):
            file = f'{order:02d}-{track.id}.wav'
            audio_io.save(folder / file, track.audio, self.samplerate, fmt='wav', subtype='FLOAT')  # complete material
            keep.add(file)
            index['tracks'].append({'id': track.id, 'name': track.name, 'file': file, 'offset': track.offset, 'gain_db': track.gain_db, 'pan': track.pan,
                                    'mute': track.mute, 'solo': track.solo, 'colour': list(track.colour), 'source': track.source, 'height': track.height,
                                    'start': track.start, 'length': track.length, 'fadeIn': track.fade_in, 'fadeOut': track.fade_out,
                                    'inserts': [{k: v for k, v in n.items() if not k.startswith('_')} for n in track.inserts],
                                    'automation': {k: lane.to_dict() for k, lane in track.automation.items()}, 'automationView': track.automation_view})
        for stale in folder.glob('*.wav'):
            if stale.name not in keep:
                stale.unlink()
        (folder / 'session.json').write_text(json.dumps(index, indent=2, ensure_ascii=False), 'utf-8')
        self.name, self.path, self.dirty = folder.name, folder, False
        return folder / 'session.json'

    @classmethod
    def load_session(cls, folder):
        folder = Path(folder)
        if folder.is_file():
            folder = folder.parent
        index = json.loads((folder / 'session.json').read_text('utf-8-sig'))
        if index.get('format') != 'cytools-audiostudio-session':
            raise ValueError('Not an AudioStudio session')
        document = cls(index.get('samplerate', 48000))
        for item in index.get('tracks', []):
            audio, rate = audio_io.load(folder / item['file'])
            track = Track(item.get('id', uuid.uuid4().hex[:8]), item.get('name', 'Track'), audio, int(item.get('offset', 0)), float(item.get('gain_db', 0.0)),
                          float(item.get('pan', 0.0)), bool(item.get('mute', False)), bool(item.get('solo', False)), tuple(item.get('colour', COLOURS[0])),
                          item.get('source', ''), float(item.get('height', 110.0)), int(item.get('start', 0)), int(item.get('length', -1)),
                          float(item.get('fadeIn', 0.0)), float(item.get('fadeOut', 0.0)))
            if rate != document.samplerate:
                track.audio = audio_io.resample(track.audio, rate, document.samplerate)
            track.inserts = _load_inserts(item.get('inserts'))
            track.automation = _load_automation(item.get('automation'))
            track.automation_view = str(item.get('automationView', '') or '')
            document.tracks.append(track)
        document.master = MasterBus.from_dict(index.get('master'))
        tail = index.get('tail') or {}
        document.tail = {**DEFAULT_TAIL, **{k: tail[k] for k in DEFAULT_TAIL if k in tail}}
        document.cursor = float(index.get('cursor', 0.0))
        document.selection = tuple(index['selection']) if index.get('selection') else None
        document.name, document.path, document.dirty = folder.name, folder, False
        return document
