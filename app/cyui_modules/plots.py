from dataclasses import dataclass, field
from math import log, exp, isfinite, nan
from .common import Range, ui, zoom_range, take_wheel, wheel_taken
from .canvas import Canvas, CanvasState


@dataclass
class Axis:
    view: Range = field(default_factory=Range)
    logarithmic: bool = False

    def fraction(self, value):
        if not self.view.valid or not isfinite(value):
            return nan
        if self.logarithmic:
            return log(value / self.view.minimum) / log(self.view.maximum / self.view.minimum) if value > 0 and self.view.minimum > 0 else nan
        return (value - self.view.minimum) / self.view.span

    def value(self, fraction):
        try:
            return self.view.minimum * (self.view.maximum / self.view.minimum) ** fraction if self.logarithmic and self.view.minimum > 0 else self.view.minimum + fraction * self.view.span
        except (OverflowError, ZeroDivisionError):
            return nan


def _navigate(axis, shift, anchor, factor):
    """Pan by shift (a fraction of the view) and zoom by factor around anchor, like C++.

    A log axis pans and zooms in log space only while its range is positive; otherwise it
    moves like a linear one. A result that is not a finite, non-empty range is rejected.
    """
    view = axis.view
    try:
        if axis.logarithmic and view.minimum > 0 and view.maximum > 0:
            low, high = log(view.minimum), log(view.maximum)
            delta = shift * (high - low)
            moved = Range(low + delta, high + delta)
            if anchor > 0 and isfinite(anchor):
                moved = zoom_range(moved, log(anchor), factor)
            if not (abs(moved.minimum) <= 700 and abs(moved.maximum) <= 700):
                return
            result = Range(exp(moved.minimum), exp(moved.maximum))
        else:
            delta = shift * view.span
            result = zoom_range(Range(view.minimum + delta, view.maximum + delta), anchor, factor)
    except (OverflowError, ValueError, ZeroDivisionError):
        return
    if result.valid and (not axis.logarithmic or view.minimum <= 0 or result.minimum > 0):
        axis.view = result


@dataclass
class PlotState:
    x: Axis = field(default_factory=Axis)
    y: Axis = field(default_factory=Axis)
    dragging: bool = False


@dataclass
class Series:
    id: int
    points: object
    label: str = ''
    style: str = 'line'
    color_index: int = 0


