"""CyUI layout: tool bars, status bar, panel headers, modal dialogs.

Python port of ``Layout.h`` / ``Layout.cpp`` of CyUI (D:/_Project/CyImgui_Interface). Two
adaptations for applications drawn inside one host window (hello_imgui's full-screen window):

* ``begin_status_bar`` / ``begin_top_bar`` use viewport side bars when ``viewport=True`` (as in
  C++); by default they draw a strip at the current cursor position.
* ``FlowBar`` is an addition: tool groups separated by ``toolbar_separator`` lines that wrap to the
  next line when the window is narrow (each group remembers its width from the previous frame).
"""
from contextlib import contextmanager

from imgui_bundle import imgui

from .theme import palette, metrics, dp, alpha, bold_font
from .widgets import (scoped_colour, scoped_var, scoped_font, heading, text_faint, badge, space, overline, icon_button, button,
                      visible, clipped_text, tone_colour, NEUTRAL, PRIMARY, DANGER, SECONDARY, WARNING)
from . import icons as icon
from .theme import icons_available

BAR_FLAGS = imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_scroll_with_mouse


# ----------------------------------------------------------------------------- bars

@contextmanager
def toolbar(id, wrap=True):
    """A tool strip: bg2 ground, padding, a line under it; grows with its content (wrapping groups).
    Use as ``with toolbar('##editor-bar'): ...``."""
    p = palette()
    pad = dp(6.0, 4.0)
    flags = imgui.ChildFlags_.always_use_window_padding | (imgui.ChildFlags_.auto_resize_y if wrap else 0)
    height = 0.0 if wrap else imgui.get_frame_height() + pad.y * 2.0
    with scoped_colour((imgui.Col_.child_bg, p.bg2)), scoped_var((imgui.StyleVar_.window_padding, pad), (imgui.StyleVar_.child_rounding, 0.0), (imgui.StyleVar_.child_border_size, 0.0)):
        shown = imgui.begin_child(id, (0.0, height), flags, imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse)
    try:
        yield shown
    finally:
        pos, size = imgui.get_window_pos(), imgui.get_window_size()
        imgui.get_window_draw_list().add_line((pos.x, pos.y + size.y - 0.5), (pos.x + size.x, pos.y + size.y - 0.5), p.line)
        imgui.end_child()


class FlowBar:
    """Groups of tool controls on one line, separated by thin bars, wrapping to the next line when
    the window is too narrow::

        bar = FlowBar()
        with bar.group('transport'):
            ...widgets joined with imgui.same_line()...
    """
    _widths = {}

    def __init__(self, key=''):
        self.key = key
        self.right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        self.first = True

    @contextmanager
    def group(self, key, align_right=False):
        width = FlowBar._widths.get((self.key, key))
        if not self.first:
            gap = dp(6.0) * 2.0 + dp(1.0)
            if width is not None and imgui.get_item_rect_max().x + gap + width <= self.right:
                imgui.same_line(0.0, dp(6.0))
                origin = imgui.get_cursor_screen_pos()
                height = imgui.get_frame_height()
                imgui.get_window_draw_list().add_line((origin.x, origin.y + height * 0.18), (origin.x, origin.y + height * 0.82), palette().lineStrong)
                imgui.dummy((dp(1.0), height))
                imgui.same_line(0.0, dp(6.0))
                if align_right:
                    room = self.right - imgui.get_cursor_screen_pos().x - width
                    if room > 0:
                        imgui.dummy((room, 1.0))
                        imgui.same_line(0.0, 0.0)
        self.first = False
        imgui.begin_group()
        try:
            yield
        finally:
            imgui.end_group()
            size = imgui.get_item_rect_size()
            if size.y > 0.0:                     # a clipped (not drawn) group has no meaningful width
                FlowBar._widths[(self.key, key)] = size.x


@contextmanager
def status_bar(id, viewport=False):
    """The bottom strip: bg0 ground, small text. Use status_text() inside it."""
    p = palette()
    height = imgui.get_font_size() * 0.86 + dp(10.0)
    if viewport:
        imgui.push_style_color(imgui.Col_.window_bg, p.bg0)
        imgui.push_style_var(imgui.StyleVar_.window_padding, dp(8.0, 4.0))
        imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
        shown = imgui.internal.begin_viewport_side_bar(id, imgui.get_main_viewport(), imgui.Dir.down, height, BAR_FLAGS)
        try:
            yield shown
        finally:
            imgui.end()
            imgui.pop_style_var(2)
            imgui.pop_style_color()
        return
    with scoped_colour((imgui.Col_.child_bg, p.bg0)), scoped_var((imgui.StyleVar_.window_padding, dp(8.0, 3.0)), (imgui.StyleVar_.child_rounding, 0.0),
                                                                  (imgui.StyleVar_.child_border_size, 0.0), (imgui.StyleVar_.item_spacing, dp(10.0, 2.0))):
        shown = imgui.begin_child(id, (0.0, height), imgui.ChildFlags_.always_use_window_padding, BAR_FLAGS)
    try:
        pos, size = imgui.get_window_pos(), imgui.get_window_size()
        imgui.get_window_draw_list().add_line((pos.x, pos.y + 0.5), (pos.x + size.x, pos.y + 0.5), p.lineStrong)
        yield shown
    finally:
        imgui.end_child()


