"""CyUI theme: one semantic palette, one set of metrics, the fonts.

Python port of ``Theme.h`` / ``Theme.cpp`` of CyUI (D:/_Project/CyImgui_Interface), the interface
library of CyDAW 2, Shaderixel and CyEngineHub, for imgui-bundle (Dear ImGui 1.92). The palettes,
metrics and style values are the library's; only the language changes.

Every widget (and every custom-drawn control) takes its colours from ``palette()`` by role and its
sizes from ``metrics()`` / ``dp()``, never from hard-coded values, so changing theme is one call.
Colours are ImGui packed u32 (ABGR), like ``ImU32`` in C++.
"""
from dataclasses import dataclass, fields, replace
import os
from pathlib import Path

from imgui_bundle import imgui


# ----------------------------------------------------------------------------- colours

def rgb(hex_value, a=1.0):
    """A colour from 0xRRGGBB (as written in a design tool), with an alpha, packed as ImGui ABGR."""
    hex_value = int(hex_value)
    return ((int(a * 255.0 + 0.5) & 0xFF) << 24) | ((hex_value & 0xFF) << 16) | (hex_value & 0xFF00) | ((hex_value >> 16) & 0xFF)


@dataclass
class Palette:
    """Names say what a colour is FOR, not what it looks like: pick by role, never by hue."""
    bg0: int          # deepest: canvases, timelines, menu bar, status bar, wells
    bg1: int          # window / panel ground
    bg2: int          # headers, cards, popups, table headers
    bg3: int          # fields and buttons at rest
    bg4: int          # hovered fields and buttons
    bg5: int          # pressed / active fields, knob tracks, scrollbar grabs
    line: int         # borders, separators
    lineStrong: int   # seams between panels, table outer borders, toolbar separators
    grid: int         # minor grid in canvases
    gridStrong: int   # major grid
    text: int         # primary text
    textDim: int      # secondary text, labels, inactive icons
    textFaint: int    # hints, disabled, placeholders
    accent: int       # the one accent: active, selected, focused, the main action
    accentHover: int
    accentDim: int    # subdued accent (active-but-not-focused, drag handles)
    accentText: int   # text drawn ON an accent fill
    selection: int    # translucent selection fill (rows, rectangles, text)
    success: int
    warning: int
    error: int
    info: int


def _palette(*values):
    return Palette(*values)


# CyDAW 2 default: Bitwig's mid greys, dark seams between panels, orange.
MID_GREY = _palette(
    rgb(0x262626), rgb(0x2e2e2e), rgb(0x373737), rgb(0x414141), rgb(0x4b4b4b), rgb(0x565656),
    rgb(0x1f1f1f), rgb(0x181818), rgb(0x2d2d2d), rgb(0x383838),
    rgb(0xdadada), rgb(0xa6a6a6), rgb(0x707070),
    rgb(0xf28a2e), rgb(0xffa552), rgb(0x7d4a1d), rgb(0x1e1e1e), rgb(0xf28a2e, 0.24),
    rgb(0x5cd26e), rgb(0xf5a623), rgb(0xee5149), rgb(0x5cb4ef))

# CyDAW 2: Ableton Live's light greys, dark text, orange, blue selections.
LIGHT_GREY = _palette(
    rgb(0xb3b3b3), rgb(0xc2c2c2), rgb(0xcbcbcb), rgb(0xd6d6d6), rgb(0xe0e0e0), rgb(0xebebeb),
    rgb(0x9c9c9c), rgb(0x7f7f7f), rgb(0xa9a9a9), rgb(0x969696),
    rgb(0x161616), rgb(0x3d3d3d), rgb(0x6e6e6e),
    rgb(0xff8a00), rgb(0xffa233), rgb(0xf0c27e), rgb(0x161616), rgb(0x3d8eff, 0.26),
    rgb(0x15a34e), rgb(0xd98200), rgb(0xe0302b), rgb(0x2a86d1))

# CyDAW 2's first dark one: deep blue-greys, an amber accent.
AMBER_NIGHT = _palette(
    rgb(0x111317), rgb(0x16181d), rgb(0x1c1f25), rgb(0x24282f), rgb(0x2c313a), rgb(0x363c47),
    rgb(0x262a31), rgb(0x363b45), rgb(0x1f2228), rgb(0x2b2f37),
    rgb(0xdce1e8), rgb(0x9aa3b0), rgb(0x5f6875),
    rgb(0xf0a43a), rgb(0xf8b95c), rgb(0x7a5524), rgb(0x111317), rgb(0xf0a43a, 0.22),
    rgb(0x3dd68c), rgb(0xf5a623), rgb(0xe5484d), rgb(0x5ab0f0))

