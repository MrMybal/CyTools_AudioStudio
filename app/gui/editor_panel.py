"""Editor tab: transport, file actions, edit actions, effects on the selection, workflow apply,
and the inserts panel (track / master effect chains) under the timeline."""
from pathlib import Path
import threading
import time

import numpy as np
from imgui_bundle import imgui

from audiostudio.paths import SESSIONS, DATA
from audiostudio.dsp import effects
from audiostudio import audio_io
from .widgets import draw_effect_params, status_line, Row
from .timeline import clock

SESSION_FILTER = ['AudioStudio session', '*.json']
EXPORT_FORMATS = ['wav', 'flac', 'mp3', 'ogg', 'aac']
SUBTYPES = ['PCM_16', 'PCM_24', 'PCM_32', 'FLOAT']


class EditorPanel:
    def __init__(self, app):
        self.app = app
        self.effect_index = 0
        self.effect_values = {}
        self.effect_open = False
        self.preview_thread = None
        self.export_format = 0
        self.export_subtype = 1
        self.export_bitrate = 4
        self.export_selection_only = False
        self.silence_seconds = 1.0
        self.record_channels = 1
        self.message = ''
        self.workflow_job = None
        self.workflow_apply_all = False
        self.pending_import = []
        self.show_inserts = True
        self.inserts_height = 300.0
        self.splitting = None
        self.exporting = None                 # thread while an export renders
        self.export_progress = 0.0

    # ------------------------------------------------------------------ helpers
    @property
    def document(self):
        return self.app.document

    @property
    def player(self):
        return self.app.player

    def tr(self, text):
        return self.app.tr(text)

    def import_files(self, paths, at_cursor=True):
        for path in paths:
            try:
                track = self.document.import_file(path, offset_seconds=self.document.cursor if at_cursor else 0.0)
                self.message = self.tr('Imported ') + track.name
            except Exception as exc:
                self.app.jobs.error = f'{Path(path).name}: {exc}'
        self.app.timeline.fit(self.document)

    def export(self, path):
        """Render the mix (inserts, automation, master, tail) on a thread and encode it."""
        document = self.document
        fmt = EXPORT_FORMATS[self.export_format]
        target = Path(path)
        if target.suffix.lower() != audio_io.WRITE_FORMATS[fmt]['suffix']:
            target = target.with_suffix(audio_io.WRITE_FORMATS[fmt]['suffix'])
        selection = sorted(document.selection) if (document.selection and self.export_selection_only) else None
        subtype = SUBTYPES[self.export_subtype] if fmt in ('wav', 'flac') else None
        bitrate = audio_io.LOSSY_BITRATES[self.export_bitrate]
        self.message = self.tr('Exporting...')
        self.export_progress = 0.0

        def work():
            try:
                progress = lambda fraction: setattr(self, 'export_progress', fraction)
                audio = document.mixdown(selection[0], selection[1], progress=progress) if selection else document.mixdown(progress=progress)
                audio_io.save(target, audio, document.samplerate, fmt=fmt, subtype=subtype, bitrate_kbps=bitrate)
                tail = max(0.0, audio.shape[1] / document.samplerate - ((selection[1] - selection[0]) if selection else document.duration))
                self.message = self.tr('Exported ') + str(target) + ((' (%s %.2f s)' % (self.tr('tail'), tail)) if tail > 0.01 else '')
                self.app.last_export = str(target)
            except Exception as exc:
                self.app.jobs.error = self.tr('Export failed: ') + str(exc)
            finally:
                self.exporting = None
        self.exporting = threading.Thread(target=work, daemon=True)
        self.exporting.start()

    # ------------------------------------------------------------------ drawing
    def draw(self):
        tr = self.tr
        document, player = self.document, self.player
        self._toolbar()
        self._transport()
        imgui.separator()
        avail = imgui.get_content_region_avail().y
        reserved = 90.0 + (150.0 if self.effect_open else 0.0)
        if self.show_inserts:
            self.inserts_height = float(np.clip(self.inserts_height, 160.0, max(160.0, avail - reserved - 160.0)))
            reserved += self.inserts_height + 8
        self.app.timeline.draw(document, player, tr, height=max(160.0, avail - reserved), app=self.app)
        if self.show_inserts:
            self._splitter()
            self.app.inserts.draw(self.inserts_height)
        imgui.separator()
        self._edit_row()
        if self.effect_open:
            self._effect_dialog()
        if self.exporting is not None:
            imgui.progress_bar(float(self.export_progress), (260, 0), tr('Exporting...'))
        elif self.message:
            status_line(self.message)

    def _splitter(self):
        """Drag handle between the timeline and the inserts panel."""
        imgui.invisible_button('inserts-splitter', (-1, 6))
        if imgui.is_item_hovered() or imgui.is_item_active():
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ns)
        if imgui.is_item_activated():
            self.splitting = (self.inserts_height, imgui.get_mouse_pos().y)
        if imgui.is_item_active() and self.splitting is not None:
            self.inserts_height = self.splitting[0] - (imgui.get_mouse_pos().y - self.splitting[1])
        if imgui.is_item_deactivated():
            self.splitting = None
        rect_min, rect_max = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        imgui.get_window_draw_list().add_rect_filled((rect_min.x, rect_min.y + 2), (rect_max.x, rect_max.y - 2), imgui.get_color_u32((0.4, 0.42, 0.5, 0.6)))

    def _toolbar(self):
        tr = self.tr
        dialogs = self.app.dialogs
        row = Row()
        if row.button('Open audio', tr):
            dialogs.open_file('import', tr('Open audio files'), str(DATA / 'inputs'), multiple=True)
        if row.button('Open session', tr):
            dialogs.open_file('session', tr('Open session'), str(SESSIONS), SESSION_FILTER)
        if row.button('Save session', tr):
            if self.document.path:
                self.document.save_session(self.document.path)
                self.message = tr('Session saved: ') + str(self.document.path)
            else:
                dialogs.select_folder('save-session', tr('Choose a folder for the session'), str(SESSIONS))
        if row.button('Save session as', tr):
            dialogs.select_folder('save-session', tr('Choose a folder for the session'), str(SESSIONS))
        if row.button('New', tr):
            self.player.stop()
            self.app.new_document()
        row.text('|', disabled=True)
        _, self.export_format = row.combo('fmt', self.export_format, EXPORT_FORMATS, 70)
        fmt = EXPORT_FORMATS[self.export_format]
        if fmt in ('wav', 'flac'):
            _, self.export_subtype = row.combo('sub', self.export_subtype, SUBTYPES, 90)
        else:
            _, self.export_bitrate = row.combo('br', self.export_bitrate, [f'{b} kbps' for b in audio_io.LOSSY_BITRATES], 90)
        _, self.export_selection_only = row.checkbox('Selection only', self.export_selection_only, tr)
        if row.button('Export mix', tr):
            name = (self.document.name or 'mix') + audio_io.WRITE_FORMATS[fmt]['suffix']
            dialogs.save_file('export', tr('Export mix'), str(DATA / 'exports'), name, ['Audio', '*' + audio_io.WRITE_FORMATS[fmt]['suffix']])
        # dialog results (only the ones this tab opened)
        event = dialogs.poll() if dialogs.purpose in ('import', 'session', 'save-session', 'export') else None
        if event:
            purpose, result = event
            if purpose == 'import':
                self.import_files(result if isinstance(result, list) else [result])
            elif purpose == 'session':
                path = result[0] if isinstance(result, list) else result
                try:
                    self.app.load_document(path)
                    self.message = tr('Session loaded: ') + str(path)
                except Exception as exc:
                    self.app.jobs.error = tr('Session load failed: ') + str(exc)
            elif purpose == 'save-session':
                folder = Path(result)
                if not (folder / 'session.json').exists() and any(folder.iterdir()) if folder.exists() else False:
                    folder = folder / (self.document.name or 'session')
                self.document.save_session(folder)
                self.message = tr('Session saved: ') + str(folder)
            elif purpose == 'export':
                self.export(result)
            elif purpose == 'reference':
                self.app.reference_file = result[0] if isinstance(result, list) else result

    def _transport(self):
        tr = self.tr
        document, player = self.document, self.player
        recording = player.is_recording
        row = Row()
        if row.button('|<', tr):
            player.stop()
            document.cursor = 0.0
            player.seek(0.0)
        if row.button('Pause' if player.playing else 'Play', tr):
            if player.playing:
                player.pause()
            else:
                player.play(document.selection[0] if document.selection and player.frame >= document.seconds_to_frame(document.selection[1]) else None)
        if row.button('Stop', tr):
            player.stop()
        _, player.loop = row.checkbox('Loop selection', player.loop, tr)
        if not recording:
            if row.button('Record', tr):
                try:
                    player.start_recording(channels=self.record_channels + 1)
                    self.message = tr('Recording... press Stop recording to add the take as a new track')
                except Exception as exc:
                    self.app.jobs.error = str(exc)
            _, self.record_channels = row.combo('recch', self.record_channels, [tr('mono'), tr('stereo')], 80)
        else:
            if row.button('Stop recording', tr):
                audio = player.stop_recording()
                if audio is not None and audio.shape[1] > 0:
                    document.add_track(audio, tr('Recording ') + time.strftime('%H-%M-%S'), offset_seconds=document.frame_to_seconds(player.record_started_frame))
                    self.app.timeline.fit(document)
                    self.message = tr('Recording added as a new track')
            row.next(90)
            imgui.text_colored((1.0, 0.3, 0.3, 1.0), tr('REC ') + clock(player.recorded_seconds()))
        row.text(clock(player.position if (player.playing or recording) else document.cursor) + ' / ' + clock(document.duration))
        if document.selection:
            a, b = sorted(document.selection)
            row.text(tr('sel ') + clock(a) + ' - ' + clock(b) + f' ({b - a:.3f}s)', disabled=True)
        row.next(150)
        imgui.push_item_width(90)
        _, player.volume = imgui.slider_float(tr('Vol') + '###vol', player.volume, 0.0, 1.5, '%.2f')
        imgui.pop_item_width()
        peak_l, peak_r = player.peak
        row.next(60)
        imgui.progress_bar(min(1.0, peak_l), (60, 0), '')
        row.next(60)
        imgui.progress_bar(min(1.0, peak_r), (60, 0), '')
        if row.button('Fit', tr):
            self.app.timeline.fit(document)
        if row.button('Zoom sel', tr):
            self.app.timeline.zoom_selection(document)
        if row.button('+', tr):
            self.app.timeline.zoom(0.7)
        if row.button('-', tr):
            self.app.timeline.zoom(1.4)
        _, self.app.timeline.follow = row.checkbox('Follow', self.app.timeline.follow, tr)
        _, self.app.timeline.hand_tool = row.checkbox('Hand', self.app.timeline.hand_tool, tr)
        if imgui.is_item_hovered():
            imgui.set_tooltip(tr('Hand tool: drag the timeline with the left button (H). Right-drag and middle-drag always move the view.'))
        _, self.app.automation_write = row.checkbox('Write automation', self.app.automation_write, tr)
        if imgui.is_item_hovered():
            imgui.set_tooltip(tr('While playing, knob and slider moves are recorded into automation lanes'))
        _, self.show_inserts = row.checkbox('FX panel', self.show_inserts, tr)
        row.next(170)
        imgui.push_item_width(110)
        _, self.app.timeline.vertical_zoom = imgui.slider_float(tr('V. zoom') + '###vzoom', self.app.timeline.vertical_zoom, 0.25, 16.0, 'x%.2f', imgui.SliderFlags_.logarithmic)
        imgui.pop_item_width()
        from .player import BUFFER_SIZES
        sizes = [str(size) for size in BUFFER_SIZES]
        current = sizes.index(str(player.buffer_size)) if str(player.buffer_size) in sizes else 2
        changed, current = row.combo('buffer', current, sizes, 70)
        if changed:
            player.set_buffer_size(BUFFER_SIZES[current])
        if imgui.is_item_hovered():
            imgui.set_tooltip(tr('Audio buffer (frames): smaller = less latency, larger = safer with many effects'))
        if player.playing:
            row.text('%s %d%%' % (tr('DSP'), int(min(999, player.load * 100))), disabled=player.load < 0.7)
        if player.error:
            status_line(player.error, error=True)

    def _edit_row(self):
        tr = self.tr
        document = self.document
        has_sel = document.selection is not None
        row = Row()
        if row.button('Undo', tr):
            label = document.undo()
            self.message = (tr('Undone: ') + label) if label else tr('Nothing to undo')
        if row.button('Redo', tr):
            label = document.redo()
            self.message = (tr('Redone: ') + label) if label else tr('Nothing to redo')
        row.text('|', disabled=True)
        imgui.begin_disabled(not has_sel)
        if row.button('Cut', tr):
            document.cut()
        if row.button('Copy', tr):
            document.copy()
        imgui.end_disabled()
        imgui.begin_disabled(document.clipboard is None)
        if row.button('Paste', tr):
            document.paste()
        imgui.end_disabled()
        imgui.begin_disabled(not has_sel)
        if row.button('Delete', tr):
            document.delete(all_tracks=imgui.get_io().key_shift)
        if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
            imgui.set_tooltip(tr('Delete the selected region (Shift: on every track). To delete a whole clip: X on the track, or right-click the clip.'))
        if row.button('Trim', tr):
            document.trim()
        if row.button('Silence', tr):
            document.silence()
        imgui.end_disabled()
        if row.button('Split at cursor', tr):
            document.split()
        row.next(70)
        imgui.push_item_width(70)
        _, self.silence_seconds = imgui.input_float('##sil', self.silence_seconds, 0.0, 0.0, '%.2f')
        imgui.pop_item_width()
        if row.button('Insert silence', tr):
            document.insert_silence(max(0.0, self.silence_seconds))
        row.text('|', disabled=True)
        names = [spec.name for spec in effects.REGISTRY.values()]
        changed, self.effect_index = row.combo('effect', self.effect_index, [tr(n) for n in names], 180)
        if changed:
            self.effect_values = {}
        if row.button('Effect...', tr):
            self.effect_open = not self.effect_open
        if row.button('Apply workflow to selection', tr):
            self.app.apply_current_workflow(all_tracks=False)
        if imgui.is_item_hovered():
            imgui.set_tooltip(tr('Renders the workflow of the Workflows tab over the selection (or the whole track) with tail rendering, in the DSP worker.'))

    def _effect_dialog(self):
        tr = self.tr
        spec = list(effects.REGISTRY.values())[self.effect_index]
        imgui.begin_child('##effect-dialog', (0, 150), True)
        imgui.text(tr(spec.name) + ' - ' + tr(spec.category))
        if spec.help:
            imgui.text_wrapped(tr(spec.help))
        draw_effect_params(spec, self.effect_values, tr)
        if imgui.button(tr('Apply to selection')):
            self._apply_effect(spec, whole_track=False)
        imgui.same_line()
        if imgui.button(tr('Apply to whole track')):
            self._apply_effect(spec, whole_track=True)
        imgui.same_line()
        if imgui.button(tr('Preview selection')):
            self._preview_effect(spec)
        imgui.same_line()
        if imgui.button(tr('Close')):
            self.effect_open = False
        imgui.end_child()

    def _apply_effect(self, spec, whole_track):
        values = spec.normalize(self.effect_values)
        stateful = spec.build is not None
        document = self.document

        def function(audio, rate):
            if stateful:
                # Give the effect room to decay, then let the document overlap the tail.
                extended = np.concatenate([audio, np.zeros((audio.shape[0], int(rate * 5)), np.float32)], axis=1)
                out = effects.apply_effect(spec.id, extended, rate, values)
                from audiostudio.dsp.tail import trim, TailSettings
                return trim(out, rate, TailSettings(True, -60.0, 5.0, 0.1), audio.shape[1])
            return effects.apply_effect(spec.id, audio, rate, values)
        try:
            if document.apply(spec.name, function, all_tracks=imgui.get_io().key_shift, whole_track=whole_track):
                self.message = self.tr('Applied ') + self.tr(spec.name)
        except Exception as exc:
            self.app.jobs.error = f'{spec.name}: {exc}'

    def _preview_effect(self, spec):
        """Render the selection with the effect into a temporary document and play it."""
        document = self.document
        track = document.current_track()
        if track is None:
            return
        start, stop = document.selection_frames(track)
        a, b = max(0, start - track.offset), min(track.frames, stop - track.offset)
        if b <= a:
            return
        block = np.ascontiguousarray(track.audio[:, a:b])
        values = spec.normalize(self.effect_values)
        try:
            rendered = effects.apply_effect(spec.id, np.concatenate([block, np.zeros((block.shape[0], document.samplerate * 3), np.float32)], axis=1) if spec.build else block, document.samplerate, values)
        except Exception as exc:
            self.app.jobs.error = f'{spec.name}: {exc}'
            return
        self.app.preview_audio(rendered, document.samplerate)
