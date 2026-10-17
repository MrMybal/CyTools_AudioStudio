"""Headless session scripting for the CLI and MCP: edit a saved session with a list of actions and
run a "slot" batch (the same project rendered once per input sound).

Actions (``apply_actions``), each a dict with an ``action`` key:
  add_track      file, name?, offset_seconds?, gain_db?, pan?, mute?, solo?, inserts_from? (track whose chain
                 and lanes are copied), workflow_name? / nodes? (chain to install)
  replace_audio  track, file, offset_seconds?     every clip of the track is replaced by the file; keeps the
                 track's chain, lanes, gain, pan
  remove_track   track
  add_clip       track, file, name?, offset_seconds?, after_clips? (default true: a position already taken
                 by a clip moves the new one after the last clip of the track)
  move_clip      track, clip, to_track?, offset_seconds?   the clip then goes through the inserts of to_track
  remove_clip    track, clip
  reverse_clip   track, clip                     the clip plays backwards (again = original)
  set_track      track, name?, offset_seconds?, gain_db?, pan?, mute?, solo?
  set_inserts    target (track name/id or 'master'), workflow_name? / nodes? (empty = clear)
  set_master     gain_db?, mute?
  clear_automation  target, key? (all lanes when omitted)
  set_tail       enabled?, threshold_db?, max_seconds?, hold_seconds?
Tracks are addressed by id or by exact name (first match); clips by id, exact name or index ("0" = the
earliest clip of the track, "-1" = the last). Every action is validated before it is
applied and reported back with what it did.
"""
from pathlib import Path
import time

from .document import Document
from .. import audio_io


class BatchError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def find_track(document, key):
    key = str(key)
    track = document.track(key)
    if track is None:
        track = next((t for t in document.tracks if t.name == key), None)
    if track is None:
        raise BatchError('MissingInput', 'No track named or identified "%s" (tracks: %s)' % (key, ', '.join(t.name for t in document.tracks) or 'none'))
    return track


def find_clip(track, key):
    key = str(key)
    clip = track.clip(key) or next((c for c in track.clips if c.name == key), None)
    if clip is None and key.lstrip('-').isdigit() and -len(track.clips) <= int(key) < len(track.clips):
        clip = track.clips[int(key)]
    if clip is None:
        raise BatchError('MissingInput', 'Track "%s" has no clip "%s" (clips: %s)' % (track.name, key, ', '.join(c.name for c in track.clips) or 'none'))
    return clip


def _clip_report(document, track, clip):
    return {'track': track.id, 'clip': clip.id, 'name': clip.name, 'offsetSeconds': document.frame_to_seconds(clip.offset),
            'durationSeconds': document.frame_to_seconds(clip.frames)}


def _owner(document, key):
    if str(key) == 'master':
        return document.master
    return find_track(document, key)


def _chain_nodes(action, load_workflow):
    """Insert nodes from an inline list or a saved workflow name."""
    if action.get('nodes') is not None:
        return [dict(n) for n in action['nodes']]
    name = action.get('workflow_name')
    if name:
        if load_workflow is None:
            raise BatchError('InvalidParameters', 'workflow_name needs a workflow loader')
        return [dict(n) for n in load_workflow(name).get('nodes', []) if n.get('kind') != 'model']
    return None


def _install_chain(document, owner, nodes):
    owner.inserts = []
    for node in nodes:
        document.add_insert(owner, node)


def _apply_track_fields(document, track, action):
    changed = {}
    for key in ('gain_db', 'pan'):
        if key in action and action[key] is not None:
            setattr(track, key, float(action[key]))
            changed[key] = float(action[key])
    for key in ('mute', 'solo'):
        if key in action and action[key] is not None:
            setattr(track, key, bool(action[key]))
            changed[key] = bool(action[key])
    if action.get('name'):
        track.name = str(action['name'])
        changed['name'] = track.name
    if action.get('offset_seconds') is not None:
        track.offset = max(0, document.seconds_to_frame(float(action['offset_seconds'])))
        changed['offset_seconds'] = float(action['offset_seconds'])
    return changed


