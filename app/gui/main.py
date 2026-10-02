"""CyTools_AudioStudio interface: editor, generation, workflows, plugins, models, updates.

One Core runtime is created here and shared by every tab; the facade in ui_common adds the
Application log, Advanced operations and Options tabs. Heavy work is always a job.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from installation_ui import configure as configure_storage  # noqa: E402
configure_storage()
from imgui_bundle import hello_imgui, imgui as native  # noqa: E402
from ui_common import imgui, run, tr, configure_generation, preferences  # noqa: E402
from tool import create_runtime  # noqa: E402
from audiostudio.paths import DATA, SESSIONS, ensure_data_layout  # noqa: E402
from audiostudio.editor.document import Document  # noqa: E402
from audiostudio import audio_io  # noqa: E402
from gui.jobs import Jobs  # noqa: E402
from gui.player import Player  # noqa: E402
from gui.timeline import Timeline  # noqa: E402
from gui.widgets import Dialogs  # noqa: E402
from gui.editor_panel import EditorPanel  # noqa: E402
from gui.inserts_panel import InsertsPanel  # noqa: E402
from gui.workflow_panel import WorkflowPanel  # noqa: E402
from gui.generate_panel import GeneratePanel  # noqa: E402
from gui.plugins_panel import PluginsPanel  # noqa: E402
from gui.models_panel import ModelsPanel  # noqa: E402
from gui.updates_panel import UpdatesPanel  # noqa: E402

TABS = ('Editor', 'Generate', 'Workflows', 'Plugins', 'Models', 'Updates')


class App:
    def __init__(self, runtime, actor, session):
        self.runtime, self.actor, self.session = runtime, actor, session
        self.services = runtime.services
        self.jobs = Jobs(runtime, actor, session)
        self.document = Document(48000)
        self.player = Player(self.document)
        self.timeline = Timeline()
        self.dialogs = Dialogs()
        self.tr = tr
        self.auto_import = True
        self.last_export = ''
        self.last_voice_preset = None
        self.reference_file = ''
        self.requested_tab = None
        self.preview_player = None
        self.frames = 0
        self.automation_write = False
        self.pending_drops = []
        self.id_conflicts = {}          # frame -> number of widgets ImGui reported with a conflicting ID
        self.drop_ready = False
        self.drop_error = ''
        self.editor = EditorPanel(self)
        self.inserts = InsertsPanel(self)
        self.workflows = WorkflowPanel(self)
        self.generate = GeneratePanel(self)
        self.plugins = PluginsPanel(self)
        self.models = ModelsPanel(self)
        self.updates = UpdatesPanel(self)
        self.editor_dialog_owner = True

    # ------------------------------------------------------------------ document helpers
    def new_document(self):
        self.player.close()
        self.document = Document(48000)
        self.player = Player(self.document)
        self.timeline = Timeline()

    def load_document(self, path):
        document = Document.load_session(path)
        self.player.close()
        self.document = document
        self.player = Player(document)
        self.timeline.fit(document)

    def select_tab(self, name):
        self.requested_tab = name

    # ------------------------------------------------------------------ files dropped from the desktop
    AUDIO_SUFFIXES = {'.wav', '.flac', '.ogg', '.mp3', '.m4a', '.aac', '.aiff', '.aif', '.opus', '.wma'}

    def on_files_dropped(self, paths):
        """GLFW drop callback (main thread): queued and handled at the next frame."""
        self.pending_drops.extend(str(p) for p in paths)

    def handle_drops(self, mouse=None):
        """Audio files -> new tracks at the time under the mouse (below the hovered track), or into the
        dialog's convolution effect when dropped on it; a session folder / session.json opens it; a
        workflow .json loads into the Workflows tab."""
        if not self.pending_drops:
            return []
        paths, self.pending_drops = list(self.pending_drops), []
        mouse = mouse or native.get_mouse_pos()
        handled = []
        audio = [p for p in paths if Path(p).suffix.lower() in self.AUDIO_SUFFIXES and Path(p).is_file()]
        for path in paths:
            candidate = Path(path)
            index = candidate if candidate.name == 'session.json' else candidate / 'session.json'
            if index.is_file():
                try:
                    self.load_document(index)
                    handled.append(('session', path))
                    self.editor.message = tr('Session loaded: ') + str(index.parent)
                except Exception as exc:
                    self.jobs.error = tr('Session load failed: ') + str(exc)
            elif candidate.suffix.lower() == '.json' and candidate.is_file():
                try:
                    self.workflows.load(candidate)
                    self.select_tab('Workflows')
                    handled.append(('workflow', path))
                except Exception as exc:
                    self.jobs.error = str(exc)
        if not audio:
            return handled
        geometry = self.timeline.drop_geometry
        target = self.inserts.drop_target_node()
        if target is not None and geometry is not None and mouse.y > geometry['y1']:
            target['params']['impulse_response'] = audio[0]
            self.document.touch()
            handled.append(('impulse_response', audio[0]))
            self.editor.message = tr('Impulse response set: ') + Path(audio[0]).name
            return handled
        document = self.document
        seconds, insert_after = document.cursor, None
        if geometry is not None and geometry['x0'] <= mouse.x <= geometry['x1'] and geometry['y0'] <= mouse.y <= geometry['y1']:
            if mouse.x >= geometry['lane_x0']:
                seconds = max(0.0, geometry['start'] + (mouse.x - geometry['lane_x0']) / geometry['lane_width'] * geometry['span'])
            for track_id, top, bottom in geometry['rows']:
                if top <= mouse.y < bottom:
                    insert_after = track_id
        for path in audio:
            hovered = document.track(insert_after) if insert_after else None
            if hovered is not None and hovered.frames == 0:
                # an empty track (the + button) takes the sound and keeps its inserts
                try:
                    samples, rate = audio_io.load(path)
                    document.fill_track(hovered, samples, rate, offset_seconds=seconds, source=path)
                    hovered.name = Path(path).stem if hovered.name.startswith('Track ') else hovered.name
                    handled.append(('track', path))
                    continue
                except Exception as exc:
                    self.jobs.error = f'{Path(path).name}: {exc}'
                    continue
            try:
                track = document.import_file(path, offset_seconds=seconds)
            except Exception as exc:
                self.jobs.error = f'{Path(path).name}: {exc}'
                continue
            if insert_after is not None:
                position = next((i for i, t in enumerate(document.tracks) if t.id == insert_after), None)
                if position is not None:
                    document.tracks.remove(track)
                    document.tracks.insert(position + 1, track)
                    document.selected_track = position + 1
                    insert_after = track.id
            handled.append(('track', path))
        if handled:
            self.select_tab('Editor')
            self.editor.message = tr('Dropped: ') + ', '.join(Path(p).name for kind, p in handled if kind == 'track') + ' @ ' + '%.2f s' % seconds
            if self.timeline.view[1] < document.duration:
                self.timeline.fit(document)
        return handled

    def open_folder(self, folder):
        try:
            if sys.platform == 'win32':
                os.startfile(str(folder))
            else:
                subprocess.Popen(['xdg-open', str(folder)])
        except OSError:
            pass

    # ------------------------------------------------------------------ preview
    def preview_audio(self, audio, samplerate):
        """Play a buffer once through a throw-away document (effect preview, results)."""
        if self.preview_player is not None:
            self.preview_player.close()
        document = Document(samplerate)
        document.add_track(audio, 'preview', samplerate=samplerate, record=False)
        self.preview_player = Player(document)
        self.preview_player.output_device = self.player.output_device
        self.preview_player.play(0.0)

    def preview_file(self, path):
        try:
            audio, rate = audio_io.load(path)
            self.preview_audio(audio, rate)
        except Exception as exc:
            self.jobs.error = str(exc)

    def stop_preview(self):
        if self.preview_player is not None:
            self.preview_player.close()
            self.preview_player = None

    # ------------------------------------------------------------------ workflow application
    def export_selection_temp(self):
        document = self.document
        track = document.current_track()
        if track is None:
            self.jobs.error = tr('No track selected')
            return None
        start, stop = document.selection_frames(track)
        a, b = max(0, start - track.offset), min(track.frames, stop - track.offset)
        if b <= a:
            self.jobs.error = tr('Empty selection')
            return None
        folder = DATA / 'sessions' / '_temp'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'selection-{int(time.time())}.wav'
        audio_io.save(path, track.audio[:, a:b], document.samplerate, fmt='wav', subtype='FLOAT')
        return path

    def apply_current_workflow(self, all_tracks=False):
        """Render the Workflows tab chain over the selection of each target track through a job."""
        try:
            workflow = self.workflows.current()
        except Exception as exc:
            self.jobs.error = tr('Workflow is invalid: ') + str(exc)
            return
        if not workflow['nodes']:
            self.jobs.error = tr('The workflow has no node')
            return
        document = self.document
        targets = document.targets(all_tracks)
        if not targets:
            self.jobs.error = tr('No track')
            return
        folder = DATA / 'sessions' / '_temp'
        folder.mkdir(parents=True, exist_ok=True)
        for track in targets:
            start, stop = document.selection_frames(track)
            a, b = max(0, start - track.offset), min(track.frames, stop - track.offset)
            if b <= a:
                continue
            source = folder / f'apply-{track.id}-{int(time.time() * 1000)}.wav'
            audio_io.save(source, track.audio[:, a:b], document.samplerate, fmt='wav', subtype='FLOAT')

            def done(job, track_id=track.id, region=(a, b), source=source):
                try:
                    if job['state'] != 'Completed':
                        return
                    rendered, rate = audio_io.load(job['outputs']['file'])
                    if rate != document.samplerate:
                        rendered = audio_io.resample(rendered, rate, document.samplerate)
                    target = document.track(track_id)
                    if target is None:
                        return
                    document.selected_track = document.tracks.index(target)
                    saved_selection = document.selection
                    document.selection = (document.frame_to_seconds(target.offset + region[0]), document.frame_to_seconds(target.offset + region[1]))
                    document.apply('Workflow ' + workflow['name'], lambda audio, sr: rendered)
                    document.selection = saved_selection
                    self.editor.message = tr('Workflow applied: ') + workflow['name'] + f" ({job['outputs']['report'].get('tailSeconds', 0)} s tail)"
                finally:
                    try:
                        source.unlink()
                    except OSError:
                        pass
            self.jobs.submit('process_audio', {'input': str(source), 'workflow': workflow, 'output_format': 'wav', 'subtype': 'FLOAT'}, done, tr('Apply ') + workflow['name'])

    def batch_process(self, files):
        try:
            workflow = self.workflows.current()
        except Exception as exc:
            self.jobs.error = str(exc)
            return

        def done(job):
            if job['state'] == 'Completed':
                outputs = job['outputs']
                self.workflows.message = tr('Batch finished: ') + f"{outputs['count']} file(s), {len(outputs['failed'])} failed. " + tr('Results are in the job folder.')
                for item in outputs['results']:
                    self.generate.results.insert(0, ('Batch', item['file']))
        self.jobs.submit('batch_process', {'inputs': list(files), 'workflow': workflow, 'output_format': 'wav', 'subtype': 'PCM_24'}, done, tr('Batch'))

    def open_insert_editor(self, owner, node):
        """Plugin window of a VST3 insert: the worker shows it, the captured state is applied to the live instance."""
        def work():
            try:
                host = self.services.dsp()
                snapshot = host.request('editor', {'plugin': node['plugin'], 'plugin_name': node.get('pluginName') or '', 'params': node.get('params', {}), 'state': node.get('state', '')}, timeout=3600)
                node['params'] = snapshot.get('params', node.get('params', {}))
                node['state'] = snapshot.get('state', '')
                self.document.touch()
                self.inserts.message = tr('Plugin state captured from the window')
            except Exception as exc:
                self.jobs.error = tr('Plugin window: ') + str(exc)
        threading.Thread(target=work, daemon=True).start()

    def open_plugin_editor(self, node):
        """Open the native plugin window in the DSP worker; the state is stored in the node afterwards."""
        def work():
            try:
                host = self.services.dsp()
                snapshot = host.request('editor', {'plugin': node['plugin'], 'plugin_name': node.get('pluginName') or '', 'params': node.get('params', {}), 'state': node.get('state', '')}, timeout=3600)
                node['params'] = snapshot.get('params', node.get('params', {}))
                node['state'] = snapshot.get('state', '')
                self.workflows.message = tr('Plugin state captured from the window')
            except Exception as exc:
                self.jobs.error = tr('Plugin window: ') + str(exc)
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ frame
    def draw(self):
        self.frames += 1
        from gui.knobs import Plot
        Plot.new_frame()
        try:
            count = int(native.get_current_context().debug_draw_id_conflicts_count)
            if count:
                self.id_conflicts[self.frames] = count
        except Exception:
            pass
        self.jobs.poll()
        if self.pending_drops:
            self.handle_drops()
        if self.preview_player is not None and not self.preview_player.playing:
            self.stop_preview()
        event = self.dialogs.poll() if self.dialogs.purpose == 'batch' else None
        if event:
            self.batch_process(event[1] if isinstance(event[1], list) else [event[1]])
        if imgui.begin_tab_bar('###audiostudio-tabs'):
            for name in TABS:
                flags = native.TabItemFlags_.set_selected if self.requested_tab == name else 0
                opened, _ = imgui.begin_tab_item(name, flags=flags)
                if opened:
                    getattr(self, {'Editor': 'editor', 'Generate': 'generate', 'Workflows': 'workflows', 'Plugins': 'plugins', 'Models': 'models', 'Updates': 'updates'}[name]).draw()
                    imgui.end_tab_item()
            self.requested_tab = None
            imgui.end_tab_bar()
        if self.frames % 120 == 0:
            self.player.renderer.prune()
        self._status_bar()
        self._shortcuts()

    def _status_bar(self):
        running = self.jobs.running()
        if running:
            job = running[0]
            progress = job.get('progress') or {}
            imgui.progress_bar(float(progress.get('percent', 0)) / 100.0, (260, 0), self.jobs.progress_text(job)[:70])
            imgui.same_line()
            if len(running) > 1:
                imgui.text_disabled(f'+{len(running) - 1}')
                imgui.same_line()
            if imgui.small_button(tr('Cancel') + '##status'):
                self.jobs.cancel(job['jobId'])
            imgui.same_line()
        if self.jobs.error:
            imgui.text_colored((1.0, 0.45, 0.4, 1.0), self.jobs.error[:200])
        elif self.jobs.message:
            imgui.text_disabled(self.jobs.message[:200])

    def _shortcuts(self):
        io = native.get_io()
        if io.want_text_input:
            return
        document, player = self.document, self.player
        if native.is_key_pressed(native.Key.space):
            player.toggle()
        if io.key_ctrl and native.is_key_pressed(native.Key.z):
            document.undo()
        if io.key_ctrl and native.is_key_pressed(native.Key.y):
            document.redo()
        if io.key_ctrl and native.is_key_pressed(native.Key.x):
            document.cut()
        if io.key_ctrl and native.is_key_pressed(native.Key.c):
            document.copy()
        if io.key_ctrl and native.is_key_pressed(native.Key.v):
            document.paste()
        if native.is_key_pressed(native.Key.delete):
            document.delete(all_tracks=io.key_shift)
        if native.is_key_pressed(native.Key.home):
            document.cursor = 0.0
            player.seek(0.0)
        if native.is_key_pressed(native.Key.escape):
            document.selection = None
            self.stop_preview()
        if native.is_key_pressed(native.Key.h) and not io.key_ctrl:
            self.timeline.hand_tool = not self.timeline.hand_tool
        if native.is_key_pressed(native.Key.f) and not io.key_ctrl:
            self.editor.show_inserts = not self.editor.show_inserts

    def close(self):
        self.stop_preview()
        self.player.close()
        self.jobs.cancel_all()


def _editor_scenario(app, test_file, scenario):
    """Scripted editor session for evidence: import, effects, undo, playback, session, workflow job."""
    from audiostudio.dsp import effects
    frame = app.frames
    document = app.document
    if frame == 3:
        app.editor.import_files([test_file])
        scenario['imported'] = [(t.name, t.frames, t.channels) for t in document.tracks]
        scenario['samplerate'] = document.samplerate
    elif frame == 6 and document.tracks:
        document.selection = (0.2, min(0.8, document.duration))
        before = document.tracks[0].frames
        document.apply('gain', lambda a, sr: effects.apply_effect('gain', a, sr, {'gain_db': -6.0}))
        scenario['gainApplied'] = {'framesBefore': before, 'framesAfter': document.tracks[0].frames}
    elif frame == 9 and document.tracks:
        before = document.tracks[0].frames
        from audiostudio.dsp.tail import trim, TailSettings

        def reverb(audio, rate):
            extended = np.concatenate([audio, np.zeros((audio.shape[0], int(rate * 5)), np.float32)], axis=1)
            out = effects.apply_effect('reverb', extended, rate, {'room_size': 0.9, 'wet_level': 0.6})
            return trim(out, rate, TailSettings(True, -60.0, 5.0, 0.1), audio.shape[1])
        document.apply('Reverb', reverb)
        scenario['reverbApplied'] = {'framesBefore': before, 'framesAfter': document.tracks[0].frames, 'tailFrames': document.tracks[0].frames - before}
    elif frame == 12 and document.tracks:
        label = document.undo()
        scenario['undo'] = {'label': label, 'framesAfterUndo': document.tracks[0].frames}
    elif frame == 15 and document.tracks:
        app.player.play(0.0)
        scenario['playStarted'] = {'playing': app.player.playing, 'error': app.player.error, 'device': app.player.output_device}
    elif frame == 60:
        scenario['playhead'] = {'position': app.player.position, 'playing': app.player.playing, 'peak': app.player.peak}
        app.player.stop()
        path = document.save_session(DATA / 'sessions' / 'ui-test')
        scenario['session'] = str(path)
    elif frame == 63:
        try:
            app.workflows.load(DATA / 'workflows' / 'test-chain.json')
            document.selection = (0.0, min(0.5, document.duration))
            app.apply_current_workflow(all_tracks=False)
            scenario['workflowSubmitted'] = True
        except Exception as exc:
            scenario['workflowSubmitted'] = str(exc)
    elif frame > 63 and 'workflowApplied' not in scenario:
        scenario.setdefault('waitStart', time.time())
        if app.editor.message.startswith(tr('Workflow applied')):
            scenario['workflowApplied'] = {'message': app.editor.message, 'frames': document.tracks[0].frames if document.tracks else 0, 'seconds': time.time() - scenario['waitStart']}
        elif app.jobs.error:
            scenario['workflowApplied'] = {'error': app.jobs.error}
        elif time.time() - scenario['waitStart'] > 120:
            scenario['workflowApplied'] = {'timeout': True}
        else:
            app.frames = 70  # hold the frame counter until the job reports, then exit


def main():
    ensure_data_layout()
    jobs_dir = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--jobs-dir=')), str(DATA / 'jobs'))
    runner = hello_imgui.RunnerParams()
    runner.app_window_params.window_title = 'CyTools AudioStudio'
    runner.app_window_params.window_geometry.size = (1500, 940)
    size = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ui-window=')), None)
    if size:
        w, h = (int(x) for x in size.lower().split('x'))
        runner.app_window_params.window_geometry.size = (w, h)
    runner.ini_filename = str(DATA / 'settings' / 'imgui.ini')
    runner.fps_idling.enable_idling = False
    smoke = '--smoke-test' in sys.argv
    interactions = '--ui-test-interactions' in sys.argv
    all_effects = '--ui-test-all-effects' in sys.argv
    if interactions or all_effects:
        runner.use_imgui_test_engine = True
    test_tab = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ui-test-tab=')), None)
    with create_runtime(Path(jobs_dir)) as runtime:
        actor = runtime.authenticate(runtime.create_client('ImGui', permissions=('network',))['token'])
        session = runtime.create_session(actor, temporary=False)['sessionId']
        app = App(runtime, actor, session)
        if test_tab:
            app.requested_tab = test_tab
        demo = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ui-demo-files=')), None)
        if demo:
            app.editor.import_files([f for f in demo.split(';') if f], at_cursor=False)
            for index, track in enumerate(app.document.tracks):
                track.offset = app.document.seconds_to_frame(index * 1.5)
            app.timeline.fit(app.document)
            app.document.selected_track = 0
            app.document.selection = (0.4, 2.2)
            if len(app.document.tracks) >= 2:
                app.document.set_fade(app.document.tracks[1], 'in', 0.6, record=False)
                app.document.set_fade(app.document.tracks[1], 'out', 0.8, record=False)
            if len(app.document.tracks) >= 3:
                third = app.document.tracks[2]
                app.document.resize_clip(third, 'left', app.document.frame_to_seconds(third.offset) + 2.0, record=False)
                app.document.resize_clip(third, 'right', app.document.frame_to_seconds(third.offset) + 9.0, record=False)
            if '--ui-demo-inserts' in sys.argv and app.document.tracks:
                from audiostudio.workflow import model as workflow_model
                first = app.document.tracks[0]
                comp = app.document.add_insert(first, workflow_model.new_node('effect', effect='compressor', params={'threshold_db': -24.0, 'ratio': 4.0}))
                app.document.add_insert(first, workflow_model.new_node('effect', effect='parametric_eq', params={'b2_gain': 4.0, 'b5_gain': -3.0}))
                app.document.add_insert(app.document.master, workflow_model.new_node('effect', effect='ir_reverb', params={'mix': 0.25}))
                app.document.automation_add(first, 'gain_db', 0.0, 0.0, record=False)
                app.document.automation_add(first, 'gain_db', 1.5, -18.0, record=False)
                app.document.automation_add(first, 'gain_db', 3.0, -3.0, record=False)
                first.automation_view = 'gain_db'
                app.inserts.show(first)
                app.inserts.selected[first.id] = comp['id']
                demo_node = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ui-demo-effect=')), None)
                if demo_node:
                    node = app.document.add_insert(first, workflow_model.new_node('effect', effect=demo_node))
                    app.inserts.selected[first.id] = node['id']
                app.player.play(0.0)
        voices_demo = '--ui-demo-clone' in sys.argv
        if voices_demo:
            app.generate.voice.update({'backend': 1, 'qwen_mode': 1, 'qwen_model': 2, 'reference': str(DATA / 'reports' / 'smoke-piper.wav'),
                                       'reference_text': 'Bonjour, ceci est un test de la voix Piper dans AudioStudio.'})
            app.test_subtab = 'Voices'

        test_file = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ui-test-file=')), None)
        scenario = {}
        recorder = None
        if interactions or all_effects:
            from gui import interaction_tests
            recorder = interaction_tests.Recorder('ui-all-effects.json' if all_effects else 'ui-interactions.json')

            def register_tests():
                engine = hello_imgui.get_imgui_test_engine()
                io = native.test_engine.get_io(engine)
                io.config_run_speed = native.test_engine.TestRunSpeed.fast
                if all_effects:
                    interaction_tests.register_all_effects(app, runner, recorder)
                else:
                    interaction_tests.register(app, runner, recorder)
            runner.callbacks.register_tests = register_tests

        def gui():
            app.draw()
            if recorder is not None:
                if recorder.done:
                    summary = recorder.save()
                    print(json.dumps({'passed': summary['passed'], 'failed': summary['failed']}))
                    runner.app_shall_exit = True
                return
            if test_tab and app.frames == 2:
                app.requested_tab = test_tab
            if test_tab == 'Generate' and 4 <= app.frames <= 11 and '--ui-demo-clone' not in sys.argv:
                # Render every generation form once (each sub-tab has its own widgets).
                app.test_subtab = 'Music' if app.frames < 8 else 'Voices'
                if app.frames == 9:
                    app.generate.voice['backend'] = 0
                elif app.frames == 10:
                    app.generate.voice['backend'] = 2
                elif app.frames == 11:
                    app.generate.voice['backend'] = 3
                app.generate.music['mode'] = min(3, app.frames - 4)
            if test_file:
                _editor_scenario(app, test_file, scenario)
                if app.frames > 90:
                    reports = DATA / 'reports'
                    reports.mkdir(parents=True, exist_ok=True)
                    scenario['frames'] = app.frames
                    (reports / 'ui-editor-scenario.json').write_text(json.dumps(scenario, indent=2, default=str), 'utf-8')
                    runner.app_shall_exit = True
                return
            if (smoke or test_tab) and app.frames > 12:
                reports = DATA / 'reports'
                reports.mkdir(parents=True, exist_ok=True)
                (reports / f"ui-smoke-{test_tab or 'editor'}.json").write_text(json.dumps({'frames': app.frames, 'tab': test_tab or 'Editor', 'tracks': len(app.document.tracks), 'closed': True,
                                                                                            'idConflictFrames': len(app.id_conflicts)}), 'utf-8')
                runner.app_shall_exit = True

        def capture_config():
            operation, backend, params = app.generate._voice_parameters()
            if operation:
                return {'operationId': operation, 'parameters': params}
            s = app.generate.sfx
            return {'operationId': 'generate_sfx', 'parameters': {'prompt': s['prompt'], 'seed': max(0, s['seed']), 'variations': s['variations']},
                    'backendId': ['sfx_procedural', 'audioldm'][s['backend']]}

        def restore_config(value):
            params = value.get('parameters', {})
            if value.get('operationId') == 'generate_sfx':
                app.generate.sfx.update({'prompt': params.get('prompt', ''), 'seed': params.get('seed', 0), 'variations': params.get('variations', 1),
                                         'backend': 1 if value.get('backendId') == 'audioldm' else 0})
                app.requested_tab = 'Generate'
            elif value.get('operationId', '').startswith('voice_'):
                v = app.generate.voice
                v['text'] = params.get('text', v['text'])
                v['backend'] = {'voice_piper': 0, 'voice_qwen3tts': 1, 'voice_fishspeech': 2}.get(value['operationId'], v['backend'])
                if 'model' in params and params['model'] in ('1.7B-CustomVoice', '0.6B-CustomVoice', '1.7B-Base', '0.6B-Base', '1.7B-VoiceDesign'):
                    v['qwen_model'] = ['1.7B-CustomVoice', '0.6B-CustomVoice', '1.7B-Base', '0.6B-Base', '1.7B-VoiceDesign'].index(params['model'])
                v['instruction'] = params.get('instruction', v['instruction'])
                v['seed'] = params.get('seed', v['seed'])
                app.requested_tab = 'Generate'
        configure_generation(runtime, capture_config, restore_config)

        def install_file_drop():
            # imgui-bundle ships GLFW as a shared library that the glfw package reuses: callbacks are safe
            try:
                import glfw
                from imgui_bundle import glfw_utils
                window = glfw_utils.glfw_window_hello_imgui()
                app._drop_callback = lambda _window, paths: app.on_files_dropped(list(paths))
                glfw.set_drop_callback(window, app._drop_callback)
                app.drop_ready = True
            except Exception as exc:
                app.drop_error = str(exc)
        runner.callbacks.post_init = install_file_drop
        runner.callbacks.show_gui = gui
        try:
            run(runner)
        finally:
            app.close()
            try:
                runtime.services.pool.stop_all()
            except Exception:
                pass
        if smoke or test_tab:
            try:
                from standalone_log import save_screenshot
                pixels = hello_imgui.final_app_window_screenshot()
                if pixels.size:
                    save_screenshot(DATA / 'reports' / f"ui-{(test_tab or 'editor').lower()}-{preferences.values['language']}.png", pixels)
            except Exception as exc:
                (DATA / 'reports' / 'ui-screenshot-error.txt').write_text(str(exc), 'utf-8')


if __name__ == '__main__':
    main()
