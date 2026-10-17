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
from . import cyui
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
        self.bottom_height = 40.0             # edit bar, measured each frame
        self.fit_correction = 20.0            # item spacings below the timeline, measured each frame

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
        reserved = self.bottom_height + self.fit_correction     # edit bar and spacings, measured at the previous frame
        if self.show_inserts:
            self.inserts_height = float(np.clip(self.inserts_height, 200.0, max(200.0, avail - reserved - 160.0)))
            reserved += self.inserts_height + 8
        self.app.timeline.draw(document, player, tr, height=max(160.0, avail - reserved), app=self.app)
        if self.show_inserts:
            # effects always belong to a track or to the master bus: the FX panel shows the chain of one of them
            self._splitter()
            self.app.inserts.draw(self.inserts_height)
        top = imgui.get_cursor_screen_pos().y
        self._edit_row()
        self.bottom_height = max(30.0, imgui.get_cursor_screen_pos().y - top)
        # what still overflows (or is left free) at the bottom of the tab corrects the next frame
        # (damped, and only from frames where the bar was really laid out, so it cannot run away)
        bottom = imgui.get_window_pos().y + imgui.get_window_size().y - imgui.get_style().window_padding.y
        overflow = imgui.get_cursor_screen_pos().y - bottom
        if abs(overflow) > 1.0 and self.bottom_height > imgui.get_frame_height() and imgui.get_window_size().y > 300:
            self.fit_correction = float(np.clip(self.fit_correction + overflow * 0.5, 0.0, 120.0))

    def status(self):
        """(text, tone, progress) for the application status bar."""
        if self.exporting is not None:
            return self.tr('Exporting...'), cyui.ACCENT, float(self.export_progress)
        return self.message, cyui.NEUTRAL, None

    def _splitter(self):
        """Drag handle between the timeline and the inserts panel."""
        imgui.invisible_button('inserts-splitter', (-1, 6))
        hot = imgui.is_item_hovered() or imgui.is_item_active()
        if hot:
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ns)
        if imgui.is_item_activated():
            self.splitting = (self.inserts_height, imgui.get_mouse_pos().y)
        if imgui.is_item_active() and self.splitting is not None:
            self.inserts_height = self.splitting[0] - (imgui.get_mouse_pos().y - self.splitting[1])
        if imgui.is_item_deactivated():
            self.splitting = None
        rect_min, rect_max = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        p = cyui.palette()
        middle = (rect_min.y + rect_max.y) / 2
        imgui.get_window_draw_list().add_line((rect_min.x, middle), (rect_max.x, middle), p.accent if hot else p.lineStrong, 2.0 if hot else 1.0)

    # -- toolbar helpers: the visible label and the tooltip are translated, identities stay stable
    def _icon(self, glyph, identity, tip, active=False, enabled=True, colour=0):
        return cyui.icon_button(glyph, self.tr(tip), active, colour, id=identity, fallback=identity[:2], enabled=enabled)

    def _toggle(self, label, value, tip, colour=0, glyph=None):
        visible, _, identity = label.partition('###')
        text = cyui.icon_label(glyph, self.tr(visible)) if glyph else self.tr(visible)
        clicked, value = cyui.toggle_button(text + '###' + (identity or visible), value, colour, tip=self.tr(tip))
        return value

    def _text_button(self, label, tip, variant=cyui.SECONDARY, glyph=None, enabled=True):
        visible, _, identity = label.partition('###')
        text = cyui.icon_label(glyph, self.tr(visible)) if glyph else self.tr(visible)
        with cyui.scoped_disabled(not enabled):
            clicked = cyui.button(text + '###' + (identity or visible), variant)
        cyui.tooltip(self.tr(tip))
        return clicked

    def _combo(self, key, index, items, width, tip):
        imgui.push_item_width(width)
        _, index = imgui.combo('##' + key, index, items)
        imgui.pop_item_width()
        cyui.tooltip(self.tr(tip))
        return index

    def _clock(self, position, duration):
        """Position / length in a sunken well, monospaced."""
        p = cyui.palette()
        with cyui.scoped_font(cyui.mono_font()):
            now, total = clock(position), ' / ' + clock(duration)
            size_now, size_total = imgui.calc_text_size(now), imgui.calc_text_size(total)
            pad = cyui.dp(8.0)
            height = imgui.get_frame_height()
            origin = imgui.get_cursor_screen_pos()
            width = size_now.x + size_total.x + pad * 2
            imgui.dummy((width, height))
            draw = imgui.get_window_draw_list()
            draw.add_rect_filled(origin, (origin.x + width, origin.y + height), p.bg0, imgui.get_style().frame_rounding)
            y = origin.y + (height - size_now.y) / 2
            draw.add_text((origin.x + pad, y), p.text if cyui.is_light() else p.accent, now)     # the accent does not read on a light well
            draw.add_text((origin.x + pad + size_now.x, y), p.textFaint, total)
        cyui.tooltip(self.tr('Position (cursor or playhead) / length of the session'))

    def _toolbar(self):
        """The bar above the timeline: groups of icon buttons separated by thin lines, each with a
        tooltip naming the action and its shortcut; the one main action is Export mix."""
        tr = self.tr
        dialogs = self.app.dialogs
        document, player = self.document, self.player
        timeline = self.app.timeline
        p = cyui.palette()
        icon = cyui.icon
        with cyui.toolbar('##editor-toolbar'):
            bar = cyui.FlowBar('editor-top')
            with bar.group('session'):
                if self._text_button('Import###Open audio', 'Import audio files as new tracks at the cursor (Ctrl+O)', glyph=icon.import_file):
                    dialogs.open_file('import', tr('Open audio files'), str(DATA / 'inputs'), multiple=True)
                imgui.same_line(0, 2)
                if self._icon(icon.folder, 'Open session', 'Open a saved session (folder with session.json)'):
                    dialogs.open_file('session', tr('Open session'), str(SESSIONS), SESSION_FILTER)
                imgui.same_line(0, 2)
                if self._icon(icon.save, 'Save session', 'Save the session: tracks, clips, effects, automation (Ctrl+S)'):
                    self.save_session()
                imgui.same_line(0, 2)
                if self._text_button('Save as...###Save session as', 'Save the session in another folder', cyui.GHOST):
                    dialogs.select_folder('save-session', tr('Choose a folder for the session'), str(SESSIONS))
                imgui.same_line(0, 2)
                if self._icon(icon.add, 'New', 'Close this session and start an empty one'):
                    player.stop()
                    self.app.new_document()

            with bar.group('transport'):
                recording = player.is_recording
                if self._icon(icon.previous, '|<', 'Back to the start (Home)'):
                    player.stop()
                    document.cursor = 0.0
                    player.seek(0.0)
                imgui.same_line(0, 2)
                if self._icon(icon.pause if player.playing else icon.play, 'Play', 'Pause (Space)' if player.playing else 'Play from the cursor (Space)', active=player.playing):
                    if player.playing:
                        player.pause()
                    else:
                        player.play(document.selection[0] if document.selection and player.frame >= document.seconds_to_frame(document.selection[1]) else None)
                imgui.same_line(0, 2)
                if self._icon(icon.stop, 'Stop', 'Stop and go back to the cursor'):
                    player.stop()
                imgui.same_line(0, 2)
                if not recording:
                    if self._icon(icon.record, 'Record', 'Record from the microphone; the take becomes a new track', colour=p.error):
                        try:
                            player.start_recording(channels=self.record_channels + 1)
                            self.message = tr('Recording... press Stop recording to add the take as a new track')
                        except Exception as exc:
                            self.app.jobs.error = str(exc)
                    imgui.same_line(0, 4)
                    _, self.record_channels = cyui.segmented('##recch', [tr('Mono'), tr('Stereo')], self.record_channels)
                    cyui.tooltip(tr('Channels recorded from the microphone'))
                else:
                    if self._text_button('Stop recording', 'Add the take as a new track', cyui.DANGER, glyph=icon.stop):
                        audio = player.stop_recording()
                        if audio is not None and audio.shape[1] > 0:
                            document.add_track(audio, tr('Recording ') + time.strftime('%H-%M-%S'), offset_seconds=document.frame_to_seconds(player.record_started_frame))
                            timeline.fit(document)
                            self.message = tr('Recording added as a new track')
                    imgui.same_line()
                    imgui.align_text_to_frame_padding()
                    cyui.text_coloured(p.error, tr('REC ') + clock(player.recorded_seconds()))
                imgui.same_line(0, 2)
                if self._icon(icon.loop, 'Loop selection', 'Loop the selection while playing', active=player.loop):
                    player.loop = not player.loop

            with bar.group('clock'):
                self._clock(player.position if (player.playing or player.is_recording) else document.cursor, document.duration)
                # fixed room for the selection, so the bar does not jump when a selection appears
                imgui.same_line(0, 8)
                room = imgui.calc_text_size(tr('Selection') + ' 00:00.000 - 00:00.000 (000.000 s)').x
                place = imgui.get_cursor_screen_pos()
                imgui.dummy((room, imgui.get_frame_height()))
                if document.selection:
                    a, b = sorted(document.selection)
                    text = tr('Selection') + f' {clock(a)} - {clock(b)} ({b - a:.3f} s)'
                    imgui.get_window_draw_list().add_text((place.x, place.y + imgui.get_style().frame_padding.y), p.info, text)
                    cyui.tooltip(text)

            with bar.group('view'):
                if self._icon(icon.zoom_in, '+', 'Zoom in (mouse wheel over the tracks)'):
                    timeline.zoom(0.7)
                imgui.same_line(0, 2)
                if self._icon(icon.zoom_out, '-', 'Zoom out'):
                    timeline.zoom(1.4)
                imgui.same_line(0, 2)
                if self._icon(icon.view_all, 'Fit', 'Show the whole session'):
                    timeline.fit(document)
                imgui.same_line(0, 2)
                if self._icon(icon.crop, 'Zoom sel', 'Zoom on the selection', enabled=bool(document.selection)):
                    timeline.zoom_selection(document)
                imgui.same_line(0, 6)
                _, timeline.vertical_zoom = cyui.slider_bar('##vzoom', timeline.vertical_zoom, 0.25, 16.0, tr('Height') + ' x%.2f', cyui.dp(105.0), logarithmic=True)
                cyui.tooltip(tr('Waveform height (Ctrl + wheel over the tracks)'))
                imgui.same_line(0, 6)
                if self._icon(icon.pin, 'Follow', 'Keep the playhead in view while playing', active=timeline.follow):
                    timeline.follow = not timeline.follow
                imgui.same_line(0, 2)
                if self._icon(icon.touch, 'Hand', 'Hand tool: drag the timeline with the left button (H). Right-drag and middle-drag always move the view.', active=timeline.hand_tool):
                    timeline.hand_tool = not timeline.hand_tool

            with bar.group('options'):
                self.show_inserts = self._toggle('FX###FX panel', self.show_inserts, 'Show the effects (inserts) of the selected track or of the master under the timeline (F)', glyph=icon.equalizer)
                imgui.same_line(0, 3)
                self.app.automation_write = self._toggle('Write###Write automation', self.app.automation_write,
                                                         'Write automation: while playing, knob and slider moves are recorded into automation lanes', p.warning, glyph=icon.edit)
                imgui.same_line(0, 8)
                imgui.align_text_to_frame_padding()
                cyui.text_dim(tr('Buffer'))
                imgui.same_line()
                from .player import BUFFER_SIZES
                sizes = [str(size) for size in BUFFER_SIZES]
                current = sizes.index(str(player.buffer_size)) if str(player.buffer_size) in sizes else 2
                chosen = self._combo('buffer', current, sizes, cyui.dp(70.0), 'Audio buffer (frames): smaller = less latency, larger = safer with many effects')
                if chosen != current:
                    player.set_buffer_size(BUFFER_SIZES[chosen])

            with bar.group('output'):
                _, player.volume = cyui.slider_bar('##vol', player.volume, 0.0, 1.5, tr('Volume') + ' %.2f', cyui.dp(105.0))
                cyui.tooltip(tr('Listening volume (not part of the mix or the export)'))
                imgui.same_line(0, 6)
                peak_l, peak_r = player.peak
                cyui.meter('##output-meter', (cyui.dp(90.0), imgui.get_frame_height()), peak_l, peak_r, vertical=False)
                cyui.tooltip(tr('Output level, left and right (green / yellow above -12 dB / red above -3 dB)'))

            with bar.group('export', align_right=True):
                self.export_format = self._combo('fmt', self.export_format, EXPORT_FORMATS, cyui.dp(62.0), 'File format of the exported mix')
                fmt = EXPORT_FORMATS[self.export_format]
                imgui.same_line(0, 3)
                if fmt in ('wav', 'flac'):
                    self.export_subtype = self._combo('sub', self.export_subtype, SUBTYPES, cyui.dp(84.0), 'Sample format (bit depth)')
                else:
                    self.export_bitrate = self._combo('br', self.export_bitrate, [f'{b} kbps' for b in audio_io.LOSSY_BITRATES], cyui.dp(84.0), 'Bitrate')
                imgui.same_line(0, 6)
                self.export_selection_only = self._toggle('Selection only', self.export_selection_only, 'Export only the selected time range')
                imgui.same_line(0, 6)
                if self._text_button('Export mix...###Export mix', 'Render the mix (effects, automation, master, reverb tails) to a file', cyui.PRIMARY,
                                     glyph=icon.export_file, enabled=self.exporting is None):
                    name = (document.name or 'mix') + audio_io.WRITE_FORMATS[fmt]['suffix']
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
                    folder = folder / (document.name or 'session')
                document.save_session(folder)
                self.message = tr('Session saved: ') + str(folder)
            elif purpose == 'export':
                self.export(result)
            elif purpose == 'reference':
                self.app.reference_file = result[0] if isinstance(result, list) else result

    def save_session(self):
        """Save in place, or ask for a folder the first time (Ctrl+S)."""
        if self.document.path:
            self.document.save_session(self.document.path)
            self.message = self.tr('Session saved: ') + str(self.document.path)
        else:
            self.app.dialogs.select_folder('save-session', self.tr('Choose a folder for the session'), str(SESSIONS))

    def _edit_row(self):
        tr = self.tr
        document = self.document
        has_sel = document.selection is not None
        icon = cyui.icon
        with cyui.toolbar('##editor-edit-bar'):
            bar = cyui.FlowBar('editor-bottom')
            with bar.group('history'):
                if self._icon(icon.undo, 'Undo', 'Undo the last edit (Ctrl+Z)', enabled=bool(document.undo_stack)):
                    label = document.undo()
                    self.message = (tr('Undone: ') + label) if label else tr('Nothing to undo')
                imgui.same_line(0, 2)
                if self._icon(icon.redo, 'Redo', 'Redo (Ctrl+Y)', enabled=bool(document.redo_stack)):
                    label = document.redo()
                    self.message = (tr('Redone: ') + label) if label else tr('Nothing to redo')
            with bar.group('edit'):
                if self._icon(icon.cut, 'Cut', 'Cut the selection of the selected track (Ctrl+X)', enabled=has_sel):
                    document.cut()
                imgui.same_line(0, 2)
                if self._icon(icon.copy, 'Copy', 'Copy the selection of the selected track (Ctrl+C)', enabled=has_sel):
                    document.copy()
                imgui.same_line(0, 2)
                if self._icon(icon.paste, 'Paste', 'Insert the copied audio at the cursor or the selection start (Ctrl+V)', enabled=document.clipboard is not None):
                    document.paste()
                imgui.same_line(0, 2)
                if self._icon(icon.trash, 'Delete', 'Delete the selected region (Del; Shift: on every track). To delete a whole clip: right-click it.', enabled=has_sel):
                    document.delete(all_tracks=imgui.get_io().key_shift)
                imgui.same_line(0, 6)
                if self._text_button('Trim', 'Keep only the selection', cyui.GHOST, glyph=icon.crop, enabled=has_sel):
                    document.trim()
                imgui.same_line(0, 2)
                if self._text_button('Silence', 'Replace the selection by silence', cyui.GHOST, glyph=icon.mute, enabled=has_sel):
                    document.silence()
            with bar.group('clips'):
                if self._text_button('Split at cursor', 'Cut the clip under the cursor in two clips of the same track', cyui.GHOST, glyph=icon.trim):
                    document.split()
                imgui.same_line(0, 8)
                _, self.silence_seconds = cyui.slider_bar('##sil', self.silence_seconds, 0.0, 30.0, '%.2f s', cyui.dp(80.0))
                cyui.tooltip(tr('Length of the silence to insert (double-click to type it)'))
                imgui.same_line(0, 3)
                if self._text_button('Insert silence', 'Insert silence at the cursor; what follows moves later', cyui.GHOST, glyph=icon.add):
                    document.insert_silence(max(0.0, self.silence_seconds))
