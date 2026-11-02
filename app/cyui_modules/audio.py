"""Audio controls use the same normalized ranges, modifiers and dB meter mapping as C++."""
from dataclasses import dataclass, field
from math import log, log10, log1p, exp, expm1, sin, cos, pi, isfinite
from .common import ui, snap, take_wheel


def meter_position(db):
    return 0. if db <= -70 else max(0., min(1., exp((db-6)/26)))


def _arc(draw, center, radius, a, b, color, thickness):
    if abs(b-a) > .001:
        draw.path_arc_to(center, radius, min(a, b), max(a, b), 32)
        draw.path_stroke(color, thickness=thickness)


def knob(identifier, value, minimum, maximum, default, diameter=34., label='', logarithmic=False, bipolar=False, integer=False, steps=0, modulation=None):
    i, c = ui()
    p, io = c.palette(), i.get_io()
    i.push_id(identifier)
    origin = i.get_cursor_screen_pos()
    width, height = c.dp(diameter+12), c.dp(diameter)
    i.invisible_button('##knob', (width, height+i.get_font_size()))
    hovered, active = i.is_item_hovered(), i.is_item_active()
    valid = isfinite(minimum) and isfinite(maximum) and maximum > minimum
    logarithmic = logarithmic and valid and minimum > 0
    def fraction(v):
        # A NaN, infinite or (on a log knob) non-positive value sits at the start, as in C++.
        if not valid or not isfinite(v) or (logarithmic and v <= 0):
            return 0.
        return max(0., min(1., log(v/minimum)/log(maximum/minimum) if logarithmic else (v-minimum)/(maximum-minimum)))
    t, changed = fraction(value), False
    speed = .15 if io.key_ctrl else 4. if io.key_shift else 1.
    # The unrounded position a drag has reached, so slow moves add up to a step.
    storage, held_key = i.get_state_storage(), i.get_id('##held')
    if i.is_item_activated():
        storage.set_float(held_key, t)
    if active and io.mouse_delta.y:
        held = max(0., min(1., storage.get_float(held_key, t)-io.mouse_delta.y*.0055*speed/max(.5, i.get_style().font_scale_dpi)))
        storage.set_float(held_key, held)
        t = snap(held, 1/steps) if steps else held
        changed = True
    if hovered and io.mouse_wheel:
        t = max(0., min(1., t+io.mouse_wheel*(1/steps if steps else .02*speed)))
        take_wheel()
        changed = True
    if hovered and i.is_mouse_double_clicked(0):
        t, changed = fraction(default), True
        storage.set_float(held_key, t)
    if changed and valid:
        if steps:
            t = snap(t, 1/steps)
        value = minimum*(maximum/minimum)**t if logarithmic else minimum+(maximum-minimum)*t
        if integer:
            value = snap(value, 1)
        value = max(minimum, min(maximum, value))
        t = fraction(value)
    else:
        changed = False
    d, center, radius = i.get_window_draw_list(), (origin.x+width/2, origin.y+height/2), height/2-c.dp(2)
    start, sweep, thickness = pi*.75, pi*1.5, max(c.dp(2), height*.095)
    _arc(d, center, radius, start, start+sweep, p.bg5, thickness)
    _arc(d, center, radius, start+sweep*.5 if bipolar else start, start+sweep*t, p.accent, thickness)
    angle = start+sweep*t
    d.add_line(center, (center[0]+cos(angle)*radius*.75, center[1]+sin(angle)*radius*.75), p.text, c.dp(1.5))
    if modulation is not None:
        angle = start+sweep*max(0, min(1, modulation))
        d.add_circle_filled((center[0]+cos(angle)*(radius+c.dp(3)), center[1]+sin(angle)*(radius+c.dp(3))), c.dp(2), p.info)
    text = f'{value:.3g}' if hovered or active else c.tr(label)
    d.add_text((origin.x, origin.y+height), p.text if hovered else p.textDim, text)
    i.pop_id()
    return changed, value


def fader_position(db, minimum=-70., maximum=6.):
    """Fader travel (0..1) for a gain: the meter's dB curve, from minimum (0) to maximum (1).

    Continuous at minimum, unlike meter_position (which jumps from 0 to 0.054 at -70 dB),
    so a slow drag leaves the bottom; the top follows maximum instead of stopping at +6 dB.
    expm1/log1p keep it exact for tiny ranges, as in C++.
    """
    if not (isfinite(minimum) and isfinite(maximum)) or maximum <= minimum or db != db:
        return 0.
    drop = expm1((minimum-maximum)/26)
    return max(0., min(1., 1-expm1((max(minimum, min(maximum, db))-maximum)/26)/drop))


def fader_gain(position, minimum=-70., maximum=6.):
    """The inverse of fader_position; an empty range gives minimum."""
    if not (isfinite(minimum) and isfinite(maximum)) or maximum <= minimum or position != position:
        return minimum
    drop = expm1((minimum-maximum)/26)
    t = max(0., min(1., position))
    return max(minimum, min(maximum, maximum+26*log1p(drop*(1-t))))


