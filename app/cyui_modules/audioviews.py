from dataclasses import dataclass, field
from math import isfinite, exp, nan
from .common import Range, ui, zoom_range, take_wheel, wheel_taken
from .canvas import Canvas, CanvasState
from .plots import plot


def make_peaks(samples, columns):
    if not len(samples) or columns <= 0:
        return []
    columns = min(columns, len(samples))
    result = []
    for x in range(columns):
        values = [v for v in samples[x*len(samples)//columns:(x+1)*len(samples)//columns] if isfinite(v)]
        result.append((min(values), max(values)) if values else (nan, nan))
    return result


@dataclass
class WaveformState:
    view: Range = field(default_factory=Range)
    selection: Range = field(default_factory=lambda: Range(0, 0))
    anchor: float = 0
    selecting: bool = False
    panning: bool = False


def waveform(identifier, state, channels, coverage, playhead=0., size=(0, 180)):
    i, c = ui()
    result = {'seek': None, 'selection_changed': False}
    with Canvas(identifier, CanvasState(), size, False, False) as f:
        io, p, d = i.get_io(), c.palette(), f.draw
        mouse = state.view.minimum+(io.mouse_pos.x-f.top[0])/f.size[0]*state.view.span
        def x(t):
            return f.top[0]+(t-state.view.minimum)/state.view.span*f.size[0]
        if f.hovered and io.mouse_wheel and not wheel_taken():
            if io.key_shift:
                delta = -io.mouse_wheel*state.view.span*.1
                moved = Range(state.view.minimum+delta, state.view.maximum+delta)
                state.view = moved if moved.valid else state.view
            else:
                state.view = zoom_range(state.view, mouse, exp(-io.mouse_wheel*.15))
            take_wheel()
        if f.hovered and i.is_mouse_clicked(2):
            state.panning = True
        if not i.is_mouse_down(2):
            state.panning = False
        if state.panning:
            delta = -io.mouse_delta.x/f.size[0]*state.view.span
            moved = Range(state.view.minimum+delta, state.view.maximum+delta)
            state.view = moved if moved.valid else state.view
        if f.hovered and i.is_mouse_clicked(0):
            state.selection, state.anchor, state.selecting, result['seek'] = Range(mouse, mouse), mouse, True, mouse
        if state.selecting:
            state.selection = Range(min(state.anchor, mouse), max(state.anchor, mouse))
            result['selection_changed'] = True
            if not i.is_mouse_down(0):
                state.selecting = False
        if f.hovered and i.is_mouse_double_clicked(0):
            state.selection, state.selecting = Range(0, 0), False
        if coverage.valid:
            for channel, peaks in enumerate(channels):
                if not len(peaks):
                    continue
                height = f.size[1]/len(channels)
                mid = f.top[1]+height*(channel+.5)
                for pixel in range(min(8192, max(1, int(f.size[0])))):
                    t = state.view.minimum+(pixel+.5)/f.size[0]*state.view.span
                    if coverage.contains(t):
                        low, high = peaks[min(len(peaks)-1, int((t-coverage.minimum)/coverage.span*len(peaks)))]
                        if isfinite(low) and isfinite(high):
                            d.add_line((f.top[0]+pixel, mid-max(-1, min(1, high))*height*.45), (f.top[0]+pixel, mid-max(-1, min(1, low))*height*.45), p.info, c.dp(1))
        if state.selection.minimum != state.selection.maximum:
            d.add_rect_filled((x(min(state.selection.minimum, state.selection.maximum)), f.top[1]), (x(max(state.selection.minimum, state.selection.maximum)), f.bottom[1]), p.selection)
        d.add_line((x(playhead), f.top[1]), (x(playhead), f.bottom[1]), p.accent, c.dp(2))
    return result


def spectrum(identifier, state, series, size=(0, 240)):
    state.x.logarithmic = True
    if not state.x.view.valid or state.x.view.minimum <= 0:
        state.x.view = Range(20, 20000)
    return plot(identifier, state, series, size)


def oscilloscope(identifier, state, series, size=(0, 200)):
    state.x.logarithmic = state.y.logarithmic = False
    return plot(identifier, state, series, size)


def stereo_scope(identifier, state, series, size=(0, 200)):
    # Square, with one symmetric extent on both axes: wheel zoom scales it, the centre stays at 0.
    i, c = ui()
    state.x.logarithmic = state.y.logarithmic = False
    avail = i.get_content_region_avail()
    side = max(c.dp(1), min(size[0] if size[0] > 0 else avail.x+size[0], size[1] if size[1] > 0 else avail.y+size[1]))
    extent = state.x.view.span*.5 if state.x.view.valid else 1.
    state.x.view, state.y.view = Range(-extent, extent), Range(-extent, extent)
    result = plot(identifier, state, series, (side, side))
    zoomed = state.x.view.span*.5 if state.x.view.valid else extent
    state.x.view, state.y.view = Range(-zoomed, zoomed), Range(-zoomed, zoomed)
    return result
