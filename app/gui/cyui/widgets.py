"""CyUI widgets: the controls of CyDAW 2 / Shaderixel / CyEngineHub, made generic.

Python port of ``Widgets.h`` / ``Widgets.cpp`` of CyUI (D:/_Project/CyImgui_Interface). Every widget
draws with ``palette()`` and ``metrics()``, so it follows the theme, and is an ordinary ImGui item
(same_line, push_id, is_item_hovered... work after it).

Python conventions: where C++ takes a pointer, the function takes the value and returns
``(changed, value)``. Widgets that the C++ version identifies by their icon or label accept an
``id`` keyword so an application can keep its stable widget identities (``"Label###id"`` rule).

Value controls share the CyDAW behaviour: drag to change, Ctrl = fine, Shift = fast, the mouse
wheel nudges, a double click resets (knob) or types the value (slider bar).
"""
from contextlib import contextmanager
import math
import re
import time

from imgui_bundle import imgui

from .theme import (palette, metrics, dp, alpha, mix, brighter, rgb, vec, contrast_text, bold_font, ui_font, mono_font, icons_available)
from . import icons as icon

TAU = math.pi * 2.0
FLT_MIN = 1.175494351e-38
ARC_START = math.pi * 0.75
ARC_SWEEP = math.pi * 1.5

NEUTRAL, ACCENT, SUCCESS, WARNING, ERROR, INFO = 'neutral', 'accent', 'success', 'warning', 'error', 'info'
SECONDARY, PRIMARY, GHOST, OUTLINE, DANGER = 'secondary', 'primary', 'ghost', 'outline', 'danger'


def visible(label):
    """The part of a label ImGui draws ('##' and '###' suffixes are identity only)."""
    return str(label).split('##')[0]


def tone_colour(tone):
    p = palette()
    return {ACCENT: p.accent, SUCCESS: p.success, WARNING: p.warning, ERROR: p.error, INFO: p.info}.get(tone, p.textDim)


# ----------------------------------------------------------------------------- scoped helpers

@contextmanager
def scoped_colour(*pairs):
    """scoped_colour((imgui.Col_.text, colour), ...) with packed colours or ImVec4."""
    for index, colour in pairs:
        imgui.push_style_color(index, colour if not isinstance(colour, int) else vec(colour))
    try:
        yield
    finally:
        imgui.pop_style_color(len(pairs))


@contextmanager
def scoped_var(*pairs):
    for index, value in pairs:
        imgui.push_style_var(index, value)
    try:
        yield
    finally:
        imgui.pop_style_var(len(pairs))


@contextmanager
def scoped_font(font=None, factor=1.0):
    """A font and/or a size factor of the base size (1 = normal, 0.85 = small)."""
    imgui.push_font(font, imgui.get_style().font_size_base * factor)
    try:
        yield
    finally:
        imgui.pop_font()


@contextmanager
def scoped_id(value):
    imgui.push_id(str(value))
    try:
        yield
    finally:
        imgui.pop_id()


@contextmanager
def scoped_disabled(disabled=True):
    imgui.begin_disabled(bool(disabled))
    try:
        yield
    finally:
        imgui.end_disabled()


# ----------------------------------------------------------------------------- text

def heading(text, level=2):
    """A title: level 1 (page, 1.5x semibold), 2 (panel, 1.2x), 3 (group, 1.0x)."""
    factor = 1.5 if level <= 1 else 1.2 if level == 2 else 1.0
    with scoped_font(bold_font(), factor), scoped_colour((imgui.Col_.text, palette().text)):
        imgui.text_unformatted(text)


def section_title(text):
    """Small semibold dimmed title for a group inside a panel."""
    with scoped_font(bold_font(), 0.85), scoped_colour((imgui.Col_.text, palette().textDim)):
        imgui.text_unformatted(text)


def overline(text, colour=0):
    """CyEngineHub-style label: SMALL UPPERCASE, bold, accent-tinted. Pass the text uppercased."""
    p = palette()
    with scoped_font(bold_font(), 0.78), scoped_colour((imgui.Col_.text, colour or mix(p.accent, p.text, 0.35))):
        imgui.text_unformatted(text)


def text_dim(text):
    imgui.text_colored(vec(palette().textDim), str(text))


def text_faint(text):
    imgui.text_colored(vec(palette().textFaint), str(text))


def text_coloured(colour, text):
    imgui.text_colored(vec(colour), str(text))


def text_wrapped_dim(text):
    with scoped_colour((imgui.Col_.text, palette().textDim)):
        imgui.text_wrapped(str(text))


def text_wrapped_faint(text):
    with scoped_colour((imgui.Col_.text, palette().textFaint)):
        imgui.text_wrapped(str(text))


def text_mono(text, colour=0):
    with scoped_font(mono_font(), 1.0):
        if colour:
            imgui.text_colored(vec(colour), str(text))
        else:
            imgui.text_unformatted(str(text))


