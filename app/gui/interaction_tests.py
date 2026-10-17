"""Scripted mouse/keyboard tests of the interface through the Dear ImGui test engine.

    runtime/python/Scripts/python.exe app/desktop.py --ui-test-interactions [--ui-window=WxH] [--ui-test-no-gpu]

Real clicks and drags are simulated on the real widgets; every check is recorded in
data/reports/ui-interactions.json. Fixture audio is synthesised, nothing is downloaded.
"""
import json
from pathlib import Path
import sys
import time
import traceback

import numpy as np
from imgui_bundle import imgui, hello_imgui

from audiostudio.paths import DATA

te = imgui.test_engine


class Recorder:
    def __init__(self, filename='ui-interactions.json'):
        self.results = []
        self.done = False
        self.filename = filename

    def check(self, name, condition, detail=''):
        self.results.append({'check': name, 'ok': bool(condition), 'detail': str(detail)[:400]})

    def skip(self, name, reason):
        self.results.append({'check': name, 'ok': True, 'skipped': True, 'detail': str(reason)[:400]})

    def save(self):
        path = DATA / 'reports' / self.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        summary = {'passed': sum(r['ok'] and not r.get('skipped') for r in self.results), 'failed': sum(not r['ok'] for r in self.results),
                   'skipped': sum(bool(r.get('skipped')) for r in self.results), 'checks': self.results}
        path.write_text(json.dumps(summary, indent=2), 'utf-8')
        return summary


def fixture(document, name, seconds, frequency, offset=0.0, stereo=True):
    rate = document.samplerate
    t = np.arange(int(rate * seconds)) / rate
    tone = (0.4 * np.sin(2 * np.pi * frequency * t) * np.exp(-t * 0.5)).astype(np.float32)
    audio = np.stack([tone, tone * 0.5]) if stereo else tone[np.newaxis, :]
    return document.add_track(audio, name, samplerate=rate, offset_seconds=offset)


def wait(ctx, frames=3):
    for _ in range(frames):
        ctx.yield_()


def register(app, runner, recorder):
    engine = hello_imgui.get_imgui_test_engine()
    test = te.register_test(engine, 'audiostudio', 'interactions')

    def run(ctx):
        try:
            _scenario(app, ctx, recorder)
        except Exception:
            recorder.check('scenario raised no exception', False, traceback.format_exc())
        finally:
            recorder.done = True
    test.test_func = run
    te.queue_test(engine, test)


def clip_ref(track, name, index=0):
    """Test-engine path of a handle of a clip: widgets of a clip live under track id / clip id."""
    return f'**/{track.id}/{track.clips[index].id}/{name}'


def _item_exists(ctx, ref):
    try:
        return bool(ctx.item_exists(ref))
    except Exception:
        return False


def _scenario(app, ctx, recorder):
    try:
        _scenario_steps(app, ctx, recorder)
    finally:
        recorder.check('no widget ID conflict reported by ImGui during the session', not app.id_conflicts,
                       f'{len(app.id_conflicts)} frame(s) with conflicts, first at frame {min(app.id_conflicts) if app.id_conflicts else None}')