def reduce_plot(points, budget):
    if budget < 4 or not len(points):
        return []
    if len(points) <= budget:
        return list(points)
    buckets = max(1, (budget - 2) // 3)
    out = [points[0]]
    for b in range(buckets):
        a, end = 1 + b * (len(points) - 2) // buckets, 1 + (b + 1) * (len(points) - 2) // buckets
        if any(not all(map(isfinite, p)) for p in points[a:end]):
            out.append((points[a][0], nan))
            continue
        lo = min(range(a, end), key=lambda k: points[k][1])
        hi = max(range(a, end), key=lambda k: points[k][1])
        out.append(points[min(lo, hi)])
        if lo != hi:
            out.append(points[max(lo, hi)])
    return out + [points[-1]]


def histogram(values, view, bins):
    if not view.valid or not 0 < bins <= 1000000:
        return []
    out = [0] * bins
    for value in values:
        if isfinite(value) and view.contains(value):
            out[min(bins - 1, int((value - view.minimum) / view.span * bins))] += 1
    return out


def plot(identifier, state, series, size=(0, 240), navigation=True, max_points=65536, axes=True, legend=True, format_x=None, format_y=None):
    i, c = ui()
    with Canvas(identifier, CanvasState(), size, grid=False, navigation=False) as frame:
        p, draw, io = c.palette(), frame.draw, i.get_io()
        mouse = (state.x.value((io.mouse_pos.x - frame.top[0]) / frame.size[0]), state.y.value(1 - (io.mouse_pos.y - frame.top[1]) / frame.size[1]))
        if navigation:
            if frame.hovered and i.is_mouse_clicked(2):
                state.dragging = True
            if not i.is_mouse_down(2):
                state.dragging = False
            if state.dragging:
                _navigate(state.x, -io.mouse_delta.x / frame.size[0], mouse[0], 1)
                _navigate(state.y, io.mouse_delta.y / frame.size[1], mouse[1], 1)
            if frame.hovered and io.mouse_wheel and not wheel_taken():
                for axis, anchor in ((state.x, mouse[0]), (state.y, mouse[1])) if io.key_ctrl else ((state.x, mouse[0]),):
                    _navigate(axis, 0, anchor, exp(-io.mouse_wheel * .15))
                take_wheel()
        for n in range(1, 4):
            x, y = frame.top[0] + frame.size[0] * n / 4, frame.top[1] + frame.size[1] * n / 4
            draw.add_line((x, frame.top[1]), (x, frame.bottom[1]), p.grid, c.dp(1))
            draw.add_line((frame.top[0], y), (frame.bottom[0], y), p.grid, c.dp(1))
        skipped = []
        for line in series:
            if len(line.points) > max_points:
                skipped.append(line.id)
                continue
            previous = None
            color = c.categorical(line.color_index)
            for x, y in line.points:
                fx, fy = state.x.fraction(x), state.y.fraction(y)
                if not isfinite(fx) or not isfinite(fy):
                    previous = None
                    continue
                q = (frame.top[0] + fx * frame.size[0], frame.bottom[1] - fy * frame.size[1])
                if line.style == 'points':
                    draw.add_circle_filled(q, c.dp(2.5), color)
                elif line.style == 'bars':
                    width = max(c.dp(1), frame.size[0] / max(1, len(line.points)) * .8)
                    base = frame.bottom[1] if state.y.logarithmic else frame.bottom[1] - state.y.fraction(0) * frame.size[1]
                    draw.add_rect_filled((q[0] - width / 2, min(base, q[1])), (q[0] + width / 2, max(base, q[1])), color)
                elif previous:
                    if line.style == 'step':
                        draw.add_line(previous, (q[0], previous[1]), color, c.dp(1.5))
                        draw.add_line((q[0], previous[1]), q, color, c.dp(1.5))
                    else:
                        draw.add_line(previous, q, color, c.dp(1.5))
                previous = q
        def axis_label(position, text):
            extent = i.calc_text_size(text)
            draw.add_rect_filled((position[0]-c.dp(2), position[1]), (position[0]+extent.x+c.dp(2), position[1]+extent.y), c.alpha(p.bg0, .85))
            draw.add_text(position, p.textDim, text)
        if axes:
            for tick in range(5):
                part = tick/4
                text = format_x(state.x.value(part)) if format_x else f'{state.x.value(part):.4g}'
                width = i.calc_text_size(text).x
                axis_label((max(frame.top[0]+c.dp(3), min(frame.bottom[0]-width-c.dp(3), frame.top[0]+frame.size[0]*part-width*.5)), frame.bottom[1]-i.get_font_size()-c.dp(3)), text)
                if tick:
                    text = format_y(state.y.value(part)) if format_y else f'{state.y.value(part):.4g}'
                    axis_label((frame.top[0]+c.dp(4), max(frame.top[1]+c.dp(3), min(frame.bottom[1]-i.get_font_size()-c.dp(3), frame.bottom[1]-frame.size[1]*part-i.get_font_size()*.5))), text)
        if legend:
            x = frame.top[0]+c.dp(70)
            for line in series:
                if not line.label:
                    continue
                width = i.calc_text_size(line.label).x+c.dp(24)
                if x+width > frame.bottom[0]:
                    break
                y = frame.top[1]+c.dp(5)
                draw.add_rect_filled((x, y), (x+width, y+i.get_font_size()), c.alpha(p.bg0, .85))
                draw.add_circle_filled((x+c.dp(4), y+i.get_font_size()*.5), c.dp(3), c.categorical(line.color_index))
                draw.add_text((x+c.dp(12), y), p.text, line.label)
                x += width
        if frame.hovered:
            draw.add_line((io.mouse_pos.x, frame.top[1]), (io.mouse_pos.x, frame.bottom[1]), p.textFaint, c.dp(1))
            i.set_tooltip(f'{mouse[0]:.6g}, {mouse[1]:.6g}')
        return {'hovered': frame.hovered, 'mouse': mouse, 'skipped': skipped}


def heatmap(identifier, values, columns, rows, view, size=(0, 180)):
    i, c = ui()
    with Canvas(identifier, CanvasState(), size, grid=False, navigation=False) as frame:
        if columns <= 0 or rows <= 0 or len(values) < columns * rows or not view.valid:
            return None
        for y in range(0, rows, max(1, (rows+255) // 256)):
            for x in range(0, columns, max(1, (columns+255) // 256)):
                value = values[y * columns + x]
                color = c.mix(c.palette().bg0, c.palette().accent, max(0, min(1, (value - view.minimum) / view.span))) if isfinite(value) else c.palette().bg2
                frame.draw.add_rect_filled((frame.top[0] + x / columns * frame.size[0], frame.top[1] + y / rows * frame.size[1]), (frame.top[0] + min(columns, x + max(1, (columns+255) // 256)) / columns * frame.size[0], frame.top[1] + min(rows, y + max(1, (rows+255) // 256)) / rows * frame.size[1]), color)
        if frame.hovered:
            mouse = i.get_io().mouse_pos
            x = max(0, min(columns - 1, int((mouse.x - frame.top[0]) / frame.size[0] * columns)))
            y = max(0, min(rows - 1, int((mouse.y - frame.top[1]) / frame.size[1] * rows)))
            i.set_tooltip(f'[{x}, {y}] {values[y * columns + x]}')
            return x, y, i.is_mouse_clicked(0)