def kbd(keys):
    """A keyboard shortcut drawn as a key cap."""
    p = palette()
    with scoped_font(None, 0.82):
        size = imgui.calc_text_size(keys)
        pad = dp(5.0, 1.0)
        origin = imgui.get_cursor_screen_pos()
        box = (size.x + pad.x * 2.0, size.y + pad.y * 2.0)
        draw = imgui.get_window_draw_list()
        rounding = dp(3.0)
        draw.add_rect_filled((origin.x, origin.y + dp(1.0)), (origin.x + box[0], origin.y + box[1] + dp(1.0)), p.lineStrong, rounding)
        draw.add_rect_filled(origin, (origin.x + box[0], origin.y + box[1]), p.bg3, rounding)
        draw.add_rect(origin, (origin.x + box[0], origin.y + box[1]), p.line, rounding)
        draw.add_text((origin.x + pad.x, origin.y + pad.y), p.textDim, keys)
        imgui.dummy((box[0], box[1] + dp(1.0)))


def tooltip(text, allow_disabled=True):
    """A delayed, wrapped tooltip for the last item (nothing when text is empty)."""
    if not text:
        return
    flags = imgui.HoveredFlags_.delay_short | imgui.HoveredFlags_.no_shared_delay
    if allow_disabled:
        flags |= imgui.HoveredFlags_.allow_when_disabled
    if not imgui.is_item_hovered(flags):
        return
    if imgui.begin_tooltip():
        imgui.push_text_wrap_pos(imgui.get_font_size() * 32.0)
        imgui.text_unformatted(str(text))
        imgui.pop_text_wrap_pos()
        imgui.end_tooltip()


def help_marker(text):
    """A small (i) after the previous item, its tooltip on hover."""
    imgui.same_line(0.0, dp(4.0))
    imgui.text_disabled(icon.info if icons_available() else '(?)')
    if imgui.is_item_hovered(imgui.HoveredFlags_.delay_none) and imgui.begin_tooltip():
        imgui.push_text_wrap_pos(imgui.get_font_size() * 32.0)
        imgui.text_unformatted(str(text))
        imgui.pop_text_wrap_pos()
        imgui.end_tooltip()


def clip_text(text, max_width):
    """``text`` shortened with an ellipsis to fit ``max_width`` pixels (current font)."""
    text = str(text)
    if imgui.calc_text_size(text).x <= max_width:
        return text
    room = max_width - imgui.calc_text_size('...').x
    while text and imgui.calc_text_size(text).x > room:
        text = text[:-1]
    return text + '...'


def clipped_text(draw, position, max_width, colour, text):
    if text is None or max_width <= 4.0:
        return
    draw.add_text(position, colour, clip_text(text, max_width))


def centred_text(draw, p_min, p_max, colour, text):
    size = imgui.calc_text_size(text)
    draw.add_text((p_min[0] + (p_max[0] - p_min[0] - size.x) * 0.5, p_min[1] + (p_max[1] - p_min[1] - size.y) * 0.5), colour, text)


# ----------------------------------------------------------------------------- buttons

def _variant_colours(variant):
    p = palette()
    if variant == PRIMARY:
        return p.accent, p.accentHover, brighter(p.accent, 0.2), p.accentText, 0
    if variant == GHOST:
        return alpha(p.bg3, 0.0), p.bg4, p.bg5, p.text, 0
    if variant == OUTLINE:
        return alpha(p.bg3, 0.0), alpha(p.accent, 0.12), alpha(p.accent, 0.22), p.text, p.lineStrong
    if variant == DANGER:
        ground = mix(p.error, p.bg1, 0.35)
        return ground, p.error, brighter(p.error, 0.15), contrast_text(ground), 0
    if variant == 'success':
        ground = mix(p.success, p.bg1, 0.25)
        return ground, p.success, brighter(p.success, 0.15), contrast_text(ground), 0
    return p.bg3, p.bg4, p.bg5, p.text, 0


def button(label, variant=SECONDARY, size=(0.0, 0.0)):
    ground, hovered, active, text, border = _variant_colours(variant)
    with scoped_colour((imgui.Col_.button, ground), (imgui.Col_.button_hovered, hovered), (imgui.Col_.button_active, active), (imgui.Col_.text, text)):
        if border:
            with scoped_colour((imgui.Col_.border, border)), scoped_var((imgui.StyleVar_.frame_border_size, 1.0)):
                return imgui.button(label, size)
        return imgui.button(label, size)


def primary_button(label, size=(0.0, 0.0)):
    return button(label, PRIMARY, size)


def danger_button(label, size=(0.0, 0.0)):
    return button(label, DANGER, size)


def ghost_button(label, size=(0.0, 0.0)):
    return button(label, GHOST, size)


def icon_label(glyph, label):
    """'glyph  label' when the icon font is there, else the label alone."""
    return (glyph + '  ' + label) if (glyph and icons_available()) else label


def icon_text_button(glyph, label, variant=SECONDARY, size=(0.0, 0.0)):
    """An icon glyph then a label: icon_text_button(icon.save, 'Save###save')."""
    return button(icon_label(glyph, label), variant, size)


