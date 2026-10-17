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

SESSION_SCHEMA = 3          # 3: tracks hold a list of clips; 2 (one clip per track) still loads
DEFAULT_TAIL = {'enabled': True, 'threshold_db': -60.0, 'max_seconds': 10.0, 'hold_seconds': 0.1}

MAX_UNDO = 64
COLOURS = [(0.36, 0.72, 0.95), (0.98, 0.62, 0.2), (0.55, 0.85, 0.5), (0.9, 0.5, 0.8), (0.95, 0.85, 0.35), (0.6, 0.7, 1.0)]


def db_to_gain(db):
    return float(10.0 ** (float(db) / 20.0))


def _new_id():
    return uuid.uuid4().hex[:8]


def _as_audio(audio):
    """(channels, frames) float32, at most two channels."""
    audio = np.ascontiguousarray(np.asarray(audio, dtype=np.float32))
    if audio.ndim == 1:
        audio = audio[np.newaxis, :]
    return audio[:2] if audio.shape[0] > 2 else audio


@dataclass(eq=False)
class Clip:
    """A piece of audio placed on a track.

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
    start: int = 0                          # in-point inside audio
    length: int = -1                        # visible frames; -1 = to the end of audio
    fade_in: float = 0.0                    # seconds
    fade_out: float = 0.0                   # seconds
    source: str = ''
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

    def copy(self, new_id=False):
        return Clip(_new_id() if new_id else self.id, self.name, self.audio.copy(), self.offset, self.start, self.length,
                    self.fade_in, self.fade_out, self.source)

    def to_dict(self, file):
        return {'id': self.id, 'name': self.name, 'file': file, 'offset': self.offset, 'start': self.start, 'length': self.length,
                'fadeIn': self.fade_in, 'fadeOut': self.fade_out, 'source': self.source}


def _first_clip(attribute, default):
    """Attribute of the first clip: what a track was when it held a single clip."""
    def get(self):
        return getattr(self.clips[0], attribute) if self.clips else default

    def put(self, value):
        if self.clips:
            setattr(self.clips[0], attribute, value)
    return property(get, put)


class Track:
    """A lane of the timeline: mixer settings, insert chain, automation and any number of clips.

    Every clip of a track goes through the track's inserts, so moving a clip to another track
    gives it that track's effects. Clips may overlap; they are summed. ``offset`` / ``end`` /
    ``frames`` describe the span of all the clips; ``audio``, ``start``, ``length``, ``fade_in``,
    ``fade_out`` and ``source`` read and write the first clip (a track used to be one clip).
    """

    def __init__(self, id, name, audio=None, offset=0, gain_db=0.0, pan=0.0, mute=False, solo=False, colour=COLOURS[0], source='',
                 height=110.0, start=0, length=-1, fade_in=0.0, fade_out=0.0, inserts=None, automation=None, automation_view='', clips=None):
        self.id, self.name = id, name
        self.gain_db, self.pan, self.mute, self.solo = float(gain_db), float(pan), bool(mute), bool(solo)
        self.colour, self.height = tuple(colour), float(height)
        self.inserts = list(inserts or [])                   # insert chain: workflow-style nodes (effect / vst3)
        self.automation = dict(automation or {})             # key -> AutomationLane
        self.automation_view = automation_view               # lane shown in the timeline ('' = none)
        self.empty_channels = 2                              # channels of a track without clip
        self.clips = list(clips or [])
        if clips is None and audio is not None:
            audio = _as_audio(audio)
            self.empty_channels = int(audio.shape[0])
            if audio.shape[1]:
                self.clips.append(Clip(_new_id(), name, audio, int(offset), int(start), int(length), float(fade_in), float(fade_out), str(source)))
        self.sort()

    def __repr__(self):
        return f'Track({self.id!r}, {self.name!r}, clips={len(self.clips)})'

    # ------------------------------------------------------------------ clips
    def sort(self):
        self.clips.sort(key=lambda clip: clip.offset)

    @property
    def primary(self):
        return self.clips[0] if self.clips else None

    def clip(self, clip_id):
        return next((c for c in self.clips if c.id == clip_id), None)

    def clips_in(self, start_frame, stop_frame):
        """Clips that overlap document frames [start_frame, stop_frame)."""
        return [c for c in self.clips if c.end > start_frame and c.offset < stop_frame]

    def clip_at(self, frame, inside=False):
        """The clip under a document frame (the one starting last when they overlap)."""
        found = None
        for clip in self.clips:
            if (clip.offset < frame < clip.end) if inside else (clip.offset <= frame < clip.end):
                found = clip
        return found

    def set_audio(self, audio, offset=0, source='', name=None):
        """Replace every clip by one clip of ``audio`` at ``offset`` (frames)."""
        audio = _as_audio(audio)
        self.clips = [Clip(_new_id(), name or self.name, audio, max(0, int(offset)), source=str(source))] if audio.shape[1] else []
        if not audio.shape[1]:
            self.empty_channels = int(audio.shape[0])

    @property
    def offset(self):
        return min((c.offset for c in self.clips), default=0)

    @offset.setter
    def offset(self, value):
        """Moving a track moves all its clips together."""
        delta = int(value) - self.offset
        for clip in self.clips:
            clip.offset += delta

    @property
    def end(self):
        return max((c.end for c in self.clips), default=0)

    @property
    def frames(self):
        """Span from the first clip start to the last clip end."""
        return self.end - self.offset if self.clips else 0

    @property
    def channels(self):
        return max((c.channels for c in self.clips), default=self.empty_channels)

    @property
    def total_frames(self):
        return self.clips[0].total_frames if self.clips else 0

    @property
    def audio(self):
        return self.clips[0].audio if self.clips else np.zeros((self.empty_channels, 0), np.float32)

    @audio.setter
    def audio(self, value):
        if self.clips:
            self.clips[0].audio = _as_audio(value)
            self.clips[0].invalidate()
        else:
            self.set_audio(value)

    start = _first_clip('start', 0)
    length = _first_clip('length', -1)
    fade_in = _first_clip('fade_in', 0.0)
    fade_out = _first_clip('fade_out', 0.0)
    source = _first_clip('source', '')

    def mix_raw(self, start_frame, stop_frame, channels=None):
        """Clips summed over document frames [start_frame, stop_frame), gaps silent, without fades."""
        channels = channels or self.channels
        out = np.zeros((channels, max(0, stop_frame - start_frame)), np.float32)
        for clip in self.clips:
            a, b = max(start_frame, clip.offset), min(stop_frame, clip.end)
            if b <= a:
                continue
            block = clip.view()[:, a - clip.offset:b - clip.offset]
            if block.shape[0] != channels:
                block = np.repeat(np.mean(block, axis=0, keepdims=True), channels, axis=0)
            out[:, a - start_frame:b - start_frame] += block
        return out

    def view(self):
        """The visible samples of the track: its clip, or its clips summed over their span."""
        if len(self.clips) == 1:
            return self.clips[0].view()
        return self.mix_raw(self.offset, self.end)

    def flatten(self):
        for clip in self.clips:
            clip.flatten()
        return self

    def peaks(self):
        return self.clips[0].peaks() if self.clips else Peaks(np.zeros((self.empty_channels, 0), np.float32))

    def invalidate(self):
        for clip in self.clips:
            clip.invalidate()

    # ------------------------------------------------------------------ undo
    def snapshot(self):
        return {'clips': [c.copy() for c in self.clips], 'gain_db': self.gain_db, 'pan': self.pan, 'mute': self.mute, 'solo': self.solo,
                'name': self.name, 'empty_channels': self.empty_channels,
                'inserts': copy.deepcopy([n for n in self.inserts if not n.get('_preview')]), 'automation': {k: lane.copy() for k, lane in self.automation.items()}}

    def restore(self, state):
        self.clips = [Clip(c.id, c.name, c.audio, c.offset, c.start, c.length, c.fade_in, c.fade_out, c.source) for c in state['clips']]
        self.gain_db, self.pan, self.mute, self.solo, self.name = state['gain_db'], state['pan'], state['mute'], state['solo'], state['name']
        self.empty_channels = state.get('empty_channels', 2)
        self.inserts = copy.deepcopy(state.get('inserts', []))
        self.automation = {k: lane.copy() for k, lane in state.get('automation', {}).items()}

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
        audio = _as_audio(audio)
        if samplerate and int(samplerate) != self.samplerate:
            if not self.tracks:
                self.samplerate = int(samplerate)
            else:
                audio = audio_io.resample(audio, int(samplerate), self.samplerate)
        if record:
            self.edit('Add track ' + name, structural=True)
        track = Track(_new_id(), name, audio, self.seconds_to_frame(offset_seconds), colour=COLOURS[len(self.tracks) % len(COLOURS)], source=source)
        self.tracks.append(track)
        self.selected_track = len(self.tracks) - 1
        self.touch()
        return track

    def add_empty_track(self, name=None, channels=2):
        """A track without audio yet: for inserts, recording, dropped or generated sounds."""
        name = name or 'Track %d' % (len(self.tracks) + 1)
        return self.add_track(np.zeros((channels, 0), np.float32), name)

    def _conform(self, audio, samplerate):
        audio = _as_audio(audio)
        if samplerate and int(samplerate) != self.samplerate:
            audio = audio_io.resample(audio, int(samplerate), self.samplerate)
        return audio

    def fill_track(self, track, audio, samplerate, offset_seconds=0.0, source=''):
        """Put audio in a track (an empty one, typically) while keeping its inserts and automation."""
        audio = self._conform(audio, samplerate)
        self.edit('Fill track', [track.id])
        track.set_audio(audio, max(0, self.seconds_to_frame(offset_seconds)), source)
        self.touch()
        return track

    def free_position(self, track, frame, frames):
        """``frame`` when [frame, frame + frames) is free on the track, otherwise the end of its last clip."""
        return frame if not track.clips_in(frame, frame + max(1, frames)) else track.end

    def add_clip(self, track, audio, samplerate=None, offset_seconds=None, name='', source='', after_clips=True, record=True):
        """A new clip on an existing track. With ``after_clips`` a position already taken by a clip
        moves the new one after the last clip of the track; the clip goes through the track inserts."""
        audio = self._conform(audio, samplerate)
        frame = max(0, self.seconds_to_frame(self.cursor if offset_seconds is None else offset_seconds))
        if after_clips:
            frame = self.free_position(track, frame, audio.shape[1])
        if record:
            self.edit('Add clip ' + (name or track.name), [track.id])
        clip = Clip(_new_id(), name or track.name, audio, frame, source=str(source))
        track.clips.append(clip)
        track.sort()
        self.selected_track = self.tracks.index(track) if track in self.tracks else self.selected_track
        self.touch()
        return clip

    def import_clip(self, track, path, offset_seconds=None, after_clips=True):
        audio, rate = audio_io.load(path)
        return self.add_clip(track, audio, rate, offset_seconds, name=Path(path).stem, source=str(path), after_clips=after_clips)

    def remove_clip(self, track, clip, record=True):
        if clip not in track.clips:
            return False
        if record:
            self.edit('Delete clip ' + clip.name, [track.id])
        track.clips.remove(clip)
        self.touch()
        return True

    def duplicate_clip(self, track, clip):
        """A copy of the clip right after it on the same track."""
        self.edit('Duplicate clip ' + clip.name, [track.id])
        twin = clip.copy(new_id=True)
        twin.offset = clip.end
        track.clips.append(twin)
        track.sort()
        self.touch()
        return twin

    def reverse_clip(self, track, clip, record=True):
        """Play the clip backwards. The whole material is reversed and the window mirrored, so trimmed
        audio is kept and reversing again gives the original back; fades stay where they are."""
        if clip not in track.clips:
            return None
        if record:
            self.edit('Reverse clip ' + clip.name, [track.id])
        frames = clip.frames
        clip.audio = np.ascontiguousarray(clip.audio[:, ::-1])
        clip.start = clip.total_frames - clip.start - frames
        if clip.length >= 0 or clip.start:
            clip.length = frames
        clip.invalidate()
        self.touch()
        return clip

    def move_clip(self, source, clip, target, offset_seconds=None, record=True):
        """Move a clip in time and/or to another track (it then goes through that track's inserts).

        With ``record=False`` the move belongs to the last undo entry, which the caller opened on the
        source track: the target track is added to it before it changes."""
        if clip not in source.clips:
            return None
        ids = [source.id] + ([target.id] if target is not source else [])
        if record:
            self.edit('Move clip', ids)
        elif self.undo_stack:
            entry = self.undo_stack[-1]
            for tid in ids:
                if tid not in entry['tracks'] and self.track(tid) is not None:
                    entry['tracks'][tid] = self.track(tid).snapshot()
        if offset_seconds is not None:
            clip.offset = max(0, self.seconds_to_frame(offset_seconds))
        if target is not source:
            source.clips.remove(clip)
            target.clips.append(clip)
            self.selected_track = self.tracks.index(target)
        source.sort()
        target.sort()
        self.touch()
        return clip

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

    def _region(self, clip, start_frame, stop_frame):
        """Clamp a document frame range to a clip (or a single-clip track) and return local (a, b)."""
        a = max(0, start_frame - clip.offset)
        b = min(clip.frames, stop_frame - clip.offset)
        return a, max(a, b)

    def _replace(self, clip, a, b, block):
        """Replace local frames [a, b) of a clip with ``block`` (may change the length)."""
        if block.shape[0] != clip.channels:
            block = np.repeat(np.mean(block, axis=0, keepdims=True), clip.channels, axis=0) if block.shape[0] != 1 else np.repeat(block, clip.channels, axis=0)
        clip.audio = np.ascontiguousarray(np.concatenate([clip.audio[:, :a], block.astype(np.float32), clip.audio[:, b:]], axis=1))
        clip.invalidate()

    def _clamp_fades(self, clip):
        length = self.frame_to_seconds(clip.frames)
        clip.fade_in = min(clip.fade_in, length)
        clip.fade_out = min(clip.fade_out, max(0.0, length - clip.fade_in))

    def targets(self, all_tracks=False):
        if all_tracks:
            return list(self.tracks)
        track = self.current_track()
        return [track] if track is not None else []

    # ------------------------------------------------------------------ editing
    def delete(self, all_tracks=False):
        """Remove the selection; what follows on the track moves back (ripple)."""
        if not self.selection:
            return False
        start, stop = self.selection_frames()
        tracks = self.targets(all_tracks)
        self.edit('Delete', [t.id for t in tracks])
        removed = stop - start
        for track in tracks:
            for clip in list(track.clips):
                if clip.offset >= stop:
                    clip.offset -= removed
                    continue
                if clip.end <= start:
                    continue
                clip.flatten()
                a, b = self._region(clip, start, stop)
                self._replace(clip, a, b, clip.audio[:, :0])
                clip.offset = min(clip.offset, start)
                self._clamp_fades(clip)
                if clip.frames == 0:
                    track.clips.remove(clip)
            track.sort()
        self.cursor = self.frame_to_seconds(start)
        self.selection = None
        return True

    def silence(self, all_tracks=False):
        if not self.selection:
            return False
        start, stop = self.selection_frames()
        tracks = self.targets(all_tracks)
        self.edit('Silence', [t.id for t in tracks])
        for track in tracks:
            for clip in track.clips_in(start, stop):
                clip.flatten()
                a, b = self._region(clip, start, stop)
                clip.audio[:, a:b] = 0.0
                clip.invalidate()
        return True

    def trim(self, all_tracks=False):
        """Keep only the selection."""
        if not self.selection:
            return False
        start, stop = self.selection_frames()
        tracks = self.targets(all_tracks)
        self.edit('Trim', [t.id for t in tracks])
        for track in tracks:
            for clip in list(track.clips):
                clip.flatten()
                a, b = self._region(clip, start, stop)
                if b <= a:
                    track.clips.remove(clip)
                    continue
                clip.audio = np.ascontiguousarray(clip.audio[:, a:b])
                clip.offset = max(clip.offset, start)
                clip.invalidate()
                self._clamp_fades(clip)
        return True

    def copy(self):
        track = self.current_track()
        if track is None or not self.selection:
            return False
        start, stop = self.selection_frames()
        a, b = max(start, track.offset), min(stop, track.end)
        if b <= a or not track.clips_in(start, stop):
            return False
        self.clipboard = (track.mix_raw(a, b), self.samplerate)
        return True

    def cut(self):
        if self.copy():
            return self.delete()
        return False

    def paste(self, insert=True):
        """Insert the clipboard at the selection start or the cursor (what follows moves later), or
        replace (``insert=False``) the selection / the audio under the cursor. Outside every clip the
        clipboard becomes a new clip."""
        track = self.current_track()
        if self.clipboard is None:
            return False
        block, rate = self.clipboard
        if rate != self.samplerate:
            block = audio_io.resample(block, rate, self.samplerate)
        if track is None:
            self.add_track(block, 'Pasted', offset_seconds=self.cursor)
            return True
        count = block.shape[1]
        position = self.seconds_to_frame(self.selection[0] if self.selection else self.cursor)
        self.edit('Paste', [track.id])
        clip = track.clip_at(position) or next((c for c in track.clips if c.end == position), None)
        if clip is not None:
            clip.flatten()
            a = position - clip.offset
            if insert:
                b = a
            elif self.selection:
                b = self._region(clip, *self.selection_frames())[1]
            else:
                b = min(clip.frames, a + count)
            change = count - (b - a)
            self._replace(clip, a, b, block)
            if change:
                for other in track.clips:
                    if other is not clip and other.offset >= position:
                        other.offset += change
        else:
            if insert:
                for other in track.clips:
                    if other.offset >= position:
                        other.offset += count
            track.clips.append(Clip(_new_id(), track.name, _as_audio(block), position))
        track.sort()
        self.selection = (self.frame_to_seconds(position), self.frame_to_seconds(position + count))
        return True

    def insert_silence(self, seconds, all_tracks=False):
        position = self.seconds_to_frame(self.cursor)
        count = self.seconds_to_frame(seconds)
        tracks = self.targets(all_tracks)
        self.edit('Insert silence', [t.id for t in tracks])
        for track in tracks:
            for clip in track.clips:
                if position <= clip.offset:
                    clip.offset += count
                elif position < clip.end:
                    clip.flatten()
                    a = position - clip.offset
                    self._replace(clip, a, a, np.zeros((clip.channels, count), np.float32))
        return True

    def split(self):
        """Cut the clip under the cursor in two clips of the same track (audio is not rewritten)."""
        track = self.current_track()
        if track is None:
            return False
        position = self.seconds_to_frame(self.cursor)
        clip = track.clip_at(position, inside=True)
        if clip is None:
            return False
        self.edit('Split', [track.id])
        local = position - clip.offset
        right = Clip(_new_id(), clip.name + ' (2)', clip.audio, position, clip.start + local, clip.frames - local,
                     0.0, clip.fade_out, clip.source)
        clip.length = local
        clip.fade_out = 0.0
        self._clamp_fades(clip)
        self._clamp_fades(right)
        track.clips.append(right)
        track.sort()
        self.touch()
        return True

    def resize_clip(self, track, edge, seconds, record=True, clip=None):
        """Move one edge of a clip (the first one of the track by default). Audio outside the clip
        is kept and can be dragged back."""
        clip = clip or track.primary
        if clip is None:
            return track
        frame = self.seconds_to_frame(seconds)
        if record:
            self.edit('Resize clip', [track.id])
        if edge == 'left':
            frame = max(0, frame)
            delta = frame - clip.offset
            delta = max(-clip.start, min(delta, clip.frames - 1))
            clip.start += delta
            if clip.length >= 0:
                clip.length = max(1, clip.length - delta)
            else:
                clip.length = max(1, clip.total_frames - clip.start)
            clip.offset = max(0, clip.offset + delta)
        else:
            length = max(1, min(frame - clip.offset, clip.total_frames - clip.start))
            clip.length = int(length)
        clip.fade_in = min(clip.fade_in, self.frame_to_seconds(clip.frames))
        clip.fade_out = min(clip.fade_out, self.frame_to_seconds(clip.frames))
        track.sort()
        self.touch()
        return track

    def set_fade(self, track, side, seconds, record=True, clip=None):
        """Fade in/out length of a clip (the first one of the track by default), in seconds (0 removes it)."""
        clip = clip or track.primary
        if clip is None:
            return track
        if record:
            self.edit('Fade ' + side, [track.id])
        length = self.frame_to_seconds(clip.frames)
        value = float(max(0.0, min(seconds, length)))
        if side == 'in':
            clip.fade_in = min(value, length - clip.fade_out)
        else:
            clip.fade_out = min(value, length - clip.fade_in)
        self.touch()
        return track

    def set_offset(self, track, seconds, clip=None):
        """Move a clip, or every clip of the track together."""
        self.edit('Move clip' if clip is not None else 'Move track', [track.id])
        if clip is not None:
            clip.offset = max(0, self.seconds_to_frame(seconds))
            track.sort()
        else:
            track.offset = max(0, self.seconds_to_frame(seconds))
        self.touch()

    def write_result(self, clip, a, b, result):
        """Put a processed region back into a clip. A longer result (tail) is mixed over the audio that
        follows the region and extends the clip when it runs past its end; a shorter one shrinks it."""
        result = np.asarray(result, dtype=np.float32)
        if result.ndim == 1:
            result = result[np.newaxis, :]
        if result.shape[0] != clip.channels:
            result = np.repeat(np.mean(result, axis=0, keepdims=True), clip.channels, axis=0)
        extra = result.shape[1] - (b - a)
        if extra > 0:
            after = clip.audio[:, b:].copy()
            overlap = min(extra, after.shape[1])
            after[:, :overlap] += result[:, b - a:b - a + overlap]
            remainder = result[:, b - a + overlap:]
            clip.audio = np.ascontiguousarray(np.concatenate([clip.audio[:, :a], result[:, :b - a], after, remainder], axis=1))
            clip.invalidate()
        else:
            self._replace(clip, a, b, result)
        self._clamp_fades(clip)

    def apply(self, label, function, all_tracks=False, whole_track=False):
        """Apply ``function(audio, samplerate) -> audio`` to the selected part of every clip (or to
        whole clips). A longer result overlaps the following audio (tail), a shorter one shrinks the region."""
        tracks = self.targets(all_tracks)
        if not tracks:
            return False
        self.edit(label, [t.id for t in tracks])
        for track in tracks:
            region = self.selection_frames() if (self.selection and not whole_track) else None
            for clip in (track.clips_in(*region) if region else list(track.clips)):
                clip.flatten()
                a, b = self._region(clip, *region) if region else (0, clip.frames)
                if b <= a:
                    continue
                self.write_result(clip, a, b, function(np.ascontiguousarray(clip.audio[:, a:b]), self.samplerate))
        return True

    def apply_to_clip(self, label, track, clip, a, b, result):
        """Write an already rendered region (local frames [a, b) of the clip as it is shown) back."""
        if clip not in track.clips:
            return False
        self.edit(label, [track.id])
        clip.flatten()
        self.write_result(clip, a, min(b, clip.frames), result)
        self.touch()
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

    def reorder_insert(self, owner, node_id, index):
        """Move an insert to a position of its chain (drag and drop)."""
        current = next((i for i, n in enumerate(owner.inserts) if n['id'] == node_id), None)
        if current is None:
            return False
        index = max(0, min(int(index), len(owner.inserts) - 1))
        if index == current:
            return False
        self._edit_owner('Reorder inserts', owner)
        node = owner.inserts.pop(current)
        owner.inserts.insert(index, node)
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
                if not node.get('enabled', True) or node.get('_preview'):
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

    def _fade_gain(self, clip, local_a, local_b):
        """Fade envelope for frames [local_a, local_b) of a clip, or None when there is no fade."""
        if clip.fade_in <= 0 and clip.fade_out <= 0:
            return None
        count = local_b - local_a
        if count <= 0:
            return None
        index = np.arange(local_a, local_b, dtype=np.float32)
        gain = np.ones(count, np.float32)
        fade_in = self.seconds_to_frame(clip.fade_in)
        fade_out = self.seconds_to_frame(clip.fade_out)
        if fade_in > 0:
            gain *= np.clip(index / fade_in, 0.0, 1.0)
        if fade_out > 0:
            gain *= np.clip((clip.frames - index) / fade_out, 0.0, 1.0)
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
            clips = []
            for number, clip in enumerate(track.clips):
                file = f'{order:02d}-{track.id}-{number:02d}.wav'
                audio_io.save(folder / file, clip.audio, self.samplerate, fmt='wav', subtype='FLOAT')  # complete material
                keep.add(file)
                clips.append(clip.to_dict(file))
            index['tracks'].append({'id': track.id, 'name': track.name, 'clips': clips, 'channels': track.channels, 'gain_db': track.gain_db, 'pan': track.pan,
                                    'mute': track.mute, 'solo': track.solo, 'colour': list(track.colour), 'height': track.height,
                                    'inserts': [{k: v for k, v in n.items() if not k.startswith('_')} for n in track.inserts if not n.get('_preview')],
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
            # schema 2: one clip per track, its fields on the track; schema 3: a list of clips
            clip_items = item.get('clips') if 'clips' in item else ([dict(item, id=uuid.uuid4().hex[:8])] if item.get('file') else [])
            clips = []
            for entry in clip_items:
                audio, rate = audio_io.load(folder / entry['file'])
                if rate != document.samplerate:
                    audio = audio_io.resample(audio, rate, document.samplerate)
                clips.append(Clip(entry.get('id') or _new_id(), entry.get('name', item.get('name', 'Track')), _as_audio(audio), int(entry.get('offset', 0)),
                                  int(entry.get('start', 0)), int(entry.get('length', -1)), float(entry.get('fadeIn', 0.0)), float(entry.get('fadeOut', 0.0)),
                                  entry.get('source', '')))
            track = Track(item.get('id', _new_id()), item.get('name', 'Track'), gain_db=float(item.get('gain_db', 0.0)), pan=float(item.get('pan', 0.0)),
                          mute=bool(item.get('mute', False)), solo=bool(item.get('solo', False)), colour=tuple(item.get('colour', COLOURS[0])),
                          height=float(item.get('height', 110.0)), clips=clips)
            track.empty_channels = int(item.get('channels', 2))
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