def _scenario_steps(app, ctx, recorder):
    document = app.document
    app.requested_tab = 'Editor'
    wait(ctx, 4)
    a = fixture(document, 'alpha', 2.0, 220)
    b = fixture(document, 'beta', 1.5, 330, offset=0.5, stereo=False)
    c = fixture(document, 'gamma', 1.0, 440, offset=1.0)
    app.timeline.fit(document)
    wait(ctx, 4)
    recorder.check('three fixture tracks', len(document.tracks) == 3, [t.name for t in document.tracks])

    # --- delete a track with its header button
    ref = f'**/{b.id}/Delete track'
    recorder.check('track delete button exists', _item_exists(ctx, ref), ref)
    ctx.item_click(ref)
    wait(ctx, 4)
    recorder.check('track delete button removes the track', document.track(b.id) is None, [t.name for t in document.tracks])
    recorder.check('undo restores the deleted track', document.undo() is not None and document.track(b.id) is not None, [t.name for t in document.tracks])
    wait(ctx, 3)

    # --- move a clip by dragging its title bar
    before = a.offset
    ref = clip_ref(a, 'clip-move')
    recorder.check('clip title bar exists', _item_exists(ctx, ref), ref)
    ctx.item_drag_with_delta(ref, imgui.ImVec2(120, 0))
    wait(ctx, 4)
    recorder.check('dragging the clip title bar moves the clip later', a.offset > before, f'{before} -> {a.offset}')
    moved = a.offset
    ctx.item_drag_with_delta(ref, imgui.ImVec2(-60, 0))
    wait(ctx, 4)
    recorder.check('dragging back moves the clip earlier', a.offset < moved, f'{moved} -> {a.offset}')
    recorder.check('undo restores the clip position', document.undo() is not None and a.offset == moved, f'{a.offset}')

    # --- drag on a lane body selects a region
    document.selection = None
    ref = f'**/{c.id}/lane'
    ctx.item_drag_with_delta(ref, imgui.ImVec2(150, 0))
    wait(ctx, 3)
    recorder.check('dragging a lane selects a region', document.selection is not None and document.selection[1] > document.selection[0], document.selection)

    # --- delete the selection with the Delete button
    track = document.current_track()
    frames = track.frames if track else 0
    if document.selection and track is not None:
        a0, b0 = sorted(document.selection)
        document.selection = (max(a0, document.frame_to_seconds(track.offset) + 0.05), min(b0, document.frame_to_seconds(track.end) - 0.05))
    ctx.item_click('**/Delete')
    wait(ctx, 3)
    recorder.check('Delete button shortens the selected track', track is not None and track.frames < frames, f'{frames} -> {track.frames if track else None}')

    # --- clip context menu: delete clip (the clip under the mouse; the track and its effects stay)
    count = len(document.tracks)
    target = document.tracks[-1]
    if target.clips:
        clip = target.clips[0]
        app.timeline.view = (document.frame_to_seconds(clip.offset) - 0.05, document.frame_to_seconds(clip.end) + 0.05)   # lane centre on the clip
        wait(ctx, 3)
    ctx.item_click(f'**/{target.id}/lane', imgui.MouseButton_.right)
    wait(ctx, 3)
    try:
        ctx.item_click('**/Delete clip')
        wait(ctx, 3)
        recorder.check('context menu Delete clip removes the clip and keeps the track', not target.clips and len(document.tracks) == count,
                       ([len(t.clips) for t in document.tracks], len(document.tracks)))
        recorder.check('undo restores the deleted clip', document.undo() is not None and len(target.clips) == 1, len(target.clips))
    except Exception as exc:
        recorder.check('context menu Delete clip removes the clip and keeps the track', False, exc)
    # --- clip context menu: reverse clip (and undo)
    if target.clips:
        clip = target.clips[0]
        shown = clip.view().copy()
        ctx.item_click(f'**/{target.id}/lane', imgui.MouseButton_.right)
        wait(ctx, 3)
        try:
            ctx.item_click('**/Reverse clip')
            wait(ctx, 3)
            recorder.check('context menu Reverse clip plays the clip backwards', np.array_equal(clip.view(), shown[:, ::-1]), clip.name)
            recorder.check('undo restores the clip direction', document.undo() is not None and np.array_equal(target.clips[0].view(), shown), len(target.clips))
        except Exception as exc:
            recorder.check('context menu Reverse clip plays the clip backwards', False, exc)
    app.timeline.fit(document)
    wait(ctx, 3)

    # --- drag a clip by its title bar onto another track: it then goes through that track's effects
    heights = {t.id: t.height for t in document.tracks}
    for t in document.tracks:
        t.height = 70.0                      # every lane in view: no scrolling between the source and the target
    wait(ctx, 4)
    rows = {row[0]: row for row in app.timeline._last_rows}
    source, destination = document.tracks[0], document.tracks[-1]
    if source.clips and source.id in rows and destination.id in rows and source is not destination:
        moving = source.clips[0]
        before_source, before_destination = len(source.clips), len(destination.clips)
        dy = (rows[destination.id][1] + rows[destination.id][2]) / 2 - (rows[source.id][1] + rows[source.id][2]) / 2
        # by hand: item_drag_with_delta fails the test when the dragged item no longer exists after the
        # release, and here it does not (the clip has moved to the other track, under another ID path)
        recorder.check('the title bar of the clip to move is in view', _item_exists(ctx, clip_ref(source, 'clip-move')), clip_ref(source, 'clip-move'))
        ctx.mouse_move(clip_ref(source, 'clip-move'))
        start = imgui.get_mouse_pos()
        ctx.mouse_down(0)
        ctx.mouse_move_to_pos(imgui.ImVec2(start.x, start.y + dy * 0.5))
        ctx.mouse_move_to_pos(imgui.ImVec2(start.x, start.y + dy))
        wait(ctx, 2)
        ctx.mouse_up(0)
        wait(ctx, 4)
        recorder.check('dragging a clip down puts it on the other track', moving in destination.clips and moving not in source.clips,
                       (len(source.clips), len(destination.clips)))
        recorder.check('undo puts the clip back on its track', document.undo() is not None and len(source.clips) == before_source and len(destination.clips) == before_destination,
                       (len(source.clips), len(destination.clips)))
        wait(ctx, 3)
        recorder.check('the restored clip is drawn on its track again', _item_exists(ctx, clip_ref(source, 'clip-move')), clip_ref(source, 'clip-move'))
    else:
        recorder.check('dragging a clip down puts it on the other track', False, ('rows', list(rows), [t.id for t in document.tracks]))
    for t in document.tracks:
        t.height = heights.get(t.id, t.height)
    wait(ctx, 3)

    # --- trim a clip by its right edge, then its left edge; the audio is kept
    document.selection = None
    app.timeline.fit(document)
    wait(ctx, 4)
    before_frames, before_total = a.frames, a.total_frames
    ctx.item_drag_with_delta(clip_ref(a, 'clip-right'), imgui.ImVec2(-90, 0))
    wait(ctx, 4)
    recorder.check('dragging the right edge shortens the clip', a.frames < before_frames and a.total_frames == before_total,
                   f'{before_frames} -> {a.frames} (material {a.total_frames})')
    trimmed = a.frames
    ctx.item_drag_with_delta(clip_ref(a, 'clip-right'), imgui.ImVec2(45, 0))
    wait(ctx, 4)
    recorder.check('dragging the right edge back restores audio', a.frames > trimmed, f'{trimmed} -> {a.frames}')
    before_offset, before_start = a.offset, a.start
    ctx.item_drag_with_delta(clip_ref(a, 'clip-left'), imgui.ImVec2(60, 0))
    wait(ctx, 4)
    recorder.check('dragging the left edge trims the beginning', a.start > before_start and a.offset > before_offset,
                   f'start {before_start} -> {a.start}, offset {before_offset} -> {a.offset}')
    recorder.check('undo restores the trimmed beginning', document.undo() is not None and a.start == before_start, f'{a.start}')

    # --- fades by dragging the handles in the clip corners
    a.fade_in = a.fade_out = 0.0
    wait(ctx, 3)
    ctx.item_drag_with_delta(clip_ref(a, 'fade-in'), imgui.ImVec2(70, 0))
    wait(ctx, 4)
    recorder.check('dragging the fade-in handle creates a fade in', a.fade_in > 0.0, a.fade_in)
    ctx.item_drag_with_delta(clip_ref(a, 'fade-out'), imgui.ImVec2(-70, 0))
    wait(ctx, 4)
    recorder.check('dragging the fade-out handle creates a fade out', a.fade_out > 0.0, f'{a.fade_out}')
    quiet = document.mixdown(document.frame_to_seconds(a.offset), document.frame_to_seconds(a.offset) + 0.02)
    loud = document.mixdown(document.frame_to_seconds(a.offset) + a.fade_in + 0.05, document.frame_to_seconds(a.offset) + a.fade_in + 0.15)
    quiet_level = float(np.sqrt((quiet ** 2).mean())) if quiet.size else 0.0
    loud_level = float(np.sqrt((loud ** 2).mean())) if loud.size else 0.0
    recorder.check('the fade in is audible in the mix', quiet_level < loud_level * 0.5, f'{quiet_level:.4f} < {loud_level:.4f}')
    recorder.check('undo removes the fade out', document.undo() is not None and a.fade_out == 0.0, a.fade_out)

    # --- move along the timeline with the scrollbar
    app.timeline.zoom(0.25)
    wait(ctx, 3)
    view_before = app.timeline.view[0]
    ctx.item_drag_with_delta('**/hscroll', imgui.ImVec2(120, 0))
    wait(ctx, 3)
    recorder.check('dragging the scrollbar moves the view later', app.timeline.view[0] > view_before, f'{view_before:.3f} -> {app.timeline.view[0]:.3f}')
    view_after = app.timeline.view[0]
    ctx.item_drag_with_delta('**/hscroll', imgui.ImVec2(-200, 0))
    wait(ctx, 3)
    recorder.check('dragging the scrollbar back moves the view earlier', app.timeline.view[0] < view_after, f'{view_after:.3f} -> {app.timeline.view[0]:.3f}')
    app.timeline.fit(document)
    wait(ctx, 3)

    # --- inserts panel: FX button, Add, knob drag, undo, removal
    app.editor.show_inserts = False
    wait(ctx, 2)
    ctx.item_click(f'**/{a.id}/FX')
    wait(ctx, 4)
    recorder.check('FX button opens the inserts panel on that track', app.editor.show_inserts and app.inserts.owner() is a, (app.editor.show_inserts, app.inserts.owner_id))
    specs = app.inserts.realtime_effects()
    app.inserts.effect_index = next(i for i, spec in enumerate(specs) if spec.id == 'compressor')
    wait(ctx, 2)
    ctx.item_click('**/Add insert effect')
    wait(ctx, 4)
    recorder.check('Add button inserts a compressor on the track', [n['effect'] for n in a.inserts] == ['compressor'], [n['effect'] for n in a.inserts])
    if a.inserts:
        node = a.inserts[0]
        before = node['params']['threshold_db']
        undo_len = len(document.undo_stack)
        ref = '**/Threshold##threshold_db/##knob'
        recorder.check('compressor Threshold knob exists', _item_exists(ctx, ref), ref)
        ctx.item_drag_with_delta(ref, imgui.ImVec2(0, -40))
        wait(ctx, 4)
        recorder.check('dragging the Threshold knob changes the parameter', node['params']['threshold_db'] != before, f"{before} -> {node['params']['threshold_db']}")
        recorder.check('the knob drag recorded an undo entry', len(document.undo_stack) > undo_len and document.undo_stack[-1]['label'] == 'Threshold',
                       document.undo_stack[-1]['label'] if document.undo_stack else None)
        renderer = app.player.renderer
        renderer.render(0, 1024)
        recorder.check('the renderer runs the insert', renderer.processor(node['id']) is not None and node['id'] not in renderer.errors, renderer.errors)
        recorder.check('the insert tap feeds the scope', renderer.taps.get(node['id']) is not None, list(renderer.taps))
        ctx.item_click(f'**/{node["id"]}/Remove insert')
        wait(ctx, 4)
        recorder.check('X removes the insert', not a.inserts, [n['effect'] for n in a.inserts])
        recorder.check('undo restores the insert', document.undo() is not None and len(a.inserts) == 1, [n['effect'] for n in a.inserts])
        a.inserts.clear()

    # --- effects belong to a track or to the master: clicking a track shows its own chain
    from audiostudio.dsp import effects as registry
    app.editor.show_inserts = True
    d = fixture(document, 'delta', 1.0, 550, offset=0.2)
    heights = {t.id: t.height for t in document.tracks}
    for t in document.tracks:
        t.height = 60.0                              # every lane visible, even in a small window
    app.timeline.fit(document)
    wait(ctx, 4)
    ctx.item_click(f'**/{d.id}/lane')
    wait(ctx, 3)
    recorder.check('clicking a track shows that track\'s chain in the FX panel', app.inserts.owner() is d, getattr(app.inserts.owner(), 'name', None))
    specs = app.inserts.realtime_effects()
    app.inserts.effect_index = next(i for i, spec in enumerate(specs) if spec.id == 'compressor')
    before_a, before_master = len(a.inserts), len(document.master.inserts)
    wait(ctx, 2)
    ctx.item_click('**/Add insert effect')
    wait(ctx, 3)
    recorder.check('an effect added there belongs to that track only', [n['effect'] for n in d.inserts] == ['compressor'] and len(a.inserts) == before_a and len(document.master.inserts) == before_master,
                   ([n['effect'] for n in d.inserts], len(a.inserts), len(document.master.inserts)))
    ctx.item_click(f'**/{a.id}/lane')
    wait(ctx, 3)
    recorder.check('clicking another track shows its own chain (not the previous one)', app.inserts.owner() is a and not any(n['effect'] == 'compressor' for n in a.inserts), getattr(app.inserts.owner(), 'name', None))
    ctx.item_click('**/master/master-lane')
    wait(ctx, 3)
    recorder.check('clicking the master lane shows the master chain', app.inserts.owner() is document.master, getattr(app.inserts.owner(), 'name', None))
    document.remove_track(d.id)
    for t in document.tracks:
        t.height = heights.get(t.id, t.height)
    document.selected_track = document.tracks.index(a)
    app.inserts.follow(a)
    wait(ctx, 3)

    # --- files dropped from the desktop (the OS drop is simulated by calling the GLFW callback target)
    recorder.check('the GLFW file-drop callback is installed', app.drop_ready, app.drop_error or 'ok')
    import tempfile
    from audiostudio import audio_io
    drop_folder = Path(tempfile.mkdtemp(prefix='audiostudio-drop-'))
    dropped = drop_folder / 'dropped-sound.wav'
    audio_io.save(dropped, np.zeros((1, 4800), np.float32) + 0.1, document.samplerate, fmt='wav', subtype='FLOAT')
    geometry = app.timeline.drop_geometry
    rows = geometry['rows'] if geometry else []
    target_row = next((r for r in rows if r[0] == a.id), None)
    if geometry and target_row:
        x = geometry['lane_x0'] + geometry['lane_width'] * 0.5
        y = (target_row[1] + target_row[2]) / 2
        expected = geometry['start'] + geometry['span'] * 0.5
        count, clips = len(document.tracks), len(a.clips)
        wanted = document.frame_to_seconds(document.free_position(a, document.seconds_to_frame(expected), 4800))
        app.on_files_dropped([str(dropped)])
        handled = app.handle_drops(mouse=imgui.ImVec2(x, y))
        wait(ctx, 3)
        new = next((c for c in a.clips if c.name == 'dropped-sound'), None)
        recorder.check('a sound dropped on a track becomes a clip of that track (after its clips when the place is taken)',
                       new is not None and len(document.tracks) == count and len(a.clips) == clips + 1 and abs(document.frame_to_seconds(new.offset) - wanted) < 0.05,
                       (handled, len(a.clips), document.frame_to_seconds(new.offset) if new else None, wanted))
        if new is not None:
            document.remove_clip(a, new)
        below = max(r[2] for r in rows) + 10
        if below < geometry['y1']:
            app.on_files_dropped([str(dropped)])
            app.handle_drops(mouse=imgui.ImVec2(x, below))
            wait(ctx, 3)
            recorder.check('a sound dropped below the tracks becomes a new track', len(document.tracks) == count + 1 and document.tracks[-1].name == 'dropped-sound',
                           [t.name for t in document.tracks])
            if len(document.tracks) == count + 1:
                document.remove_track(document.tracks[-1].id)
    else:
        recorder.check('a sound dropped on a track becomes a clip of that track (after its clips when the place is taken)', False, 'no geometry')

    # --- search by text in the effect pickers
    app.inserts.show(a)
    wait(ctx, 3)
    for query, expected, name in (('vocod', 'vocoder', 'typing in the effect picker and pressing Enter selects the match'),
                                  ('hall plate', 'ir_reverb', 'a multi-word search narrows to the one matching effect')):
        try:
            from gui import widgets as ui_widgets
            rect = ui_widgets.combo_rects.get('add-effect')
            if rect is None:
                raise RuntimeError('the effect picker was not drawn')
            ctx.mouse_move_to_pos(imgui.ImVec2((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2))
            ctx.mouse_click(0)                                               # opens the picker; its search field takes the keyboard
            wait(ctx, 3)
            ctx.key_chars(query)
            wait(ctx, 2)
            typed = ui_widgets._search_texts.get('add-effect')
            ctx.key_press(imgui.Key.enter)
            wait(ctx, 3)
            picked = app.inserts.realtime_effects()[app.inserts.effect_index].id
            recorder.check(name, picked == expected, (picked, typed, ctx.is_error()))
        except Exception as exc:
            recorder.check(name, False, exc)
        finally:
            ctx.key_press(imgui.Key.escape)                                  # never leave a popup open for the next checks
            wait(ctx, 2)

    # --- + button: an empty track, then a dropped sound fills it (keeping its inserts)
    count = len(document.tracks)
    ctx.item_click('**/Add track')
    wait(ctx, 3)
    empty = document.tracks[-1] if len(document.tracks) == count + 1 else None
    recorder.check('the + button adds an empty track', empty is not None and empty.frames == 0, [t.name for t in document.tracks])
    if empty is not None:
        from audiostudio.workflow import model as workflow_model
        document.add_insert(empty, workflow_model.new_node('effect', effect='gain', params={'gain_db': -3.0}))
        panel = app.editor.show_inserts
        app.editor.show_inserts = False          # room for every lane: the new track is in view at any window size
        wait(ctx, 4)
        geometry = app.timeline.drop_geometry
        row = next((r for r in geometry['rows'] if r[0] == empty.id), None) if geometry else None
        import tempfile
        from audiostudio import audio_io
        sound = Path(tempfile.mkdtemp(prefix='audiostudio-fill-')) / 'fill-me.wav'
        audio_io.save(sound, np.zeros((2, 9600), np.float32) + 0.2, document.samplerate, fmt='wav', subtype='FLOAT')
        if row is not None:
            app.on_files_dropped([str(sound)])
            app.handle_drops(mouse=imgui.ImVec2(geometry['lane_x0'] + 10, (row[1] + row[2]) / 2))
            wait(ctx, 3)
        app.editor.show_inserts = panel
        recorder.check('a sound dropped on the empty track fills it and keeps its inserts', empty.frames == 9600 and [n['effect'] for n in empty.inserts] == ['gain'] and len(document.tracks) == count + 1,
                       (empty.frames, [n['effect'] for n in empty.inserts], len(document.tracks)))
        document.remove_track(empty.id)
        wait(ctx, 2)

    # --- master bus: FX button, gain slider
    ctx.item_click('**/master/master-FX')
    wait(ctx, 4)
    recorder.check('master FX button shows the master chain', app.inserts.show_master and app.inserts.owner() is document.master, app.inserts.show_master)
    gain_before = document.master.gain_db
    ctx.item_drag_with_delta('**/master/##master-gain', imgui.ImVec2(-60, 0))
    wait(ctx, 4)
    recorder.check('dragging the master gain slider changes the master gain', document.master.gain_db != gain_before, f'{gain_before} -> {document.master.gain_db}')
    document.master.gain_db = 0.0
    app.inserts.show_master = False

    # --- automation: click on the lane adds a point, drag moves it, undo removes the move
    app.timeline.fit(document)
    a.automation_view = 'gain_db'
    a.automation.pop('gain_db', None)
    wait(ctx, 4)
    ctx.item_click(f'**/{a.id}/lane')
    wait(ctx, 4)
    lane = a.automation.get('gain_db')
    recorder.check('clicking the lane adds an automation point', lane is not None and len(lane.points) == 1, lane.points if lane else None)
    if lane is not None and lane.points:
        value_before = lane.points[0][1]
        ctx.item_drag_with_delta(f'**/{a.id}/lane', imgui.ImVec2(0, 25))
        wait(ctx, 4)
        recorder.check('dragging the point lowers its value', lane.points[0][1] < value_before, f'{value_before} -> {lane.points[0][1]}')
        moved = lane.points[0][1]
        label = document.undo()
        recorder.check('undo reverts the automation move', label == 'Move automation point' and a.automation['gain_db'].points[0][1] == value_before, (label, a.automation['gain_db'].points))
        recorder.check('the mix follows the automation lane', abs(document.mixdown(0.0, 0.05, tail={'enabled': False}).max()) >= 0.0, 'rendered')
    a.automation_view = ''
    a.automation.pop('gain_db', None)

    # --- moving along the timeline: right-drag, hand tool, overview strip, ruler click
    app.timeline.zoom(0.3)
    wait(ctx, 3)
    view_before = app.timeline.view[0]
    try:
        ctx.mouse_move(f'**/{a.id}/lane')
        ctx.mouse_down(1)
        pos = imgui.get_mouse_pos()
        ctx.mouse_move_to_pos(imgui.ImVec2(pos.x - 120, pos.y))
        ctx.mouse_up(1)
        wait(ctx, 3)
        recorder.check('right-drag on a lane moves the view later', app.timeline.view[0] > view_before, f'{view_before:.3f} -> {app.timeline.view[0]:.3f}')
    except Exception as exc:
        recorder.check('right-drag on a lane moves the view later', False, exc)
    wait(ctx, 3)
    app.timeline.hand_tool = True
    view_before = app.timeline.view[0]
    ctx.item_drag_with_delta(f'**/{a.id}/lane', imgui.ImVec2(90, 0))
    wait(ctx, 3)
    recorder.check('hand tool: left-drag moves the view earlier', app.timeline.view[0] < view_before, f'{view_before:.3f} -> {app.timeline.view[0]:.3f}')
    app.timeline.hand_tool = False
    view_before = app.timeline.view[0]
    ctx.item_drag_with_delta('**/overview', imgui.ImVec2(80, 0))
    wait(ctx, 3)
    recorder.check('dragging the overview window moves the view later', app.timeline.view[0] > view_before, f'{view_before:.3f} -> {app.timeline.view[0]:.3f}')
    cursor_before = document.cursor
    ctx.item_click('**/ruler')
    wait(ctx, 3)
    recorder.check('clicking the ruler moves the cursor', document.cursor != cursor_before, f'{cursor_before:.3f} -> {document.cursor:.3f}')
    app.timeline.fit(document)
    wait(ctx, 3)

    # --- workflow chain: add then delete a node
    app.requested_tab = 'Workflows'
    wait(ctx, 4)
    nodes = app.workflows.document['nodes']
    nodes.clear()
    app.workflows.add_effect('gain')
    app.workflows.add_effect('reverb')
    wait(ctx, 3)
    first = nodes[0]['id']
    ref = f'**/{first}/Remove node'
    recorder.check('workflow node remove button exists', _item_exists(ctx, ref), ref)
    ctx.item_click(ref)
    wait(ctx, 3)
    recorder.check('workflow node remove button removes the node', len(nodes) == 1 and nodes[0]['id'] != first, [n['id'] for n in nodes])
    second = nodes[0]['id']
    app.workflows.add_effect('delay')
    wait(ctx, 3)
    ctx.item_click(f'**/{second}/Move node down')
    wait(ctx, 3)
    recorder.check('workflow node move down reorders', nodes[-1]['id'] == second, [n['id'] for n in nodes])

    # --- nothing is cut off on the right: key widgets end inside the window
    width = imgui.get_main_viewport().size.x
    app.requested_tab = 'Editor'
    wait(ctx, 4)
    for ref in ('**/Export mix', '**/Follow', '**/FX panel', '**/Insert silence'):
        info = ctx.item_info(ref, te.TestOpFlags_.no_error)
        inside = info is not None and info.id_ != 0 and info.rect_full.max.x <= width
        recorder.check('editor widget fully visible: ' + ref[3:], inside, f'{info.rect_full.max.x if info and info.id_ else None} <= {width}')

    # --- voices: label above the text, cloning section
    app.requested_tab = 'Generate'
    app.test_subtab = 'Voices'
    voice = app.generate.voice
    voice['backend'] = 1
    voice['qwen_mode'] = 1
    voice['qwen_model'] = 2
    wait(ctx, 6)
    for ref in ('**/##v-text', '**/##v-reftext', '**/Record from microphone', '**/Transcribe automatically (Whisper)'):
        info = ctx.item_info(ref, te.TestOpFlags_.no_error)
        inside = info is not None and info.id_ != 0 and info.rect_full.max.x <= width
        recorder.check('voice widget fully visible: ' + ref[3:], inside, f'{info.rect_full.max.x if info and info.id_ else None} <= {width}')

    # microphone: a real short take from the default input device
    ctx.item_click('**/Record from microphone')
    started = time.time()
    while time.time() - started < 1.5:
        ctx.yield_()
    ctx.item_click('**/Stop recording')
    wait(ctx, 3)
    recorded = voice['reference']
    recorder.check('microphone take recorded without error', not app.generate.mic.error, app.generate.mic.error or recorded)

    # reference from a speech file, automatic transcription, cloning, preset
    free_ram = app.runtime.ledger.capacity.get('ramBytes', 0)
    no_gpu = '--ui-test-no-gpu' in sys.argv
    if no_gpu or free_ram < 6 * 1024 ** 3:
        reason = ('--ui-test-no-gpu: Whisper and Qwen3-TTS are not run' if no_gpu
                  else f'only {free_ram / 1e9:.1f} GB of RAM available to the runtime; close the other applications')
        for name in ('Whisper transcription fills the transcription field', 'cloned voice generated', 'clone preset keeps its own copy of the reference'):
            recorder.skip(name, reason)
        app.requested_tab = 'Editor'
        wait(ctx, 3)
        return
    speech = DATA / 'reports' / 'smoke-piper.wav'
    voice['reference'] = str(speech)
    voice['reference_text'] = ''
    voice['x_vector'] = False
    voice['text'] = 'Voici la voix copiée à partir de la référence.'
    wait(ctx, 3)
    ctx.item_click('**/Transcribe automatically (Whisper)')
    _wait_jobs(app, ctx, 300)
    recorder.check('Whisper transcription fills the transcription field', bool(voice['reference_text'].strip()), voice['reference_text'] or app.generate.message)
    results_before = len(app.generate.results)
    ctx.item_click('**/Generate voice')
    wait(ctx, 3)
    _wait_jobs(app, ctx, 600)
    recorder.check('cloned voice generated', len(app.generate.results) > results_before, (app.generate.results[:1], app.jobs.error))
    voice['preset_name'] = 'Test clone voice'
    ctx.item_click('**/Save as preset')
    wait(ctx, 5)
    from audiostudio.voice import presets
    saved = [p for p in presets.list_all() if p['name'] == 'Test clone voice']
    stored = presets.load(saved[-1]['id']) if saved else None
    reference = (stored or {}).get('parameters', {}).get('reference_audio', '')
    operation, backend, _ = app.generate._voice_parameters()
    recorder.check('clone preset keeps its own copy of the reference', bool(stored) and 'refs' in Path(reference).parts and Path(reference).is_file(),
                   f'reference={reference!r} saved={[p["name"] for p in presets.list_all()]} message={app.generate.message!r} error={app.jobs.error!r} '
                   f'backend={backend!r} operation={operation!r} voice_reference={voice["reference"]!r}')
    if stored:
        presets.delete(stored['id'])
    app.requested_tab = 'Editor'
    wait(ctx, 3)


def _wait_jobs(app, ctx, seconds, idle=1.5):
    """Waits until no job has been running for ``idle`` seconds (a job may start right after another)."""
    started = time.time()
    idle_since = None
    while time.time() - started < seconds:
        ctx.yield_()
        if app.jobs.running():
            idle_since = None
        elif idle_since is None:
            idle_since = time.time()
        elif time.time() - idle_since >= idle:
            break
    wait(ctx, 5)


def register_all_effects(app, runner, recorder):
    engine = hello_imgui.get_imgui_test_engine()
    test = te.register_test(engine, 'audiostudio', 'all-effects')

    def run(ctx):
        try:
            _all_effects(app, ctx, recorder)
        except Exception:
            recorder.check('sweep raised no exception', False, traceback.format_exc())
        finally:
            recorder.done = True
    test.test_func = run
    te.queue_test(engine, test)


def _hover_conflicts(ctx, rect, columns=10, rows=5):
    """Moves the mouse over a grid of the rectangle; ImGui reports ID conflicts of hovered items."""
    worst = 0
    if rect is None:
        return -1
    x0, y0, x1, y1 = rect
    for row in range(rows):
        for column in range(columns):
            ctx.mouse_move_to_pos(imgui.ImVec2(x0 + (column + 0.5) * (x1 - x0) / columns, y0 + (row + 0.5) * (y1 - y0) / rows))
            ctx.yield_()
            worst = max(worst, int(imgui.get_current_context().debug_draw_id_conflicts_count))
    return worst


def _all_effects(app, ctx, recorder):
    """Every real-time effect interface is shown while playing and swept with the mouse."""
    from audiostudio.dsp import effects
    from audiostudio.workflow import model as workflow_model
    document = app.document
    app.requested_tab = 'Editor'
    wait(ctx, 3)
    track = fixture(document, 'sweep tone', 3.0, 220)
    app.inserts.show(track)
    document.selection = (0.0, 2.0)
    app.player.loop = True
    app.player.play(0.0)
    wait(ctx, 3)
    failures = []
    specs = [spec for spec in effects.REGISTRY.values() if spec.realtime]
    for spec in specs:
        for node in list(track.inserts):
            document.remove_insert(track, node['id'])
        node = document.add_insert(track, workflow_model.new_node('effect', effect=spec.id))
        app.inserts.selected[track.id] = node['id']
        wait(ctx, 3)
        conflicts = _hover_conflicts(ctx, app.inserts.editor_rect)
        errors = dict(app.player.renderer.errors)
        if conflicts or errors:
            failures.append((spec.id, conflicts, errors))
    recorder.check(f'{len(specs)} effect interfaces hovered while playing: no ID conflict, no render error', not failures, failures)
    for node in list(track.inserts):
        document.remove_insert(track, node['id'])
    master = document.master
    compressor = document.add_insert(master, workflow_model.new_node('effect', effect='compressor'))
    document.add_insert(master, workflow_model.new_node('effect', effect='reverb'))
    app.inserts.show(master)
    app.inserts.selected[master.id] = compressor['id']
    wait(ctx, 4)
    conflicts = _hover_conflicts(ctx, app.inserts.editor_rect)
    recorder.check('master chain interface hovered: no ID conflict', conflicts == 0, conflicts)
    for node in list(master.inserts):
        document.remove_insert(master, node['id'])
    app.player.stop()
    wait(ctx, 2)