def icon_button(glyph, tip=None, active=False, active_colour=0, size=(0.0, 0.0), id=None, fallback=None, enabled=True):
    """A flat square icon button, tinted when active (a tool, a mode, play...). ``id`` keeps a
    stable widget identity; ``fallback`` is the text drawn when the icon font is missing;
    ``enabled=False`` draws it faint and ignores clicks (its tooltip still shows)."""
    p = palette()
    width = size[0] if size[0] > 0 else imgui.get_frame_height() + dp(2.0)
    height = size[1] if size[1] > 0 else imgui.get_frame_height()
    origin = imgui.get_cursor_screen_pos()
    if not enabled:
        imgui.begin_disabled()
    if id is None:
        imgui.push_id(glyph)
        imgui.push_id(tip or '')
        clicked = imgui.invisible_button('##icon', (width, height))
    else:
        clicked = imgui.invisible_button(id if '#' in id else '###' + id, (width, height))
    hovered, held = imgui.is_item_hovered(), imgui.is_item_active()
    if id is None:
        imgui.pop_id()
        imgui.pop_id()
    draw = imgui.get_window_draw_list()
    colour = active_colour or p.accent
    rounding = imgui.get_style().frame_rounding
    p_max = (origin.x + width, origin.y + height)
    if active:
        draw.add_rect_filled(origin, p_max, alpha(colour, 0.28 if held else 0.18), rounding)
    elif hovered:
        draw.add_rect_filled(origin, p_max, p.bg5 if held else p.bg4, rounding)
    shown = glyph if icons_available() else (fallback or visible(tip or '?')[:2])
    tint = p.textFaint if not enabled else (colour if active else (p.text if hovered else p.textDim))
    centred_text(draw, (origin.x, origin.y), p_max, tint, shown)
    tooltip(tip)
    if not enabled:
        imgui.end_disabled()
    return clicked and enabled


def toggle_button(label, value, on_colour=0, size=(0.0, 0.0), tip=None):
    """A compact rounded toggle that fills with ``on_colour`` when on (M, S, R, a word).
    Returns (clicked, value)."""
    p = palette()
    on_colour = on_colour or p.accent
    shown = visible(label)
    text_size = imgui.calc_text_size(shown)
    width = size[0] if size[0] > 0 else text_size.x + imgui.get_style().frame_padding.x * 2.0
    height = size[1] if size[1] > 0 else imgui.get_frame_height()
    origin = imgui.get_cursor_screen_pos()
    clicked = imgui.invisible_button(label, (width, height))
    if clicked:
        value = not value
    hovered = imgui.is_item_hovered()
    draw = imgui.get_window_draw_list()
    fill = (brighter(on_colour, 0.1) if hovered else on_colour) if value else (p.bg4 if hovered else p.bg3)
    draw.add_rect_filled(origin, (origin.x + width, origin.y + height), fill, imgui.get_style().frame_rounding)
    colour = contrast_text(on_colour) if value else (p.text if hovered else p.textDim)
    draw.add_text((origin.x + (width - text_size.x) * 0.5, origin.y + (height - text_size.y) * 0.5), colour, shown)
    tooltip(tip)
    return clicked, value


def toggle_switch(label, value):
    """An on/off switch with its label after it (settings). Returns (changed, value)."""
    p = palette()
    style = imgui.get_style()
    height = imgui.get_frame_height()
    track_h = round(height * 0.72)
    track_w = round(track_h * 1.8)
    shown = visible(label)
    text_size = imgui.calc_text_size(shown)
    origin = imgui.get_cursor_screen_pos()
    width = track_w + (style.item_inner_spacing.x + text_size.x if shown else 0.0)
    clicked = imgui.invisible_button(label or '##switch', (width, height))
    if clicked:
        value = not value
    hovered = imgui.is_item_hovered()
    storage = imgui.get_state_storage()
    key = imgui.get_item_id()
    target = 1.0 if value else 0.0
    t = storage.get_float(key, target)
    step = imgui.get_io().delta_time * 12.0
    t = min(target, t + step) if t < target else max(target, t - step)
    storage.set_float(key, t)
    draw = imgui.get_window_draw_list()
    t_min = (origin.x, origin.y + (height - track_h) * 0.5)
    t_max = (t_min[0] + track_w, t_min[1] + track_h)
    off = p.bg5 if hovered else p.bg4
    on = p.accentHover if hovered else p.accent
    draw.add_rect_filled(t_min, t_max, mix(off, on, t), track_h * 0.5)
    radius = track_h * 0.5 - dp(2.5)
    centre = (t_min[0] + track_h * 0.5 + (track_w - track_h) * t, t_min[1] + track_h * 0.5)
    off_knob = p.text if contrast_text(p.bg1) == rgb(0xFFFFFF) else rgb(0xFFFFFF)
    draw.add_circle_filled((centre[0], centre[1] + dp(0.5)), radius + dp(0.5), rgb(0x000000, 0.18), 20)
    draw.add_circle_filled(centre, radius, mix(off_knob, contrast_text(p.accent), t), 20)
    if shown:
        draw.add_text((t_max[0] + style.item_inner_spacing.x, origin.y + (height - text_size.y) * 0.5), p.text, shown)
    return clicked, value