# Shaderixel: dark slate, a violet accent, cyan for information.
VIOLET = _palette(
    rgb(0x16171b), rgb(0x1b1c21), rgb(0x222329), rgb(0x282a32), rgb(0x343640), rgb(0x40424e),
    rgb(0x30323a), rgb(0x3a3c46), rgb(0xffffff, 0.04), rgb(0xffffff, 0.09),
    rgb(0xdee0e8), rgb(0x8c909e), rgb(0x686c7a),
    rgb(0x7c5cff), rgb(0x967cff), rgb(0x4c3fa0), rgb(0xffffff), rgb(0x7c5cff, 0.35),
    rgb(0x4cd4a0), rgb(0xf5a623), rgb(0xf0505a), rgb(0x2ec4d6))

# CyEngineHub: a very dark navy, flat, a blue accent.
NAVY = _palette(
    rgb(0x0a0e13), rgb(0x0d1218), rgb(0x111820), rgb(0x18212c), rgb(0x1f2a37), rgb(0x263343),
    rgb(0x1c2632), rgb(0x283748), rgb(0x111820), rgb(0x1c2632),
    rgb(0xd9e2ec), rgb(0xa4b3c2), rgb(0x65788d),
    rgb(0x2d7ff9), rgb(0x4a93ff), rgb(0x1d4e7a), rgb(0xffffff), rgb(0x2d7ff9, 0.25),
    rgb(0x65cca9), rgb(0xf2b84b), rgb(0xe8747c), rgb(0x70a8fa))


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    palette: Palette
    light: bool = False


THEMES = (
    Theme('mid-grey', 'Mid grey (CyDAW)', MID_GREY, False),
    Theme('light-grey', 'Light grey (CyDAW)', LIGHT_GREY, True),
    Theme('amber-night', 'Amber night (CyDAW)', AMBER_NIGHT, False),
    Theme('violet', 'Violet (Shaderixel)', VIOLET, False),
    Theme('navy', 'Navy (CyEngineHub)', NAVY, False),
)
DEFAULT_THEME = 'mid-grey'

# (key, label, group) of every palette field: editors and .cytheme files.
PALETTE_FIELDS = (
    ('bg0', 'Deepest ground (canvas, bars)', 0), ('bg1', 'Panel ground', 0), ('bg2', 'Header / card ground', 0),
    ('bg3', 'Fields and buttons', 0), ('bg4', 'Hover', 0), ('bg5', 'Active', 0),
    ('line', 'Lines', 1), ('lineStrong', 'Strong lines', 1), ('grid', 'Grid', 1), ('gridStrong', 'Grid (major)', 1),
    ('text', 'Text', 2), ('textDim', 'Secondary text', 2), ('textFaint', 'Faint text', 2),
    ('accent', 'Accent', 3), ('accentHover', 'Accent hovered', 3), ('accentDim', 'Accent dimmed', 3),
    ('accentText', 'Text on accent', 3), ('selection', 'Selection', 3),
    ('success', 'Success', 4), ('warning', 'Warning', 4), ('error', 'Error', 4), ('info', 'Information', 4),
)


def alpha(colour, factor):
    """Multiplies the alpha of a colour."""
    current = ((colour >> 24) & 0xFF) / 255.0
    byte = int(min(1.0, max(0.0, current * factor)) * 255.0 + 0.5)
    return (colour & 0x00FFFFFF) | (byte << 24)


def mix(a, b, t):
    out = 0
    for shift in (0, 8, 16, 24):
        x, y = (a >> shift) & 0xFF, (b >> shift) & 0xFF
        out |= (int(x + (y - x) * t + 0.5) & 0xFF) << shift
    return out


def brighter(colour, amount):
    """Towards white."""
    return mix(colour, (colour & 0xFF000000) | 0x00FFFFFF, amount)


def darker(colour, amount):
    """Towards black."""
    return mix(colour, colour & 0xFF000000, amount)


def vec(colour):
    """ImVec4 (r, g, b, a) floats of a packed colour."""
    return imgui.ImVec4(((colour >> 0) & 0xFF) / 255.0, ((colour >> 8) & 0xFF) / 255.0,
                        ((colour >> 16) & 0xFF) / 255.0, ((colour >> 24) & 0xFF) / 255.0)


