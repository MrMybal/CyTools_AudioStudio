"""Multitrack timeline: track headers, clips with waveforms, ruler, selection, cursor, playhead,
automation lanes, master bus lane, overview strip.

A track holds any number of clips; all of them go through the track's inserts.
Mouse on a clip lane:
  drag on the clip title bar         = move the clip in time (snaps to 0, cursor and other clip edges),
                                       or up / down onto another track, which then plays it through its effects
  drag a left/right clip edge        = trim the clip (audio is kept: drag back to restore it)
  drag a fade handle (top corners)   = fade in / fade out of the clip
  drag on the waveform / empty lane  = select a time range on that track
  click                              = place the cursor
  double-click                       = select the whole clip
  right-click                        = clip menu (delete, duplicate, reverse, split, move to cursor, move to another track)
  right-drag, middle-drag, Space+drag, the hand tool, the scrollbar or the overview strip = move along the timeline
  wheel = zoom around the mouse, Shift+wheel = scroll, Ctrl+wheel = vertical zoom
  drag the lower edge of a track     = change its height
Header buttons: FX opens the insert chain of the track in the panel below, A chooses the
automation lane drawn over the lane. With a lane shown: click = add a point, drag a point =
move it, double-click or right-click a point = remove it (Ctrl+drag still selects).
Stereo tracks show the left channel above the right one. The master bus is the last lane.
"""
import numpy as np
from imgui_bundle import imgui

from .knobs import level_meter, horizontal_meter
from . import cyui

HEADER_WIDTH = 200.0
RULER_HEIGHT = 22.0
TITLE_HEIGHT = 16.0
MIN_TRACK_HEIGHT = 60.0
MAX_TRACK_HEIGHT = 400.0
SNAP_PIXELS = 8.0
EDGE_WIDTH = 7.0
FADE_HANDLE = 9.0
SCROLLBAR_HEIGHT = 12.0
OVERVIEW_HEIGHT = 18.0
POINT_RADIUS = 5.0
METER_WIDTH = 6.0