def segmented(id, labels, current, width=0.0):
    """Joined buttons, one selected (view modes, units). width: 0 = natural, -1 = fill the row.
    Returns (changed, current)."""
    p = palette()
    style = imgui.get_style()
    imgui.push_id(id)
    height = imgui.get_frame_height()
    inset = dp(2.0)
    widths = [imgui.calc_text_size(visible(label)).x + style.frame_padding.x * 2.6 for label in labels]
    natural = sum(widths)
    total = width if width > 0 else (imgui.get_content_region_avail().x if width < 0 else natural + inset * 2.0)
    scale = (total - inset * 2.0) / natural if natural > 0 else 1.0
    origin = imgui.get_cursor_screen_pos()
    draw = imgui.get_window_draw_list()
    draw.add_rect_filled(origin, (origin.x + total, origin.y + height), p.bg0, style.frame_rounding + inset)
    changed = False
    x = origin.x + inset
    for index, label in enumerate(labels):
        w = widths[index] * scale
        imgui.set_cursor_screen_pos((x, origin.y + inset))
        size = (w, height - inset * 2.0)
        identity = label.split('###')[1] if '###' in label else str(index)
        if imgui.invisible_button('##segment' + identity, size) and current != index:
            current, changed = index, True
        hovered = imgui.is_item_hovered()
        selected = current == index
        p_min, p_max = (x, origin.y + inset), (x + w, origin.y + height - inset)
        if selected:
            draw.add_rect_filled(p_min, p_max, p.accentDim, style.frame_rounding)
        elif hovered:
            draw.add_rect_filled(p_min, p_max, p.bg3, style.frame_rounding)
        shown = visible(label)
        text_size = imgui.calc_text_size(shown)
        draw.add_text((p_min[0] + (w - text_size.x) * 0.5, p_min[1] + (size[1] - text_size.y) * 0.5),
                      contrast_text(p.accentDim) if selected else (p.text if hovered else p.textDim), shown)
        x += w
    imgui.set_cursor_screen_pos(origin)
    imgui.dummy((total, height))
    imgui.pop_id()
    return changed, current


def link_text(label):
    return imgui.text_link(label)


# ----------------------------------------------------------------------------- value controls

class _Entry:
    id = None
    text = ''
    fresh = False
    wheel_frame = -1


def take_wheel():
    """The wheel this frame went to a control under the pointer: views leave it alone."""
    _Entry.wheel_frame = imgui.get_frame_count()


def wheel_taken():
    return _Entry.wheel_frame == imgui.get_frame_count()


def value_speed():
    """Ctrl: 0.15 (fine), Shift: 4 (fast), else 1."""
    io = imgui.get_io()
    return 0.15 if io.key_ctrl else 4.0 if io.key_shift else 1.0


def typed_number(text):
    """A typed number: a comma is a decimal point, 'k' multiplies by 1000; None when not a number."""
    match = re.fullmatch(r'\s*([-+]?(?:\d+[.,]?\d*|[.,]\d+)(?:[eE][-+]?\d+)?)\s*([kK]?)\s*', str(text))
    if not match:
        return None
    value = float(match.group(1).replace(',', '.'))
    if not math.isfinite(value):
        return None
    return value * 1000.0 if match.group(2) else value


def value_entry(key, p_min, p_max, value, minimum, maximum, open_now, scale=1.0):
    """A number typed in over a rectangle: call every frame; ``open_now`` opens it. Enter sets,
    Escape leaves. Returns (set, value). ``key`` is unique in the current ID scope."""
    popup = '##entry-' + str(key)
    identity = imgui.get_id(popup)
    if open_now:
        _Entry.id, _Entry.text, _Entry.fresh = identity, '%.6g' % (value * scale), True
        imgui.open_popup(popup)
    if _Entry.id != identity:
        return False, value
    width = max(p_max[0] - p_min[0], dp(72.0))
    imgui.set_next_window_pos(((p_min[0] + p_max[0] - width) * 0.5, p_min[1] - dp(3.0)))
    imgui.set_next_window_size((width, 0.0))
    with scoped_var((imgui.StyleVar_.window_padding, dp(2.0, 2.0))):
        shown = imgui.begin_popup(popup, imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_resize | imgui.WindowFlags_.no_move
                                  | imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.always_auto_resize)
    if not shown:
        _Entry.id = None
        return False, value
    done = False
    if _Entry.fresh:
        imgui.set_keyboard_focus_here()
        _Entry.fresh = False
    imgui.set_next_item_width(-1.0)
    entered, _Entry.text = imgui.input_text('##typed', _Entry.text, imgui.InputTextFlags_.enter_returns_true | imgui.InputTextFlags_.auto_select_all)
    if entered:
        number = typed_number(_Entry.text)
        if number is not None:
            lo, hi = min(minimum, maximum), max(minimum, maximum)
            value = min(hi, max(lo, number / (scale or 1.0)))
            done = True
        imgui.close_current_popup()
        _Entry.id = None
    elif imgui.is_key_pressed(imgui.Key.escape):
        imgui.close_current_popup()
        _Entry.id = None
    imgui.end_popup()
    return done, value


def meter_position(gain_db):
    """A meter's position (0..1) for a level in dB (CyDAW law)."""
    if gain_db <= -70.0:
        return 0.0
    return min(1.0, max(0.0, math.exp((gain_db - 6.0) / 26.0)))


def _to_db(gain):
    return 20.0 * math.log10(gain) if gain > 1e-5 else -100.0


