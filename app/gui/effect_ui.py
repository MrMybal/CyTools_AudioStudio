"""Interfaces of the insert effects: one drawing routine per family (dynamics, multiband, EQ,
filter, reverb, delay, modulation, distortion, vocoder, stereo, analyser, generic) plus the
VST3 panel. Every panel starts with the same header: input / output meters and a real-time
scope of the audio entering and leaving the node, read from the renderer taps.

Parameters are edited in ``node['params']``; the renderer applies them on the next block.
A knob drag records one undo entry; with automation "write" armed while playing, the value
is also written into the lane of that parameter.
"""
import collections
import json
import math
from pathlib import Path

import numpy as np
from imgui_bundle import imgui

from audiostudio.dsp import effects
from audiostudio.dsp import processors as P
from audiostudio.dsp import filters as dsp_filters
from audiostudio.dsp import space as dsp_space
from audiostudio.paths import PRESETS
from .knobs import (knob, level_meter, reduction_meter, Plot, col, text_col, accent, accent_col, warm, cool, theme_col, freq_label, FREQ_GRID, gain_to_db)
from .widgets import Row, draw_plugin_params
from . import cyui

SCOPE_FRAMES = 2048
GR_HISTORY = 240


def safe_name(name):
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in str(name))[:60] or 'preset'