def fader(identifier, value, minimum=-70., maximum=6., size=(30, 150)):
    i, c = ui()
    p, io = c.palette(), i.get_io()
    size = max(c.dp(8), c.dp(size[0])), max(c.dp(20), c.dp(size[1]))
    origin = i.get_cursor_screen_pos()
    i.invisible_button(identifier, size)
    changed, travel = False, max(c.dp(2), size[1]-c.dp(14))
    speed = .15 if io.key_ctrl else 4. if io.key_shift else 1.
    # The drag keeps its own float position: re-deriving it from the dB value every frame
    # loses the small moves of a slow drag.
    storage, key = i.get_state_storage(), i.get_item_id()
    if i.is_item_activated():
        storage.set_float(key, fader_position(value, minimum, maximum))
    if i.is_item_active() and io.mouse_delta.y:
        part = max(0., min(1., storage.get_float(key, fader_position(value, minimum, maximum))-io.mouse_delta.y/travel*speed))
        storage.set_float(key, part)
        value, changed = fader_gain(part, minimum, maximum), True
    if i.is_item_hovered() and io.mouse_wheel:
        value, changed = max(minimum, min(maximum, (value if isfinite(value) else minimum)+io.mouse_wheel*speed)), True
        take_wheel()
    if i.is_item_hovered() and i.is_mouse_double_clicked(0):
        value, changed = max(minimum, min(maximum, 0)), True
    d, center = i.get_window_draw_list(), origin.x+size[0]/2
    d.add_rect_filled((center-c.dp(2), origin.y), (center+c.dp(2), origin.y+size[1]), p.bg0)
    y = origin.y+c.dp(7)+travel*(1-fader_position(value, minimum, maximum))
    d.add_rect_filled((origin.x, y-c.dp(4)), (origin.x+size[0], y+c.dp(4)), p.accent, c.dp(2))
    return changed, value


@dataclass
class MeterState:
    hold: list = field(default_factory=lambda: [-120., -120.])
    time: float = 0.


def meter(identifier, peaks, rms, size=(16, 150), vertical=True, state=None):
    """Peak (faint) and RMS bars for one or two channels of linear gains, with a peak hold.

    The hold decays at 18 dB/s; without a state it is kept per widget in ImGui's storage.
    """
    i, c = ui()
    size = tuple(c.dp(x) for x in size)
    origin = i.get_cursor_screen_pos()
    i.invisible_button(identifier, size)
    d, p = i.get_window_draw_list(), c.palette()
    gains = list(peaks)[:2] or [0.]
    rms = list(rms)
    channels = len(gains)
    storage = keys = None
    if state is None:
        storage, keys = i.get_state_storage(), [i.get_id(f'{identifier}##hold{n}') for n in range(3)]
        state = MeterState([storage.get_float(keys[0], -120.), storage.get_float(keys[1], -120.)], storage.get_float(keys[2], 0.))
    now = i.get_time()
    elapsed = max(0., now-state.time)
    state.time = now
    d.add_rect_filled(origin, (origin.x+size[0], origin.y+size[1]), p.bg0)
    def bar(channel, part, color, thickness=0.):
        if vertical:
            left, right = origin.x+size[0]*channel/channels, origin.x+size[0]*(channel+1)/channels-c.dp(1)
            y = origin.y+size[1]*(1-part)
            if thickness:
                d.add_line((left, y), (right, y), color, thickness)
            else:
                d.add_rect_filled((left, y), (right, origin.y+size[1]), color)
        else:
            top, bottom = origin.y+size[1]*channel/channels, origin.y+size[1]*(channel+1)/channels
            x = origin.x+size[0]*part
            if thickness:
                d.add_line((x, top), (x, bottom), color, thickness)
            else:
                d.add_rect_filled((origin.x, top), (x, bottom), color)
    for channel in range(channels):
        gain = gains[channel]
        db = max(-120., 20*log10(gain)) if gain > 0 and isfinite(gain) else -120.
        hold = state.hold[channel] if isfinite(state.hold[channel]) else -120.
        state.hold[channel] = max(db, hold-elapsed*18)
        for value, alpha in ((gain, .45), (rms[channel] if channel < len(rms) else gain, 1.)):
            part = meter_position(20*log10(value)) if value > 0 and isfinite(value) else 0.
            color = c.alpha(p.error if db >= 0 else p.warning if db > -3 else p.success, alpha)
            bar(channel, part, color)
        held = meter_position(state.hold[channel])
        if held > 0:
            bar(channel, held, c.alpha(p.error if state.hold[channel] > -.1 else p.text, .8), c.dp(1))
    if storage is not None:
        for key, value in zip(keys, (state.hold[0], state.hold[1], state.time)):
            storage.set_float(key, value)