def meter(id, size, peak_left, peak_right, rms_left=None, rms_right=None, vertical=True):
    """A level meter: peak (and RMS) of two channels, linear gain (1 = 0 dB), with a peak hold."""
    p = palette()
    rms_left = peak_left if rms_left is None else rms_left
    rms_right = peak_right if rms_right is None else rms_right
    origin = imgui.get_cursor_screen_pos()
    imgui.push_id(id)
    imgui.dummy(size)
    storage = imgui.get_state_storage()
    hold_id, hold_time_id = imgui.get_id('hold'), imgui.get_id('holdTime')
    draw = imgui.get_window_draw_list()
    now = float(imgui.get_time())
    peak_db = max(_to_db(peak_left), _to_db(peak_right))
    hold, hold_time = storage.get_float(hold_id, -100.0), storage.get_float(hold_time_id, 0.0)
    if peak_db >= hold or now - hold_time > 1.5:
        hold, hold_time = peak_db, now
    storage.set_float(hold_id, hold)
    storage.set_float(hold_time_id, hold_time)
    w, h = size
    draw.add_rect_filled(origin, (origin.x + w, origin.y + h), p.bg0, dp(2.0))
    gap = dp(1.0)
    mid, top = meter_position(-12.0), meter_position(-3.0)

    def segment(index, a, b, colour):
        if vertical:
            bar = (w - gap) * 0.5
            x0 = origin.x + index * (bar + gap)
            draw.add_rect_filled((x0, origin.y + h * (1.0 - b)), (x0 + bar, origin.y + h * (1.0 - a)), colour)
        else:
            bar = (h - gap) * 0.5
            y0 = origin.y + index * (bar + gap)
            draw.add_rect_filled((origin.x + w * a, y0), (origin.x + w * b, y0 + bar), colour)

    def level(index, value, opacity):
        segment(index, 0.0, min(value, mid), alpha(p.success, opacity))
        if value > mid:
            segment(index, mid, min(value, top), alpha(p.warning, opacity))
        if value > top:
            segment(index, top, value, alpha(p.error, opacity))

    for index, (peak, rms) in enumerate(((peak_left, rms_left), (peak_right, rms_right))):
        level(index, meter_position(_to_db(peak)), 0.45)
        level(index, meter_position(_to_db(rms)), 1.0)
    held = meter_position(hold)
    if held > 0.0:
        colour = alpha(p.error if hold > -0.1 else p.text, 0.8)
        if vertical:
            y = origin.y + h * (1.0 - held)
            draw.add_line((origin.x, y), (origin.x + w, y), colour, 1.0)
        else:
            x = origin.x + w * held
            draw.add_line((x, origin.y), (x, origin.y + h), colour, 1.0)
    imgui.pop_id()


def drag_value(id, value, speed, minimum, maximum, fmt='%.2f', width=0.0):
    if width:
        imgui.set_next_item_width(width)
    return imgui.drag_float(id, float(value), speed * value_speed(), minimum, maximum, fmt, imgui.SliderFlags_.always_clamp)


def slider_bar(id, value, minimum, maximum, fmt='%.2f', width=0.0, colour=0, logarithmic=False):
    """A slider drawn as a filled bar with the value in it (inspectors). Drag or click to set,
    wheel nudges, double click types the value. Returns (changed, value). The widget identity is
    ``id`` / '##bar'."""
    p = palette()
    if width == 0.0:
        width = imgui.calc_item_width()
    elif width < 0.0:
        width = max(dp(20.0), imgui.get_content_region_avail().x + width)
    height = imgui.get_frame_height()
    origin = imgui.get_cursor_screen_pos()
    imgui.push_id(id)
    imgui.invisible_button('##bar', (width, height))
    hovered, active = imgui.is_item_hovered(), imgui.is_item_active()
    io = imgui.get_io()
    lo, hi = float(minimum), float(maximum)
    log = logarithmic and lo > 0 and hi > lo
    to_t = (lambda v: (math.log(v / lo) / math.log(hi / lo)) if v > 0 else 0.0) if log else (lambda v: (v - lo) / (hi - lo) if hi > lo else 0.0)
    from_t = (lambda t: lo * (hi / lo) ** t) if log else (lambda t: lo + (hi - lo) * t)
    value = float(value)
    changed = False
    if active and not imgui.is_mouse_double_clicked(imgui.MouseButton_.left) and hi > lo:
        t = min(1.0, max(0.0, (io.mouse_pos.x - origin.x) / max(1.0, width)))
        new = from_t(t)
        if new != value:
            value, changed = new, True
    if hovered and io.mouse_wheel != 0.0 and hi > lo:
        value = from_t(min(1.0, max(0.0, to_t(value) + io.mouse_wheel * 0.01 * value_speed())))
        changed = True
        take_wheel()
    typed, number = value_entry('bar', (origin.x, origin.y), (origin.x + width, origin.y + height), value, lo, hi,
                                hovered and imgui.is_mouse_double_clicked(imgui.MouseButton_.left))
    if typed:
        value, changed = number, True
    draw = imgui.get_window_draw_list()
    rounding = imgui.get_style().frame_rounding
    p_max = (origin.x + width, origin.y + height)
    draw.add_rect_filled(origin, p_max, p.bg5 if active else p.bg4 if hovered else p.bg3, rounding)
    t = min(1.0, max(0.0, to_t(value)))
    if t > 0.0:
        draw.push_clip_rect(origin, (origin.x + width * t, p_max[1]), True)
        draw.add_rect_filled(origin, p_max, alpha(colour or p.accent, 0.55 if (hovered or active) else 0.42), rounding)
        draw.pop_clip_rect()
    try:
        text = fmt % value if '%' in fmt else fmt
    except (TypeError, ValueError):
        text = '%.3g' % value
    centred_text(draw, (origin.x, origin.y), p_max, p.text, text.replace('%%', '%'))
    imgui.pop_id()
    return changed, value


# ----------------------------------------------------------------------------- fields

