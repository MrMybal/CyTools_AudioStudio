"""Drawing primitives for the effect interfaces: rotary knobs, level and gain-reduction meters,
plot areas with dB / log-frequency axes. Everything is drawn with the window draw list so it
follows the ImGui theme (dark, light, classic) of the Options tab.
"""
import math

import numpy as np
from imgui_bundle import imgui

KNOB_SIZE = 44.0
METER_WIDTH = 10.0


def col(r, g, b, a=1.0):
    return imgui.get_color_u32((r, g, b, a))


def theme_col(index, alpha=None):
    """A style colour as u32 (optionally with another alpha)."""
    c = imgui.get_style().color_(index)
    return imgui.get_color_u32((c.x, c.y, c.z, c.w if alpha is None else alpha))


def accent():
    c = imgui.get_style().color_(imgui.Col_.slider_grab)
    return (c.x, c.y, c.z)


def text_col(alpha=1.0):
    return theme_col(imgui.Col_.text, alpha)


def frame_bg(alpha=None):
    return theme_col(imgui.Col_.frame_bg, alpha)


def db_to_unit(db, floor=-60.0):
    return float(np.clip((db - floor) / -floor, 0.0, 1.0))


def gain_to_db(value):
    return 20.0 * math.log10(max(float(value), 1e-9))


# ----------------------------------------------------------------------------- knob

def knob(label, value, minimum, maximum, fmt='%.2f', log=False, size=KNOB_SIZE, tooltip='', default=None, automated=False):
    """Rotary knob; drag vertically (Ctrl for fine), double-click resets. Returns (changed, value)."""
    io = imgui.get_io()
    imgui.push_id(label)
    origin = imgui.get_cursor_screen_pos()
    text_h = imgui.get_text_line_height()
    width = max(size, imgui.calc_text_size(label.split('##')[0]).x + 4)
    imgui.invisible_button('##knob', (width, size + text_h * 2 + 4))
    hovered, active = imgui.is_item_hovered(), imgui.is_item_active()
    changed = False
    minimum, maximum = float(minimum), float(maximum)
    value = float(np.clip(value, minimum, maximum))
    if log and minimum > 0:
        to_norm = lambda v: (math.log(v) - math.log(minimum)) / (math.log(maximum) - math.log(minimum))
        from_norm = lambda n: math.exp(math.log(minimum) + n * (math.log(maximum) - math.log(minimum)))
    else:
        to_norm = lambda v: (v - minimum) / (maximum - minimum) if maximum > minimum else 0.0
        from_norm = lambda n: minimum + n * (maximum - minimum)
    norm = float(np.clip(to_norm(value), 0.0, 1.0))
    if active and (io.mouse_delta.y != 0.0 or io.mouse_delta.x != 0.0):
        speed = 0.0025 if io.key_ctrl else 0.01
        norm = float(np.clip(norm - io.mouse_delta.y * speed + io.mouse_delta.x * speed * 0.5, 0.0, 1.0))
        value = from_norm(norm)
        changed = True
    if hovered and imgui.is_mouse_double_clicked(imgui.MouseButton_.left) and default is not None:
        value = float(np.clip(default, minimum, maximum))
        norm = float(np.clip(to_norm(value), 0.0, 1.0))
        changed = True
    if hovered and io.mouse_wheel != 0.0:
        norm = float(np.clip(norm + io.mouse_wheel * (0.01 if io.key_ctrl else 0.04), 0.0, 1.0))
        value = from_norm(norm)
        changed = True
    draw = imgui.get_window_draw_list()
    centre = (origin.x + width / 2, origin.y + size / 2)
    radius = size / 2 - 3
    start_angle, end_angle = math.pi * 0.75, math.pi * 2.25
    draw.add_circle_filled(centre, radius, frame_bg(), 32)
    draw.path_clear()
    draw.path_arc_to(centre, radius - 2, start_angle, end_angle, 32)
    draw.path_stroke(theme_col(imgui.Col_.frame_bg_hovered), 3.0, 0)
    angle = start_angle + norm * (end_angle - start_angle)
    ar, ag, ab = accent()
    if norm > 0.001:
        draw.path_clear()
        draw.path_arc_to(centre, radius - 2, start_angle, angle, 32)
        draw.path_stroke(col(ar, ag, ab, 1.0 if (hovered or active) else 0.85), 3.0, 0)
    tip = (centre[0] + math.cos(angle) * (radius - 7), centre[1] + math.sin(angle) * (radius - 7))
    draw.add_line(centre, tip, text_col(0.95), 2.0)
    if automated:
        draw.add_circle_filled((origin.x + width - 5, origin.y + 5), 3.5, col(1.0, 0.6, 0.2), 12)
    text = label.split('##')[0]
    draw.add_text((origin.x + (width - imgui.calc_text_size(text).x) / 2, origin.y + size + 2), text_col(0.9), text)
    shown = fmt % value if '%' in fmt else fmt
    draw.add_text((origin.x + (width - imgui.calc_text_size(shown).x) / 2, origin.y + size + text_h + 2), text_col(0.7), shown)
    if hovered and tooltip:
        imgui.set_tooltip(tooltip)
    imgui.pop_id()
    return changed, value