def clock(seconds):
    seconds = max(0.0, float(seconds))
    return '%02d:%06.3f' % (int(seconds // 60), seconds % 60)


def colour(r, g, b, a=1.0):
    """A literal colour: only for data colours (track colours stored as float tuples)."""
    return cyui.from_floats(r, g, b, a)


def P():
    """The CyUI palette: every other colour of the timeline is taken from it by role."""
    return cyui.palette()


class Timeline:
    def __init__(self):
        self.view = (0.0, 10.0)        # visible seconds
        self.drag_start = None
        self.dragged = False
        self.moving = None             # {'track', 'clip', 'offset', 'mouse_x', 'edited', 'target'}
        self.resizing = None           # (track, start_height, mouse_y)
        self.trimming = None           # {'track', 'clip', 'edge', 'edited'}
        self.fading = None             # {'track', 'clip', 'side', 'edited'}
        self.menu_clip = None
        self._last_rows = []           # (track id, top, bottom) of the previous frame: target of a clip dragged vertically
        self.panning = None            # view start when a grab began
        self.follow = True
        self.vertical_zoom = 1.0
        self.menu_track = None
        self.hand_tool = False
        self.auto_drag = None          # {'owner', 'key', 'index'}
        self.right_drag = None         # (mouse_x, dragged)
        self.overview_drag = None
        self.drop_geometry = None      # last frame: where the lanes are, to place dropped files
        self._peak_cache = {}

    def fit(self, document):
        self.view = (0.0, max(1.0, document.duration * 1.02))

    def zoom_selection(self, document):
        if document.selection:
            a, b = sorted(document.selection)
            margin = max(0.05, (b - a) * 0.1)
            self.view = (max(0.0, a - margin), b + margin)

    def zoom(self, factor, anchor=None):
        start, stop = self.view
        span = max(1e-4, stop - start)
        anchor = (start + stop) / 2 if anchor is None else anchor
        ratio = (anchor - start) / span
        new_span = max(0.002, span * factor)
        begin = max(0.0, anchor - ratio * new_span)
        self.view = (begin, begin + new_span)

    def pan(self, delta_seconds):
        start, stop = self.view
        span = stop - start
        begin = max(0.0, start + delta_seconds)
        self.view = (begin, begin + span)

    def _ensure_visible(self, seconds):
        start, stop = self.view
        span = stop - start
        if seconds < start or seconds > stop:
            begin = max(0.0, seconds - span * 0.1)
            self.view = (begin, begin + span)

    # ------------------------------------------------------------------ drawing helpers
    def _peaks(self, clip, channel, fa, fb, columns, version):
        key = (clip.id, channel, clip.frames, clip.start, fa, fb, columns, version)
        cached = self._peak_cache.get((clip.id, channel))
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        if channel is None:
            low, high = clip.peaks().read(clip.start + fa, clip.start + fb, columns, audio=clip.audio)
        else:
            block = clip.audio[channel:channel + 1, clip.start + fa:clip.start + fb]
            if block.shape[1] == 0:
                low = high = np.zeros(0, np.float32)
            else:
                edges = np.linspace(0, block.shape[1], columns + 1).astype(int)[:-1] if block.shape[1] > columns else np.arange(block.shape[1])
                low = np.minimum.reduceat(block[0], edges)
                high = np.maximum.reduceat(block[0], edges)
        self._peak_cache[(clip.id, channel)] = (key, low, high)
        return low, high

    def _draw_wave(self, draw, track, clip, channel, x0, x1, top, bottom, fa, fb, version, head_x, muted):
        columns = max(1, int(x1 - x0))
        if channel is not None and clip.frames and (fb - fa) / columns < 64:
            low, high = self._peaks(clip, channel, fa, fb, columns, version)
        elif channel is not None:
            block = clip.audio[channel, clip.start + fa:clip.start + fb]
            if block.size == 0:
                return
            edges = np.linspace(0, block.size, columns + 1).astype(int)[:-1]
            key = (clip.id, channel, clip.frames, clip.start, fa, fb, columns, version)
            cached = self._peak_cache.get((clip.id, channel))
            if cached is not None and cached[0] == key:
                low, high = cached[1], cached[2]
            else:
                low, high = np.minimum.reduceat(block, edges), np.maximum.reduceat(block, edges)
                self._peak_cache[(clip.id, channel)] = (key, low, high)
        else:
            low, high = self._peaks(clip, None, fa, fb, columns, version)
        middle = (top + bottom) / 2
        half = max(1.0, (bottom - top) / 2 - 1)
        gain = 10 ** (track.gain_db / 20) * self.vertical_zoom
        draw.add_line((x0, middle), (x1, middle), P().line)
        count = len(low)
        if not count:
            return
        step = (x1 - x0) / count
        base = colour(*track.colour, 0.45 if muted else 1.0)
        if cyui.is_light():
            base = cyui.darker(base, 0.35)          # track colours are pastel: darker on a light ground
        played = P().accent
        for i in range(count):
            x = x0 + (i + 0.5) * step
            y_top = middle - min(1.0, float(high[i]) * gain) * half
            y_bottom = middle - max(-1.0, float(low[i]) * gain) * half
            if y_bottom - y_top < 1.0:
                y_bottom = y_top + 1.0
            draw.add_line((x, y_top), (x, y_bottom), played if x <= head_x else base, max(1.0, step))

    def _snap(self, document, clip, seconds, to_x):
        """Snap to 0, the cursor and the edges of every other clip when within SNAP_PIXELS."""
        candidates = [0.0, document.cursor]
        for track in document.tracks:
            for other in track.clips:
                if other is not clip:
                    candidates += [document.frame_to_seconds(other.offset), document.frame_to_seconds(other.end)]
        x = to_x(seconds)
        best = min(candidates, key=lambda c: abs(to_x(c) - x))
        return best if abs(to_x(best) - x) <= SNAP_PIXELS else seconds

    def _row_at(self, y):
        return next((track_id for track_id, top, bottom in self._last_rows if top <= y < bottom), None)

    # ------------------------------------------------------------------ automation overlay
    def _automation(self, document, owner, draw, x0, y_top, x1, y1, to_x, to_t, hovered, lane_id, tr):
        """Draw the shown lane of ``owner`` and handle point editing. Returns True when it consumed the mouse."""
        key = owner.automation_view
        if not key:
            return False
        lo, hi, default, kind = document.automation_range(owner, key)
        lane = owner.automation.get(key)
        span_v = (hi - lo) or 1.0
        to_y = lambda v: y1 - 4 - (float(np.clip(v, lo, hi)) - lo) / span_v * (y1 - y_top - 8)
        from_y = lambda y: lo + float(np.clip((y1 - 4 - y) / (y1 - y_top - 8), 0.0, 1.0)) * span_v
        label = dict(document.automatable_keys(owner)).get(key, key)
        draw.add_rect_filled((x0, y_top), (x1, y1), cyui.alpha(P().warning, 0.06))
        draw.add_text((x0 + 4, y1 - 16), cyui.alpha(P().warning, 0.9), tr('Automation: ') + tr(label))
        start, stop = self.view
        columns = max(2, int((x1 - x0) / 2))
        times = np.linspace(start, stop, columns)
        if lane is not None and lane.points:
            values = lane.values(times, default)
            points = [imgui.ImVec2(float(to_x(t)), float(to_y(v))) for t, v in zip(times, values)]
            draw.add_polyline(points, cyui.alpha(P().warning, 0.95), 2.0, 0)
        else:
            y = to_y(default)
            draw.add_line((x0, y), (x1, y), cyui.alpha(P().warning, 0.5), 1.0)
        mouse = imgui.get_mouse_pos()
        near = None
        if lane is not None:
            for index, (t, v) in enumerate(lane.points):
                px, py = to_x(t), to_y(v)
                if x0 - POINT_RADIUS <= px <= x1 + POINT_RADIUS:
                    is_near = hovered and abs(mouse.x - px) <= POINT_RADIUS + 2 and abs(mouse.y - py) <= POINT_RADIUS + 2
                    if is_near:
                        near = index
                    draw.add_circle_filled((px, py), POINT_RADIUS + (1.5 if is_near else 0.0), cyui.brighter(P().warning, 0.25) if is_near else P().warning, 12)
                    draw.add_circle((px, py), POINT_RADIUS, cyui.alpha(P().bg0, 0.9), 12, 1.0)
        io = imgui.get_io()
        consumed = False
        if self.auto_drag and self.auto_drag['owner'] is owner and self.auto_drag['key'] == key:
            if imgui.is_mouse_down(imgui.MouseButton_.left):
                index = self.auto_drag['index']
                value = from_y(mouse.y)
                if kind == 'bool':
                    value = 1.0 if value >= 0.5 else 0.0
                self.auto_drag['index'] = document.automation_move(owner, key, index, max(0.0, to_t(mouse.x)), value)
                imgui.set_tooltip('%s  %s' % (clock(lane.points[self.auto_drag['index']][0]) if lane else '', self._format(value, kind, key)))
            else:
                self.auto_drag = None
            return True
        if not hovered or io.key_ctrl or self.hand_tool:
            return False
        if near is not None:
            imgui.set_mouse_cursor(imgui.MouseCursor_.hand)
            if imgui.is_mouse_double_clicked(imgui.MouseButton_.left) or imgui.is_mouse_clicked(imgui.MouseButton_.right):
                document.automation_remove(owner, key, near)
                consumed = True
            elif imgui.is_mouse_clicked(imgui.MouseButton_.left):
                document._edit_owner('Move automation point', owner)
                self.auto_drag = {'owner': owner, 'key': key, 'index': near}
                consumed = True
            else:
                t, v = lane.points[near]
                imgui.set_tooltip('%s  %s' % (clock(t), self._format(v, kind, key)))
        elif imgui.is_mouse_clicked(imgui.MouseButton_.left) and not imgui.is_mouse_double_clicked(imgui.MouseButton_.left):
            value = from_y(mouse.y)
            if kind == 'bool':
                value = 1.0 if value >= 0.5 else 0.0
            index = document.automation_add(owner, key, max(0.0, to_t(mouse.x)), value)
            self.auto_drag = {'owner': owner, 'key': key, 'index': index}
            consumed = True
        elif mouse.y >= y_top:
            imgui.set_tooltip(tr('Click to add an automation point (Ctrl+drag selects)'))
        return consumed

    @staticmethod
    def _format(value, kind, key):
        if kind == 'bool':
            return 'on' if value >= 0.5 else 'off'
        if key == 'gain_db' or key.endswith('_db'):
            return '%.1f dB' % value
        if key == 'pan':
            return '%.2f' % value
        return '%.3g' % value

    def _automation_button(self, document, owner, tr):
        """The 'A' button of a header: popup listing the automation lanes."""
        active = bool(owner.automation_view)
        clicked, _ = cyui.toggle_button('A###Automation', active, P().warning, tip=tr('Automation lane shown over this track'))
        if clicked:
            imgui.open_popup('automation-menu')
        if imgui.begin_popup('automation-menu'):
            if imgui.menu_item(tr('None (hide)'), '', not owner.automation_view)[0]:
                owner.automation_view = ''
            for key, label in document.automatable_keys(owner):
                lane = owner.automation.get(key)
                text = tr(label) + (f'  ({len(lane)})' if lane is not None and lane.points else '')
                if imgui.menu_item(text + '##' + key, '', owner.automation_view == key)[0]:
                    owner.automation_view = key
            if owner.automation_view and owner.automation.get(owner.automation_view):
                imgui.separator()
                if imgui.menu_item(tr('Clear this lane'), '', False)[0]:
                    document.automation_clear(owner, owner.automation_view)
            imgui.end_popup()

    # ------------------------------------------------------------------ main draw
    def draw(self, document, player, tr=lambda t: t, height=None, app=None):
        io = imgui.get_io()
        total_height = height or max(200.0, imgui.get_content_region_avail().y)
        origin = imgui.get_cursor_screen_pos()
        width = max(300.0, imgui.get_content_region_avail().x)
        lane_x0 = origin.x + HEADER_WIDTH
        lane_width = max(50.0, width - HEADER_WIDTH - 14)
        if player.playing and self.follow:
            self._ensure_visible(player.position)
        start, stop = self.view
        span = max(1e-4, stop - start)
        to_x = lambda t: lane_x0 + (t - start) / span * lane_width
        to_t = lambda x: start + (x - lane_x0) / lane_width * span
        mouse = imgui.get_mouse_pos()
        draw = imgui.get_window_draw_list()
        renderer = player.renderer

        # ---------------------------------------------------------------- ruler
        imgui.set_cursor_screen_pos((lane_x0, origin.y))
        imgui.invisible_button('ruler', (lane_width, RULER_HEIGHT))
        ruler_hovered = imgui.is_item_hovered()
        draw.add_rect_filled((origin.x, origin.y), (origin.x + width, origin.y + RULER_HEIGHT), P().bg1)
        ticks = max(2, int(lane_width // 90))
        step = _nice_step(span / ticks)
        t = np.floor(start / step) * step
        while t <= stop + step:
            x = to_x(t)
            if lane_x0 <= x <= lane_x0 + lane_width:
                draw.add_line((x, origin.y + RULER_HEIGHT - 8), (x, origin.y + RULER_HEIGHT), P().textFaint)
                draw.add_text((x + 3, origin.y + 3), P().textDim, clock(t))
            t += step
        if document.selection:
            a, b = sorted(document.selection)
            draw.add_rect_filled((max(lane_x0, to_x(a)), origin.y + RULER_HEIGHT - 6), (min(lane_x0 + lane_width, to_x(b)), origin.y + RULER_HEIGHT), cyui.alpha(P().accent, 0.6))
        if ruler_hovered and (imgui.is_mouse_clicked(imgui.MouseButton_.left) or imgui.is_mouse_dragging(imgui.MouseButton_.left, 2.0)):
            seconds = float(np.clip(to_t(mouse.x), 0, max(document.duration, 0.0)))
            document.cursor = seconds
            player.seek(seconds)
        if ruler_hovered and io.mouse_wheel != 0:
            self.zoom(0.8 if io.mouse_wheel > 0 else 1.25, anchor=to_t(mouse.x))
        if ruler_hovered:
            imgui.set_tooltip(tr('Click or drag to move the cursor, wheel to zoom'))
        # add-track button in the corner above the track headers: always in view, however many tracks
        imgui.set_cursor_screen_pos((origin.x + 4, origin.y + 1))
        imgui.push_style_var(imgui.StyleVar_.frame_padding, (8.0, 1.0))
        caption = cyui.icon_label(cyui.icon.add, tr('Track')) if cyui.icons_available() else tr('+ Track')
        if cyui.button(caption + '###Add track', cyui.GHOST, (HEADER_WIDTH - 14, RULER_HEIGHT - 2)):
            document.add_empty_track()
            if app is not None:
                app.editor.message = tr('Empty track added: record, drop or generate a sound into it, or add inserts.')
        imgui.pop_style_var()
        if imgui.is_item_hovered():
            imgui.set_tooltip(tr('Add an empty track'))

        # ---------------------------------------------------------------- lanes (own child: own draw list and clipping)
        imgui.set_cursor_screen_pos((origin.x, origin.y + RULER_HEIGHT))
        master_height = float(document.master.height)
        available = total_height - RULER_HEIGHT - SCROLLBAR_HEIGHT - OVERVIEW_HEIGHT - master_height - 6
        imgui.begin_child('lanes', (width, max(40.0, available)), imgui.ChildFlags_.none, imgui.WindowFlags_.no_scroll_with_mouse if not io.key_alt else 0)
        draw = imgui.get_window_draw_list()
        child_origin = imgui.get_cursor_screen_pos()
        y = child_origin.y
        remove_id = None
        hover_time = None
        version = document.version
        head_x = to_x(player.position) if (player.playing or player.is_recording) else -1e9
        rows = []
        self.drop_geometry = {'x0': origin.x, 'x1': origin.x + width, 'y0': origin.y, 'y1': origin.y + total_height, 'lane_x0': lane_x0,
                              'lane_width': lane_width, 'start': start, 'span': span, 'rows': rows,
                              # the part of the scrolling lanes that is on screen: rows outside it are hidden
                              'lanes_y0': imgui.get_window_pos().y, 'lanes_y1': imgui.get_window_pos().y + imgui.get_window_size().y}
        for index, track in enumerate(list(document.tracks)):
            lane_height = float(track.height)
            rows.append((track.id, y, y + lane_height))
            selected = index == document.selected_track
            imgui.push_id(track.id)
            # -- header
            draw.add_rect_filled((child_origin.x, y), (child_origin.x + HEADER_WIDTH - 4, y + lane_height - 2),
                                 cyui.mix(P().bg2, P().accent, 0.10) if selected else P().bg2)
            draw.add_rect_filled((child_origin.x, y), (child_origin.x + 4, y + lane_height - 2), colour(*track.colour))
            imgui.set_cursor_screen_pos((child_origin.x + 8, y + 4))
            imgui.push_item_width(HEADER_WIDTH - 54)
            changed, name = imgui.input_text('##name', track.name)
            if changed:
                track.name = name
                document.touch()
            imgui.pop_item_width()
            imgui.same_line(0, 2)
            if cyui.icon_button(cyui.icon.close, tr('Delete this track (Ctrl+Z to undo)'), id='Delete track', fallback='X'):
                remove_id = track.id
            imgui.set_cursor_screen_pos((child_origin.x + 8, y + 28))
            clicked, value = cyui.toggle_button(tr('M') + '###mute', track.mute, P().warning, tip=tr('Mute'))
            if clicked:
                track.mute = value
                document.touch()
            imgui.same_line(0, 3)
            clicked, value = cyui.toggle_button(tr('S') + '###solo', track.solo, P().success, tip=tr('Solo'))
            if clicked:
                track.solo = value
                document.touch()
            imgui.same_line(0, 3)
            chain_length = sum(1 for n in track.inserts if not n.get('_preview'))      # the Effect... audition insert is not counted
            fx_active = chain_length > 0
            clicked, _ = cyui.toggle_button(('FX %d' % chain_length if fx_active else 'FX') + '###FX', fx_active,
                                            tip=tr('Effects and VST3 plugins of this track (inserts)'))
            if clicked and app is not None:
                app.inserts.show(track)
            imgui.same_line(0, 3)
            self._automation_button(document, track, tr)
            imgui.same_line(0, 3)
            if cyui.icon_button(cyui.icon.chevron_up, tr('Move the track up'), id='Move track up', fallback='^', size=(imgui.get_frame_height() * 0.8, 0)):
                document.move_track(track.id, -1)
            imgui.same_line(0, 0)
            if cyui.icon_button(cyui.icon.chevron_down, tr('Move the track down'), id='Move track down', fallback='v', size=(imgui.get_frame_height() * 0.8, 0)):
                document.move_track(track.id, 1)
            if lane_height >= 80:
                imgui.set_cursor_screen_pos((child_origin.x + 8, y + 52))
                imgui.push_item_width(HEADER_WIDTH - 26)
                changed, gain = cyui.slider_bar('##gain', track.gain_db, -48.0, 12.0, tr('Gain') + ' %.1f dB')
                if imgui.is_item_activated():
                    document.edit('Gain', [track.id])
                if changed:
                    track.gain_db = gain
                    document.touch()
                    if app is not None and app.automation_write and player.playing:
                        document.automation_write(track, 'gain_db', player.position, gain)
                if lane_height >= 104:
                    imgui.set_cursor_screen_pos((child_origin.x + 8, y + 76))
                    changed, pan = cyui.slider_bar('##pan', track.pan, -1.0, 1.0, tr('Pan') + ' %.2f', 0.0, P().info)
                    if imgui.is_item_activated():
                        document.edit('Pan', [track.id])
                    if changed:
                        track.pan = pan
                        document.touch()
                        if app is not None and app.automation_write and player.playing:
                            document.automation_write(track, 'pan', player.position, pan)
                imgui.pop_item_width()
            # level meter on the right edge of the header
            peak = renderer.track_peaks.get(track.id, (0.0, 0.0)) if (player.playing or player.is_recording) else (0.0, 0.0)
            self._vertical_meter(draw, child_origin.x + HEADER_WIDTH - 16, y + 4, y + lane_height - 6, peak)
            header_hovered = imgui.is_mouse_hovering_rect((child_origin.x, y), (child_origin.x + HEADER_WIDTH, y + lane_height))
            if header_hovered and imgui.is_mouse_clicked(imgui.MouseButton_.left):
                document.selected_track = index
                if app is not None:
                    app.inserts.follow(track)

            # -- lane background, selection
            x0, y0, x1, y1 = lane_x0, y, lane_x0 + lane_width, y + lane_height - 2
            draw.add_rect_filled((x0, y0), (x1, y1), cyui.mix(P().bg0, P().bg1, 0.6) if selected else P().bg0)
            if document.selection and (selected or io.key_shift):
                a, b = sorted(document.selection)
                draw.add_rect_filled((max(x0, to_x(a)), y0), (min(x1, to_x(b)), y1), P().selection)

            # -- clips (title bar + waveform)
            visible = []
            for clip in track.clips:
                clip_a, clip_b = document.frame_to_seconds(clip.offset), document.frame_to_seconds(clip.end)
                vis_a, vis_b = max(start, clip_a), min(stop, clip_b)
                if vis_b <= vis_a or not clip.frames:
                    continue
                visible.append((clip, clip_a, clip_b, vis_a, vis_b))
                leaving = self.moving is not None and self.moving['clip'] is clip and self.moving['target'] != track.id
                alpha = 0.35 if leaving else 1.0
                px_a, px_b = to_x(vis_a), to_x(vis_b)
                draw.add_rect_filled((px_a, y0), (px_b, y1), colour(*track.colour, 0.07))
                draw.add_rect_filled((px_a, y0), (px_b, y0 + TITLE_HEIGHT), colour(*track.colour, (0.55 if selected else 0.35) * alpha))
                draw.add_rect((px_a, y0), (px_b, y1), colour(*track.colour, 0.6 * alpha))
                draw.push_clip_rect((px_a, y0), (px_b, y0 + TITLE_HEIGHT), True)
                draw.add_text((px_a + 4, y0 + 1), cyui.alpha(P().text, 0.95 * alpha), f'{clip.name}  {clock(clip_a)}')
                draw.pop_clip_rect()
                fa = document.seconds_to_frame(vis_a) - clip.offset
                fb = document.seconds_to_frame(vis_b) - clip.offset
                wave_top = y0 + TITLE_HEIGHT + 1
                if clip.channels >= 2 and (y1 - wave_top) >= 50:
                    middle = (wave_top + y1) / 2
                    self._draw_wave(draw, track, clip, 0, px_a, px_b, wave_top, middle - 1, fa, fb, version, head_x, track.mute or leaving)
                    self._draw_wave(draw, track, clip, 1, px_a, px_b, middle + 1, y1, fa, fb, version, head_x, track.mute or leaving)
                    draw.add_line((px_a, middle), (px_b, middle), P().line)
                    draw.add_text((px_b - 26 if px_b - px_a > 50 else px_a + 2, wave_top + 1), P().textFaint, 'L')
                    draw.add_text((px_b - 26 if px_b - px_a > 50 else px_a + 2, middle + 2), P().textFaint, 'R')
                else:
                    self._draw_wave(draw, track, clip, None, px_a, px_b, wave_top, y1, fa, fb, version, head_x, track.mute or leaving)
            # -- lane body: selection, cursor, menu, panning, automation
            under = track.clip_at(document.seconds_to_frame(max(0.0, to_t(mouse.x)))) if x0 <= mouse.x <= x1 else None
            under = under if any(item[0] is under for item in visible) else None
            body_top = y0 + (TITLE_HEIGHT if under is not None else 0)
            imgui.set_cursor_screen_pos((x0, y0))
            imgui.set_next_item_allow_overlap()
            imgui.invisible_button('lane', (lane_width, lane_height - 2))
            hovered = imgui.is_item_hovered()
            active = imgui.is_item_active()
            automation_consumed = False
            if track.automation_view:
                automation_consumed = self._automation(document, track, draw, x0, y0 + (TITLE_HEIGHT if visible else 0), x1, y1, to_x, to_t, hovered, 'lane', tr)
            if hovered:
                hover_time = to_t(mouse.x)
                self._wheel(io, span, start, to_t, mouse)
                grabbing = (imgui.is_mouse_dragging(imgui.MouseButton_.middle) or (imgui.is_key_down(imgui.Key.space) and imgui.is_mouse_dragging(imgui.MouseButton_.left))
                            or (self.hand_tool and imgui.is_mouse_dragging(imgui.MouseButton_.left)) or imgui.is_mouse_dragging(imgui.MouseButton_.right, 3.0))
                if grabbing:
                    imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)
                    self.pan(-io.mouse_delta.x / lane_width * span)
                    if imgui.is_mouse_dragging(imgui.MouseButton_.right, 3.0):
                        self.right_drag = True
                elif self.hand_tool:
                    imgui.set_mouse_cursor(imgui.MouseCursor_.hand)
            editing_points = bool(track.automation_view) and not io.key_ctrl and not self.hand_tool
            if imgui.is_item_activated() and mouse.y >= body_top and not editing_points and not self.hand_tool:
                document.selected_track = index
                if app is not None:
                    app.inserts.follow(track)
                self.drag_start = float(max(0.0, to_t(mouse.x)))
                self.dragged = False
                self.drag_track = track.id
            if hovered and imgui.is_mouse_double_clicked(imgui.MouseButton_.left) and under is not None and not editing_points:
                document.selected_track = index
                document.selection = (document.frame_to_seconds(under.offset), document.frame_to_seconds(under.end))
                self.drag_start = None
            if active and self.drag_start is not None and getattr(self, 'drag_track', None) == track.id and imgui.is_mouse_dragging(imgui.MouseButton_.left, 3.0):
                self.dragged = True
                document.selection = tuple(sorted((self.drag_start, float(max(0.0, to_t(mouse.x))))))
            if imgui.is_item_deactivated() and self.drag_start is not None and getattr(self, 'drag_track', None) == track.id:
                if not self.dragged:
                    document.cursor = self.drag_start
                    document.selection = None
                    player.seek(self.drag_start)
                self.drag_start = None
            if imgui.is_item_hovered() and imgui.is_mouse_released(imgui.MouseButton_.right) and not automation_consumed:
                if self.right_drag:
                    self.right_drag = None
                else:
                    document.selected_track = index
                    self.menu_track = track.id
                    self.menu_clip = under.id if under is not None else None
                    self.menu_time = to_t(mouse.x)
                    imgui.open_popup('clip-menu')
            if imgui.begin_popup('clip-menu'):
                self._clip_menu(document, track, app, tr)
                imgui.end_popup()

            # -- per clip: title bar = move handle (also to another track), edges = trim, top corners = fades
            if not editing_points:
                draw.push_clip_rect((x0, y0), (x1, y1), True)
                for clip, clip_a, clip_b, vis_a, vis_b in visible:
                    imgui.push_id(clip.id)
                    self._clip_handles(document, track, index, clip, clip_a, clip_b, vis_a, vis_b, draw, x0, x1, y0, y1, to_x, to_t, mouse, lane_width, span, tr)
                    imgui.pop_id()
                draw.pop_clip_rect()

            # -- cursor and playhead
            cursor_x = to_x(document.cursor)
            if x0 <= cursor_x <= x1:
                draw.add_line((cursor_x, y0), (cursor_x, y1), cyui.alpha(P().text, 0.75), 1.0)
            if x0 <= head_x <= x1:
                draw.add_line((head_x, y0), (head_x, y1), P().error if player.is_recording else P().accent, 1.5)

            # -- height handle (lower edge)
            imgui.set_cursor_screen_pos((child_origin.x, y1 - 3))
            imgui.invisible_button('resize', (width - 14, 5))
            if imgui.is_item_hovered() or imgui.is_item_active():
                imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ns)
            if imgui.is_item_activated():
                self.resizing = (track, track.height, mouse.y)
            if imgui.is_item_active() and self.resizing and self.resizing[0] is track:
                track.height = float(np.clip(self.resizing[1] + mouse.y - self.resizing[2], MIN_TRACK_HEIGHT, MAX_TRACK_HEIGHT))
            if imgui.is_item_deactivated():
                self.resizing = None
            imgui.pop_id()
            y += lane_height
        self._moving_ghost(document, draw, rows, to_x, tr)
        self._last_rows = list(rows)
        if remove_id is not None:
            document.remove_track(remove_id)
        y += 8
        if not document.tracks:
            draw.add_text((lane_x0 + 12, child_origin.y + 12), P().textFaint, tr('No track. Open a file, record, or generate a sound.'))

        imgui.set_cursor_screen_pos((child_origin.x, y))
        imgui.dummy((width - 14, 8))
        imgui.end_child()
        # ---------------------------------------------------------------- master bus lane (fixed under the scrolling tracks)
        imgui.begin_child('master-lane-area', (width, master_height), imgui.ChildFlags_.none, imgui.WindowFlags_.no_scroll_with_mouse)
        draw = imgui.get_window_draw_list()
        master_origin = imgui.get_cursor_screen_pos()
        self._master_lane(document, player, draw, master_origin, master_origin.y, width, lane_x0, lane_width, to_x, to_t, head_x, tr, app, io, span, start, mouse)
        imgui.end_child()
        self._scrollbar(document, lane_x0, lane_width, tr)
        self._overview(document, lane_x0, lane_width, tr)
        if hover_time is not None and not (self.moving or self.resizing or self.auto_drag or self.fading or self.trimming):
            imgui.set_tooltip(clock(hover_time))

    def _clip_menu(self, document, track, app, tr):
        """Right-click menu of a lane: the clip under the mouse, or the track when there is none."""
        clip = track.clip(self.menu_clip) if self.menu_clip else None
        imgui.text_disabled(clip.name if clip is not None else track.name)
        imgui.begin_disabled(clip is None)
        if imgui.menu_item(tr('Delete clip') + '###Delete clip', '', False)[0]:
            document.remove_clip(track, clip)
        if imgui.menu_item(tr('Duplicate clip') + '###Duplicate clip', '', False)[0]:
            document.duplicate_clip(track, clip)
        if imgui.menu_item(tr('Reverse clip') + '###Reverse clip', '', False)[0]:
            document.reverse_clip(track, clip)
        imgui.end_disabled()
        if imgui.menu_item(tr('Split at cursor') + '###Split at cursor', '', False)[0]:
            document.split()
        imgui.begin_disabled(clip is None)
        if imgui.menu_item(tr('Move clip to cursor') + '###Move clip to cursor', '', False)[0]:
            document.set_offset(track, document.cursor, clip=clip)
        if imgui.menu_item(tr('Select whole clip') + '###Select whole clip', '', False)[0]:
            document.selection = (document.frame_to_seconds(clip.offset), document.frame_to_seconds(clip.end))
        others = [other for other in document.tracks if other is not track]
        if others and imgui.begin_menu(tr('Move to track') + '###Move to track'):
            for other in others:
                if imgui.menu_item(other.name + '###to-' + other.id, '', False)[0]:
                    document.move_clip(track, clip, other)
                    if app is not None:
                        app.inserts.follow(other)
            imgui.end_menu()
        imgui.end_disabled()
        imgui.separator()
        if imgui.menu_item(tr('Inserts (effects, VST3)...') + '###Open inserts', '', False)[0] and app is not None:
            app.inserts.show(track)

    def _clip_handles(self, document, track, index, clip, clip_a, clip_b, vis_a, vis_b, draw, x0, x1, y0, y1, to_x, to_t, mouse, lane_width, span, tr):
        px_a, px_b = to_x(vis_a), to_x(vis_b)
        clip_px_a, clip_px_b = to_x(clip_a), to_x(clip_b)
        wave_top = y0 + TITLE_HEIGHT + 1
        # -- move: in time, and onto another track when the mouse leaves this one
        imgui.set_cursor_screen_pos((px_a, y0))
        imgui.invisible_button('clip-move', (max(4.0, px_b - px_a), TITLE_HEIGHT))
        if imgui.is_item_hovered():
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)
            imgui.set_tooltip(tr('Drag to move the clip, up or down to put it on another track'))
        if imgui.is_item_activated():
            document.selected_track = index
            self.moving = {'track': track, 'clip': clip, 'offset': clip_a, 'mouse_x': mouse.x, 'edited': False, 'target': track.id}
        moving = self.moving if (self.moving is not None and self.moving['clip'] is clip) else None
        if imgui.is_item_active() and moving is not None:
            delta = (mouse.x - moving['mouse_x']) / lane_width * span
            if abs(mouse.x - moving['mouse_x']) >= 1.0:
                if not moving['edited']:
                    document.edit('Move clip', [track.id])
                    moving['edited'] = True
                clip.offset = document.seconds_to_frame(max(0.0, self._snap(document, clip, moving['offset'] + delta, to_x)))
                document.touch()
            moving['target'] = self._row_at(mouse.y) or track.id
        if imgui.is_item_deactivated() and moving is not None:
            target = document.track(moving['target'])
            if target is not None and target is not track:
                document.move_clip(track, clip, target, record=not moving['edited'])
            else:
                track.sort()
            self.moving = None
        # -- trim: the edges below the fade handles
        edge_top = wave_top + FADE_HANDLE + 1
        for side, handle_x in (('left', clip_px_a), ('right', clip_px_b - EDGE_WIDTH)):
            if handle_x + EDGE_WIDTH < x0 or handle_x > x1 or y1 - edge_top < 4:
                continue
            imgui.set_cursor_screen_pos((handle_x, edge_top))
            imgui.invisible_button('clip-' + side, (EDGE_WIDTH, y1 - edge_top))
            trimming = self.trimming is not None and self.trimming['clip'] is clip and self.trimming['edge'] == side
            if imgui.is_item_hovered() or trimming:
                imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ew)
                draw.add_rect_filled((handle_x, edge_top), (handle_x + EDGE_WIDTH, y1), cyui.alpha(P().accent, 0.45))
                if imgui.is_item_hovered():
                    imgui.set_tooltip(tr('Drag to trim the clip (the audio is kept)'))
            if imgui.is_item_activated():
                document.selected_track = index
                self.trimming = {'track': track, 'clip': clip, 'edge': side, 'edited': False}
                trimming = True
            if imgui.is_item_active() and trimming:
                if not self.trimming['edited']:
                    document.edit('Resize clip', [track.id])
                    self.trimming['edited'] = True
                document.resize_clip(track, side, self._snap(document, clip, to_t(mouse.x), to_x), record=False, clip=clip)
            if imgui.is_item_deactivated() and self.trimming is not None and self.trimming['clip'] is clip:
                self.trimming = None
        # -- fades: the curve, and a handle flush with the clip edge (it follows the end of the fade)
        fade_in_x = to_x(clip_a + clip.fade_in)
        fade_out_x = to_x(clip_b - clip.fade_out)
        if clip.fade_in > 0:
            draw.add_triangle_filled((clip_px_a, y1), (fade_in_x, wave_top), (clip_px_a, wave_top), cyui.alpha(P().bg0, 0.65))
            draw.add_line((clip_px_a, y1), (fade_in_x, wave_top), cyui.alpha(P().text, 0.8), 1.5)
        if clip.fade_out > 0:
            draw.add_triangle_filled((fade_out_x, wave_top), (clip_px_b, y1), (clip_px_b, wave_top), cyui.alpha(P().bg0, 0.65))
            draw.add_line((fade_out_x, wave_top), (clip_px_b, y1), cyui.alpha(P().text, 0.8), 1.5)
        for side in ('in', 'out'):
            if side == 'in':
                left = min(max(clip_px_a, fade_in_x), clip_px_b - FADE_HANDLE)
            else:
                left = max(min(clip_px_b, fade_out_x) - FADE_HANDLE, clip_px_a)
            if left < x0 or left + FADE_HANDLE > x1:
                continue                                  # that corner is scrolled out of view
            imgui.set_cursor_screen_pos((left, wave_top))
            imgui.invisible_button('fade-' + side, (FADE_HANDLE, FADE_HANDLE))
            hovered_fade = imgui.is_item_hovered()
            fading = self.fading is not None and self.fading['clip'] is clip and self.fading['side'] == side
            draw.add_rect_filled((left, wave_top), (left + FADE_HANDLE, wave_top + FADE_HANDLE), P().accent if (hovered_fade or fading) else P().bg5, 2.0)
            draw.add_rect((left, wave_top), (left + FADE_HANDLE, wave_top + FADE_HANDLE), P().lineStrong, 2.0)
            if hovered_fade:
                imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ew)
                imgui.set_tooltip(tr('Drag for a fade in') if side == 'in' else tr('Drag for a fade out'))
            if imgui.is_item_activated():
                document.selected_track = index
                self.fading = {'track': track, 'clip': clip, 'side': side, 'edited': False}
                fading = True
            if imgui.is_item_active() and fading:
                if not self.fading['edited']:
                    document.edit('Fade ' + side, [track.id])
                    self.fading['edited'] = True
                seconds = (to_t(mouse.x) - clip_a) if side == 'in' else (clip_b - to_t(mouse.x))
                document.set_fade(track, side, max(0.0, seconds), record=False, clip=clip)
            if imgui.is_item_deactivated() and self.fading is not None and self.fading['clip'] is clip:
                self.fading = None

    def _moving_ghost(self, document, draw, rows, to_x, tr):
        """Outline of a clip dragged onto another track, in that track's lane."""
        moving = self.moving
        if moving is None or moving['target'] == moving['track'].id:
            return
        row = next((r for r in rows if r[0] == moving['target']), None)
        target = document.track(moving['target'])
        if row is None or target is None:
            return
        clip = moving['clip']
        a, b = to_x(document.frame_to_seconds(clip.offset)), to_x(document.frame_to_seconds(clip.end))
        top, bottom = row[1], row[2] - 2
        draw.add_rect_filled((a, top), (b, bottom), colour(*target.colour, 0.25))
        draw.add_rect((a, top), (b, bottom), colour(*target.colour, 0.95), rounding=0.0, thickness=2.0)
        draw.add_text((a + 4, top + 1), P().text, clip.name + '  -> ' + target.name)
        imgui.set_tooltip(tr('Release to move the clip to ') + target.name)

    def _wheel(self, io, span, start, to_t, mouse):
        if io.mouse_wheel != 0:
            if io.key_ctrl:
                self.vertical_zoom = float(np.clip(self.vertical_zoom * (1.25 if io.mouse_wheel > 0 else 0.8), 0.25, 16.0))
            elif io.key_shift:
                self.pan(-io.mouse_wheel * span * 0.15)
            else:
                self.zoom(0.8 if io.mouse_wheel > 0 else 1.25, anchor=to_t(mouse.x))

    def _vertical_meter(self, draw, x, y_top, y_bottom, peak):
        for channel, value in enumerate(peak[:2]):
            x0 = x + channel * (METER_WIDTH + 1)
            draw.add_rect_filled((x0, y_top), (x0 + METER_WIDTH, y_bottom), P().bg0)
            if value > 0:
                db = 20 * np.log10(max(value, 1e-6))
                fill = float(np.clip((db + 60.0) / 60.0, 0.0, 1.0))
                top = y_bottom - fill * (y_bottom - y_top)
                shade = P().error if db > -3 else (P().warning if db > -12 else P().success)
                draw.add_rect_filled((x0, top), (x0 + METER_WIDTH, y_bottom), shade)

    def _master_lane(self, document, player, draw, child_origin, y, width, lane_x0, lane_width, to_x, to_t, head_x, tr, app, io, span, start, mouse):
        master = document.master
        lane_height = float(master.height)
        renderer = player.renderer
        imgui.push_id('master')
        draw.add_rect_filled((child_origin.x, y), (child_origin.x + HEADER_WIDTH - 4, y + lane_height - 2), cyui.mix(P().bg2, P().accent, 0.08))
        draw.add_rect_filled((child_origin.x, y), (child_origin.x + 4, y + lane_height - 2), P().accent)
        imgui.set_cursor_screen_pos((child_origin.x + 8, y + 4))
        imgui.align_text_to_frame_padding()
        with cyui.scoped_font(cyui.bold_font()):
            imgui.text(tr('Master'))
        imgui.same_line()
        clicked, value = cyui.toggle_button(tr('M') + '###master-mute', master.mute, P().warning, tip=tr('Mute'))
        if clicked:
            master.mute = value
            document.touch()
        imgui.same_line(0, 3)
        fx_active = bool(master.inserts)
        clicked, _ = cyui.toggle_button(('FX %d' % len(master.inserts) if fx_active else 'FX') + '###master-FX', fx_active,
                                        tip=tr('Effects and VST3 plugins of the master bus'))
        if clicked and app is not None:
            app.inserts.show(master)
        imgui.same_line(0, 3)
        self._automation_button(document, master, tr)
        imgui.set_cursor_screen_pos((child_origin.x + 8, y + 28))
        imgui.push_item_width(HEADER_WIDTH - 26)
        changed, gain = cyui.slider_bar('##master-gain', master.gain_db, -48.0, 12.0, tr('Gain') + ' %.1f dB')
        if imgui.is_item_activated():
            document.edit('Master gain', [])
        if changed:
            master.gain_db = gain
            document.touch()
            if app is not None and app.automation_write and player.playing:
                document.automation_write(master, 'gain_db', player.position, gain)
        imgui.pop_item_width()
        peak = renderer.master_peak if (player.playing or player.is_recording) else (0.0, 0.0)
        imgui.set_cursor_screen_pos((child_origin.x + 8, y + 52))
        horizontal_meter(peak[0], peak[1], HEADER_WIDTH - 30, 7.0)
        if lane_height >= 88:
            imgui.set_cursor_screen_pos((child_origin.x + 8, y + 72))
            imgui.text_disabled('%.1f / %.1f dBFS' % (20 * np.log10(max(peak[0], 1e-6)), 20 * np.log10(max(peak[1], 1e-6))) if peak[0] > 0 else tr('stereo output'))
        # lane
        x0, y0, x1, y1 = lane_x0, y, lane_x0 + lane_width, y + lane_height - 2
        draw.add_rect_filled((x0, y0), (x1, y1), cyui.mix(P().bg0, P().accent, 0.04))
        imgui.set_cursor_screen_pos((x0, y0))
        imgui.invisible_button('master-lane', (lane_width, lane_height - 2))
        hovered = imgui.is_item_hovered()
        master_header = imgui.is_mouse_hovering_rect((child_origin.x, y), (child_origin.x + HEADER_WIDTH, y + lane_height))
        if app is not None and (imgui.is_item_activated() or (master_header and imgui.is_mouse_clicked(imgui.MouseButton_.left))):
            app.inserts.follow(master)
        if master.automation_view:
            self._automation(document, master, draw, x0, y0, x1, y1, to_x, to_t, hovered, 'master-lane', tr)
        elif hovered:
            imgui.set_tooltip(tr('Master bus: A shows a volume automation lane here'))
        if hovered:
            self._wheel(io, span, start, to_t, mouse)
            if imgui.is_mouse_dragging(imgui.MouseButton_.middle) or imgui.is_mouse_dragging(imgui.MouseButton_.right, 3.0):
                self.pan(-io.mouse_delta.x / lane_width * span)
        cursor_x = to_x(document.cursor)
        if x0 <= cursor_x <= x1:
            draw.add_line((cursor_x, y0), (cursor_x, y1), cyui.alpha(P().text, 0.75), 1.0)
        if x0 <= head_x <= x1:
            draw.add_line((head_x, y0), (head_x, y1), P().accent, 1.5)
        imgui.set_cursor_screen_pos((child_origin.x, y1 - 3))
        imgui.invisible_button('resize', (width - 14, 5))
        if imgui.is_item_hovered() or imgui.is_item_active():
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ns)
        if imgui.is_item_activated():
            self.resizing = (master, master.height, mouse.y)
        if imgui.is_item_active() and self.resizing and self.resizing[0] is master:
            master.height = float(np.clip(self.resizing[1] + mouse.y - self.resizing[2], MIN_TRACK_HEIGHT, MAX_TRACK_HEIGHT))
        if imgui.is_item_deactivated():
            self.resizing = None
        imgui.pop_id()
        return y + lane_height

    def _scrollbar(self, document, lane_x0, lane_width, tr):
        """Horizontal scrollbar: drag it to move along the timeline like in a DAW."""
        total = max(document.duration, self.view[1], 1.0)
        start, stop = self.view
        span = max(1e-4, stop - start)
        origin = imgui.get_cursor_screen_pos()
        imgui.set_cursor_screen_pos((lane_x0, origin.y))
        imgui.invisible_button('hscroll', (lane_width, SCROLLBAR_HEIGHT))
        hovered, active = imgui.is_item_hovered(), imgui.is_item_active()
        draw = imgui.get_window_draw_list()
        y0 = origin.y
        y1 = y0 + SCROLLBAR_HEIGHT
        draw.add_rect_filled((lane_x0, y0), (lane_x0 + lane_width, y1), P().bg1, 3.0)
        width_ratio = min(1.0, span / total)
        handle_w = max(24.0, lane_width * width_ratio)
        handle_x = lane_x0 + (start / total) * lane_width
        handle_x = min(handle_x, lane_x0 + lane_width - handle_w)
        draw.add_rect_filled((handle_x, y0 + 2), (handle_x + handle_w, y1 - 2), P().accentDim if active else (cyui.brighter(P().bg5, 0.12) if hovered else P().bg5), 3.0)
        if hovered:
            imgui.set_tooltip(tr('Drag to move along the timeline'))
        mouse = imgui.get_mouse_pos()
        if imgui.is_item_activated():
            self.panning = (start, mouse.x, handle_x <= mouse.x <= handle_x + handle_w)
        if active and self.panning is not None:
            base_start, base_mouse, on_handle = self.panning
            if on_handle:
                begin = max(0.0, base_start + (mouse.x - base_mouse) / lane_width * total)
            else:
                begin = max(0.0, (mouse.x - lane_x0) / lane_width * total - span / 2)
            self.view = (begin, begin + span)
        if imgui.is_item_deactivated():
            self.panning = None

    def _overview(self, document, lane_x0, lane_width, tr):
        """Overview strip: every clip over the whole document; drag the window to navigate."""
        total = max(document.duration, self.view[1], 1.0)
        start, stop = self.view
        span = max(1e-4, stop - start)
        origin = imgui.get_cursor_screen_pos()
        imgui.set_cursor_screen_pos((lane_x0, origin.y + 2))
        imgui.invisible_button('overview', (lane_width, OVERVIEW_HEIGHT))
        hovered, active = imgui.is_item_hovered(), imgui.is_item_active()
        draw = imgui.get_window_draw_list()
        y0, y1 = origin.y + 2, origin.y + 2 + OVERVIEW_HEIGHT
        draw.add_rect_filled((lane_x0, y0), (lane_x0 + lane_width, y1), P().bg0, 3.0)
        rows = max(1, len(document.tracks))
        row_h = (OVERVIEW_HEIGHT - 4) / rows
        for index, track in enumerate(document.tracks):
            top = y0 + 2 + index * row_h
            for clip in track.clips:
                a = lane_x0 + document.frame_to_seconds(clip.offset) / total * lane_width
                b = lane_x0 + document.frame_to_seconds(clip.end) / total * lane_width
                draw.add_rect_filled((a, top), (max(a + 1, b), top + max(1.0, row_h - 1)), colour(*track.colour, 0.8))
        win_a = lane_x0 + start / total * lane_width
        win_b = lane_x0 + min(1.0, stop / total) * lane_width
        draw.add_rect_filled((win_a, y0), (win_b, y1), cyui.alpha(P().text, 0.10))
        draw.add_rect((win_a, y0), (win_b, y1), P().accent if (hovered or active) else cyui.alpha(P().text, 0.35))
        cursor_x = lane_x0 + document.cursor / total * lane_width
        draw.add_line((cursor_x, y0), (cursor_x, y1), cyui.alpha(P().text, 0.7))
        mouse = imgui.get_mouse_pos()
        if imgui.is_item_activated():
            self.overview_drag = (start, mouse.x, win_a <= mouse.x <= win_b)
        if active and self.overview_drag is not None:
            base_start, base_mouse, on_window = self.overview_drag
            if on_window:
                begin = max(0.0, base_start + (mouse.x - base_mouse) / lane_width * total)
            else:
                begin = max(0.0, (mouse.x - lane_x0) / lane_width * total - span / 2)
            self.view = (begin, begin + span)
        if imgui.is_item_deactivated():
            self.overview_drag = None
        if hovered and imgui.is_mouse_double_clicked(imgui.MouseButton_.left):
            self.fit(document)
        if hovered:
            imgui.set_tooltip(tr('Overview: drag the window to navigate, double-click to fit'))


def _nice_step(raw):
    if raw <= 0:
        return 1.0
    magnitude = 10 ** np.floor(np.log10(raw))
    for factor in (1, 2, 5, 10):
        if factor * magnitude >= raw:
            return float(factor * magnitude)
    return float(10 * magnitude)