def search_field(id, text, hint='Search', width=0.0):
    """A search box: magnifier, hint, a clear button. Returns (changed, text)."""
    p = palette()
    style = imgui.get_style()
    height = imgui.get_frame_height()
    icon_room = height * 0.9
    imgui.push_id(id)
    origin = imgui.get_cursor_screen_pos()
    field_width = (width if width > 0 else imgui.get_content_region_avail().x + width) if width else imgui.calc_item_width()
    field_width = max(dp(40.0), field_width)
    imgui.set_next_item_width(field_width)
    imgui.set_next_item_allow_overlap()
    with scoped_var((imgui.StyleVar_.frame_padding, imgui.ImVec2(style.frame_padding.x + icon_room * 0.75, style.frame_padding.y)),
                    (imgui.StyleVar_.frame_rounding, height * 0.5)):
        changed, text = imgui.input_text_with_hint('##search', hint or '', text)
    focused = imgui.is_item_active()
    end = imgui.get_cursor_screen_pos()
    draw = imgui.get_window_draw_list()
    _magnifier(draw, (origin.x + style.frame_padding.x + icon_room * 0.3, origin.y + height * 0.5), height * 0.48, p.accent if focused else p.textFaint)
    if text:
        imgui.set_cursor_screen_pos((origin.x + field_width - height, origin.y))
        if imgui.invisible_button('##clear', (height, height)):
            text, changed = '', True
        _cross(draw, (origin.x + field_width - height * 0.5, origin.y + height * 0.5), height * 0.26, p.text if imgui.is_item_hovered() else p.textFaint)
        imgui.set_cursor_screen_pos(end)
    imgui.pop_id()
    return changed, text


def _magnifier(draw, centre, size, colour):
    r = size * 0.32
    c = (centre[0] - size * 0.08, centre[1] - size * 0.08)
    draw.add_circle(c, r, colour, 16, max(1.2, size * 0.1))
    draw.add_line((c[0] + r * 0.7, c[1] + r * 0.7), (centre[0] + size * 0.42, centre[1] + size * 0.42), colour, max(1.4, size * 0.12))


def _cross(draw, centre, size, colour):
    h, t = size * 0.5, max(1.2, size * 0.12)
    draw.add_line((centre[0] - h, centre[1] - h), (centre[0] + h, centre[1] + h), colour, t)
    draw.add_line((centre[0] - h, centre[1] + h), (centre[0] + h, centre[1] - h), colour, t)


def text_field(id, text, hint='', width=0.0):
    if width:
        imgui.set_next_item_width(width)
    return imgui.input_text_with_hint(id, hint or '', text)


def combo(id, current, items, width=0.0):
    if width:
        imgui.set_next_item_width(width)
    return imgui.combo(id, current, list(items))


# ----------------------------------------------------------------------------- containers

def begin_card(id, title=None, height=0.0, tone=NEUTRAL):
    """A card: rounded raised ground (bg2), a line, padding, an optional title. Always call
    end_card(), whatever begin_card returned. height: 0 = fit content, >0 fixed, <0 fill minus."""
    p = palette()
    toned = tone != NEUTRAL
    ground = mix(p.bg2, tone_colour(tone), 0.08) if toned else p.bg2
    border = mix(p.line, tone_colour(tone), 0.55) if toned else p.line
    flags = imgui.ChildFlags_.borders | imgui.ChildFlags_.always_use_window_padding
    if height == 0.0:
        flags |= imgui.ChildFlags_.auto_resize_y
    m = metrics()
    with scoped_colour((imgui.Col_.child_bg, ground), (imgui.Col_.border, border)), \
            scoped_var((imgui.StyleVar_.child_rounding, dp(m.rounding_large + 2.0)), (imgui.StyleVar_.window_padding, dp(m.card_padding, m.card_padding))):
        shown = imgui.begin_child(id, (0.0, 0.0 if height == 0.0 else (dp(height) if height > 0 else height)), flags)
    if shown and title:
        heading(title, 3)
        imgui.dummy((0.0, dp(2.0)))
    return shown


def end_card():
    imgui.end_child()


def begin_section(label, default_open=True):
    """A collapsible section with a full-width header bar. Call end_section() only when it returned True."""
    p = palette()
    with scoped_colour((imgui.Col_.header, p.bg2), (imgui.Col_.header_hovered, p.bg3), (imgui.Col_.header_active, p.bg4)), scoped_font(bold_font(), 0.92):
        return imgui.collapsing_header(label, imgui.TreeNodeFlags_.default_open if default_open else 0)


def end_section():
    imgui.dummy((0.0, dp(4.0)))


def begin_properties(id, label_width=0.0):
    """Label / value rows in two aligned columns (inspectors, settings). Call end_properties()
    only when it returned True. property() writes the label and readies the value column."""
    avail = imgui.get_content_region_avail().x
    width = dp(label_width) if label_width > 0 else max(dp(80.0), avail * 0.38)
    if not imgui.begin_table(id, 2, imgui.TableFlags_.none):
        return False
    imgui.table_setup_column('##label', imgui.TableColumnFlags_.width_fixed, width)
    imgui.table_setup_column('##value', imgui.TableColumnFlags_.width_stretch)
    return True


def property(label, help=None):
    imgui.table_next_row()
    imgui.table_set_column_index(0)
    imgui.align_text_to_frame_padding()
    room = imgui.get_content_region_avail().x - (imgui.get_font_size() if help else 0.0)
    if imgui.calc_text_size(label).x <= room:
        text_dim(label)
    else:
        text_dim(clip_text(label, room))
        tooltip(label)
    if help:
        help_marker(help)
    imgui.table_set_column_index(1)
    imgui.set_next_item_width(-FLT_MIN)                # the value column, full width