# ----------------------------------------------------------------------------- meters

def level_meter(peak, width=METER_WIDTH, height=90.0, floor=-60.0, hold=None, label=''):
    """Vertical peak meter in dB (green / yellow / red). ``hold`` is a peak-hold value in dB or None."""
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy((width + (imgui.calc_text_size(label).x + 4 if label else 0), height))
    draw = imgui.get_window_draw_list()
    x0, y0, x1, y1 = origin.x, origin.y, origin.x + width, origin.y + height
    draw.add_rect_filled((x0, y0), (x1, y1), frame_bg())
    db = gain_to_db(peak) if peak > 0 else floor
    fill = db_to_unit(db, floor)
    top = y1 - fill * height
    # three zones
    green_top = y1 - db_to_unit(-12.0, floor) * height
    yellow_top = y1 - db_to_unit(-3.0, floor) * height
    if fill > 0:
        draw.add_rect_filled((x0 + 1, max(top, green_top)), (x1 - 1, y1 - 1), col(0.3, 0.8, 0.35))
        if top < green_top:
            draw.add_rect_filled((x0 + 1, max(top, yellow_top)), (x1 - 1, green_top), col(0.9, 0.8, 0.2))
        if top < yellow_top:
            draw.add_rect_filled((x0 + 1, top), (x1 - 1, yellow_top), col(0.95, 0.3, 0.25))
    if hold is not None and hold > floor:
        y = y1 - db_to_unit(hold, floor) * height
        draw.add_line((x0 + 1, y), (x1 - 1, y), text_col(0.9), 1.5)
    if label:
        draw.add_text((x1 + 3, y1 - imgui.get_text_line_height()), text_col(0.7), label)
    return db


def reduction_meter(reduction_db, width=METER_WIDTH, height=90.0, range_db=-30.0, label='GR'):
    """Gain-reduction meter growing downwards from the top (0 dB)."""
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy((width + imgui.calc_text_size(label).x + 4, height))
    draw = imgui.get_window_draw_list()
    x0, y0, x1, y1 = origin.x, origin.y, origin.x + width, origin.y + height
    draw.add_rect_filled((x0, y0), (x1, y1), frame_bg())
    amount = float(np.clip(reduction_db / range_db, 0.0, 1.0)) if reduction_db < 0 else 0.0
    if amount > 0:
        draw.add_rect_filled((x0 + 1, y0 + 1), (x1 - 1, y0 + 1 + amount * (height - 2)), col(0.98, 0.62, 0.2))
    draw.add_text((x1 + 3, y0), text_col(0.7), label)
    draw.add_text((x1 + 3, y1 - imgui.get_text_line_height()), text_col(0.7), '%.1f' % reduction_db)


def horizontal_meter(peak_l, peak_r, width=140.0, height=8.0, floor=-60.0):
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy((width, height * 2 + 2))
    draw = imgui.get_window_draw_list()
    for row, peak in enumerate((peak_l, peak_r)):
        y0 = origin.y + row * (height + 2)
        draw.add_rect_filled((origin.x, y0), (origin.x + width, y0 + height), frame_bg())
        db = gain_to_db(peak) if peak > 0 else floor
        fill = db_to_unit(db, floor) * width
        if fill > 0:
            colour = col(0.95, 0.3, 0.25) if db > -3.0 else (col(0.9, 0.8, 0.2) if db > -12.0 else col(0.3, 0.8, 0.35))
            draw.add_rect_filled((origin.x, y0), (origin.x + fill, y0 + height), colour)


# ----------------------------------------------------------------------------- plots