def floats(colour):
    """(r, g, b, a) floats of a packed colour, for code that wants tuples."""
    return (((colour >> 0) & 0xFF) / 255.0, ((colour >> 8) & 0xFF) / 255.0, ((colour >> 16) & 0xFF) / 255.0, ((colour >> 24) & 0xFF) / 255.0)


def from_floats(r, g, b, a=1.0):
    """A packed colour from float components (track colours stored as tuples)."""
    channel = lambda v: int(min(1.0, max(0.0, float(v))) * 255.0 + 0.5)
    return (channel(a) << 24) | (channel(b) << 16) | (channel(g) << 8) | channel(r)


_CATEGORICAL = (0xf0a43a, 0x5ab0f0, 0x52d1a2, 0xc792ea, 0xe8765a, 0x7fd1e8, 0xe8c547, 0x9ccc65, 0xf06292, 0x8c9eff, 0x4dd0b5, 0xffb74d)


def categorical(index):
    """The n-th colour of a pleasant categorical set (tracks, layers, tags, series)."""
    return rgb(_CATEGORICAL[int(index) % len(_CATEGORICAL)])


def contrast_text(ground):
    """Dark or light text, whichever reads on ``ground``."""
    r, g, b = (ground & 0xFF) / 255.0, ((ground >> 8) & 0xFF) / 255.0, ((ground >> 16) & 0xFF) / 255.0
    return rgb(0x141414) if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.55 else rgb(0xFFFFFF)


# ----------------------------------------------------------------------------- theme files

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


# ----------------------------------------------------------------------------- metrics

@dataclass(frozen=True)
class Metrics:
    font_size: float           # base text size, before DPI
    window_padding: tuple
    frame_padding: tuple
    item_spacing: tuple
    item_inner_spacing: tuple
    cell_padding: tuple
    indent: float
    scrollbar: float
    grab_min: float
    rounding: float            # frames, buttons, fields
    rounding_large: float      # windows, popups, cards
    rounding_small: float      # grabs, chips, badges
    card_padding: float        # inside begin_card
    toolbar_height: float      # extra height around a frame for top bars


COMPACT = Metrics(14.0, (8.0, 6.0), (6.0, 3.0), (6.0, 4.0), (4.0, 4.0), (5.0, 2.0), 14.0, 10.0, 9.0, 4.0, 6.0, 3.0, 10.0, 14.0)
COMFORTABLE = Metrics(16.0, (10.0, 10.0), (8.0, 5.0), (8.0, 6.0), (6.0, 4.0), (6.0, 4.0), 16.0, 11.0, 10.0, 6.0, 8.0, 4.0, 14.0, 16.0)
DENSITIES = ('compact', 'comfortable')


class _State:
    palette = replace(MID_GREY)
    theme_key = DEFAULT_THEME
    light = False
    density = 'compact'
    metrics = COMPACT
    dpi = 1.0
    square_windows = False
    icons = False
    fonts = {}                 # 'ui' / 'bold' / 'mono' -> ImFont


def palette():
    return _State.palette


def metrics():
    return _State.metrics


def density():
    return _State.density


def dpi():
    return _State.dpi


def current_theme_key():
    return _State.theme_key


def is_light():
    return _State.light


def find_theme(key):
    return next((t for t in THEMES if t.key == key), None)


def dp(x, y=None):
    """Scales a design value (in 96-dpi pixels) to the screen: every hard-coded size in custom drawing."""
    scale = _State.dpi
    return float(x) * scale if y is None else imgui.ImVec2(float(x) * scale, float(y) * scale)