def end_properties():
    imgui.end_table()


def toolbar_separator():
    """A thin vertical bar between toolbar groups (on the same line)."""
    imgui.same_line(0.0, dp(6.0))
    origin = imgui.get_cursor_screen_pos()
    height = imgui.get_frame_height()
    imgui.get_window_draw_list().add_line((origin.x, origin.y + height * 0.18), (origin.x, origin.y + height * 0.82), palette().lineStrong)
    imgui.dummy((dp(1.0), height))
    imgui.same_line(0.0, dp(6.0))


def divider(spacing=4.0):
    imgui.dummy((0.0, dp(spacing)))
    origin = imgui.get_cursor_screen_pos()
    width = imgui.get_content_region_avail().x
    imgui.get_window_draw_list().add_line(origin, (origin.x + width, origin.y), palette().line)
    imgui.dummy((0.0, dp(spacing)))


def space(height=8.0):
    imgui.dummy((0.0, dp(height)))


# ----------------------------------------------------------------------------- status & feedback

def badge(text, tone=NEUTRAL):
    """A small rounded pill: badge('BETA', WARNING)."""
    p = palette()
    colour = p.textDim if tone == NEUTRAL else tone_colour(tone)
    line = imgui.get_frame_height()
    with scoped_font(bold_font(), 0.74):
        size = imgui.calc_text_size(text)
        pad = dp(6.0, 2.0)
        box = (size.x + pad.x * 2.0, size.y + pad.y * 2.0)
        origin = imgui.get_cursor_screen_pos()
        top = origin.y + max(0.0, (line - box[1]) * 0.5)
        draw = imgui.get_window_draw_list()
        rounding = dp(metrics().rounding_small + 1.0)
        draw.add_rect_filled((origin.x, top), (origin.x + box[0], top + box[1]), p.bg4 if tone == NEUTRAL else alpha(colour, 0.16), rounding)
        draw.add_rect((origin.x, top), (origin.x + box[0], top + box[1]), alpha(colour, 0.35), rounding)
        draw.add_text((origin.x + pad.x, top + pad.y), p.text if tone == NEUTRAL else mix(colour, p.text, 0.3), text)
    imgui.dummy((box[0], line))


def status_dot(colour, tip=None):
    line = imgui.get_text_line_height()
    origin = imgui.get_cursor_screen_pos()
    radius = line * 0.24
    imgui.dummy((radius * 2.0 + dp(2.0), line))
    draw = imgui.get_window_draw_list()
    centre = (origin.x + radius + dp(1.0), origin.y + line * 0.5)
    draw.add_circle_filled(centre, radius * 1.8, alpha(colour, 0.18), 16)
    draw.add_circle_filled(centre, radius, colour, 16)
    tooltip(tip)


def progress_bar(fraction, size=(-1.0, 0.0), overlay=None, tone=ACCENT):
    """A thin progress bar; fraction < 0 draws an indeterminate one."""
    p = palette()
    w, h = size
    if w <= 0.0:
        w = max(dp(20.0), imgui.get_content_region_avail().x + (w + 1.0 if w < 0.0 else 0.0))
    if h <= 0.0:
        h = imgui.get_frame_height() if overlay else dp(6.0)
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy((w, h))
    draw = imgui.get_window_draw_list()
    rounding = min(h * 0.5, imgui.get_style().frame_rounding + dp(2.0))
    p_max = (origin.x + w, origin.y + h)
    colour = p.textDim if tone == NEUTRAL else tone_colour(tone)
    draw.add_rect_filled(origin, p_max, p.bg3, rounding)
    if fraction >= 0.0:
        t = min(1.0, max(0.0, float(fraction)))
        if t > 0.0:
            draw.add_rect_filled(origin, (origin.x + max(rounding * 2.0, w * t), p_max[1]), colour, rounding)
    else:
        phase = (imgui.get_time() * 0.8) % 1.0
        segment = w * 0.3
        x0 = origin.x - segment + (w + segment) * phase
        draw.push_clip_rect(origin, p_max, True)
        draw.add_rect_filled((x0, origin.y), (x0 + segment, p_max[1]), colour, rounding)
        draw.pop_clip_rect()
    if overlay:
        centred_text(draw, (origin.x, origin.y), p_max, p.text, clip_text(overlay, w - dp(8.0)))


def spinner(id, radius=7.0, colour=0):
    imgui.push_id(id)
    r = dp(radius)
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy((r * 2.0 + dp(2.0), r * 2.0 + dp(2.0)))
    draw = imgui.get_window_draw_list()
    centre = (origin.x + r + dp(1.0), origin.y + r + dp(1.0))
    start = imgui.get_time() * 6.0
    thickness = max(1.5, r * 0.28)
    draw.path_clear()
    draw.path_arc_to(centre, r - thickness * 0.5, 0.0, TAU, 24)
    draw.path_stroke(alpha(palette().textFaint, 0.35), thickness, 0)
    draw.path_clear()
    draw.path_arc_to(centre, r - thickness * 0.5, start, start + math.pi * 1.3, 32)
    draw.path_stroke(colour or palette().accent, thickness, 0)
    imgui.pop_id()


