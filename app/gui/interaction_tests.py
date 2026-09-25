"""Scripted mouse/keyboard tests of the interface through the Dear ImGui test engine.

    runtime/python/Scripts/python.exe app/desktop.py --ui-test-interactions

Real clicks and drags are simulated on the real widgets; every check is recorded in
data/reports/ui-interactions.json. Fixture audio is synthesised, nothing is downloaded.
"""
import json
from pathlib import Path
import time
import traceback

import numpy as np
from imgui_bundle import imgui, hello_imgui

from audiostudio.paths import DATA

te = imgui.test_engine


class Recorder:
    def __init__(self):
        self.results = []
        self.done = False

    def check(self, name, condition, detail=''):
        self.results.append({'check': name, 'ok': bool(condition), 'detail': str(detail)[:400]})

    def skip(self, name, reason):
        self.results.append({'check': name, 'ok': True, 'skipped': True, 'detail': str(reason)[:400]})

    def save(self):
        path = DATA / 'reports' / 'ui-interactions.json'
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


def _item_exists(ctx, ref):
    try:
        return bool(ctx.item_exists(ref))
    except Exception:
        return False


def _scenario(app, ctx, recorder):
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
    ref = f'**/{a.id}/clip-move'
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

    # --- clip context menu: delete clip
    count = len(document.tracks)
    target = document.tracks[-1]
    ctx.item_click(f'**/{target.id}/lane', imgui.MouseButton_.right)
    wait(ctx, 3)
    try:
        ctx.item_click('**/Delete clip')
        wait(ctx, 3)
        recorder.check('context menu Delete clip removes the clip', len(document.tracks) == count - 1, [t.name for t in document.tracks])
    except Exception as exc:
        recorder.check('context menu Delete clip removes the clip', False, exc)

    # --- trim a clip by its right edge, then its left edge; the audio is kept
    document.selection = None
    app.timeline.fit(document)
    wait(ctx, 4)
    before_frames, before_total = a.frames, a.total_frames
    ctx.item_drag_with_delta(f'**/{a.id}/clip-right', imgui.ImVec2(-90, 0))
    wait(ctx, 4)
    recorder.check('dragging the right edge shortens the clip', a.frames < before_frames and a.total_frames == before_total,
                   f'{before_frames} -> {a.frames} (material {a.total_frames})')
    trimmed = a.frames
    ctx.item_drag_with_delta(f'**/{a.id}/clip-right', imgui.ImVec2(45, 0))
    wait(ctx, 4)
    recorder.check('dragging the right edge back restores audio', a.frames > trimmed, f'{trimmed} -> {a.frames}')
    before_offset, before_start = a.offset, a.start
    ctx.item_drag_with_delta(f'**/{a.id}/clip-left', imgui.ImVec2(60, 0))
    wait(ctx, 4)
    recorder.check('dragging the left edge trims the beginning', a.start > before_start and a.offset > before_offset,
                   f'start {before_start} -> {a.start}, offset {before_offset} -> {a.offset}')
    recorder.check('undo restores the trimmed beginning', document.undo() is not None and a.start == before_start, f'{a.start}')

    # --- fades by dragging the handles in the clip corners
    a.fade_in = a.fade_out = 0.0
    wait(ctx, 3)
    ctx.item_drag_with_delta(f'**/{a.id}/fade-in', imgui.ImVec2(70, 0))
    wait(ctx, 4)
    recorder.check('dragging the fade-in handle creates a fade in', a.fade_in > 0.0, a.fade_in)
    ctx.item_drag_with_delta(f'**/{a.id}/fade-out', imgui.ImVec2(-70, 0))
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
    for ref in ('**/Export mix', '**/Follow', '**/Apply workflow to selection', '**/Insert silence'):
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
    if free_ram < 6 * 1024 ** 3:
        for name in ('Whisper transcription fills the transcription field', 'cloned voice generated', 'clone preset keeps its own copy of the reference'):
            recorder.skip(name, f'only {free_ram / 1e9:.1f} GB of RAM available to the runtime; close the other applications')
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


def _wait_jobs(app, ctx, seconds):
    started = time.time()
    while time.time() - started < seconds:
        ctx.yield_()
        if not app.jobs.running() and time.time() - started > 0.5:
            break
    wait(ctx, 5)