def apply_actions(document, actions, load_workflow=None):
    """Apply the actions in order; returns one report per action."""
    reports = []
    for index, action in enumerate(actions or []):
        if not isinstance(action, dict) or not action.get('action'):
            raise BatchError('InvalidParameters', 'actions[%d] must be an object with an "action" key' % index)
        kind = str(action['action'])
        report = {'index': index, 'action': kind}
        if kind == 'add_track':
            file = action.get('file')
            if not file or not Path(str(file)).is_file():
                raise BatchError('MissingInput', 'add_track: file not found: %s' % file)
            track = document.import_file(str(file), offset_seconds=float(action.get('offset_seconds', 0.0) or 0.0), name=action.get('name'))
            source = action.get('inserts_from')
            if source:
                track.inserts, track.automation = document.copy_chain(find_track(document, source))
            nodes = _chain_nodes(action, load_workflow)
            if nodes is not None:
                _install_chain(document, track, nodes)
            report.update(_apply_track_fields(document, track, {k: v for k, v in action.items() if k not in ('name', 'offset_seconds')}))
            report.update({'track': track.id, 'name': track.name, 'frames': track.frames, 'inserts': len(track.inserts)})
        elif kind == 'replace_audio':
            track = find_track(document, action.get('track'))
            file = action.get('file')
            if not file or not Path(str(file)).is_file():
                raise BatchError('MissingInput', 'replace_audio: file not found: %s' % file)
            audio, rate = audio_io.load(str(file))
            if rate != document.samplerate:
                audio = audio_io.resample(audio, rate, document.samplerate)
            document.edit('Replace audio', [track.id])
            track.set_audio(audio, track.offset, str(file), name=Path(str(file)).stem)      # every clip of the slot is replaced
            if action.get('offset_seconds') is not None:
                track.offset = max(0, document.seconds_to_frame(float(action['offset_seconds'])))
            document.touch()
            report.update({'track': track.id, 'name': track.name, 'frames': track.frames})
        elif kind == 'add_clip':
            track = find_track(document, action.get('track'))
            file = action.get('file')
            if not file or not Path(str(file)).is_file():
                raise BatchError('MissingInput', 'add_clip: file not found: %s' % file)
            offset = action.get('offset_seconds')
            clip = document.import_clip(track, str(file), offset_seconds=float(offset) if offset is not None else None,
                                        after_clips=bool(action.get('after_clips', True)))
            if action.get('name'):
                clip.name = str(action['name'])
            report.update(_clip_report(document, track, clip))
        elif kind == 'move_clip':
            track = find_track(document, action.get('track'))
            clip = find_clip(track, action.get('clip'))
            target = find_track(document, action['to_track']) if action.get('to_track') else track
            offset = action.get('offset_seconds')
            document.move_clip(track, clip, target, offset_seconds=float(offset) if offset is not None else None)
            report.update(_clip_report(document, target, clip), fromTrack=track.id)
        elif kind == 'reverse_clip':
            track = find_track(document, action.get('track'))
            clip = find_clip(track, action.get('clip'))
            document.reverse_clip(track, clip)
            report.update(_clip_report(document, track, clip))
        elif kind == 'remove_clip':
            track = find_track(document, action.get('track'))
            clip = find_clip(track, action.get('clip'))
            document.remove_clip(track, clip)
            report.update({'track': track.id, 'clip': clip.id, 'name': clip.name})
        elif kind == 'remove_track':
            track = find_track(document, action.get('track'))
            document.remove_track(track.id)
            report.update({'track': track.id, 'name': track.name})
        elif kind == 'set_track':
            track = find_track(document, action.get('track'))
            document.edit('Set track', [track.id])
            report.update(_apply_track_fields(document, track, action))
            report.update({'track': track.id})
        elif kind == 'set_inserts':
            owner = _owner(document, action.get('target', 'master'))
            nodes = _chain_nodes(action, load_workflow) or []
            document._edit_owner('Set inserts', owner)
            _install_chain(document, owner, nodes)
            report.update({'target': owner.id, 'inserts': [n.get('effect') or n.get('pluginName') or n['kind'] for n in owner.inserts]})
        elif kind == 'set_master':
            document.edit('Set master', [])
            if action.get('gain_db') is not None:
                document.master.gain_db = float(action['gain_db'])
            if action.get('mute') is not None:
                document.master.mute = bool(action['mute'])
            report.update({'gain_db': document.master.gain_db, 'mute': document.master.mute})
        elif kind == 'clear_automation':
            owner = _owner(document, action.get('target', 'master'))
            keys = [action['key']] if action.get('key') else list(owner.automation)
            for key in keys:
                document.automation_clear(owner, key)
            report.update({'target': owner.id, 'cleared': keys})
        elif kind == 'set_tail':
            for key in ('enabled', 'threshold_db', 'max_seconds', 'hold_seconds'):
                if action.get(key) is not None:
                    document.tail[key] = bool(action[key]) if key == 'enabled' else float(action[key])
            report.update(dict(document.tail))
        else:
            raise BatchError('InvalidParameters', 'Unknown action: ' + kind)
        reports.append(report)
    return reports


