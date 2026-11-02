"""AudioStudio host adapters for the unchanged, pinned CyUI library.
Only transport wrapping, numeric entry and palette-file persistence are host extensions.
"""
from contextlib import contextmanager
from dataclasses import make_dataclass, fields, replace
from pathlib import Path
from types import SimpleNamespace
import math, re, json
import cyui as core
from cyui import *
from cyui_modules import audio
from cyui_modules.common import take_wheel, wheel_taken

PRIMARY='primary'; SECONDARY='secondary'; GHOST='ghost'; DANGER='danger'
NEUTRAL='neutral'; ACCENT='accent'; SUCCESS='success'; WARNING='warning'; ERROR='error'; INFO='info'
DEFAULT_THEME='mid-grey'; DENSITIES=('compact','comfortable')
Palette=make_dataclass('Palette',[(k,int) for k in core.FIELDS])
THEMES=tuple(SimpleNamespace(key=k,name=name,palette=Palette(**palette),light=light) for k,name,palette,light in core.THEMES)
MID_GREY, LIGHT_GREY, AMBER_NIGHT, VIOLET, NAVY=(t.palette for t in THEMES)
COMPACT=SimpleNamespace(font_size=14.); COMFORTABLE=SimpleNamespace(font_size=16.)
PALETTE_FIELDS=tuple((k,k,0) for k in core.FIELDS)
BAR_FLAGS=imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_scroll_with_mouse
FLT_MIN=1.175494351e-38
visible=core._visible
def scoped_colour(*pairs): return core.scoped_color(*(x for pair in pairs for x in pair))
def scoped_var(*pairs): return core.scoped_var(*(x for pair in pairs for x in pair))
current_theme_key=core.current_theme
meter_position=audio.meter_position

def dp(x,y=None): return core.dp(x) if y is None else core.dp2(x,y)
def floats(colour): return tuple(core.vec(colour))
def from_floats(r,g,b,a=1.): return core.rgb((round(max(0,min(1,r))*255)<<16)|(round(max(0,min(1,g))*255)<<8)|round(max(0,min(1,b))*255),a)
def value_speed():
    io=imgui.get_io()
    return .15 if io.key_ctrl else 4. if io.key_shift else 1.
def text_wrapped_dim(text):
    imgui.push_text_wrap_pos(0); core.text_dim(text); imgui.pop_text_wrap_pos()
def text_wrapped_faint(text):
    imgui.push_text_wrap_pos(0); core.text_faint(text); imgui.pop_text_wrap_pos()
def set_palette(value): core.set_palette(vars(value) if not isinstance(value,dict) else value)
def metrics(): return core.metrics()
def status_text(text,tone=NEUTRAL): core.status_text(tone,text)
def icon_button(glyph,tip='',active=False,active_colour=0,size=(0.,0.),id=None,fallback=None,enabled=True):
    with core.scoped_disabled(not enabled), core.scoped_id(id or glyph+str(tip)):
        clicked=core.icon_button(glyph,tip or '',active,active_colour,size)
        ICON_ITEMS[tuple(_host_scope)+(id or glyph+str(tip),)]=(imgui.get_frame_count(),imgui.get_item_id())
        return clicked
def toggle_button(label,value,on_colour=0,size=(0.,0.),tip=None):
    with scoped_colour((imgui.Col_.button, core.alpha(on_colour or core.palette().accent,.25))) if value else core.scoped_disabled(False):
        changed=core.button(label,'secondary',size)
    core.tooltip(tip or '')
    return changed,not value if changed else value
def slider_bar(identifier,value,minimum,maximum,fmt='%.2f',width=0.,colour=0,logarithmic=False):
    # Native typed entry is retained; logarithmic sliders use the binding's supported flag.
    if logarithmic:
        if width: imgui.set_next_item_width(width)
        return imgui.slider_float(identifier,float(value),minimum,maximum,fmt,imgui.SliderFlags_.logarithmic)
    return core.slider_bar(identifier,value,minimum,maximum,fmt,width,colour)
def progress_bar(fraction,size=(-1.,0.),overlay='',tone=ACCENT): return core.progress_bar(fraction,size,overlay or '',tone)
def meter(identifier,size,peak_l,peak_r=0.,rms_l=None,rms_r=None,vertical=True):
    scale=core.dpi()
    return audio.meter(identifier,[peak_l,peak_r],[peak_l if rms_l is None else rms_l,peak_r if rms_r is None else rms_r],tuple(v/scale for v in size),vertical)

def clip_text(text, max_width):
    """``text`` shortened with an ellipsis to fit ``max_width`` pixels (current font)."""
    text = str(text)
    if imgui.calc_text_size(text).x <= max_width:
        return text
    room = max_width - imgui.calc_text_size('...').x
    while text and imgui.calc_text_size(text).x > room:
        text = text[:-1]
    return text + '...'

def icon_label(glyph, label):
    """'glyph  label' when the icon font is there, else the label alone."""
    return (glyph + '  ' + label) if (glyph and icons_available()) else label

class _Entry:
    id = None
    text = ''
    fresh = False
    wheel_frame = -1

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

def palette_to_text(value):
    lines = ['// CyUI theme: key = #RRGGBB or #RRGGBBAA']
    for key, _, _ in PALETTE_FIELDS:
        colour = getattr(value, key)
        r, g, b, a = colour & 0xFF, (colour >> 8) & 0xFF, (colour >> 16) & 0xFF, (colour >> 24) & 0xFF
        lines.append(f'{key} = #{r:02X}{g:02X}{b:02X}' + ('' if a == 0xFF else f'{a:02X}'))
    return '\n'.join(lines) + '\n'

def palette_from_text(text, base):
    """Reads ``key = #RRGGBB[AA]`` lines or a JSON object of the same keys (CyDAW 2 .cytheme);
    what the text lacks keeps ``base``'s colour."""
    import re
    known = {key for key, _, _ in PALETTE_FIELDS}
    out = replace(base)
    text = re.sub(r'//[^\n]*', '', str(text))
    for key, digits in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\W*?#([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6})(?![0-9A-Fa-f])', text):
        if key not in known:
            continue
        value = int(digits, 16)
        a = value & 0xFF if len(digits) == 8 else 0xFF
        colour = value >> 8 if len(digits) == 8 else value
        setattr(out, key, (a << 24) | ((colour & 0xFF) << 16) | (colour & 0xFF00) | ((colour >> 16) & 0xFF))
    return out

def save_palette(path, value):
    Path(path).write_text(palette_to_text(value), 'utf-8')

def load_palette(path, base):
    return palette_from_text(Path(path).read_text('utf-8-sig')[:1024 * 1024], base)

def palette_field_names():
    return [f.name for f in fields(Palette)]

# Semantic item references for native interaction tests; rendering remains in CyUI.
ICON_ITEMS={}
_host_scope=[]
def push_id(value):
    _host_scope.append(str(value));imgui.push_id(value)
def pop_id():
    if _host_scope:_host_scope.pop()
    imgui.pop_id()