def _style_colours(style):
    p = _State.palette
    C = imgui.Col_
    pairs = (
        (C.text, p.text), (C.text_disabled, p.textFaint), (C.window_bg, p.bg1), (C.child_bg, alpha(p.bg2, 0.0)),
        (C.popup_bg, alpha(p.bg2, 0.98)), (C.border, p.line), (C.border_shadow, 0),
        (C.frame_bg, p.bg3), (C.frame_bg_hovered, p.bg4), (C.frame_bg_active, p.bg5),
        (C.title_bg, p.bg0), (C.title_bg_active, p.bg0), (C.title_bg_collapsed, p.bg0), (C.menu_bar_bg, p.bg0),
        (C.scrollbar_bg, alpha(p.bg0, 0.0)), (C.scrollbar_grab, p.bg5), (C.scrollbar_grab_hovered, brighter(p.bg5, 0.12)),
        (C.scrollbar_grab_active, p.accentDim), (C.check_mark, p.accent), (C.slider_grab, p.accent), (C.slider_grab_active, p.accentHover),
        (C.button, p.bg3), (C.button_hovered, p.bg4), (C.button_active, p.bg5),
        (C.header, alpha(p.accent, 0.16)), (C.header_hovered, p.bg4), (C.header_active, alpha(p.accent, 0.26)),
        (C.separator, p.line), (C.separator_hovered, p.accentDim), (C.separator_active, p.accent),
        (C.resize_grip, alpha(p.bg5, 0.0)), (C.resize_grip_hovered, p.accentDim), (C.resize_grip_active, p.accent),
        (C.tab_hovered, p.bg4), (C.tab, p.bg0), (C.tab_selected, p.bg1), (C.tab_selected_overline, p.accent),
        (C.tab_dimmed, p.bg0), (C.tab_dimmed_selected, p.bg1), (C.tab_dimmed_selected_overline, alpha(p.accent, 0.35)),
        (C.docking_preview, alpha(p.accent, 0.45)), (C.docking_empty_bg, p.bg0),
        (C.plot_lines, p.info), (C.plot_lines_hovered, p.accent), (C.plot_histogram, p.accent), (C.plot_histogram_hovered, p.accentHover),
        (C.table_header_bg, p.bg2), (C.table_border_strong, p.lineStrong), (C.table_border_light, p.line),
        (C.table_row_bg, 0), (C.table_row_bg_alt, alpha(p.text, 0.025)), (C.text_link, p.info),
        (C.text_selected_bg, alpha(p.accent, 0.30)), (C.drag_drop_target, p.accent), (C.nav_cursor, p.accent),
        (C.nav_windowing_highlight, alpha(p.accent, 0.7)), (C.nav_windowing_dim_bg, rgb(0x000000, 0.35)),
        (C.modal_window_dim_bg, rgb(0x000000, 0.25 if _State.light else 0.45)),
        (C.input_text_cursor, p.accent), (C.tree_lines, p.line),
        (C.drag_drop_target_bg, alpha(p.accent, 0.10)), (C.unsaved_marker, p.accent), (C.checkbox_selected_bg, p.bg4),
    )
    for index, colour in pairs:
        style.set_color_(index, vec(colour))
    if _State.square_windows:
        c = style.color_(C.window_bg)
        style.set_color_(C.window_bg, imgui.ImVec4(c.x, c.y, c.z, 1.0))


def _apply_style():
    """Sizes, roundings and colours, scaled by the DPI. Every scaled value is set here (no
    ScaleAllSizes), so applying again (theme or density change) never compounds the scale."""
    style = imgui.get_style()
    m, s = _State.metrics, _State.dpi
    v2 = lambda pair: imgui.ImVec2(pair[0] * s, pair[1] * s)
    style.font_size_base = m.font_size
    style.window_padding = v2(m.window_padding)
    style.frame_padding = v2(m.frame_padding)
    style.item_spacing = v2(m.item_spacing)
    style.item_inner_spacing = v2(m.item_inner_spacing)
    style.cell_padding = v2(m.cell_padding)
    style.indent_spacing = m.indent * s
    style.scrollbar_size = m.scrollbar * s
    style.scrollbar_padding = 1.0 * s
    style.grab_min_size = m.grab_min * s
    style.window_border_size = 1.0
    style.child_border_size = 1.0
    style.popup_border_size = 1.0
    style.frame_border_size = 0.0
    style.tab_border_size = 0.0
    style.tab_bar_border_size = 1.0
    style.tab_bar_overline_size = 2.0
    style.window_rounding = 0.0 if _State.square_windows else m.rounding_large * s
    style.child_rounding = (m.rounding_large - 1.0) * s
    style.frame_rounding = m.rounding * s
    style.popup_rounding = m.rounding_large * s
    style.scrollbar_rounding = 8.0 * s
    style.grab_rounding = m.rounding_small * s
    style.tab_rounding = (m.rounding + 1.0) * s
    style.window_title_align = imgui.ImVec2(0.0, 0.5)
    style.window_menu_button_position = imgui.Dir.none
    style.separator_text_border_size = 1.0
    style.separator_text_padding = v2((10.0, 2.0))
    style.docking_separator_size = 2.0
    style.window_min_size = v2((60.0, 40.0))
    style.hover_delay_short = 0.25
    style.hover_delay_normal = 0.55
    style.anti_aliased_lines = True
    style.anti_aliased_fill = True
    style.font_scale_dpi = s
    _style_colours(style)