class EffectUI:
    def __init__(self, app):
        self.app = app
        self.spectra = {}                    # node id -> smoothed spectrum (dB)
        self.gr_history = collections.defaultdict(lambda: collections.deque(maxlen=GR_HISTORY))
        self.peak_hold = {}                  # (node id, which, channel) -> (db, time)
        self.eq_band = {}                    # node id -> selected band
        self.mb_band = {}                    # node id -> selected band
        self.preset_name = ''
        self.dragging = None                 # (node id, what)

    def tr(self, text):
        return self.app.tr(text)

    # ------------------------------------------------------------------ helpers
    @property
    def document(self):
        return self.app.document

    def _record(self, owner, label):
        self.document._edit_owner(label, owner)

    def _set_param(self, owner, node, key, value):
        node['params'][key] = value
        self.document.touch()
        player = self.app.player
        if getattr(self.app, 'automation_write', False) and player.playing:
            self.document.automation_write(owner, node['id'] + '.' + key, player.position, float(value) if not isinstance(value, bool) else (1.0 if value else 0.0))

    def _lane_menu(self, owner, node, param_id, label):
        """Right-click menu of a parameter: show / clear its automation lane."""
        key = node['id'] + '.' + param_id
        if imgui.begin_popup_context_item('##lane-' + param_id):
            imgui.text_disabled(label)
            if imgui.menu_item(self.tr('Show automation lane'), '', owner.automation_view == key)[0]:
                owner.automation_view = '' if owner.automation_view == key else key
            lane = owner.automation.get(key)
            if imgui.menu_item(self.tr('Add automation point at cursor'), '', False)[0]:
                lo, hi, current, kind = self.document.automation_range(owner, key)
                self.document.automation_add(owner, key, self.document.cursor, current)
                owner.automation_view = key
            if lane is not None and imgui.menu_item(self.tr('Clear automation'), '', False)[0]:
                self.document.automation_clear(owner, key)
            imgui.end_popup()

    def param_knob(self, owner, node, param, size=44.0, log=None):
        """One parameter as a knob / checkbox / combo. Returns True when it changed."""
        tr = self.tr
        values = node['params']
        current = values.get(param.id, param.default)
        key = node['id'] + '.' + param.id
        lane = owner.automation.get(key)
        automated = lane is not None and lane.active
        label = tr(param.label)
        changed = False
        if param.kind == 'bool':
            imgui.begin_group()
            changed, value = imgui.checkbox(label + '##' + param.id, bool(current))
            if changed:
                self._record(owner, label)
                self._set_param(owner, node, param.id, bool(value))
            imgui.end_group()
            self._lane_menu(owner, node, param.id, label)
            return changed
        if param.kind == 'enum':
            choices = list(param.choices)
            index = choices.index(current) if current in choices else 0
            imgui.push_item_width(max(90.0, size * 2.2))
            changed, index = imgui.combo(label + '##' + param.id, index, [tr(str(c)) for c in choices])
            imgui.pop_item_width()
            if changed:
                self._record(owner, label)
                self._set_param(owner, node, param.id, choices[index])
            return changed
        if param.kind == 'string':
            imgui.push_item_width(220)
            changed, value = imgui.input_text(label + '##' + param.id, str(current or ''))
            imgui.pop_item_width()
            if changed:
                self._set_param(owner, node, param.id, value)
            return changed
        lo = float(param.minimum if param.minimum is not None else -100.0)
        hi = float(param.maximum if param.maximum is not None else 100.0)
        use_log = log if log is not None else (param.unit == 'Hz' and lo > 0)
        fmt = '%d' if param.kind == 'int' else ('%.0f' if hi - lo >= 200 else ('%.1f' if hi - lo >= 20 else '%.2f'))
        if param.unit:
            fmt += ' ' + param.unit.replace('%', '%%')      # a '%' unit must not break the format
        changed, value = knob(label + '##' + param.id, float(current), lo, hi, fmt, log=use_log, size=size,
                              tooltip=tr(param.help) if param.help else '', default=float(param.default), automated=automated)
        if imgui.is_item_activated():
            self._record(owner, label)
        if changed:
            self._set_param(owner, node, param.id, int(round(value)) if param.kind == 'int' else float(value))
        self._lane_menu(owner, node, param.id, label)
        return changed

    def knob_row(self, owner, node, params, size=44.0):
        """Knobs on wrapping rows."""
        right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        first = True
        changed = False
        for param in params:
            width = max(size, imgui.calc_text_size(self.tr(param.label)).x + 4) if param.kind in ('float', 'int') else 150.0
            if not first and imgui.get_item_rect_max().x + imgui.get_style().item_spacing.x + width <= right:
                imgui.same_line()
            first = False
            changed = self.param_knob(owner, node, param, size) or changed
        return changed

    # ------------------------------------------------------------------ header: meters + scope
    def header(self, node, renderer, width, height=64.0):
        tap = renderer.taps.get(node['id'])
        tr = self.tr
        meter_w = 12.0
        imgui.begin_group()
        in_peaks = tap.in_peak if tap else (0.0, 0.0)
        out_peaks = tap.out_peak if tap else (0.0, 0.0)
        level_meter(in_peaks[0], meter_w, height)
        imgui.same_line(0, 2)
        level_meter(in_peaks[1], meter_w, height, label=tr('in'))
        imgui.same_line()
        available = max(240.0, width - (meter_w * 4 + 100))
        scope_w = available * 0.58
        spectrum_w = available - scope_w - imgui.get_style().item_spacing.x
        plot = Plot(scope_w, height, (0, SCOPE_FRAMES), (-1.0, 1.0))
        plot.draw.add_line((plot.x0, plot.py(0)), (plot.x1, plot.py(0)), text_col(0.15))
        if tap is not None:
            xs = np.arange(SCOPE_FRAMES)
            mono_in = tap.recent('input', SCOPE_FRAMES).mean(axis=0)
            mono_out = tap.recent('output', SCOPE_FRAMES).mean(axis=0)
            step = max(1, SCOPE_FRAMES // int(scope_w))
            plot.line(xs[::step], mono_in[::step], text_col(0.35), 1.0)
            plot.line(xs[::step], mono_out[::step], accent_col(0.95), 1.2)
        plot.end()
        if plot.hovered:
            imgui.set_tooltip(tr('Waveform entering (grey) and leaving (colour) this effect'))
        imgui.same_line()
        # spectrometer: what the effect does to the frequencies, live
        spectrum_plot = Plot(spectrum_w, height, (20.0, 20000.0), (-90.0, 0.0), log_x=True)
        freqs, db_in = self.spectrum(node, renderer, 'input', slot='header')
        _, db_out = self.spectrum(node, renderer, 'output', slot='header')
        self.draw_spectrum_in(spectrum_plot, freqs, db_in, text_col(0.16))
        spectrum_plot.line(freqs, db_out, accent_col(0.95), 1.2)
        for value in (100, 1000, 10000):
            x = spectrum_plot.px(value)
            spectrum_plot.draw.add_line((x, spectrum_plot.y0), (x, spectrum_plot.y1), text_col(0.10))
            spectrum_plot.draw.add_text((x + 2, spectrum_plot.y1 - imgui.get_text_line_height()), text_col(0.45), freq_label(value))
        spectrum_plot.end()
        if spectrum_plot.hovered:
            mouse = imgui.get_mouse_pos()
            imgui.set_tooltip(tr('Spectrum entering (grey) and leaving (colour) this effect') + '   %s Hz' % freq_label(round(spectrum_plot.x_at(mouse.x))))
        imgui.same_line()
        level_meter(out_peaks[0], meter_w, height)
        imgui.same_line(0, 2)
        level_meter(out_peaks[1], meter_w, height, label=tr('out'))
        imgui.end_group()

    SPECTRUM_POINTS = 200

    def spectrum(self, node, renderer, which='output', slot=''):
        """Smoothed magnitude spectrum in dB on 200 log-spaced bands over 20 Hz .. 20 kHz.

        ``slot`` separates the smoothing state of two displays of the same node (header, EQ view)."""
        tap = renderer.taps.get(node['id'])
        sr = float(self.document.samplerate)
        size = 4096
        centres = np.exp(np.linspace(math.log(20.0), math.log(20000.0), self.SPECTRUM_POINTS))
        if tap is None:
            return centres, np.full(centres.shape, -100.0)
        mono = tap.recent(which, size).mean(axis=0).astype(np.float64)
        window = np.hanning(size)
        spectrum = np.abs(np.fft.rfft(mono * window)) * (2.0 / window.sum())
        freqs = np.fft.rfftfreq(size, 1.0 / sr)
        # max-pool the FFT bins into the log bands so the drawing has one value per band
        edges = np.exp(np.linspace(math.log(20.0), math.log(20000.0), self.SPECTRUM_POINTS + 1))
        indices = np.searchsorted(freqs, edges)
        pooled = np.full(self.SPECTRUM_POINTS, 1e-7)
        for index in range(self.SPECTRUM_POINTS):
            a, b = indices[index], max(indices[index] + 1, indices[index + 1])
            if a < spectrum.shape[0]:
                pooled[index] = spectrum[a:b].max()
        db = 20.0 * np.log10(pooled + 1e-7)
        previous = self.spectra.get((node['id'], which, slot))
        if previous is not None and previous.shape == db.shape:
            db = np.maximum(db, previous - 3.0)         # slow fall, instant rise
            db = 0.6 * previous + 0.4 * db
        self.spectra[(node['id'], which, slot)] = db
        return centres, db

    def draw_spectrum_in(self, plot, freqs, db, colour=None):
        mask = (freqs >= plot.x_min) & (freqs <= plot.x_max)
        if not mask.any():
            return
        plot.fill_under(freqs[mask], db[mask], colour or text_col(0.14))

    # ------------------------------------------------------------------ dispatch
    def draw(self, owner, node, renderer, width):
        """Interface of an effect node (kind 'effect'); returns nothing."""
        spec = effects.REGISTRY.get(node.get('effect'))
        if spec is None:
            imgui.text_colored(cyui.vec(cyui.palette().error), self.tr('Unknown effect: ') + str(node.get('effect')))
            return
        self.header(node, renderer, width)
        error = renderer.errors.get(node['id'])
        if error:
            imgui.text_colored(cyui.vec(cyui.palette().error), error)
        if spec.help:
            imgui.text_disabled(self.tr(spec.help))
        family = spec.ui or 'generic'
        method = getattr(self, 'ui_' + family, None) or self.ui_generic
        method(owner, node, spec, renderer, width)
        self.presets_row(node, spec)

    # ------------------------------------------------------------------ families
    def ui_generic(self, owner, node, spec, renderer, width):
        self.knob_row(owner, node, spec.params)

    def ui_dynamics(self, owner, node, spec, renderer, width):
        tr = self.tr
        meters = renderer.meters(node['id'])
        processor = renderer.processor(node['id'])
        gr = float(meters.get('gain_reduction_db', 0.0))
        tap = renderer.taps.get(node['id'])
        if 'gain_reduction_db' not in meters and tap is not None:
            # JUCE limiter: estimate from the peaks around the node.
            peak_in, peak_out = max(tap.in_peak), max(tap.out_peak)
            gr = min(0.0, gain_to_db(peak_out) - gain_to_db(peak_in)) if peak_in > 1e-6 else 0.0
        self.gr_history[node['id']].append(gr)
        imgui.begin_group()
        self.knob_row(owner, node, [p for p in spec.params if p.kind in ('float', 'int')])
        for param in [p for p in spec.params if p.kind in ('bool', 'enum')]:
            self.param_knob(owner, node, param)
            imgui.same_line()
        imgui.new_line()
        imgui.end_group()
        imgui.same_line()
        # transfer curve
        imgui.begin_group()
        plot_size = 130.0
        plot = Plot(plot_size, plot_size, (-60.0, 0.0), (-60.0, 0.0))
        plot.grid_x((-40, -20), fmt=lambda v: '%d' % v)
        plot.grid_y((-40, -20), fmt=lambda v: '%d' % v)
        levels = np.linspace(-60.0, 0.0, 61)
        plot.line(levels, levels, text_col(0.25), 1.0)
        if processor is not None and hasattr(processor, 'curve'):
            try:
                plot.line(levels, processor.curve(levels), accent_col(), 2.0)
            except Exception:
                pass
        level = float(meters.get('level_db', -100.0))
        if level > -60.0 and processor is not None and hasattr(processor, 'curve'):
            try:
                out_level = float(processor.curve(np.array([level]))[0])
                plot.point(level, out_level, 4.0, warm())
            except Exception:
                pass
        plot.end()
        if plot.hovered:
            imgui.set_tooltip(tr('Input level (dB) -> output level (dB); the dot is the current level'))
        imgui.end_group()
        imgui.same_line()
        reduction_meter(gr, height=plot_size, label=tr('GR'))
        imgui.same_line()
        history = np.asarray(self.gr_history[node['id']])
        plot = Plot(120.0, plot_size, (0, GR_HISTORY), (-30.0, 0.0))
        plot.grid_y((-20, -10), fmt=lambda v: '%d' % v)
        if history.size > 1:
            plot.fill_under(np.arange(history.size), history, warm(0.6))
        plot.end()
        if plot.hovered:
            imgui.set_tooltip(tr('Gain reduction over the last seconds'))

    def ui_multiband(self, owner, node, spec, renderer, width):
        tr = self.tr
        meters = renderer.meters(node['id'])
        params = node['params']
        bands = int(params.get('bands', 3))
        sr = self.document.samplerate
        # crossover view over the output spectrum; drag a crossover line to move it
        plot = Plot(max(300.0, width - 20), 120.0, (20.0, 20000.0), (-90.0, 0.0), log_x=True)
        freqs, db = self.spectrum(node, renderer)
        self.draw_spectrum_in(plot, freqs, db)
        plot.grid_x(FREQ_GRID, fmt=freq_label)
        crossovers = [params.get(f'crossover_{n}_hz', 1000.0) for n in range(1, bands)]
        mouse = imgui.get_mouse_pos()
        reductions = meters.get('band_reduction_db', [0.0] * bands)
        edges = [20.0] + list(crossovers) + [20000.0]
        for index in range(bands):
            x_a, x_b = plot.px(edges[index]), plot.px(edges[index + 1])
            red = float(reductions[index]) if index < len(reductions) else 0.0
            colour = warm(0.25 + min(0.5, -red / 24.0)) if red < 0 else cool(0.12)
            plot.draw.add_rect_filled((x_a, plot.y0), (x_b, plot.y1), colour if index == self.mb_band.get(node['id'], 0) else cool(0.06 + (min(0.4, -red / 24.0) if red < 0 else 0)))
            plot.draw.add_text((x_a + 4, plot.y0 + 2), text_col(0.8), f'{index + 1}: {red:.1f} dB')
        for n, freq in enumerate(crossovers, start=1):
            x = plot.px(freq)
            near = abs(mouse.x - x) < 6 and plot.hovered
            plot.draw.add_line((x, plot.y0), (x, plot.y1), text_col(0.9 if near else 0.5), 2.0)
            if near and imgui.is_mouse_clicked(imgui.MouseButton_.left):
                self.dragging = (node['id'], 'crossover', n)
                self._record(owner, tr('Crossover'))
        if self.dragging and self.dragging[0] == node['id'] and self.dragging[1] == 'crossover':
            if imgui.is_mouse_down(imgui.MouseButton_.left):
                n = self.dragging[2]
                value = float(np.clip(plot.x_at(mouse.x), 40.0, 16000.0))
                self._set_param(owner, node, f'crossover_{n}_hz', value)
            else:
                self.dragging = None
        plot.end()
        if plot.hovered and not self.dragging:
            imgui.set_tooltip(tr('Drag a crossover line; click a band to edit it'))
        elif plot.hovered and imgui.is_mouse_clicked(imgui.MouseButton_.left) and not self.dragging:
            pass
        if plot.hovered and imgui.is_mouse_clicked(imgui.MouseButton_.left) and not self.dragging:
            f = plot.x_at(mouse.x)
            self.mb_band[node['id']] = sum(1 for c in crossovers if f > c)
        general = [p for p in spec.params if not p.id.startswith('b')]
        self.knob_row(owner, node, general)
        selected = min(self.mb_band.get(node['id'], 0), bands - 1)
        imgui.separator_text(tr('Band') + f' {selected + 1}')
        for n in range(bands):
            if imgui.radio_button(f'{n + 1}##band{n}', selected == n):
                self.mb_band[node['id']] = n
            imgui.same_line()
        imgui.new_line()
        prefix = f'b{selected + 1}_'
        band_params = [p for p in spec.params if p.id.startswith(prefix)]
        imgui.begin_group()
        self.knob_row(owner, node, band_params)
        imgui.end_group()
        imgui.same_line()
        red = float(reductions[selected]) if selected < len(reductions) else 0.0
        reduction_meter(red, height=80.0, label=tr('GR'))

    def ui_eq(self, owner, node, spec, renderer, width):
        tr = self.tr
        processor = renderer.processor(node['id'])
        params = node['params']
        sr = self.document.samplerate
        freqs = np.exp(np.linspace(math.log(20.0), math.log(20000.0), 256))
        plot = Plot(max(320.0, width - 20), 150.0, (20.0, 20000.0), (-24.0, 24.0), log_x=True)
        sfreqs, sdb = self.spectrum(node, renderer)
        # spectrum drawn on a -90..0 scale mapped into the plot height
        mapped = (sdb + 90.0) / 90.0 * 48.0 - 24.0
        self.draw_spectrum_in(plot, sfreqs, mapped)
        plot.grid_x(FREQ_GRID, fmt=freq_label)
        plot.grid_y((-18, -12, -6, 0, 6, 12, 18), fmt=lambda v: '%+d' % v)
        if processor is not None and hasattr(processor, 'response'):
            try:
                plot.line(freqs, processor.response(freqs), accent_col(), 2.2)
            except Exception:
                pass
        selected = self.eq_band.get(node['id'], 1)
        mouse = imgui.get_mouse_pos()
        hovered_band = None
        for n in range(1, dsp_filters.EQ_BANDS + 1):
            if not params.get(f'b{n}_on', False):
                continue
            freq, gain = float(params.get(f'b{n}_freq', 1000.0)), float(params.get(f'b{n}_gain', 0.0))
            kind = params.get(f'b{n}_type', 'peak')
            y_value = gain if kind in ('peak', 'low_shelf', 'high_shelf') else 0.0
            p = plot.point(freq, y_value, 6.0 if n == selected else 5.0, accent_col(0.9 if n == selected else 0.55), text_col(0.9))
            plot.draw.add_text((p[0] + 7, p[1] - 8), text_col(0.8), str(n))
            if plot.hovered and abs(mouse.x - p[0]) < 8 and abs(mouse.y - p[1]) < 8:
                hovered_band = n
        if plot.hovered and hovered_band and imgui.is_mouse_clicked(imgui.MouseButton_.left) and not self.dragging:
            self.eq_band[node['id']] = hovered_band
            self.dragging = (node['id'], 'eq', hovered_band)
            self._record(owner, tr('EQ band'))
        if plot.hovered and hovered_band and imgui.get_io().mouse_wheel != 0.0:
            q = float(params.get(f'b{hovered_band}_q', 1.0))
            self._set_param(owner, node, f'b{hovered_band}_q', float(np.clip(q * (1.15 if imgui.get_io().mouse_wheel > 0 else 0.87), 0.1, 18.0)))
        if plot.hovered and hovered_band and imgui.is_mouse_double_clicked(imgui.MouseButton_.left):
            self._record(owner, tr('EQ band'))
            self._set_param(owner, node, f'b{hovered_band}_gain', 0.0)
        if plot.hovered and hovered_band is None and imgui.is_mouse_double_clicked(imgui.MouseButton_.left):
            free = next((n for n in range(1, dsp_filters.EQ_BANDS + 1) if not params.get(f'b{n}_on', False)), None)
            if free is not None:
                self._record(owner, tr('EQ band'))
                self._set_param(owner, node, f'b{free}_on', True)
                self._set_param(owner, node, f'b{free}_type', 'peak')
                self._set_param(owner, node, f'b{free}_freq', float(np.clip(plot.x_at(mouse.x), 20.0, 20000.0)))
                self._set_param(owner, node, f'b{free}_gain', float(np.clip(plot.y_at(mouse.y), -24.0, 24.0)))
                self.eq_band[node['id']] = free
        if self.dragging and self.dragging[0] == node['id'] and self.dragging[1] == 'eq':
            n = self.dragging[2]
            if imgui.is_mouse_down(imgui.MouseButton_.left):
                self._set_param(owner, node, f'b{n}_freq', float(np.clip(plot.x_at(mouse.x), 20.0, 20000.0)))
                if params.get(f'b{n}_type', 'peak') in ('peak', 'low_shelf', 'high_shelf'):
                    self._set_param(owner, node, f'b{n}_gain', float(np.clip(plot.y_at(mouse.y), -24.0, 24.0)))
            else:
                self.dragging = None
        plot.end()
        if plot.hovered and not self.dragging:
            imgui.set_tooltip(tr('Drag a band point (frequency / gain), wheel = Q, double-click empty = new band, double-click point = reset gain'))
        imgui.text(tr('Band'))
        for n in range(1, dsp_filters.EQ_BANDS + 1):
            imgui.same_line()
            on = params.get(f'b{n}_on', False)
            if not on:
                imgui.push_style_var(imgui.StyleVar_.alpha, 0.5)
            if imgui.radio_button(f'{n}##eqband{n}', selected == n):
                self.eq_band[node['id']] = n
            if not on:
                imgui.pop_style_var()
        selected = self.eq_band.get(node['id'], 1)
        prefix = f'b{selected}_'
        band_params = [p for p in spec.params if p.id.startswith(prefix)]
        self.knob_row(owner, node, band_params)
        imgui.same_line()
        self.param_knob(owner, node, next(p for p in spec.params if p.id == 'output_db'))

    def ui_graphic_eq(self, owner, node, spec, renderer, width):
        tr = self.tr
        processor = renderer.processor(node['id'])
        freqs = np.exp(np.linspace(math.log(20.0), math.log(20000.0), 200))
        plot = Plot(max(300.0, width - 20), 90.0, (20.0, 20000.0), (-14.0, 14.0), log_x=True)
        sfreqs, sdb = self.spectrum(node, renderer)
        self.draw_spectrum_in(plot, sfreqs, (sdb + 90.0) / 90.0 * 28.0 - 14.0)
        plot.grid_x(FREQ_GRID, fmt=freq_label)
        plot.grid_y((-12, -6, 0, 6, 12), fmt=lambda v: '%+d' % v)
        if processor is not None:
            plot.line(freqs, processor.response(freqs), accent_col(), 2.0)
        plot.end()
        for index, param in enumerate(spec.params[:10]):
            if index:
                imgui.same_line()
            imgui.begin_group()
            value = float(node['params'].get(param.id, 0.0))
            changed, value = imgui.v_slider_float('##' + param.id, (26, 110), value, -12.0, 12.0, '%.0f')
            if imgui.is_item_activated():
                self._record(owner, param.label)
            if changed:
                self._set_param(owner, node, param.id, float(value))
            if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(imgui.MouseButton_.left):
                self._set_param(owner, node, param.id, 0.0)
            self._lane_menu(owner, node, param.id, param.label)
            imgui.text_disabled(freq_label(dsp_filters.GRAPHIC_FREQS[index]))
            imgui.end_group()
        imgui.same_line()
        self.param_knob(owner, node, spec.params[-1])

    def ui_filter(self, owner, node, spec, renderer, width):
        processor = renderer.processor(node['id'])
        freqs = np.exp(np.linspace(math.log(20.0), math.log(20000.0), 200))
        plot = Plot(max(260.0, min(width - 20, 420.0)), 110.0, (20.0, 20000.0), (-48.0, 24.0), log_x=True)
        sfreqs, sdb = self.spectrum(node, renderer)
        self.draw_spectrum_in(plot, sfreqs, (sdb + 90.0) / 90.0 * 72.0 - 48.0)
        plot.grid_x(FREQ_GRID, fmt=freq_label)
        plot.grid_y((-36, -24, -12, 0, 12), fmt=lambda v: '%+d' % v)
        response = None
        if processor is not None and hasattr(processor, 'response'):
            try:
                response = processor.response(freqs)
            except Exception:
                response = None
        if response is None:
            try:
                response = dsp_filters.static_response(node['effect'], spec.normalize(node['params']), freqs, self.document.samplerate)
            except Exception:
                response = None
        if response is not None:
            plot.line(freqs, response, accent_col(), 2.0)
        cutoff = renderer.meters(node['id']).get('cutoff_hz')
        if cutoff:
            x = plot.px(cutoff)
            plot.draw.add_line((x, plot.y0), (x, plot.y1), warm(0.8), 1.5)
        plot.end()
        imgui.same_line()
        imgui.begin_group()
        self.knob_row(owner, node, spec.params)
        imgui.end_group()

    def ui_reverb(self, owner, node, spec, renderer, width):
        tr = self.tr
        processor = renderer.processor(node['id'])
        plot = Plot(max(260.0, min(width - 20, 420.0)), 110.0, (0.0, 1.0), (-80.0, 0.0))
        plot.grid_y((-60, -40, -20), fmt=lambda v: '%d' % v)
        if processor is not None and hasattr(processor, 'envelope'):
            times, levels = processor.envelope(160)
            total = float(times[-1]) if len(times) else 1.0
            plot.x_max = max(total, 0.1)
            plot.grid_x([round(total * f, 1) for f in (0.25, 0.5, 0.75)], fmt=lambda v: '%.1fs' % v)
            plot.fill_under(times, levels, accent_col(0.35))
            plot.line(times, levels, accent_col(), 1.5)
        else:
            params = spec.normalize(node['params'])
            decay = 0.3 + 3.5 * float(params.get('room_size', 0.5)) if 'room_size' in params else 2.0
            damping = float(params.get('damping', 0.5)) if 'damping' in params else 0.5
            times = np.linspace(0.0, decay * 1.1, 160)
            levels = -60.0 * times / max(decay, 0.05) * (1.0 + damping * 0.5)
            plot.x_max = max(times[-1], 0.1)
            plot.grid_x([round(times[-1] * f, 1) for f in (0.25, 0.5, 0.75)], fmt=lambda v: '%.1fs' % v)
            plot.fill_under(times, levels, accent_col(0.35))
            plot.line(times, levels, accent_col(), 1.5)
        plot.end()
        if plot.hovered:
            imgui.set_tooltip(tr('Decay of the reverb (dB over time)'))
        imgui.same_line()
        imgui.begin_group()
        self.knob_row(owner, node, spec.params)
        imgui.end_group()

    def ui_delay(self, owner, node, spec, renderer, width):
        tr = self.tr
        params = spec.normalize(node['params'])
        plot = Plot(max(260.0, min(width - 20, 420.0)), 100.0, (0.0, 1.0), (0.0, 1.0))
        taps = []
        if node['effect'] == 'multitap_delay':
            base = params['delay_ms'] / 1000.0
            for n in range(1, 5):
                if params.get(f'tap{n}_on'):
                    taps.append((base * params[f'tap{n}_time'], 10 ** (params[f'tap{n}_gain_db'] / 20.0), params[f'tap{n}_pan']))
        else:
            delay = params.get('delay_seconds', params.get('delay_ms', 350.0) / 1000.0)
            feedback = float(params.get('feedback', 0.0))
            level = 1.0
            side = 0.0
            for repeat in range(1, 12):
                level *= max(feedback, 0.0) if repeat > 1 else 1.0
                if level < 0.02:
                    break
                pan = 0.0
                if node['effect'] == 'pingpong_delay':
                    pan = (-0.8 if repeat % 2 else 0.8) * float(params.get('ping_pong', 1.0))
                taps.append((delay * repeat, level, pan))
        span = max([t[0] for t in taps] + [0.5]) * 1.1
        plot.x_max = span
        plot.grid_x([round(span * f, 2) for f in (0.25, 0.5, 0.75)], fmt=lambda v: '%.2fs' % v)
        plot.draw.add_rect_filled((plot.px(0) - 1, plot.py(1.0)), (plot.px(0) + 2, plot.py(0)), text_col(0.6))
        for t, level, pan in taps:
            x = plot.px(t)
            colour = accent_col() if abs(pan) < 0.3 else (cool() if pan < 0 else warm())
            plot.draw.add_rect_filled((x - 2, plot.py(min(1.0, level))), (x + 2, plot.py(0)), colour)
        plot.draw.add_text((plot.x0 + 4, plot.y0 + 2), text_col(0.6), tr('echoes (blue = left, orange = right)'))
        plot.end()
        imgui.same_line()
        imgui.begin_group()
        self.knob_row(owner, node, spec.params)
        imgui.end_group()

    def ui_modulation(self, owner, node, spec, renderer, width):
        tr = self.tr
        params = spec.normalize(node['params'])
        plot = Plot(max(220.0, min(width - 20, 360.0)), 90.0, (0.0, 2.0), (-1.2, 1.2))
        plot.draw.add_line((plot.x0, plot.py(0)), (plot.x1, plot.py(0)), text_col(0.15))
        phases = np.linspace(0.0, 2.0, 200)
        shape = params.get('shape', 'sine')
        depth = float(params.get('depth', 1.0))
        wave = P.lfo(shape if shape in ('sine', 'triangle', 'square', 'saw') else 'sine', phases) * depth
        plot.line(phases, wave, accent_col(), 2.0)
        rate = float(params.get('rate_hz', params.get('frequency_hz', 1.0)))
        meters = renderer.meters(node['id'])
        if 'lfo' in meters:
            plot.point(0.0, float(meters['lfo']), 4.0, warm())
        plot.draw.add_text((plot.x0 + 4, plot.y0 + 2), text_col(0.6), tr('LFO') + ' %.2f Hz  (%.2f s / %s)' % (rate, 1.0 / max(rate, 1e-3), tr('cycle')))
        plot.end()
        imgui.same_line()
        imgui.begin_group()
        self.knob_row(owner, node, spec.params)
        imgui.end_group()

    def ui_distortion(self, owner, node, spec, renderer, width):
        tr = self.tr
        processor = renderer.processor(node['id'])
        params = spec.normalize(node['params'])
        size = 110.0
        plot = Plot(size, size, (-1.0, 1.0), (-1.0, 1.0))
        plot.draw.add_line((plot.x0, plot.py(0)), (plot.x1, plot.py(0)), text_col(0.15))
        plot.draw.add_line((plot.px(0), plot.y0), (plot.px(0), plot.y1), text_col(0.15))
        xs = np.linspace(-1.0, 1.0, 101)
        plot.line(xs, xs, text_col(0.25), 1.0)
        curve = None
        if processor is not None and hasattr(processor, 'curve'):
            try:
                curve = np.clip(processor.curve(xs), -1.5, 1.5)
            except Exception:
                curve = None
        elif node['effect'] == 'clipping':
            threshold = 10 ** (params['threshold_db'] / 20.0)
            curve = np.clip(xs, -threshold, threshold)
        elif node['effect'] == 'distortion':
            drive = 10 ** (params['drive_db'] / 20.0)
            curve = np.tanh(xs * drive)
        elif node['effect'] == 'bitcrush':
            levels = 2 ** float(params['bit_depth'])
            curve = np.round(xs * levels / 2) / (levels / 2)
        if curve is not None:
            plot.line(xs, curve, accent_col(), 2.0)
        plot.end()
        if plot.hovered:
            imgui.set_tooltip(tr('Transfer curve: input -> output'))
        imgui.same_line()
        imgui.begin_group()
        self.knob_row(owner, node, spec.params)
        imgui.end_group()

    def ui_vocoder(self, owner, node, spec, renderer, width):
        tr = self.tr
        meters = renderer.meters(node['id'])
        levels = meters.get('band_level_db', [])
        plot = Plot(max(260.0, min(width - 20, 420.0)), 90.0, (0.0, max(1, len(levels))), (-60.0, 0.0))
        plot.grid_y((-40, -20), fmt=lambda v: '%d' % v)
        for index, level in enumerate(levels):
            x_a, x_b = plot.px(index + 0.1), plot.px(index + 0.9)
            plot.draw.add_rect_filled((x_a, plot.py(max(-60.0, float(level)))), (x_b, plot.py(-60.0)), accent_col(0.85))
        plot.draw.add_text((plot.x0 + 4, plot.y0 + 2), text_col(0.6), tr('band levels of the voice (modulator)'))
        plot.end()
        if node['params'].get('carrier') == 'sidechain':
            imgui.text_disabled(tr('Carrier = the side-chain track chosen above in the insert'))
        self.knob_row(owner, node, spec.params)

    def ui_stereo(self, owner, node, spec, renderer, width):
        tr = self.tr
        tap = renderer.taps.get(node['id'])
        size = 110.0
        plot = Plot(size, size, (-1.0, 1.0), (-1.0, 1.0))
        plot.draw.add_line((plot.px(-1), plot.py(-1)), (plot.px(1), plot.py(1)), text_col(0.15))
        plot.draw.add_line((plot.px(-1), plot.py(1)), (plot.px(1), plot.py(-1)), text_col(0.15))
        if tap is not None:
            self._goniometer(plot, tap.recent('output', 1024))
        plot.end()
        if plot.hovered:
            imgui.set_tooltip(tr('Goniometer: vertical = mono, wide = stereo, horizontal = out of phase'))
        imgui.same_line()
        imgui.begin_group()
        self.knob_row(owner, node, spec.params)
        imgui.end_group()

    def _goniometer(self, plot, block):
        left, right = block[0], block[1]
        # rotate 45°: mid vertical, side horizontal
        mid = (left + right) * 0.7071
        side = (left - right) * 0.7071
        scale = 1.0 / max(1e-3, float(np.max(np.abs(block))) * 1.1)
        colour = accent_col(0.6)
        xs = side * scale
        ys = mid * scale
        for x, y in zip(xs[::2], ys[::2]):
            plot.draw.add_rect_filled((plot.px(x) - 1, plot.py(y) - 1), (plot.px(x) + 1, plot.py(y) + 1), colour)

    def ui_analyzer(self, owner, node, spec, renderer, width):
        tr = self.tr
        tap = renderer.taps.get(node['id'])
        half = max(240.0, (width - 40) / 2)
        # spectrum
        plot = Plot(half, 150.0, (20.0, 20000.0), (-90.0, 0.0), log_x=True)
        freqs, db = self.spectrum(node, renderer)
        self.draw_spectrum_in(plot, freqs, db, accent_col(0.45))
        plot.line(freqs, db, accent_col(0.9), 1.2)
        plot.grid_x(FREQ_GRID, fmt=freq_label)
        plot.grid_y((-60, -40, -20), fmt=lambda v: '%d' % v)
        plot.draw.add_text((plot.x0 + 4, plot.y0 + 2), text_col(0.6), tr('Spectrum'))
        plot.end()
        imgui.same_line()
        # goniometer
        plot = Plot(150.0, 150.0, (-1.0, 1.0), (-1.0, 1.0))
        plot.draw.add_line((plot.px(-1), plot.py(-1)), (plot.px(1), plot.py(1)), text_col(0.15))
        plot.draw.add_line((plot.px(-1), plot.py(1)), (plot.px(1), plot.py(-1)), text_col(0.15))
        if tap is not None:
            self._goniometer(plot, tap.recent('output', 1024))
        plot.draw.add_text((plot.x0 + 4, plot.y0 + 2), text_col(0.6), tr('Stereo field'))
        plot.end()
        imgui.same_line()
        # levels: peak, RMS, correlation
        imgui.begin_group()
        if tap is not None:
            block = tap.recent('output', 4096)
            rms = float(np.sqrt(np.mean(block ** 2)))
            left, right = block[0], block[1]
            denominator = float(np.sqrt(np.sum(left ** 2) * np.sum(right ** 2)))
            correlation = float(np.sum(left * right) / denominator) if denominator > 1e-9 else 0.0
            imgui.text(tr('Peak') + ' L %.1f dB  R %.1f dB' % (gain_to_db(tap.out_peak[0]), gain_to_db(tap.out_peak[1])))
            imgui.text(tr('RMS') + ' %.1f dB' % gain_to_db(rms))
            imgui.text(tr('Correlation') + ' %+.2f' % correlation)
            imgui.progress_bar((correlation + 1.0) / 2.0, (140, 0), '')
        imgui.end_group()

    def ui_dynamic_eq(self, owner, node, spec, renderer, width):
        tr = self.tr
        processor = renderer.processor(node['id'])
        meters = renderer.meters(node['id'])
        params = node['params']
        freqs = np.exp(np.linspace(math.log(20.0), math.log(20000.0), 200))
        plot = Plot(max(320.0, width - 20), 130.0, (20.0, 20000.0), (-24.0, 24.0), log_x=True)
        sfreqs, sdb = self.spectrum(node, renderer)
        self.draw_spectrum_in(plot, sfreqs, (sdb + 90.0) / 90.0 * 48.0 - 24.0)
        plot.grid_x(FREQ_GRID, fmt=freq_label)
        plot.grid_y((-12, -6, 0, 6, 12), fmt=lambda v: '%+d' % v)
        if processor is not None:
            try:
                plot.line(freqs, processor.response(freqs), accent_col(), 2.2)
            except Exception:
                pass
        reductions = meters.get('band_reduction_db', [])
        selected = self.eq_band.get(node['id'], 1)
        for n in range(1, 4):
            if not params.get(f'b{n}_on', False):
                continue
            freq = float(params.get(f'b{n}_freq', 1000.0))
            red = float(reductions[n - 1]) if n - 1 < len(reductions) else 0.0
            p_ = plot.point(freq, red + float(params.get(f'b{n}_static_db', 0.0)), 6.0 if n == selected else 5.0, warm(0.9 if n == selected else 0.55), text_col(0.9))
            plot.draw.add_text((p_[0] + 7, p_[1] - 8), text_col(0.8), '%d  %.1f dB' % (n, red))
        plot.end()
        if plot.hovered:
            imgui.set_tooltip(tr('Current response: the points show each band with its live gain change'))
        imgui.text(tr('Band'))
        for n in range(1, 4):
            imgui.same_line()
            if imgui.radio_button(f'{n}##dyneq{n}', selected == n):
                self.eq_band[node['id']] = n
        selected = self.eq_band.get(node['id'], 1)
        prefix = f'b{selected}_'
        imgui.begin_group()
        self.knob_row(owner, node, [p for p in spec.params if p.id.startswith(prefix)])
        imgui.end_group()
        imgui.same_line()
        red = float(reductions[selected - 1]) if selected - 1 < len(reductions) else 0.0
        reduction_meter(red, height=80.0, range_db=-24.0, label=tr('GR'))

    def ui_loudness(self, owner, node, spec, renderer, width):
        tr = self.tr
        meters = renderer.meters(node['id'])
        processor = renderer.processor(node['id'])
        history = self.gr_history[node['id']]
        history.append(float(meters.get('lufs_m', -100.0)))
        imgui.begin_group()
        for key, label in (('lufs_m', tr('Momentary')), ('lufs_s', tr('Short-term')), ('lufs_i', tr('Integrated'))):
            value = float(meters.get(key, -100.0))
            imgui.text('%-12s' % label)
            imgui.same_line(130)
            imgui.text_colored(cyui.vec(cyui.palette().warning if value > -100 else cyui.palette().textFaint), ('%6.1f LUFS' % value) if value > -100 else '   --  LUFS')
        imgui.text('%-12s' % tr('Peak'))
        imgui.same_line(130)
        imgui.text('%6.1f dBFS' % float(meters.get('peak_db', -100.0)))
        if imgui.button(tr('Reset integration')) and processor is not None:
            processor.reset_integration()
            history.clear()
        imgui.end_group()
        imgui.same_line()
        plot = Plot(max(260.0, width - 260), 110.0, (0, GR_HISTORY), (-40.0, 0.0))
        plot.grid_y((-30, -23, -14, -6), fmt=lambda v: '%d' % v)
        values = np.asarray(history)
        if values.size > 1:
            plot.line(np.arange(values.size), np.clip(values, -40.0, 0.0), accent_col(), 1.8)
        for target, name in ((-14.0, 'streaming'), (-23.0, 'broadcast')):
            y = plot.py(target)
            plot.draw.add_line((plot.x0, y), (plot.x1, y), warm(0.5), 1.0)
            plot.draw.add_text((plot.x1 - 70, y - 14), warm(0.8), '%d %s' % (int(target), name))
        plot.end()
        if plot.hovered:
            imgui.set_tooltip(tr('Momentary loudness over the last seconds; -14 LUFS streaming, -23 LUFS broadcast'))

    def ui_denoise(self, owner, node, spec, renderer, width):
        tr = self.tr
        meters = renderer.meters(node['id'])
        sr = float(self.document.samplerate)
        plot = Plot(max(320.0, width - 20), 140.0, (20.0, 20000.0), (-100.0, 0.0), log_x=True)
        spectrum = meters.get('spectrum_db')
        profile = meters.get('profile_db')
        if spectrum is not None and profile is not None:
            freqs = np.fft.rfftfreq(2048, 1.0 / sr)
            mask = (freqs >= 20.0) & (freqs <= 20000.0)
            plot.fill_under(freqs[mask][::2], np.asarray(spectrum)[mask][::2], accent_col(0.35))
            plot.line(freqs[mask][::2], np.asarray(profile)[mask][::2] + 20.0 * np.log10(max(0.5, float(node['params'].get('sensitivity', 1.5)))), warm(0.95), 1.8)
        plot.grid_x(FREQ_GRID, fmt=freq_label)
        plot.grid_y((-80, -60, -40, -20), fmt=lambda v: '%d' % v)
        plot.draw.add_text((plot.x0 + 4, plot.y0 + 2), text_col(0.7), tr('input spectrum (fill) and noise threshold (orange)') + '   %s %.1f dB' % (tr('reduction'), float(meters.get('reduction_db', 0.0))))
        plot.end()
        if node['params'].get('learn'):
            imgui.text_colored(cyui.vec(cyui.palette().warning), tr('Learning the noise profile: play a noise-only passage, then switch Learn off.'))
        self.knob_row(owner, node, spec.params)

    def ui_pattern(self, owner, node, spec, renderer, width):
        tr = self.tr
        meters = renderer.meters(node['id'])
        params = node['params']
        if 'pattern' in params:
            pattern = str(params.get('pattern', ''))
            steps = [c in '1xX' for c in pattern[:16]] + [False] * max(0, 16 - len(pattern))
            current = int(meters.get('step', -1))
            changed = False
            for index, on in enumerate(steps):
                if index:
                    imgui.same_line(0, 3)
                imgui.push_id(index)
                p = cyui.palette()
                ground = p.warning if index == current else (p.accent if on else p.bg3)
                imgui.push_style_color(imgui.Col_.button, cyui.vec(ground))
                imgui.push_style_color(imgui.Col_.text, cyui.vec(cyui.contrast_text(ground) if (on or index == current) else p.textDim))
                if imgui.button('%d' % (index + 1), (max(22.0, (width - 80) / 16 - 3), 26)):
                    steps[index] = not on
                    changed = True
                imgui.pop_style_color(2)
                imgui.pop_id()
            if changed:
                self._record(owner, tr('Pattern'))
                self._set_param(owner, node, 'pattern', ''.join('1' if on else '0' for on in steps))
            imgui.text_disabled(tr('Click the steps to open / close them; the orange step is playing.'))
        else:
            fraction = float(meters.get('step', 0.0))
            imgui.progress_bar(fraction, (max(200.0, width - 40), 14), tr('period'))
        self.knob_row(owner, node, [p for p in spec.params if p.id != 'pattern'])

    def ui_pitch(self, owner, node, spec, renderer, width):
        tr = self.tr
        meters = renderer.meters(node['id'])
        pitch = float(meters.get('pitch_hz', 0.0))
        note = str(meters.get('note', '-'))
        correction = float(meters.get('correction_st', 0.0))
        imgui.begin_group()
        imgui.text(tr('Detected') + ': ' + ('%.1f Hz' % pitch if pitch > 0 else tr('unvoiced')))
        imgui.text(tr('Target note') + ': ' + note)
        imgui.text(tr('Correction') + ': %+.2f st' % correction)
        imgui.end_group()
        imgui.same_line()
        plot = Plot(220.0, 60.0, (-1.0, 1.0), (0.0, 1.0))
        plot.draw.add_line((plot.px(0), plot.y0), (plot.px(0), plot.y1), text_col(0.3))
        x = plot.px(float(np.clip(correction, -1.0, 1.0)))
        plot.draw.add_rect_filled((min(x, plot.px(0)), plot.y0 + 8), (max(x, plot.px(0)), plot.y1 - 8), accent_col(0.85))
        plot.draw.add_text((plot.x0 + 4, plot.y0 + 2), text_col(0.6), '-1 st')
        plot.draw.add_text((plot.x1 - 34, plot.y0 + 2), text_col(0.6), '+1 st')
        plot.end()
        self.knob_row(owner, node, spec.params)

    # ------------------------------------------------------------------ presets
    def presets_row(self, node, spec):
        tr = self.tr
        folder = PRESETS / 'effects' / safe_name(spec.id)
        files = sorted(folder.glob('*.json')) if folder.is_dir() else []
        imgui.separator()
        row = Row()
        row.text(tr('Preset'), disabled=True)
        row.next(160)
        imgui.push_item_width(160)
        _, self.preset_name = imgui.input_text('##preset-name', self.preset_name)
        imgui.pop_item_width()
        if row.button('Save preset', tr):
            name = safe_name(self.preset_name or spec.name)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (name + '.json')).write_text(json.dumps({'effect': spec.id, 'name': self.preset_name or spec.name, 'params': spec.normalize(node['params'])}, indent=2), 'utf-8')
            self.preset_name = ''
        if files:
            labels = [f.stem for f in files]
            row.next(160)
            imgui.push_item_width(160)
            if imgui.begin_combo('##preset-load', tr('Load preset...')):
                for file in files:
                    if imgui.selectable(file.stem, False)[0]:
                        try:
                            value = json.loads(file.read_text('utf-8-sig'))
                            node['params'] = spec.normalize(value.get('params', {}))
                            self.document.touch()
                        except Exception as exc:
                            self.app.jobs.error = str(exc)
                imgui.end_combo()
            imgui.pop_item_width()
        if row.button('Reset', tr):
            node['params'] = spec.defaults()
            self.document.touch()

    # ------------------------------------------------------------------ VST3
    def draw_vst(self, owner, node, renderer, width):
        tr = self.tr
        self.header(node, renderer, width)
        error = renderer.errors.get(node['id'])
        if error:
            imgui.text_colored(cyui.vec(cyui.palette().error), error)
        description = node.get('_description') or {}
        imgui.text(f"{description.get('name') or node.get('pluginName') or Path(node['plugin']).stem}  {description.get('manufacturer', '')} {description.get('version', '')}")
        imgui.text_disabled(str(node['plugin']))
        latency = renderer.latency.get(node['id'], 0)
        if latency:
            imgui.same_line()
            imgui.text_disabled(tr('latency') + f' {latency}')
        row = Row()
        if row.button('Open plugin window', tr):
            self.app.open_insert_editor(owner, node)
        if row.button('Capture state', tr):
            processor = renderer.processor(node['id'])
            if processor is not None and hasattr(processor, 'capture'):
                snapshot = processor.capture()
                node['params'] = snapshot['params']
                node['state'] = snapshot['state']
                self.document.touch()
        if node.get('state'):
            row.text(tr('saved state') + f" ({len(node['state'])})", disabled=True)
        folder = PRESETS / 'plugins' / safe_name(node.get('pluginName') or Path(node['plugin']).stem)
        files = sorted(folder.glob('*.json')) if folder.is_dir() else []
        row.next(140)
        imgui.push_item_width(140)
        _, self.preset_name = imgui.input_text('##vst-preset-name', self.preset_name)
        imgui.pop_item_width()
        if row.button('Save preset', tr):
            processor = renderer.processor(node['id'])
            snapshot = processor.capture() if processor is not None and hasattr(processor, 'capture') else {'params': node.get('params', {}), 'state': node.get('state', '')}
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (safe_name(self.preset_name or 'preset') + '.json')).write_text(json.dumps({'plugin': node['plugin'], 'pluginName': node.get('pluginName', ''), **snapshot}, indent=2), 'utf-8')
            self.preset_name = ''
        if files:
            row.next(150)
            imgui.push_item_width(150)
            if imgui.begin_combo('##vst-preset-load', tr('Load preset...')):
                for file in files:
                    if imgui.selectable(file.stem, False)[0]:
                        try:
                            value = json.loads(file.read_text('utf-8-sig'))
                            node['params'] = dict(value.get('params', {}))
                            node['state'] = value.get('state', '')
                            self.document.touch()
                        except Exception as exc:
                            self.app.jobs.error = str(exc)
                imgui.end_combo()
            imgui.pop_item_width()
        imgui.separator()
        imgui.push_item_width(min(320.0, max(180.0, width - 220)))
        parameters = description.get('parameters', {})
        shown = 0
        for name, info in parameters.items():
            if shown >= 64:
                imgui.text_disabled(tr('... more parameters in the plugin window'))
                break
            shown += 1
            imgui.push_id(name)
            label = str(info.get('label') or name)
            if info.get('normalized'):
                label += ' (0–1)'
            current = node['params'].get(name, info.get('value'))
            key = node['id'] + '.' + name
            lane = owner.automation.get(key)
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
                changed, value = imgui.slider_float(label + (' ' + info['units'] if info.get('units') else '') + ('  (A)' if lane and lane.active else ''), cur, lo, hi, '%.3f')
            if imgui.is_item_activated():
                self._record(owner, label)
            if changed:
                self._set_param(owner, node, name, value)
            self._lane_menu(owner, node, name, label)
            imgui.pop_id()
        imgui.pop_item_width()
        if not parameters:
            imgui.text_disabled(tr('This plugin exposes no parameters'))
