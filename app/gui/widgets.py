"""Shared widgets: parameter editors from effect specs / plugin descriptions, file dialogs."""
from pathlib import Path

from imgui_bundle import imgui, portable_file_dialogs as pfd

AUDIO_FILTER = ['Audio', '*.wav *.flac *.ogg *.mp3 *.m4a *.aac *.aiff *.aif *.opus *.wma', 'All files', '*']


def draw_effect_params(spec, values, tr=lambda t: t):
    """Draw the parameters of an EffectSpec; returns True when a value changed."""
    changed_any = False
    for param in spec.params:
        imgui.push_id(param.id)
        label = tr(param.label) + (f' ({param.unit})' if param.unit else '')
        current = values.get(param.id, param.default)
        if param.kind == 'bool':
            changed, value = imgui.checkbox(label, bool(current))
        elif param.kind == 'enum':
            choices = list(param.choices)
            index = choices.index(current) if current in choices else 0
            changed, index = imgui.combo(label, index, [str(c) for c in choices])
            value = choices[index]
        elif param.kind == 'int':
            changed, value = imgui.slider_int(label, int(current), int(param.minimum if param.minimum is not None else 0), int(param.maximum if param.maximum is not None else 100))
        elif param.kind == 'string':
            changed, value = imgui.input_text(label, str(current or ''))
        else:
            lo = float(param.minimum if param.minimum is not None else -100.0)
            hi = float(param.maximum if param.maximum is not None else 100.0)
            flags = imgui.SliderFlags_.logarithmic if (param.unit == 'Hz' and lo > 0) else 0
            changed, value = imgui.slider_float(label, float(current), lo, hi, '%.3f', flags)
        if changed:
            values[param.id] = value
            changed_any = True
        if param.help and imgui.is_item_hovered():
            imgui.set_tooltip(tr(param.help))
        imgui.pop_id()
    return changed_any


def draw_plugin_params(description, values, tr=lambda t: t, max_shown=64):
    """Draw VST3 parameters from a describe() result; returns True when a value changed."""
    changed_any = False
    parameters = description.get('parameters', {})
    shown = 0
    for name, info in parameters.items():
        if shown >= max_shown:
            imgui.text_disabled(tr('... more parameters in the plugin window'))
            break
        shown += 1
        imgui.push_id(name)
        label = str(info.get('label') or name)
        current = values.get(name, info.get('value'))
        if info.get('choices'):
            choices = info['choices']
            index = choices.index(str(current)) if str(current) in choices else 0
            changed, index = imgui.combo(label, index, choices)
            value = choices[index]
        elif info.get('type') == 'bool' or isinstance(current, bool):
            changed, value = imgui.checkbox(label, bool(current))
        else:
            lo, hi = float(info.get('minimum', 0.0)), float(info.get('maximum', 1.0))
            if hi <= lo:
                lo, hi = 0.0, 1.0
            try:
                cur = float(current)
            except (TypeError, ValueError):
                cur = lo
            changed, value = imgui.slider_float(label + (' ' + info['units'] if info.get('units') else ''), cur, lo, hi, '%.3f')
        if changed:
            values[name] = value
            changed_any = True
        imgui.pop_id()
    if not parameters:
        imgui.text_disabled(tr('This plugin exposes no parameters'))
    return changed_any


_search_texts = {}
combo_rects = {}          # key -> screen rectangle of the last drawn search combo


def search_combo(key, index, labels, width, haystacks=None, groups=None, tooltips=None, tr=lambda t: t):
    """Combo whose popup starts with a search field (accent / case insensitive, every word must match).

    Enter picks the first match. ``groups`` draws category separators when the search is empty.
    Returns (changed, index)."""
    from .search import matches
    labels = list(labels)
    preview = labels[index] if 0 <= index < len(labels) else ''
    changed = False
    origin = imgui.get_cursor_screen_pos()
    combo_rects[key] = (origin.x, origin.y, origin.x + width, origin.y + imgui.get_frame_height())   # for scripted tests
    imgui.push_item_width(width)
    if imgui.begin_combo('##' + key, preview, imgui.ComboFlags_.height_large):
        if imgui.is_window_appearing():
            _search_texts[key] = ''
            imgui.set_keyboard_focus_here()
        imgui.push_item_width(-1)
        enter, text = imgui.input_text_with_hint('##search-' + key, tr('Search...'), _search_texts.get(key, ''), imgui.InputTextFlags_.enter_returns_true)
        imgui.pop_item_width()
        _search_texts[key] = text
        group, first = None, None
        for i, label in enumerate(labels):
            if not matches(text, haystacks[i] if haystacks else label):
                continue
            if first is None:
                first = i
            if groups and not text.strip() and groups[i] != group:
                group = groups[i]
                imgui.separator_text(str(group))
            if imgui.selectable(label + '##pick' + str(i), i == index)[0]:
                index, changed = i, True
            if tooltips and tooltips[i] and imgui.is_item_hovered():
                imgui.set_tooltip(tooltips[i])
        if first is None:
            imgui.text_disabled(tr('No match'))
        elif enter:
            index, changed = first, True
            imgui.close_current_popup()
        imgui.end_combo()
    imgui.pop_item_width()
    return changed, index