def status_bar_height():
    return imgui.get_font_size() * 0.86 + dp(10.0)


def status_text(text, tone=NEUTRAL):
    p = palette()
    with scoped_font(None, 0.86):
        imgui.text_colored(_vec(p.textFaint if tone == NEUTRAL else tone_colour(tone)), str(text))


def _vec(colour):
    from .theme import vec
    return vec(colour)


def panel_header(title, subtitle=None):
    heading(title, 2)
    if subtitle:
        with scoped_font(None, 0.88):
            text_faint(subtitle)


def align_right(width):
    right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
    imgui.set_cursor_pos_x(max(imgui.get_cursor_pos_x(), right - width))


def button_width(label):
    return imgui.calc_text_size(visible(label)).x + imgui.get_style().frame_padding.x * 2.0


# ----------------------------------------------------------------------------- sidebar

def sidebar_group(label):
    space(6.0)
    imgui.indent(dp(4.0))
    overline(label, palette().textFaint)
    imgui.unindent(dp(4.0))
    space(2.0)


def sidebar_item(glyph, label, active=False, badge_text=None):
    p = palette()
    width = imgui.get_content_region_avail().x
    height = imgui.get_frame_height() + dp(8.0)
    origin = imgui.get_cursor_screen_pos()
    imgui.push_id(label)
    clicked = imgui.invisible_button('##item', (width, height))
    hovered = imgui.is_item_hovered()
    imgui.pop_id()
    draw = imgui.get_window_draw_list()
    rounding = imgui.get_style().frame_rounding + dp(2.0)
    p_max = (origin.x + width, origin.y + height)
    if active:
        draw.add_rect_filled(origin, p_max, alpha(p.accent, 0.16), rounding)
        draw.add_rect(origin, p_max, alpha(p.accent, 0.45), rounding)
    elif hovered:
        draw.add_rect_filled(origin, p_max, p.bg3, rounding)
    colour = p.text if (active or hovered) else p.textDim
    x = origin.x + dp(10.0)
    y = origin.y + (height - imgui.get_font_size()) * 0.5
    if glyph and icons_available():
        draw.add_text((x, y), p.accent if active else colour, glyph)
        x += imgui.get_font_size() + dp(10.0)
    clipped_text(draw, (x, y), p_max[0] - x - dp(8.0), colour, label)
    imgui.dummy((0.0, dp(1.0)))
    return clicked


# ----------------------------------------------------------------------------- modal

class _Modal:
    open_flag = None


def begin_modal(title, opened=True, width=420.0):
    """A centred modal with a title and a close button. Returns (shown, opened); call end_modal()
    only when shown."""
    if opened and not imgui.is_popup_open(title):
        imgui.open_popup(title)
    viewport = imgui.get_main_viewport()
    imgui.set_next_window_pos(viewport.get_center(), imgui.Cond_.appearing, (0.5, 0.5))
    imgui.set_next_window_size((dp(width), 0.0), imgui.Cond_.always)
    p = palette()
    with scoped_var((imgui.StyleVar_.window_padding, dp(18.0, 16.0)), (imgui.StyleVar_.window_rounding, dp(metrics().rounding_large + 4.0))), \
            scoped_colour((imgui.Col_.popup_bg, p.bg2), (imgui.Col_.border, p.lineStrong)):
        shown = imgui.begin_popup_modal(title, None, imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_saved_settings)[0]
    if not shown:
        return False, False
    with scoped_font(bold_font(), 1.15):
        imgui.text_unformatted(visible(title))
    imgui.same_line()
    align_right(imgui.get_frame_height())
    if icon_button(icon.close, None, fallback='x', id='##modal-close'):
        imgui.close_current_popup()
        opened = False
    space(6.0)
    return True, opened


def end_modal():
    imgui.end_popup()


def modal_buttons(confirm, cancel=None, danger=False):
    """Right-aligned buttons: returns 1 for confirm (or Enter), 2 for cancel (or Escape), else 0."""
    space(10.0)
    style = imgui.get_style()
    confirm_w = max(dp(84.0), button_width(confirm))
    cancel_w = max(dp(84.0), button_width(cancel)) if cancel else 0.0
    align_right(confirm_w + (cancel_w + style.item_spacing.x if cancel else 0.0))
    result = 0
    if cancel:
        if button(cancel, SECONDARY, (cancel_w, 0.0)) or imgui.is_key_pressed(imgui.Key.escape, False):
            result = 2
        imgui.same_line()
    if button(confirm, DANGER if danger else PRIMARY, (confirm_w, 0.0)) or (imgui.is_key_pressed(imgui.Key.enter, False) and not imgui.is_any_item_active()):
        result = 1
    if result:
        imgui.close_current_popup()
    return result
