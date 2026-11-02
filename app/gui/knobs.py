"""Drawing primitives for the effect interfaces: rotary knobs, level and gain-reduction meters,
plot areas with dB / log-frequency axes. Colours come from the CyUI palette by role (gui/cyui), so
every drawing follows the theme chosen in the Options tab.
"""
import math

import numpy as np
from imgui_bundle import imgui

from . import cyui
from cyui_modules import audio
from cyui_modules.plots import Axis
from cyui_modules.common import Range

KNOB_SIZE = 44.0
METER_WIDTH = 10.0


def col(r, g, b, a=1.0):
    """A literal colour (track colours stored as float tuples)."""
    return cyui.from_floats(r, g, b, a)


def accent():
    """The theme accent as (r, g, b) floats."""
    return cyui.floats(cyui.palette().accent)[:3]


def accent_col(alpha=1.0):
    return cyui.alpha(cyui.palette().accent, alpha)


def warm(alpha=1.0):
    """The second highlight of the plots (levels, thresholds, markers): the palette's warning tone."""
    return cyui.alpha(cyui.palette().warning, alpha)


def cool(alpha=1.0):
    """Information tone (left channel, bands): the palette's info colour."""
    return cyui.alpha(cyui.palette().info, alpha)


def text_col(alpha=1.0):
    return cyui.alpha(cyui.palette().text, alpha)


def grid_col(major=False):
    p = cyui.palette()
    return p.gridStrong if major else p.grid


def label_col():
    return cyui.palette().textFaint


def frame_bg(alpha=None):
    """The ground of canvases and wells (bg0)."""
    colour = cyui.palette().bg0
    return colour if alpha is None else cyui.alpha(colour, alpha)


def theme_col(index, alpha=None):
    """A style colour as u32 (optionally with another alpha)."""
    c = imgui.get_style().color_(index)
    return imgui.get_color_u32((c.x, c.y, c.z, c.w if alpha is None else alpha))


def db_to_unit(db, floor=-60.0):
    return float(np.clip((db - floor) / -floor, 0.0, 1.0))


def gain_to_db(value):
    return 20.0 * math.log10(max(float(value), 1e-9))


# ----------------------------------------------------------------------------- knob

def knob(label,value,minimum,maximum,fmt='%.2f',log=False,size=KNOB_SIZE,tooltip='',default=None,automated=False):
    """Shared rotary control plus the host's formatted, directly editable value."""
    imgui.begin_group()
    origin=imgui.get_cursor_screen_pos()
    changed,value=audio.knob(label,float(value),float(minimum),float(maximum),float(value if default is None else default),
        diameter=size/cyui.core.dpi(),label=label.split('##')[0],logarithmic=log)
    knob.last_activated=imgui.is_item_activated() or (changed and not imgui.is_item_active())
    cyui.push_id(label)
    if tooltip:cyui.tooltip(tooltip)
    # CyUI Python does not expose its C++ typed-entry popover. Retain that host
    # capability, including units/precision and Escape, rather than losing it.
    text_h=imgui.get_text_line_height()
    shown=fmt%value if '%' in fmt else fmt
    open_now=imgui.selectable(shown+'##value',False,0,(max(size,cyui.dp(58)),text_h))[0]
    pos=imgui.get_item_rect_min();maximum_pos=imgui.get_item_rect_max()
    typed,number=cyui.value_entry('knob',tuple(pos),tuple(maximum_pos),value,minimum,maximum,open_now)
    if typed:value=number;changed=True;knob.last_activated=True
    if automated:
        imgui.get_window_draw_list().add_circle_filled((origin.x+size,origin.y+cyui.dp(3)),cyui.dp(3),cyui.palette().warning)
    cyui.pop_id()
    imgui.end_group()
    return changed,value


# ----------------------------------------------------------------------------- meters

def level_meter(peak,width=METER_WIDTH,height=90.0,floor=-60.0,hold=None,label=''):
    audio.meter('##level-'+label,[float(peak)],[float(peak)],(width/cyui.core.dpi(),height/cyui.core.dpi()),True)
    if label:imgui.same_line();cyui.text_faint(label)
    return gain_to_db(peak) if peak>0 else floor


def reduction_meter(reduction_db, width=METER_WIDTH, height=90.0, range_db=-30.0, label='GR'):
    """Gain-reduction meter growing downwards from the top (0 dB)."""
    p = cyui.palette()
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy((width + imgui.calc_text_size(label).x + 4, height))
    draw = imgui.get_window_draw_list()
    x0, y0, x1, y1 = origin.x, origin.y, origin.x + width, origin.y + height
    draw.add_rect_filled((x0, y0), (x1, y1), p.bg0, 2.0)
    amount = float(np.clip(reduction_db / range_db, 0.0, 1.0)) if reduction_db < 0 else 0.0
    if amount > 0:
        draw.add_rect_filled((x0 + 1, y0 + 1), (x1 - 1, y0 + 1 + amount * (height - 2)), p.warning)
    draw.add_text((x1 + 3, y0), p.textFaint, label)
    draw.add_text((x1 + 3, y1 - imgui.get_text_line_height()), p.textDim, '%.1f' % reduction_db)


def horizontal_meter(peak_l, peak_r, width=140.0, height=8.0, floor=-60.0):
    """Two horizontal level bars (left above right), CyUI meter law and colours, with a peak hold."""
    cyui.meter('##hmeter', (width, height * 2 + 2), peak_l, peak_r, vertical=False)


# ----------------------------------------------------------------------------- plots

class Plot:
    """A plot area: maps x in [x_min, x_max] (optionally log) and y in [y_min, y_max] to pixels.

    Each plot of a frame gets its own widget identifier (a serial reset by ``Plot.new_frame``), so
    several plots in one interface never share an ID."""

    _serial = 0

    @classmethod
    def new_frame(cls):
        cls._serial = 0

    def __init__(self, width, height, x_range, y_range, log_x=False):
        self.origin = imgui.get_cursor_screen_pos()
        self.width, self.height = float(width), float(height)
        self.x_min, self.x_max = float(x_range[0]), float(x_range[1])
        self.y_min, self.y_max = float(y_range[0]), float(y_range[1])
        self.log_x = log_x
        self.draw = imgui.get_window_draw_list()
        Plot._serial += 1
        imgui.invisible_button('##plot%d' % Plot._serial, (self.width, self.height))
        self.hovered = imgui.is_item_hovered()
        self.active = imgui.is_item_active()
        self.x0, self.y0 = self.origin.x, self.origin.y
        self.x1, self.y1 = self.origin.x + self.width, self.origin.y + self.height
        self.draw.add_rect_filled((self.x0, self.y0), (self.x1, self.y1), frame_bg(), 3.0)
        self.draw.push_clip_rect((self.x0, self.y0), (self.x1, self.y1), True)

    def end(self):
        self.draw.pop_clip_rect()
        self.draw.add_rect((self.x0, self.y0), (self.x1, self.y1), cyui.palette().line, 3.0)

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
            self.draw.add_line((x, self.y0), (x, self.y1), grid_col(True))
            if labels:
                text = fmt(value) if fmt else str(value)
                self.draw.add_text((x + 2, self.y1 - imgui.get_text_line_height() - 1), label_col(), text)

    def grid_y(self, values, labels=True, fmt=None):
        for value in values:
            y = self.py(value)
            self.draw.add_line((self.x0, y), (self.x1, y), grid_col(True))
            if labels:
                text = fmt(value) if fmt else str(value)
                self.draw.add_text((self.x0 + 2, y - imgui.get_text_line_height() / 2), label_col(), text)

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