class Dialogs:
    """Non-blocking portable file dialogs polled every frame."""

    def __init__(self):
        self.pending = None
        self.purpose = None

    def open_file(self, purpose, title, folder='', filters=None, multiple=False):
        options = pfd.opt.multiselect if multiple else pfd.opt.none
        self.pending = pfd.open_file(title, folder or str(Path.home()), filters or AUDIO_FILTER, options)
        self.purpose = purpose

    def save_file(self, purpose, title, folder='', default_name='', filters=None):
        self.pending = pfd.save_file(title, str(Path(folder or Path.home()) / default_name), filters or AUDIO_FILTER)
        self.purpose = purpose

    def select_folder(self, purpose, title, folder=''):
        self.pending = pfd.select_folder(title, folder or str(Path.home()))
        self.purpose = purpose

    def poll(self):
        """Returns (purpose, result) when a dialog finished, else None. result is a list or a string."""
        if self.pending is None or not self.pending.ready(0):
            return None
        result = self.pending.result()
        purpose = self.purpose
        self.pending, self.purpose = None, None
        if isinstance(result, list):
            return (purpose, result) if result else None
        return (purpose, result) if result else None

    @property
    def busy(self):
        return self.pending is not None


def status_line(text, error=False):
    if error:
        imgui.text_colored((1.0, 0.45, 0.4, 1.0), text)
    else:
        imgui.text_wrapped(text)


def help_marker(text):
    imgui.same_line()
    imgui.text_disabled('(?)')
    if imgui.is_item_hovered():
        imgui.set_tooltip(text)


# ----------------------------------------------------------------------------- layout helpers

class Row:
    """Places widgets on one line and wraps to the next when the window is too narrow.

    Call ``row.next(width)`` before every widget except the first; ``width`` is the width the
    next widget will take (use ``Row.button_width(label)`` for buttons).
    """

    def __init__(self):
        self.right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        self.first = True

    def next(self, width):
        if self.first:
            self.first = False
            return
        spacing = imgui.get_style().item_spacing.x
        if imgui.get_item_rect_max().x + spacing + width <= self.right:
            imgui.same_line()

    @staticmethod
    def text_width(text):
        return imgui.calc_text_size(str(text).split('##')[0]).x

    @staticmethod
    def button_width(label):
        return Row.text_width(label) + imgui.get_style().frame_padding.x * 2

    @staticmethod
    def check_width(label):
        return imgui.get_frame_height() + imgui.get_style().item_inner_spacing.x + Row.text_width(label)

    def button(self, label, tr=lambda t: t, small=False):
        visible, _, identity = label.partition('###')
        text = tr(visible)
        self.next(Row.button_width(text))
        widget = imgui.small_button if small else imgui.button
        return widget(text + '###' + (identity or visible))

    def checkbox(self, label, value, tr=lambda t: t):
        visible, _, identity = label.partition('###')
        text = tr(visible)
        self.next(Row.check_width(text))
        return imgui.checkbox(text + '###' + (identity or visible), value)

    def combo(self, key, index, items, width):
        self.next(width)
        imgui.push_item_width(width)
        result = imgui.combo('##' + key, index, items)
        imgui.pop_item_width()
        return result

    def text(self, text, disabled=False):
        self.next(Row.text_width(text))
        (imgui.text_disabled if disabled else imgui.text)(text)


def multiline(label, value, height, key, tr=lambda t: t):
    """Label above, field over the full width (a label on the right would be cut off)."""
    imgui.text(tr(label))
    return imgui.input_text_multiline('##' + key, value, (-1, height))


def field(label, value, key, tr=lambda t: t, width=-1):
    """Single-line input with its label above."""
    imgui.text(tr(label))
    imgui.push_item_width(width)
    result = imgui.input_text('##' + key, value)
    imgui.pop_item_width()
    return result


_thumbnails = {}


def file_peaks(path, columns=240):
    """Cached min/max envelope of an audio file for a thumbnail (None when unreadable)."""
    from audiostudio import audio_io
    import numpy as np
    try:
        stamp = Path(path).stat().st_mtime_ns
    except OSError:
        return None
    key = (str(path), columns)
    cached = _thumbnails.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        audio, rate = audio_io.load(path)
    except Exception:
        return None
    mono_low, mono_high = audio.min(axis=0), audio.max(axis=0)
    edges = np.linspace(0, len(mono_low), columns + 1).astype(int)[:-1] if len(mono_low) > columns else np.arange(len(mono_low))
    value = (np.minimum.reduceat(mono_low, edges), np.maximum.reduceat(mono_high, edges), audio.shape[1] / float(rate))
    if len(_thumbnails) > 200:
        _thumbnails.clear()
    _thumbnails[key] = (stamp, value)
    return value


def thumbnail(path, width=240.0, height=38.0, colour=(0.36, 0.72, 0.95)):
    """Draw a small waveform of a file; returns its duration in seconds (or None)."""
    peaks = file_peaks(path, max(16, int(width)))
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy((width, height))
    draw = imgui.get_window_draw_list()
    draw.add_rect_filled(origin, (origin.x + width, origin.y + height), imgui.get_color_u32((0.08, 0.09, 0.11, 1.0)))
    if peaks is None:
        return None
    low, high, duration = peaks
    middle, half = origin.y + height / 2, height / 2 - 2
    count = len(low)
    if count:
        step = width / count
        for i in range(count):
            x = origin.x + (i + 0.5) * step
            top, bottom = middle - float(high[i]) * half, middle - float(low[i]) * half
            draw.add_line((x, top), (x, max(bottom, top + 1)), imgui.get_color_u32((*colour, 1.0)), max(1.0, step))
    return duration
