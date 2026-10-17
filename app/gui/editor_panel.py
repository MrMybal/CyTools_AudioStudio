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
from .widgets import status_line, Row, Toolbar, tooltip
from .knobs import horizontal_meter
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
        self.preview_node = None             # selected effect of the dialog chain
        self.preview_chain = []              # temporary inserts that let the Effect... dialog be heard live
        self.preview_track = None
        self.chain_index = 0
        self.add_index = 0
        self.dialog_rect = None
        self.splitting = None
        self.exporting = None                 # thread while an export renders
        self.export_progress = 0.0
        self.bottom_height = 100.0            # edit bar + status line, measured each frame

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
        avail = imgui.get_content_region_avail().y
        reserved = self.bottom_height + 8.0            # edit bar and status line, measured at the previous frame
        if self.show_inserts:
            self.inserts_height = float(np.clip(self.inserts_height, 200.0, max(200.0, avail - reserved - 160.0)))
            reserved += self.inserts_height + 8
        self.app.timeline.draw(document, player, tr, height=max(160.0, avail - reserved), app=self.app)
        if self.show_inserts:
            # effects always belong to a track or to the master bus: the FX panel shows the chain of one of them
            self._splitter()
            self.app.inserts.draw(self.inserts_height)
        imgui.separator()
        top = imgui.get_cursor_screen_pos().y
        self._edit_row()
        if self.exporting is not None:
            imgui.progress_bar(float(self.export_progress), (260, 0), tr('Exporting...'))
        elif self.message:
            status_line(self.message)
        self.bottom_height = max(60.0, imgui.get_cursor_screen_pos().y - top + imgui.get_frame_height())

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

    def _button(self, label, tip, enabled=True):
        """A toolbar button: translated label, stable identity (``visible###identity``), tooltip."""
        visible, _, identity = label.partition('###')
        imgui.begin_disabled(not enabled)
        clicked = imgui.button(self.tr(visible) + '###' + (identity or visible))
        imgui.end_disabled()
        tooltip(self.tr(tip))
        return clicked

    def _check(self, label, value, tip):
        visible, _, identity = label.partition('###')
        _, value = imgui.checkbox(self.tr(visible) + '###' + (identity or visible), value)
        tooltip(self.tr(tip))
        return value

    def _combo(self, key, index, items, width, tip):
        imgui.push_item_width(width)
        _, index = imgui.combo('##' + key, index, items)
        imgui.pop_item_width()
        tooltip(self.tr(tip))
        return index

    def _toolbar(self):
        """The bar above the timeline: one framed, titled group per job."""
        tr = self.tr
        dialogs = self.app.dialogs
        document, player = self.document, self.player
        timeline = self.app.timeline
        bar = Toolbar()
        with bar.group('session', tr('Session')):
            if self._button('Open audio...###Open audio', 'Add audio files as new tracks at the cursor'):
                dialogs.open_file('import', tr('Open audio files'), str(DATA / 'inputs'), multiple=True)
            imgui.same_line()
            if self._button('Open...###Open session', 'Open a saved session (folder with session.json)'):
                dialogs.open_file('session', tr('Open session'), str(SESSIONS), SESSION_FILTER)
            imgui.same_line()
            if self._button('Save###Save session', 'Save the session (tracks, clips, effects, automation)'):
                if document.path:
                    document.save_session(document.path)
                    self.message = tr('Session saved: ') + str(document.path)
                else:
                    dialogs.select_folder('save-session', tr('Choose a folder for the session'), str(SESSIONS))
            imgui.same_line()
            if self._button('Save as...###Save session as', 'Save the session in another folder'):
                dialogs.select_folder('save-session', tr('Choose a folder for the session'), str(SESSIONS))
            imgui.same_line()
            if self._button('New', 'Close this session and start an empty one'):
                player.stop()
                self.app.new_document()

        with bar.group('transport', tr('Transport')):
            recording = player.is_recording
            if self._button('|<', 'Back to the start'):
                player.stop()
                document.cursor = 0.0
                player.seek(0.0)
            imgui.same_line()
            if self._button(('Pause' if player.playing else 'Play') + '###Play', 'Play from the cursor (Space)' if not player.playing else 'Pause'):
                if player.playing:
                    player.pause()
                else:
                    player.play(document.selection[0] if document.selection and player.frame >= document.seconds_to_frame(document.selection[1]) else None)
            imgui.same_line()
            if self._button('Stop', 'Stop and go back to the cursor'):
                player.stop()
            imgui.same_line()
            if not recording:
                imgui.push_style_color(imgui.Col_.button, (0.55, 0.16, 0.16, 1.0))
                clicked = self._button('Rec###Record', 'Record from the microphone; the take becomes a new track')
                imgui.pop_style_color()
                if clicked:
                    try:
                        player.start_recording(channels=self.record_channels + 1)
                        self.message = tr('Recording... press Stop recording to add the take as a new track')
                    except Exception as exc:
                        self.app.jobs.error = str(exc)
                imgui.same_line()
                self.record_channels = self._combo('recch', self.record_channels, [tr('mono'), tr('stereo')], 75, 'Channels recorded from the microphone')
            else:
                if self._button('Stop recording', 'Add the take as a new track'):
                    audio = player.stop_recording()
                    if audio is not None and audio.shape[1] > 0:
                        document.add_track(audio, tr('Recording ') + time.strftime('%H-%M-%S'), offset_seconds=document.frame_to_seconds(player.record_started_frame))
                        timeline.fit(document)
                        self.message = tr('Recording added as a new track')
                imgui.same_line()
                imgui.text_colored((1.0, 0.3, 0.3, 1.0), tr('REC ') + clock(player.recorded_seconds()))
            imgui.same_line()
            player.loop = self._check('Loop###Loop selection', player.loop, 'Repeat the selection while playing')
            imgui.same_line(0, 14)
            position = player.position if (player.playing or recording) else document.cursor
            imgui.text_colored((0.55, 0.85, 1.0, 1.0), clock(position))
            tooltip(tr('Position (cursor or playhead)'))
            imgui.same_line()
            imgui.text_disabled('/ ' + clock(document.duration))
            tooltip(tr('Length of the session'))
            # fixed room for the selection, so the bar does not jump when a selection appears
            imgui.same_line(0, 10)
            room = imgui.calc_text_size(tr('Selection') + ' 00:00.000 - 00:00.000 (000.000 s)').x
            place = imgui.get_cursor_screen_pos()
            imgui.dummy((room, imgui.get_frame_height()))
            if document.selection:
                a, b = sorted(document.selection)
                text = tr('Selection') + f' {clock(a)} - {clock(b)} ({b - a:.3f} s)'
                imgui.get_window_draw_list().add_text((place.x, place.y + imgui.get_style().frame_padding.y), imgui.get_color_u32((0.45, 0.65, 1.0, 1.0)), text)
                tooltip(text)

        with bar.group('output', tr('Output')):
            imgui.push_item_width(110)
            _, player.volume = imgui.slider_float('##vol', player.volume, 0.0, 1.5, tr('Volume') + ' %.2f')
            imgui.pop_item_width()
            tooltip(tr('Listening volume (not part of the mix or the export)'))
            imgui.same_line()
            peak_l, peak_r = player.peak
            horizontal_meter(peak_l, peak_r, 90.0, max(4.0, (imgui.get_frame_height() - 2) / 2))
            tooltip(tr('Output level, left and right (green / yellow above -12 dB / red above -3 dB)'))
            if player.playing:
                imgui.same_line()
                imgui.text_disabled('%s %d%%' % (tr('DSP'), int(min(999, player.load * 100))))
                tooltip(tr('Time spent computing the audio, in percent of the buffer duration'))

        with bar.group('view', tr('View')):
            if self._button('Fit###Fit', 'Show the whole session'):
                timeline.fit(document)
            imgui.same_line()
            if self._button('Selection###Zoom sel', 'Zoom on the selection', enabled=bool(document.selection)):
                timeline.zoom_selection(document)
            imgui.same_line()
            if self._button(' + ###+', 'Zoom in (mouse wheel over the tracks)'):
                timeline.zoom(0.7)
            imgui.same_line()
            if self._button(' - ###-', 'Zoom out'):
                timeline.zoom(1.4)
            imgui.same_line()
            imgui.push_item_width(120)
            _, timeline.vertical_zoom = imgui.slider_float('##vzoom', timeline.vertical_zoom, 0.25, 16.0, tr('Height') + ' x%.2f', imgui.SliderFlags_.logarithmic)
            imgui.pop_item_width()
            tooltip(tr('Waveform height (Ctrl + wheel over the tracks)'))
            imgui.same_line()
            timeline.follow = self._check('Follow###Follow', timeline.follow, 'Keep the playhead in view while playing')
            imgui.same_line()
            timeline.hand_tool = self._check('Hand###Hand', timeline.hand_tool,
                                             'Hand tool: drag the timeline with the left button (H). Right-drag and middle-drag always move the view.')

        with bar.group('options', tr('Options')):
            self.show_inserts = self._check('Effects panel###FX panel', self.show_inserts, 'Show the effects (inserts) of the selected track or of the master under the timeline')
            imgui.same_line()
            self.app.automation_write = self._check('Write automation', self.app.automation_write, 'While playing, knob and slider moves are recorded into automation lanes')
            imgui.same_line()
            from .player import BUFFER_SIZES
            sizes = [str(size) for size in BUFFER_SIZES]
            current = sizes.index(str(player.buffer_size)) if str(player.buffer_size) in sizes else 2
            imgui.text_disabled(tr('Buffer'))
            imgui.same_line()
            chosen = self._combo('buffer', current, sizes, 70, 'Audio buffer (frames): smaller = less latency, larger = safer with many effects')
            if chosen != current:
                player.set_buffer_size(BUFFER_SIZES[chosen])

        with bar.group('export', tr('Export')):
            self.export_format = self._combo('fmt', self.export_format, EXPORT_FORMATS, 65, 'File format of the exported mix')
            fmt = EXPORT_FORMATS[self.export_format]
            imgui.same_line()
            if fmt in ('wav', 'flac'):
                self.export_subtype = self._combo('sub', self.export_subtype, SUBTYPES, 85, 'Sample format (bit depth)')
            else:
                self.export_bitrate = self._combo('br', self.export_bitrate, [f'{b} kbps' for b in audio_io.LOSSY_BITRATES], 85, 'Bitrate')
            imgui.same_line()
            self.export_selection_only = self._check('Selection only', self.export_selection_only, 'Export only the selected time range')
            imgui.same_line()
            if self._button('Export mix...###Export mix', 'Render the mix (effects, automation, master, reverb tails) to a file'):
                name = (document.name or 'mix') + audio_io.WRITE_FORMATS[fmt]['suffix']
                dialogs.save_file('export', tr('Export mix'), str(DATA / 'exports'), name, ['Audio', '*' + audio_io.WRITE_FORMATS[fmt]['suffix']])
        if player.error:
            status_line(player.error, error=True)

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
                    folder = folder / (document.name or 'session')
                document.save_session(folder)
                self.message = tr('Session saved: ') + str(folder)
            elif purpose == 'export':
                self.export(result)
            elif purpose == 'reference':
                self.app.reference_file = result[0] if isinstance(result, list) else result

    def _edit_row(self):
        tr = self.tr
        document = self.document
        has_sel = document.selection is not None
        bar = Toolbar()
        with bar.group('history', tr('History')):
            if self._button('Undo', 'Undo the last edit (Ctrl+Z)', enabled=bool(document.undo_stack)):
                label = document.undo()
                self.message = (tr('Undone: ') + label) if label else tr('Nothing to undo')
            imgui.same_line()
            if self._button('Redo', 'Redo (Ctrl+Y)', enabled=bool(document.redo_stack)):
                label = document.redo()
                self.message = (tr('Redone: ') + label) if label else tr('Nothing to redo')
        with bar.group('edit', tr('Edit the selection')):
            if self._button('Cut', 'Cut the selection of the selected track', enabled=has_sel):
                document.cut()
            imgui.same_line()
            if self._button('Copy', 'Copy the selection of the selected track', enabled=has_sel):
                document.copy()
            imgui.same_line()
            if self._button('Paste', 'Insert the copied audio at the cursor or the selection start', enabled=document.clipboard is not None):
                document.paste()
            imgui.same_line()
            if self._button('Delete', 'Delete the selected region (Shift: on every track). To delete a whole clip: right-click it.', enabled=has_sel):
                document.delete(all_tracks=imgui.get_io().key_shift)
            imgui.same_line()
            if self._button('Trim', 'Keep only the selection', enabled=has_sel):
                document.trim()
            imgui.same_line()
            if self._button('Silence', 'Replace the selection by silence', enabled=has_sel):
                document.silence()
        with bar.group('clips', tr('Clips')):
            if self._button('Split at cursor', 'Cut the clip under the cursor in two clips of the same track'):
                document.split()
            imgui.same_line()
            imgui.push_item_width(70)
            _, self.silence_seconds = imgui.input_float('##sil', self.silence_seconds, 0.0, 0.0, '%.2f s')
            imgui.pop_item_width()
            tooltip(tr('Length of the silence to insert'))
            imgui.same_line()
            if self._button('Insert silence', 'Insert silence at the cursor; what follows moves later'):
                document.insert_silence(max(0.0, self.silence_seconds))