class Plot:
    """A plot area: maps x in [x_min, x_max] (optionally log) and y in [y_min, y_max] to pixels."""

    def __init__(self, width, height, x_range, y_range, log_x=False):
        self.origin = imgui.get_cursor_screen_pos()
        self.width, self.height = float(width), float(height)
        self.x_min, self.x_max = float(x_range[0]), float(x_range[1])
        self.y_min, self.y_max = float(y_range[0]), float(y_range[1])
        self.log_x = log_x
        self.draw = imgui.get_window_draw_list()
        imgui.invisible_button('##plot', (self.width, self.height))
        self.hovered = imgui.is_item_hovered()
        self.active = imgui.is_item_active()
        self.x0, self.y0 = self.origin.x, self.origin.y
        self.x1, self.y1 = self.origin.x + self.width, self.origin.y + self.height
        self.draw.add_rect_filled((self.x0, self.y0), (self.x1, self.y1), frame_bg())
        self.draw.push_clip_rect((self.x0, self.y0), (self.x1, self.y1), True)

    def end(self):
        self.draw.pop_clip_rect()
        self.draw.add_rect((self.x0, self.y0), (self.x1, self.y1), theme_col(imgui.Col_.border))

    def px(self, x):
        if self.log_x:
            lo, hi = math.log(max(self.x_min, 1e-6)), math.log(max(self.x_max, 1e-6))
            t = (math.log(max(float(x), 1e-6)) - lo) / (hi - lo)
        else:
            t = (float(x) - self.x_min) / (self.x_max - self.x_min) if self.x_max != self.x_min else 0.0
        return self.x0 + t * self.width

    def py(self, y):
        t = (float(y) - self.y_min) / (self.y_max - self.y_min) if self.y_max != self.y_min else 0.0
        return self.y1 - t * self.height

    def x_at(self, px):
        t = (px - self.x0) / self.width
        if self.log_x:
            lo, hi = math.log(max(self.x_min, 1e-6)), math.log(max(self.x_max, 1e-6))
            return math.exp(lo + t * (hi - lo))
        return self.x_min + t * (self.x_max - self.x_min)

    def y_at(self, py):
        t = (self.y1 - py) / self.height
        return self.y_min + t * (self.y_max - self.y_min)

    def grid_x(self, values, labels=True, fmt=None):
        for value in values:
            x = self.px(value)
            self.draw.add_line((x, self.y0), (x, self.y1), text_col(0.12))
            if labels:
                text = fmt(value) if fmt else str(value)
                self.draw.add_text((x + 2, self.y1 - imgui.get_text_line_height() - 1), text_col(0.5), text)

    def grid_y(self, values, labels=True, fmt=None):
        for value in values:
            y = self.py(value)
            self.draw.add_line((self.x0, y), (self.x1, y), text_col(0.12))
            if labels:
                text = fmt(value) if fmt else str(value)
                self.draw.add_text((self.x0 + 2, y - imgui.get_text_line_height() / 2), text_col(0.5), text)

    def line(self, xs, ys, colour, thickness=1.5):
        xs, ys = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
        if xs.size < 2:
            return
        if self.log_x:
            lo, hi = math.log(max(self.x_min, 1e-6)), math.log(max(self.x_max, 1e-6))
            pxs = self.x0 + (np.log(np.maximum(xs, 1e-6)) - lo) / (hi - lo) * self.width
        else:
            pxs = self.x0 + (xs - self.x_min) / (self.x_max - self.x_min) * self.width
        pys = self.y1 - (np.clip(ys, self.y_min - 10, self.y_max + 10) - self.y_min) / (self.y_max - self.y_min) * self.height
        points = [imgui.ImVec2(float(x), float(y)) for x, y in zip(pxs, pys)]
        self.draw.add_polyline(points, colour, thickness, 0)

    def fill_under(self, xs, ys, colour):
        """Area between the curve and the bottom of the plot, as one concave polygon (no seams)."""
        xs, ys = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
        if xs.size < 2:
            return
        if self.log_x:
            lo, hi = math.log(max(self.x_min, 1e-6)), math.log(max(self.x_max, 1e-6))
            pxs = self.x0 + (np.log(np.maximum(xs, 1e-6)) - lo) / (hi - lo) * self.width
        else:
            pxs = self.x0 + (xs - self.x_min) / (self.x_max - self.x_min) * self.width
        pys = self.y1 - (np.clip(ys, self.y_min, self.y_max) - self.y_min) / (self.y_max - self.y_min) * self.height
        points = [imgui.ImVec2(float(pxs[0]), float(self.y1))]
        points += [imgui.ImVec2(float(x), float(y)) for x, y in zip(pxs, pys)]
        points.append(imgui.ImVec2(float(pxs[-1]), float(self.y1)))
        self.draw.add_concave_poly_filled(points, colour)

    def point(self, x, y, radius, colour, outline=None):
        p = (self.px(x), self.py(y))
        self.draw.add_circle_filled(p, radius, colour, 16)
        if outline is not None:
            self.draw.add_circle(p, radius, outline, 16, 1.5)
        return p


def freq_label(value):
    value = float(value)
    return ('%gk' % (value / 1000.0)) if value >= 1000 else '%g' % value


FREQ_GRID = (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000)