def empty_state(title, message=None, glyph=None):
    """A centred title and message filling the rest of a panel ('No layers yet')."""
    p = palette()
    area = imgui.get_content_region_avail()
    origin = imgui.get_cursor_screen_pos()
    draw = imgui.get_window_draw_list()
    middle = origin.y + max(dp(60.0), area.y * 0.45)
    if glyph and icons_available():
        with scoped_font(ui_font(), 2.4):
            centred_text(draw, (origin.x, middle - dp(70.0)), (origin.x + area.x, middle - dp(24.0)), p.textFaint, glyph)
    with scoped_font(bold_font(), 1.1):
        centred_text(draw, (origin.x, middle - dp(22.0)), (origin.x + area.x, middle), p.textDim, title)
    if message:
        centred_text(draw, (origin.x, middle), (origin.x + area.x, middle + dp(20.0)), p.textFaint, message)
    imgui.dummy((area.x, max(0.0, middle + dp(24.0) - origin.y)))


def callout(tone, text):
    """A notice block with a coloured bar: callout(WARNING, 'Unsaved changes')."""
    p = palette()
    colour = p.textDim if tone == NEUTRAL else tone_colour(tone)
    width = imgui.get_content_region_avail().x
    pad = dp(10.0, 7.0)
    bar = dp(3.0)
    wrap = max(dp(40.0), width - pad.x * 2.0 - bar)
    size = imgui.calc_text_size(text, None, False, wrap)
    origin = imgui.get_cursor_screen_pos()
    p_max = (origin.x + width, origin.y + size.y + pad.y * 2.0)
    draw = imgui.get_window_draw_list()
    rounding = imgui.get_style().frame_rounding
    draw.add_rect_filled(origin, p_max, mix(p.bg2, colour, 0.10), rounding)
    draw.add_rect_filled(origin, (origin.x + bar, p_max[1]), colour, rounding, imgui.ImDrawFlags_.round_corners_left)
    draw.add_text(imgui.get_font(), imgui.get_font_size(), (origin.x + bar + pad.x, origin.y + pad.y), p.text, text, None, wrap)
    imgui.dummy((width, p_max[1] - origin.y))


def colour_chip(id, colour, size):
    origin = imgui.get_cursor_screen_pos()
    clicked = imgui.invisible_button(id, size)
    draw = imgui.get_window_draw_list()
    p_max = (origin.x + size[0], origin.y + size[1])
    draw.add_rect_filled(origin, p_max, colour, dp(2.0))
    if imgui.is_item_hovered():
        draw.add_rect(origin, p_max, palette().text, dp(2.0), 0, 1.5)
    return clicked


# ----------------------------------------------------------------------------- notifications

class _Toasts:
    items = []           # [text, tone, until, id]
    serial = 0


def notify(text, tone=NEUTRAL, seconds=4.0):
    """A toast at the bottom right of the main viewport; render_notifications() draws them."""
    if not text:
        return
    now = imgui.get_time() if imgui.get_current_context() is not None else time.monotonic()
    _Toasts.serial += 1
    _Toasts.items.append([str(text), tone, now + seconds, _Toasts.serial])
    del _Toasts.items[:-6]


def notifications():
    """The toasts shown now: [(text, tone), ...] (tests, status displays)."""
    return [(item[0], item[1]) for item in _Toasts.items]


def render_notifications(bottom_margin=0.0):
    """Once per frame, after everything else. ``bottom_margin`` keeps the toasts above a status bar."""
    now = imgui.get_time()
    _Toasts.items = [item for item in _Toasts.items if item[2] >= now]
    if not _Toasts.items:
        return
    p = palette()
    viewport = imgui.get_main_viewport()
    y = viewport.work_pos.y + viewport.work_size.y - dp(16.0) - bottom_margin
    x = viewport.work_pos.x + viewport.work_size.x - dp(16.0)
    flags = (imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.always_auto_resize | imgui.WindowFlags_.no_saved_settings
             | imgui.WindowFlags_.no_focus_on_appearing | imgui.WindowFlags_.no_nav | imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_docking)
    rounding = dp(metrics().rounding_large + 2.0)
    for item in reversed(list(_Toasts.items)):
        text, tone, until, serial = item
        fade = min(1.0, max(0.0, (until - now) / 0.3))
        imgui.set_next_window_pos((x, y), imgui.Cond_.always, (1.0, 1.0))
        imgui.set_next_window_bg_alpha(0.98 * fade)
        height = 0.0
        with scoped_var((imgui.StyleVar_.window_padding, dp(14.0, 9.0)), (imgui.StyleVar_.window_rounding, rounding), (imgui.StyleVar_.alpha, max(0.01, fade))), \
                scoped_colour((imgui.Col_.window_bg, p.bg2), (imgui.Col_.border, p.lineStrong)):
            if imgui.begin('##cyuiToast%d' % serial, None, flags)[0]:
                colour = p.accent if tone == NEUTRAL else tone_colour(tone)
                pos, size = imgui.get_window_pos(), imgui.get_window_size()
                imgui.get_window_draw_list().add_rect_filled(pos, (pos.x + dp(3.0), pos.y + size.y), colour, rounding, imgui.ImDrawFlags_.round_corners_left)
                imgui.push_text_wrap_pos(imgui.get_font_size() * 26.0)
                imgui.text_unformatted(text)
                imgui.pop_text_wrap_pos()
                if imgui.is_window_hovered() and imgui.is_mouse_clicked(imgui.MouseButton_.left):
                    item[2] = now + 0.3
                height = size.y
            imgui.end()
        y -= height + dp(8.0)