def describe(document):
    return {'samplerate': document.samplerate, 'durationSeconds': document.duration,
            'tracks': [{'id': t.id, 'name': t.name, 'offsetSeconds': document.frame_to_seconds(t.offset), 'durationSeconds': document.frame_to_seconds(t.frames),
                        'channels': t.channels, 'gain_db': t.gain_db, 'pan': t.pan, 'mute': t.mute, 'solo': t.solo,
                        'clips': [{'id': c.id, 'name': c.name, 'offsetSeconds': document.frame_to_seconds(c.offset),
                                   'durationSeconds': document.frame_to_seconds(c.frames)} for c in t.clips],
                        'inserts': [n.get('effect') or n.get('pluginName') or n['kind'] for n in t.inserts], 'automation': sorted(t.automation)} for t in document.tracks],
            'master': {'gain_db': document.master.gain_db, 'mute': document.master.mute,
                       'inserts': [n.get('effect') or n.get('pluginName') or n['kind'] for n in document.master.inserts], 'automation': sorted(document.master.automation)},
            'tail': dict(document.tail)}


def load_or_new(session, samplerate=48000):
    if session:
        source = Path(str(session))
        index = source if source.is_file() else source / 'session.json'
        if not index.is_file():
            raise BatchError('MissingInput', 'Session not found: ' + str(session))
        return Document.load_session(index)
    return Document(int(samplerate))


def batch_session(document, inputs, slot, render, progress=None, cancel=None, load_workflow=None):
    """Render the document once per input placed in the slot.

    ``slot``: track (existing placeholder whose audio is replaced, or the name of a new track),
    offset_seconds, gain_db, pan, inserts_from, workflow_name / nodes, solo (render the slot alone).
    ``render(document, stem)`` writes the mix and returns a result dict. Returns (results, failed).
    """
    slot = dict(slot or {})
    slot_name = str(slot.get('track') or 'Batch')
    placeholder = next((t for t in document.tracks if t.name == slot_name or t.id == slot_name), None)
    results, failed = [], []
    total = max(1, len(inputs))
    for index, item in enumerate(inputs):
        if cancel is not None and cancel():
            raise BatchError('Cancelled', 'Batch cancelled')
        if progress:
            progress(index / total, 'File %d/%d' % (index + 1, total))
        source = Path(str(item))
        started = time.monotonic()
        try:
            if not source.is_file():
                raise BatchError('MissingInput', 'Input not found: ' + str(source))
            if placeholder is not None:
                apply_actions(document, [{'action': 'replace_audio', 'track': placeholder.id, 'file': str(source), 'offset_seconds': slot.get('offset_seconds')}], load_workflow)
                track = placeholder
                _apply_track_fields(document, track, {k: slot[k] for k in ('gain_db', 'pan') if k in slot})
            else:
                action = {'action': 'add_track', 'file': str(source), 'name': slot_name, 'offset_seconds': slot.get('offset_seconds', 0.0),
                          'gain_db': slot.get('gain_db'), 'pan': slot.get('pan'), 'inserts_from': slot.get('inserts_from'),
                          'workflow_name': slot.get('workflow_name'), 'nodes': slot.get('nodes')}
                apply_actions(document, [action], load_workflow)
                track = document.tracks[-1]
            saved_solo = [(t, t.solo) for t in document.tracks]
            if slot.get('solo'):
                for t in document.tracks:
                    t.solo = t is track
            try:
                result = render(document, source.stem)
            finally:
                for t, value in saved_solo:
                    t.solo = value
            result.update({'input': str(source), 'seconds': round(time.monotonic() - started, 3)})
            results.append(result)
        except BatchError as exc:
            if exc.code == 'Cancelled':
                raise
            failed.append({'input': str(source), 'code': exc.code, 'message': str(exc)})
        except Exception as exc:
            failed.append({'input': str(source), 'code': 'RenderFailed', 'message': str(exc)})
        finally:
            if placeholder is None:
                stray = next((t for t in document.tracks if t.name == slot_name), None)
                if stray is not None:
                    document.remove_track(stray.id)
    if progress:
        progress(1.0, 'done')
    return results, failed