def set_palette(value):
    """The palette drawn with from now on; ImGui's own colours follow."""
    _State.palette = replace(value)
    if imgui.get_current_context() is not None:
        _style_colours(imgui.get_style())


def set_theme(key):
    """Applies a built-in theme by key; False when unknown."""
    found = find_theme(key)
    if found is None:
        return False
    _State.theme_key, _State.light = found.key, found.light
    set_palette(found.palette)
    return True


def set_density(value):
    _State.density = value if value in DENSITIES else 'compact'
    _State.metrics = COMFORTABLE if _State.density == 'comfortable' else COMPACT
    if imgui.get_current_context() is not None:
        _apply_style()


def apply(theme_key=DEFAULT_THEME, density_key='compact', dpi_scale=1.0, square_windows=False):
    """Sets ImGui's style (sizes, roundings, colours) from the theme. Call after the context exists,
    and again when the theme, the density or the DPI changes."""
    _State.dpi = max(0.5, float(dpi_scale or 1.0))
    _State.square_windows = bool(square_windows)
    _State.density = density_key if density_key in DENSITIES else 'compact'
    _State.metrics = COMFORTABLE if _State.density == 'comfortable' else COMPACT
    if not set_theme(theme_key):
        set_theme(DEFAULT_THEME)
    _apply_style()


def apply_dpi(dpi_scale):
    _State.dpi = max(0.5, float(dpi_scale or 1.0))
    _apply_style()


# ----------------------------------------------------------------------------- fonts

def _windows_font(name):
    if os.name != 'nt':
        return None
    return Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / name


def _first_existing(candidates):
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def load_fonts(size=None, fallback_folder=None, icons=True):
    """Loads the interface font (Segoe UI), semibold (Segoe UI Semibold) and mono (Consolas), the
    first two with the Segoe MDL2 icon glyphs merged; falls back to fonts in ``fallback_folder``
    (Inter, Roboto, JetBrains Mono, Cousine) and then to ImGui's own font. Call from the backend's
    font-loading callback (hello_imgui: ``runner.callbacks.load_additional_fonts``)."""
    io = imgui.get_io()
    size = float(size or _State.metrics.font_size)
    folder = Path(fallback_folder) if fallback_folder else None
    in_folder = lambda name: (folder / name) if folder else None
    _State.icons = False
    _State.fonts = {}

    def add(candidates, font_size):
        path = _first_existing(candidates)
        config = imgui.ImFontConfig()
        config.oversample_h = 2
        config.oversample_v = 2
        config.pixel_snap_h = True
        if path is not None:
            font = io.fonts.add_font_from_file_ttf(str(path), font_size, config)
            if font is not None:
                return font
        return io.fonts.add_font_default()

    def merge_icons(font_size):
        if not icons:
            return
        path = _windows_font('segmdl2.ttf')
        if path is None or not path.is_file():
            return
        config = imgui.ImFontConfig()
        config.merge_mode = True
        config.pixel_snap_h = True
        config.glyph_offset = imgui.ImVec2(0.0, 2.0)
        config.glyph_min_advance_x = font_size
        if io.fonts.add_font_from_file_ttf(str(path), font_size * 0.95, config) is not None:
            _State.icons = True

    _State.fonts['ui'] = add([_windows_font('segoeui.ttf'), in_folder('Inter-Regular.ttf'), in_folder('Roboto-Regular.ttf'), in_folder('Roboto-Medium.ttf')], size)
    merge_icons(size)
    _State.fonts['bold'] = add([_windows_font('seguisb.ttf'), in_folder('Inter-SemiBold.ttf'), in_folder('Roboto-Bold.ttf'), in_folder('Roboto-Medium.ttf')], size)
    merge_icons(size)
    _State.fonts['mono'] = add([_windows_font('consola.ttf'), in_folder('JetBrainsMono-Regular.ttf'), in_folder('Cousine-Regular.ttf')], size - 1.0)
    io.font_default = _State.fonts['ui']
    return dict(_State.fonts)


def ui_font():
    return _State.fonts.get('ui')


def bold_font():
    return _State.fonts.get('bold') or _State.fonts.get('ui')


def mono_font():
    return _State.fonts.get('mono') or _State.fonts.get('ui')


def icons_available():
    """Whether the icon glyphs can be drawn (Segoe MDL2 Assets was found and merged)."""
    return _State.icons


def palette_field_names():
    return [f.name for f in fields(Palette)]
