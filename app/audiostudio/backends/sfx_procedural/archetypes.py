"""Procedural text-to-sound engine (ported verbatim from the reference sfx.py).

A prompt is normalised, matched against an explicit archetype catalogue and
turned into a deterministic synthesis recipe. The recipe is then rendered with
the primitives of synth.py. There is no model and no training data here: the
mapping from words to synthesis parameters is the hand-written table below.
"""
import hashlib
import re
import unicodedata
import numpy as np
from . import synth as dsp

MAX_LAYERS = 3
MIN_DURATION = 0.2
MAX_DURATION = 30.0
SAMPLE_RATES = (16000, 22050, 24000, 44100, 48000)


def _n(seconds, rate):
    return max(int(round(seconds*rate)), 16)


# --------------------------------------------------------------------------
# Renderers. Each returns mono float32 audio of `seconds`; `m` holds modifiers.
# --------------------------------------------------------------------------

def _explosion(rng, rate, seconds, m):
    n = _n(seconds, rate)
    body = dsp.pink(rng, n, rate)*dsp.exp_decay(n, rate, seconds*0.30)
    body = dsp.sweep_lowpass(body, rate, dsp.line([(0, 4200), (0.12, 1500), (1, 170)], n)*m['bright'])
    sub = dsp.osc(dsp.line([(0, 95), (1, 24)], n)*m['pitch'], rate, 'sine')*dsp.exp_decay(n, rate, seconds*0.22)
    crack = dsp.highpass(dsp.white(rng, n), rate, 2200)*dsp.exp_decay(n, rate, 0.012)
    return body*1.0+sub*0.95+crack*0.30


def _thunder(rng, rate, seconds, m):
    n = _n(seconds, rate)
    swell = 0.25+0.75*np.abs(dsp.smooth_random(rng, n, rate, 1.3))
    body = dsp.sweep_lowpass(dsp.brown(rng, n, rate)*swell, rate,
                             dsp.line([(0, 900), (0.3, 430), (1, 150)], n)*m['bright'])
    body *= dsp.line([(0, 1.0), (0.2, 0.9), (1, 0.0)], n)**1.4
    crack = dsp.highpass(dsp.white(rng, n), rate, 1400)*dsp.exp_decay(n, rate, 0.05)
    return body*1.6+crack*0.22


def _laser(rng, rate, seconds, m):
    n = _n(seconds, rate)
    freq = dsp.line([(0, 2600), (0.12, 1400), (1, 170)], n)*m['pitch']
    tone = dsp.osc(freq, rate, 'saw' if m['metallic'] else 'sine')+0.45*dsp.osc(freq*1.5, rate, 'sine')
    return dsp.lowpass(tone, rate, rate*0.42)*dsp.ad(n, rate, 0.002, seconds*0.30)


def _electric(rng, rate, seconds, m):
    n = _n(seconds, rate)
    crackle = dsp.bandpass(dsp.white(rng, n), rate, 800*m['pitch'], 7500*m['bright'])
    opening = (dsp.smooth_random(rng, n, rate, 110*m['rate']) > 0.05).astype(np.float32)
    tone = dsp.osc(dsp.line([(0, 1700), (1, 850)], n)*m['pitch'], rate, 'square')*0.28
    return dsp.lowpass((crackle+tone)*opening, rate, rate*0.42)*dsp.ad(n, rate, 0.001, seconds*0.35)


def _beep(rng, rate, seconds, m):
    n = _n(seconds, rate)
    freq = np.full(n, 880.0)*m['pitch']
    tone = dsp.osc(freq, rate, 'square' if m['metallic'] else 'sine')+0.25*dsp.osc(freq*2.0, rate, 'sine')
    return dsp.lowpass(tone, rate, rate*0.42)*dsp.ad(n, rate, 0.005, seconds*0.30)


def _alarm(rng, rate, seconds, m):
    n = _n(seconds, rate)
    period = 0.62/m['rate']
    high = dsp.gate(n, rate, period, 0.5)
    tone = dsp.osc(np.full(n, 740.0)*m['pitch'], rate, 'square')*high
    tone += dsp.osc(np.full(n, 554.0)*m['pitch'], rate, 'square')*(1.0-high)
    return dsp.lowpass(tone, rate, 4200*m['bright'])*0.8


def _siren(rng, rate, seconds, m):
    n = _n(seconds, rate)
    ticks = np.arange(n)/rate
    freq = (720.0+360.0*np.sin(dsp.TWO_PI*ticks*0.42*m['rate']))*m['pitch']
    return (dsp.osc(freq, rate, 'sine')+0.45*dsp.osc(freq*2.0, rate, 'sine')+0.2*dsp.osc(freq*3.0, rate, 'sine'))*0.7


def _rain(rng, rate, seconds, m):
    n = _n(seconds, rate)
    bed = dsp.bandpass(dsp.white(rng, n), rate, 650/m['pitch'], 8500*m['bright'])
    bed *= 0.8+0.2*dsp.smooth_random(rng, n, rate, 5.0)
    click = dsp.highpass(dsp.white(rng, 384), rate, 3200)*dsp.exp_decay(384, rate, 0.004)
    drops = dsp.sparse(rng, n, dsp.poisson_positions(rng, n, rate, 55*m['rate']), click)
    return bed*1.0+drops*0.45


def _wind(rng, rate, seconds, m):
    n = _n(seconds, rate)
    cutoff = (300.0+950.0*(0.5+0.5*dsp.smooth_random(rng, n, rate, 0.33*m['rate'])))*m['bright']
    body = dsp.sweep_lowpass(dsp.brown(rng, n, rate), rate, cutoff)
    body *= 0.5+0.5*(0.5+0.5*dsp.smooth_random(rng, n, rate, 0.2))
    whistle = dsp.osc((620.0+240.0*dsp.smooth_random(rng, n, rate, 0.28))*m['pitch'], rate, 'sine')
    return body+whistle*0.05*(0.5+0.5*dsp.smooth_random(rng, n, rate, 0.14))


def _ocean(rng, rate, seconds, m):
    n = _n(seconds, rate)
    ticks = np.arange(n)/rate
    swell = (0.5+0.5*np.sin(dsp.TWO_PI*ticks/max(5.5/m['rate'], 0.4)-1.2))**2.0
    body = dsp.sweep_lowpass(dsp.pink(rng, n, rate), rate, (400.0+2400.0*swell)*m['bright'])
    foam = dsp.bandpass(dsp.white(rng, n), rate, 2000, 9000*m['bright'])*swell**3
    return body*(0.35+0.65*swell)*1.2+foam*0.35


def _fire(rng, rate, seconds, m):
    n = _n(seconds, rate)
    bed = dsp.lowpass(dsp.pink(rng, n, rate), rate, 900*m['bright'])*(0.6+0.4*dsp.smooth_random(rng, n, rate, 2.0))
    snap = dsp.bandpass(dsp.white(rng, 512), rate, 1800, 9000)*dsp.exp_decay(512, rate, 0.006)
    crackle = dsp.sparse(rng, n, dsp.poisson_positions(rng, n, rate, 22*m['rate']), snap)
    return bed*0.5+crackle*1.6


def _water_drop(rng, rate, seconds, m):
    n = _n(seconds, rate)
    freq = dsp.line([(0, 1600), (0.3, 780), (1, 430)], n)*m['pitch']
    tone = dsp.osc(freq, rate, 'sine')*dsp.ad(n, rate, 0.002, seconds*0.22)
    tap = dsp.highpass(dsp.white(rng, n), rate, 4000)*dsp.exp_decay(n, rate, 0.003)
    return tone*0.9+tap*0.25


def _bubble(rng, rate, seconds, m):
    n = _n(seconds, rate)
    out = np.zeros(n, dtype=np.float32)
    for index in range(max(int(4*m['rate']), 1)):
        length = _n(min(0.09, seconds), rate)
        freq = dsp.line([(0, rng.uniform(320, 620)), (1, rng.uniform(900, 1500))], length)*m['pitch']
        dsp.place(out, dsp.osc(freq, rate, 'sine')*dsp.ad(length, rate, 0.002, 0.02), int(rng.uniform(0, n)))
    return out


def _footsteps(rng, rate, seconds, m):
    n = _n(seconds, rate)
    length = _n(0.14, rate)
    thud = dsp.lowpass(dsp.white(rng, length), rate, 700/m['pitch'])*dsp.ad(length, rate, 0.002, 0.028)
    scuff = dsp.bandpass(dsp.white(rng, length), rate, 1800, 6500*m['bright'])*dsp.ad(length, rate, 0.004, 0.02)
    return dsp.sparse(rng, n, dsp.periodic_positions(n, rate, 0.56/m['rate'], 0.06, rng), thud*1.0+scuff*0.35)


def _heartbeat(rng, rate, seconds, m):
    n = _n(seconds, rate)
    length = _n(0.30, rate)
    thump = dsp.osc(dsp.line([(0, 72), (1, 34)], length)*m['pitch'], rate, 'sine')*dsp.ad(length, rate, 0.006, 0.055)
    period = 0.92/m['rate']
    first = dsp.periodic_positions(n, rate, period)
    second = np.clip(first+int(0.29*period*rate), 0, max(n-1, 0))
    return dsp.sparse(rng, n, first, thump, np.ones(first.size))+dsp.sparse(rng, n, second, thump*0.6, np.ones(second.size))


def _engine(rng, rate, seconds, m):
    n = _n(seconds, rate)
    firing = (52.0*m['rate'])*(1.0+0.05*dsp.smooth_random(rng, n, rate, 0.7))
    body = dsp.osc(firing*m['pitch'], rate, 'saw')+0.5*dsp.osc(firing*2.0*m['pitch'], rate, 'saw')
    body = dsp.lowpass(body, rate, 1100*m['bright'])
    body *= 0.65+0.35*dsp.gate(n, rate, 1.0/max(firing.mean(), 1.0), 0.55, 900.0)
    hiss = dsp.bandpass(dsp.white(rng, n), rate, 900, 5200*m['bright'])*0.12
    return body*0.8+hiss


def _helicopter(rng, rate, seconds, m):
    n = _n(seconds, rate)
    length = _n(0.09, rate)
    blade = dsp.lowpass(dsp.white(rng, length), rate, 420/m['pitch'])*dsp.ad(length, rate, 0.002, 0.016)
    thumps = dsp.sparse(rng, n, dsp.periodic_positions(n, rate, 0.075/m['rate']), blade, np.ones(dsp.periodic_positions(n, rate, 0.075/m['rate']).size))
    turbine = dsp.bandpass(dsp.white(rng, n), rate, 700, 4800*m['bright'])*0.18
    return thumps*1.2+turbine


def _bell(rng, rate, seconds, m):
    n = _n(seconds, rate)
    base = 540.0*m['pitch']
    partials = (1.0, 2.76, 5.40, 8.93, 13.34, 18.64) if m['metallic'] else (1.0, 2.76, 5.40, 8.93)
    gains = (1.0, 0.55, 0.34, 0.2, 0.13, 0.08)
    out = np.zeros(n, dtype=np.float32)
    for ratio, gain in zip(partials, gains):
        out += dsp.osc(np.full(n, base*ratio), rate, 'sine')*dsp.exp_decay(n, rate, seconds*0.32/ratio**0.45)*gain
    strike = dsp.highpass(dsp.white(rng, n), rate, 3500)*dsp.exp_decay(n, rate, 0.004)
    return out*0.7+strike*0.2


def _chime(rng, rate, seconds, m):
    n = _n(seconds, rate)
    out = np.zeros(n, dtype=np.float32)
    steps = (0, 2, 4, 7, 9, 12)
    for index, semitone in enumerate(steps):
        length = max(n-int(index*0.085*rate), _n(0.05, rate))
        freq = 880.0*m['pitch']*2.0**(semitone/12.0)
        voice = sum(dsp.osc(np.full(length, freq*ratio), rate, 'sine')*gain
                    for ratio, gain in ((1.0, 1.0), (2.76, 0.3), (5.4, 0.12)))
        dsp.place(out, voice*dsp.exp_decay(length, rate, seconds*0.22), int(index*0.085*rate))
    return out*0.6


def _coin(rng, rate, seconds, m):
    n = _n(seconds, rate)
    out = np.zeros(n, dtype=np.float32)
    first = _n(min(0.07, seconds*0.35), rate)
    second = max(n-first, 16)
    out = dsp.place(out, dsp.osc(np.full(first, 988.0*m['pitch']), rate, 'square')*dsp.ad(first, rate, 0.002, 0.05), 0)
    out = dsp.place(out, dsp.osc(np.full(second, 1319.0*m['pitch']), rate, 'square')*dsp.ad(second, rate, 0.002, seconds*0.16), first)
    return dsp.lowpass(out, rate, rate*0.4)*0.7


def _powerup(rng, rate, seconds, m):
    n = _n(seconds, rate)
    out = np.zeros(n, dtype=np.float32)
    for index, semitone in enumerate((0, 4, 7, 12, 16, 19, 24)):
        length = _n(max(seconds/7.0, 0.03), rate)
        tone = dsp.osc(np.full(length, 440.0*m['pitch']*2.0**(semitone/12.0)), rate, 'square')
        dsp.place(out, tone*dsp.ad(length, rate, 0.002, seconds/9.0), int(index*seconds/7.0*rate))
    sweep = dsp.osc(dsp.line([(0, 300), (1, 2400)], n)*m['pitch'], rate, 'sine')*dsp.line([(0, 0.0), (1, 0.5)], n)
    return dsp.lowpass(out*0.6+sweep*0.4, rate, rate*0.4)


def _impact(rng, rate, seconds, m):
    n = _n(seconds, rate)
    sub = dsp.osc(dsp.line([(0, 150), (0.4, 62), (1, 38)], n)*m['pitch'], rate, 'sine')*dsp.ad(n, rate, 0.001, seconds*0.16)
    body = dsp.lowpass(dsp.white(rng, n), rate, 1200*m['bright'])*dsp.ad(n, rate, 0.001, seconds*0.07)
    return sub*1.0+body*0.5


def _glass(rng, rate, seconds, m):
    n = _n(seconds, rate)
    burst = dsp.highpass(dsp.white(rng, n), rate, 2500)*dsp.ad(n, rate, 0.001, 0.02)
    shard = dsp.highpass(dsp.white(rng, 1024), rate, 4000)*dsp.exp_decay(1024, rate, 0.012)
    shards = dsp.sparse(rng, n, dsp.poisson_positions(rng, n, rate, 90*m['rate']), shard)
    ring = sum(dsp.resonator(dsp.white(rng, n), rate, freq*m['pitch'], 45.0)*dsp.exp_decay(n, rate, seconds*0.18)
               for freq in (3100.0, 4700.0, 6300.0))
    return burst*0.8+shards*0.9+ring*2.5


def _whoosh(rng, rate, seconds, m):
    n = _n(seconds, rate)
    centre = dsp.line([(0, 320), (0.5, 3200), (1, 380)], n)*m['pitch']
    body = dsp.sweep_bandpass(dsp.white(rng, n), rate, centre, 2.2)
    return body*dsp.line([(0, 0.0), (0.45, 1.0), (1, 0.0)], n)**1.4*3.0


def _click(rng, rate, seconds, m):
    n = _n(seconds, rate)
    return dsp.highpass(dsp.white(rng, n), rate, 2200/m['pitch'])*dsp.ad(n, rate, 0.0005, 0.0025)


def _typing(rng, rate, seconds, m):
    n = _n(seconds, rate)
    length = _n(0.05, rate)
    key = dsp.bandpass(dsp.white(rng, length), rate, 1200/m['pitch'], 7000*m['bright'])*dsp.ad(length, rate, 0.0005, 0.007)
    return dsp.sparse(rng, n, dsp.poisson_positions(rng, n, rate, 6.5*m['rate']), key)


def _birds(rng, rate, seconds, m):
    n = _n(seconds, rate)
    out = np.zeros(n, dtype=np.float32)
    for _ in range(max(int(seconds*2.2*m['rate']), 1)):
        length = _n(rng.uniform(0.06, 0.16), rate)
        top = rng.uniform(3200, 4800)*m['pitch']
        freq = dsp.line([(0, top*0.62), (0.35, top), (1, top*0.78)], length)
        chirp = dsp.osc(freq, rate, 'sine')*(1.0+0.25*dsp.osc(freq*0.06, rate, 'sine'))
        dsp.place(out, chirp*dsp.ad(length, rate, 0.006, 0.035), int(rng.uniform(0, n)))
    return out*0.8


def _crickets(rng, rate, seconds, m):
    n = _n(seconds, rate)
    length = _n(0.22, rate)
    burst = dsp.osc(np.full(length, 4600.0)*m['pitch'], rate, 'sine')*dsp.gate(length, rate, 0.012/m['rate'], 0.45, 2500.0)
    burst = burst*dsp.line([(0, 0.0), (0.2, 1.0), (0.8, 1.0), (1, 0.0)], length)
    return dsp.sparse(rng, n, dsp.periodic_positions(n, rate, 0.7/m['rate'], 0.12, rng), burst)*0.7


def _drone(rng, rate, seconds, m):
    n = _n(seconds, rate)
    base = 110.0*m['pitch']
    out = np.zeros(n, dtype=np.float32)
    for index, gain in enumerate((1.0, 0.5, 0.33, 0.24, 0.16, 0.1)):
        detune = 1.0+0.0015*(index+1)*dsp.smooth_random(rng, n, rate, 0.12)
        out += dsp.osc(base*(index+1)*detune, rate, 'sine')*gain
    return dsp.lowpass(out, rate, 3000*m['bright'])*0.5


def _robot(rng, rate, seconds, m):
    n = _n(seconds, rate)
    steps = np.repeat(rng.uniform(140, 420, max(int(seconds*9*m['rate']), 2)), max(n//max(int(seconds*9*m['rate']), 2), 1))
    freq = np.resize(steps, n)*m['pitch']
    voice = dsp.osc(freq, rate, 'square')+0.5*dsp.osc(freq*2.01, rate, 'saw')
    voice = dsp.ring_modulate(dsp.lowpass(voice, rate, 2600*m['bright']), rate, 62.0, 0.55)
    return voice*dsp.line([(0, 0.0), (0.05, 1.0), (0.95, 1.0), (1, 0.0)], n)*0.6


def _portal(rng, rate, seconds, m):
    n = _n(seconds, rate)
    sweep = dsp.line([(0, 90), (0.6, 900), (1, 260)], n)*m['pitch']
    voices = sum(dsp.osc(sweep*ratio, rate, 'saw') for ratio in (1.0, 1.005, 1.49, 2.01))
    body = dsp.sweep_lowpass(voices, rate, dsp.line([(0, 600), (0.5, 5200), (1, 900)], n)*m['bright'])
    shimmer = dsp.bandpass(dsp.white(rng, n), rate, 3000, 9000)*dsp.line([(0, 0.0), (0.7, 0.5), (1, 0.0)], n)
    return body*0.35+shimmer*0.6


def _door(rng, rate, seconds, m):
    n = _n(seconds, rate)
    friction = dsp.white(rng, n)*(0.4+0.6*np.abs(dsp.smooth_random(rng, n, rate, 14.0*m['rate'])))
    creak = dsp.sweep_bandpass(friction, rate, (420.0+260.0*dsp.smooth_random(rng, n, rate, 1.6))*m['pitch'], 1.25)
    creak *= dsp.line([(0, 0.2), (0.3, 1.0), (0.85, 0.7), (1, 0.0)], n)
    latch = dsp.lowpass(dsp.white(rng, n), rate, 900)*dsp.exp_decay(n, rate, 0.035)
    return creak*4.0+dsp.place(np.zeros(n, dtype=np.float32), latch*0.6, int(n*0.92))


def _applause(rng, rate, seconds, m):
    n = _n(seconds, rate)
    clap = dsp.bandpass(dsp.white(rng, 768), rate, 900, 6500*m['bright'])*dsp.exp_decay(768, rate, 0.012)
    return dsp.sparse(rng, n, dsp.poisson_positions(rng, n, rate, 160*m['rate']), clap)*0.8


def _phone(rng, rate, seconds, m):
    n = _n(seconds, rate)
    tone = (dsp.osc(np.full(n, 440.0)*m['pitch'], rate, 'sine')+dsp.osc(np.full(n, 480.0)*m['pitch'], rate, 'sine'))*0.5
    ring = dsp.gate(n, rate, 3.0/m['rate'], 0.62, 60.0)*dsp.gate(n, rate, 0.05, 0.5, 900.0)
    return tone*ring


def _static(rng, rate, seconds, m):
    n = _n(seconds, rate)
    return dsp.bandpass(dsp.white(rng, n), rate, 200/m['pitch'], 9000*m['bright'])*(0.8+0.2*dsp.smooth_random(rng, n, rate, 30.0))


def _texture(rng, rate, seconds, m):
    """Fallback for prompts with no recognised sound word: a neutral bed."""
    n = _n(seconds, rate)
    bed = dsp.sweep_lowpass(dsp.pink(rng, n, rate), rate,
                            (500.0+1800.0*(0.5+0.5*dsp.smooth_random(rng, n, rate, 0.5)))*m['bright'])
    return bed*dsp.line([(0, 0.0), (0.12, 1.0), (0.88, 1.0), (1, 0.0)], n)


# --------------------------------------------------------------------------
# Catalogue. `kind` drives how the layer fills the requested duration:
# oneshot = single event padded/repeated, continuous/rhythmic = full length.
# --------------------------------------------------------------------------

ARCHETYPES = {
    'explosion': (_explosion, 'oneshot', 2.4, 'Low-frequency blast with a bright transient and a falling filter sweep.',
                  ['explosion', 'explosions', 'blast', 'bomb', 'boom', 'detonation', 'grenade', 'dynamite'],
                  ['explosion', 'deflagration', 'detonation', 'bombe', 'grenade']),
    'thunder': (_thunder, 'oneshot', 4.5, 'Rolling low rumble with an initial crack.',
                ['thunder', 'thunderclap', 'storm', 'lightning', 'rumble'],
                ['tonnerre', 'orage', 'foudre', 'grondement']),
    'laser': (_laser, 'oneshot', 0.45, 'Descending pitched sweep used for laser and blaster shots.',
              ['laser', 'blaster', 'pew', 'phaser', 'raygun', 'shot'],
              ['laser', 'blaster', 'rayon', 'tir']),
    'electric': (_electric, 'oneshot', 0.9, 'Gated broadband crackle with an unstable tone: sparks and electricity.',
                 ['electric', 'electricity', 'spark', 'sparks', 'zap', 'taser', 'shock', 'arc'],
                 ['electrique', 'electricite', 'etincelle', 'etincelles', 'decharge', 'arc']),
    'beep': (_beep, 'oneshot', 0.22, 'Short electronic tone for interfaces and confirmations.',
             ['beep', 'bip', 'blip', 'tone', 'notification', 'ping', 'confirm'],
             ['bip', 'signal', 'notification', 'tonalite']),
    'alarm': (_alarm, 'continuous', 3.0, 'Two-tone alternating alarm pattern.',
              ['alarm', 'alert', 'warning', 'buzzer', 'klaxon'],
              ['alarme', 'alerte', 'avertissement', 'klaxon', 'sonnerie']),
    'siren': (_siren, 'continuous', 4.0, 'Continuously sweeping emergency siren.',
              ['siren', 'ambulance', 'police', 'firetruck', 'emergency'],
              ['sirene', 'ambulance', 'police', 'pompier', 'urgence']),
    'rain': (_rain, 'continuous', 6.0, 'Filtered noise bed with individual droplet transients.',
             ['rain', 'rainfall', 'raining', 'shower', 'drizzle', 'downpour'],
             ['pluie', 'averse', 'bruine', 'pluvieux']),
    'wind': (_wind, 'continuous', 6.0, 'Slowly modulated low noise with an occasional whistle.',
             ['wind', 'windy', 'gust', 'breeze', 'gale', 'storm'],
             ['vent', 'rafale', 'brise', 'bourrasque', 'tempete']),
    'ocean': (_ocean, 'continuous', 8.0, 'Swelling surf with foam bursts.',
              ['ocean', 'sea', 'wave', 'waves', 'surf', 'beach', 'shore'],
              ['ocean', 'mer', 'vague', 'vagues', 'ressac', 'plage', 'rivage']),
    'fire': (_fire, 'continuous', 6.0, 'Low roar plus random crackles: fire, campfire, burning.',
             ['fire', 'campfire', 'burning', 'flame', 'flames', 'crackle', 'crackling', 'bonfire'],
             ['feu', 'flamme', 'flammes', 'brasier', 'crepitement', 'cheminee']),
    'water_drop': (_water_drop, 'oneshot', 0.3, 'Single pitched droplet with a fast falling pitch.',
                   ['drop', 'droplet', 'drip', 'dripping', 'faucet', 'tap'],
                   ['goutte', 'gouttes', 'egouttement', 'robinet']),
    'bubble': (_bubble, 'oneshot', 0.6, 'Rising short sweeps: bubbles and liquid movement.',
               ['bubble', 'bubbles', 'bubbling', 'liquid', 'underwater', 'potion'],
               ['bulle', 'bulles', 'liquide', 'immerge', 'potion']),
    'footsteps': (_footsteps, 'rhythmic', 4.0, 'Repeated thud plus scuff at a walking rate.',
                  ['footstep', 'footsteps', 'walking', 'walk', 'steps', 'running', 'boots'],
                  ['pas', 'marche', 'demarche', 'course', 'bottes']),
    'heartbeat': (_heartbeat, 'rhythmic', 5.0, 'Two low thumps per beat.',
                  ['heartbeat', 'heart', 'pulse', 'heartbeats'],
                  ['coeur', 'battement', 'battements', 'pouls', 'cardiaque']),
    'engine': (_engine, 'continuous', 5.0, 'Harmonic saw stack pulsed at a firing rate, plus intake hiss.',
               ['engine', 'motor', 'car', 'truck', 'idle', 'revving', 'machine', 'diesel'],
               ['moteur', 'voiture', 'camion', 'ralenti', 'machine', 'diesel']),
    'helicopter': (_helicopter, 'rhythmic', 5.0, 'Fast blade thumps over turbine noise.',
                   ['helicopter', 'chopper', 'rotor', 'propeller'],
                   ['helicoptere', 'rotor', 'helice']),
    'bell': (_bell, 'oneshot', 3.0, 'Inharmonic partials with a struck attack.',
             ['bell', 'bells', 'gong', 'ring', 'doorbell', 'chime'],
             ['cloche', 'cloches', 'gong', 'sonnette', 'carillon']),
    'chime': (_chime, 'oneshot', 2.4, 'Ascending bell arpeggio: magic, reward, success.',
              ['magic', 'magical', 'sparkle', 'fairy', 'success', 'reward', 'twinkle'],
              ['magie', 'magique', 'feerique', 'reussite', 'recompense', 'scintillement']),
    'coin': (_coin, 'oneshot', 0.5, 'Two ascending square tones: pickup, coin, item.',
             ['coin', 'pickup', 'item', 'collect', 'point', 'bonus'],
             ['piece', 'ramassage', 'objet', 'bonus', 'point']),
    'powerup': (_powerup, 'oneshot', 0.7, 'Ascending arpeggio with a rising sweep.',
                ['powerup', 'upgrade', 'levelup', 'boost', 'charge'],
                ['amelioration', 'bonus', 'montee', 'charge']),
    'impact': (_impact, 'oneshot', 0.7, 'Sub-bass thump plus a filtered noise transient.',
               ['impact', 'punch', 'hit', 'thud', 'slam', 'crash', 'kick', 'knock'],
               ['impact', 'coup', 'choc', 'poing', 'claquement', 'frappe']),
    'glass': (_glass, 'oneshot', 1.3, 'High inharmonic burst with scattered shards.',
              ['glass', 'shatter', 'break', 'breaking', 'window', 'ceramic'],
              ['verre', 'brise', 'casse', 'vitre', 'ceramique', 'eclat']),
    'whoosh': (_whoosh, 'oneshot', 1.0, 'Noise band sweeping up then down: swing, pass-by, transition.',
               ['whoosh', 'swoosh', 'swipe', 'swing', 'transition', 'passby', 'air'],
               ['souffle', 'sifflement', 'passage', 'transition', 'balayage']),
    'click': (_click, 'oneshot', 0.03, 'Very short broadband transient.',
              ['click', 'tick', 'tap', 'switch', 'button'],
              ['clic', 'tic', 'tap', 'interrupteur', 'bouton']),
    'typing': (_typing, 'rhythmic', 4.0, 'Irregular key clicks.',
               ['typing', 'keyboard', 'keys', 'typewriter'],
               ['frappe', 'clavier', 'touches', 'dactylo']),
    'birds': (_birds, 'continuous', 6.0, 'Random frequency-modulated chirps.',
              ['bird', 'birds', 'chirp', 'chirping', 'tweet', 'sparrow'],
              ['oiseau', 'oiseaux', 'gazouillis', 'pepiement', 'moineau']),
    'crickets': (_crickets, 'rhythmic', 6.0, 'High pulsed bursts at a slow repetition rate.',
                 ['cricket', 'crickets', 'insect', 'insects', 'night', 'cicada'],
                 ['grillon', 'grillons', 'insecte', 'insectes', 'nuit', 'cigale']),
    'drone': (_drone, 'continuous', 6.0, 'Sustained detuned harmonic stack.',
              ['drone', 'hum', 'ambience', 'ambient', 'atmosphere', 'background', 'humming'],
              ['bourdonnement', 'ambiance', 'atmosphere', 'fond', 'nappe']),
    'robot': (_robot, 'continuous', 1.8, 'Stepped ring-modulated tones: robot, computer speech.',
              ['robot', 'robotic', 'android', 'computer', 'digital', 'cyborg'],
              ['robot', 'robotique', 'androide', 'ordinateur', 'numerique']),
    'portal': (_portal, 'oneshot', 3.0, 'Detuned saw sweep with shimmer: sci-fi portal, teleport.',
               ['portal', 'teleport', 'scifi', 'sci', 'fi', 'warp', 'spaceship', 'futuristic', 'energy'],
               ['portail', 'teleportation', 'vaisseau', 'futuriste', 'energie']),
    'door': (_door, 'oneshot', 2.0, 'Modulated friction band: creaking door or hinge.',
             ['door', 'creak', 'creaking', 'hinge', 'squeak'],
             ['porte', 'grincement', 'grince', 'grincer', 'gond', 'craquement']),
    'applause': (_applause, 'continuous', 5.0, 'Dense random claps.',
                 ['applause', 'clapping', 'crowd', 'audience', 'cheer'],
                 ['applaudissements', 'applaudir', 'foule', 'public', 'ovation']),
    'phone': (_phone, 'continuous', 5.0, 'Two-tone ringing pattern.',
              ['phone', 'telephone', 'ringing', 'ringtone', 'call'],
              ['telephone', 'sonnerie', 'appel']),
    'static': (_static, 'continuous', 4.0, 'Broadband noise bed: radio static, hiss.',
               ['static', 'noise', 'radio', 'hiss', 'interference', 'white'],
               ['statique', 'bruit', 'radio', 'souffle', 'interference', 'friture']),
    'texture': (_texture, 'continuous', 4.0, 'Neutral filtered noise bed used when no sound word is recognised.',
                ['texture', 'abstract', 'undefined'], ['texture', 'abstrait']),
}

_STOPWORDS = {
    'a', 'an', 'the', 'of', 'with', 'and', 'or', 'in', 'on', 'at', 'to', 'for', 'from', 'by',
    'sound', 'sounds', 'effect', 'effects', 'sfx', 'audio', 'noise_of', 'like', 'some', 'my',
    'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'd', 'l', 'et', 'ou', 'avec', 'dans',
    'sur', 'au', 'aux', 'son', 'sons', 'bruit', 'bruits', 'effet', 'effets', 'sonore', 'sonores',
    'qui', 'que', 'ce', 'cette', 'est', 'genre',
}

_NUMBERS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
            'nine': 9, 'ten': 10, 'un': 1, 'une': 1, 'deux': 2, 'trois': 3, 'quatre': 4, 'cinq': 5,
            'sept': 7, 'huit': 8, 'neuf': 9, 'dix': 10}

# Modifier word -> (field, value). Multiplicative fields combine by product.
_MODIFIERS = {
    'deep': ('pitch', 0.6), 'low': ('pitch', 0.7), 'bass': ('pitch', 0.6), 'heavy': ('pitch', 0.75),
    'grave': ('pitch', 0.6), 'basse': ('pitch', 0.7), 'lourd': ('pitch', 0.75), 'profond': ('pitch', 0.65),
    'high': ('pitch', 1.5), 'higher': ('pitch', 1.5), 'shrill': ('pitch', 1.8), 'tiny': ('pitch', 1.9),
    'aigu': ('pitch', 1.5), 'aigue': ('pitch', 1.5), 'strident': ('pitch', 1.8), 'petit': ('pitch', 1.6),
    'bright': ('bright', 1.6), 'sharp': ('bright', 1.5), 'crisp': ('bright', 1.4), 'clair': ('bright', 1.5),
    'brillant': ('bright', 1.6), 'vif': ('bright', 1.4),
    'muffled': ('bright', 0.45), 'dull': ('bright', 0.55), 'soft': ('bright', 0.7),
    'etouffe': ('bright', 0.45), 'sourd': ('bright', 0.5), 'doux': ('bright', 0.7),
    'long': ('duration', 2.0), 'longue': ('duration', 2.0), 'sustained': ('duration', 2.0),
    'short': ('duration', 0.5), 'brief': ('duration', 0.45), 'quick': ('duration', 0.5),
    'court': ('duration', 0.5), 'bref': ('duration', 0.45), 'breve': ('duration', 0.45),
    'rapidement': ('rate', 1.9), 'lentement': ('rate', 0.5), 'doucement': ('bright', 0.7),
    'fortement': ('drive', 1.0), 'faiblement': ('level_db', -14.0),
    'fast': ('rate', 1.9), 'rapid': ('rate', 1.9), 'rapide': ('rate', 1.9), 'vite': ('rate', 1.9),
    'slow': ('rate', 0.5), 'lent': ('rate', 0.5), 'lente': ('rate', 0.5), 'calme': ('rate', 0.7),
    'gentle': ('rate', 0.7), 'light': ('rate', 0.8), 'leger': ('rate', 0.8),
    'loud': ('drive', 1.0), 'fort': ('drive', 1.0), 'puissant': ('drive', 1.0),
    'aggressive': ('drive', 1.0), 'agressif': ('drive', 1.0), 'massive': ('drive', 1.0),
    'quiet': ('level_db', -14.0), 'faible': ('level_db', -14.0), 'discret': ('level_db', -14.0),
    'silencieux': ('level_db', -18.0), 'whisper': ('level_db', -20.0),
    'distant': ('distance', 1.0), 'far': ('distance', 1.0), 'faraway': ('distance', 1.0),
    'lointain': ('distance', 1.0), 'loin': ('distance', 1.0), 'eloigne': ('distance', 1.0),
    'close': ('distance', -0.5), 'near': ('distance', -0.5), 'proche': ('distance', -0.5),
    'echo': ('reverb', 0.42), 'reverb': ('reverb', 0.45), 'cave': ('reverb', 0.55),
    'cavern': ('reverb', 0.55), 'hall': ('reverb', 0.45), 'church': ('reverb', 0.55),
    'reverberation': ('reverb', 0.45), 'caverne': ('reverb', 0.55),
    'grotte': ('reverb', 0.55), 'eglise': ('reverb', 0.55), 'salle': ('reverb', 0.35),
    'dry': ('reverb', 0.0), 'sec': ('reverb', 0.0),
    'metallic': ('metallic', 1.0), 'metal': ('metallic', 1.0), 'metallique': ('metallic', 1.0),
    'robotic': ('metallic', 1.0), 'steel': ('metallic', 1.0), 'acier': ('metallic', 1.0),
}

_REPEAT_WORDS = {'repeated', 'repeating', 'series', 'repete', 'repetes', 'serie', 'suite', 'plusieurs'}

_DEFAULT_MODIFIERS = {'pitch': 1.0, 'bright': 1.0, 'duration': 1.0, 'rate': 1.0,
                      'level_db': 0.0, 'distance': 0.0, 'reverb': 0.12, 'metallic': 0.0,
                      'drive': 0.0, 'repeats': 1}


def variants(token):
    """A token plus the simple singular forms used for EN/FR plural matching."""
    forms = {token}
    for suffix in ('es', 's', 'x'):
        if token.endswith(suffix) and len(token) > len(suffix)+2:
            forms.add(token[:-len(suffix)])
    return forms


def _expand(words):
    expanded = set()
    for word in words:
        expanded |= variants(word)
    return expanded


def lookup(token, table):
    """Return the table entry matching the token or one of its singular forms."""
    for form in (token, *sorted(variants(token)-{token})):
        if form in table: return table[form]
    return None


def normalize_text(text):
    folded = unicodedata.normalize('NFD', str(text)).encode('ascii', 'ignore').decode('ascii').lower()
    return re.sub(r'[^a-z0-9]+', ' ', folded).strip()


def tokenize(text):
    return [token for token in normalize_text(text).split() if token]


def catalogue(language='all', query=''):
    """Public description of every archetype and the words that select it."""
    needle = normalize_text(query)
    entries = []
    for key, (_, kind, duration, description, english, french) in ARCHETYPES.items():
        keywords = sorted(set(english if language == 'en' else french if language == 'fr' else english+french))
        if needle and needle not in key and not any(needle in word for word in keywords)\
                and needle not in normalize_text(description):
            continue
        entries.append({'id': key, 'kind': kind, 'natural_duration_seconds': duration,
                        'description': description, 'keywords': keywords})
    return sorted(entries, key=lambda entry: entry['id'])


def build_recipe(prompt, *, duration_seconds=None, seed=0, sample_rate=44100, peak_dbfs=-1.0):
    """Turn a prompt into a deterministic, fully explicit synthesis recipe."""
    tokens = tokenize(prompt)
    modifiers = dict(_DEFAULT_MODIFIERS)
    consumed = set()
    for token in tokens:
        entry = lookup(token, _MODIFIERS)
        if entry:
            field, value = entry
            consumed.add(token)
            if field in ('pitch', 'bright', 'duration', 'rate'):
                modifiers[field] *= value
            elif field in ('metallic', 'drive'):
                modifiers[field] = 1.0
            elif field == 'level_db':
                modifiers[field] = min(modifiers[field], value)
            elif field == 'distance':
                modifiers[field] += value
            else:
                modifiers[field] = value
        if token in _NUMBERS or token.isdigit():
            count = _NUMBERS.get(token) or int(token)
            if 1 <= count <= 16:
                modifiers['repeats'] = count
                consumed.add(token)
        if variants(token) & _REPEAT_WORDS:
            modifiers['repeats'] = max(modifiers['repeats'], 3)
            consumed.add(token)

    scores = {}
    matched_words = {}
    for key, (_, _, _, _, english, french) in ARCHETYPES.items():
        if key == 'texture': continue
        words = _expand(english)|_expand(french)
        hits = sorted({token for token in tokens if variants(token) & words})
        if hits:
            scores[key] = len(hits)*3+sum(3 for token in hits if key in variants(token))
            matched_words[key] = hits
            consumed.update(hits)

    order = sorted(scores, key=lambda key: (-scores[key], key))[:MAX_LAYERS]
    warnings = []
    if not order:
        order = ['texture']
        matched_words['texture'] = []
        scores['texture'] = 0
        warnings.append('No catalogued sound word was recognised in the prompt; a neutral texture was '
                        'synthesised. Call list_sound_types to see the available words.')

    if modifiers['distance'] > 0:
        modifiers['bright'] *= 0.45
        modifiers['reverb'] = max(modifiers['reverb'], 0.35)
        modifiers['level_db'] = min(modifiers['level_db'], -8.0)
    modifiers['pitch'] = float(np.clip(modifiers['pitch'], 0.25, 4.0))
    modifiers['bright'] = float(np.clip(modifiers['bright'], 0.25, 3.0))
    modifiers['rate'] = float(np.clip(modifiers['rate'], 0.2, 4.0))
    modifiers['duration'] = float(np.clip(modifiers['duration'], 0.2, 5.0))
    modifiers['reverb'] = float(np.clip(modifiers['reverb'], 0.0, 0.7))

    natural = max(ARCHETYPES[key][2] for key in order)*modifiers['duration']
    if modifiers['repeats'] > 1 and all(ARCHETYPES[key][1] == 'oneshot' for key in order):
        # A repeated one-shot needs room for every occurrence plus a gap.
        natural *= modifiers['repeats']*1.5
    duration = float(np.clip(duration_seconds if duration_seconds else natural, MIN_DURATION, MAX_DURATION))

    layers = []
    for index, key in enumerate(order):
        layers.append({'archetype': key, 'kind': ARCHETYPES[key][1], 'score': scores[key],
                       'gain_db': round(-4.5*index, 2), 'matched_keywords': matched_words[key],
                       'event_seconds': round(min(ARCHETYPES[key][2]*modifiers['duration'], duration), 4)})

    if (modifiers['repeats'] == 1 and all(layer['kind'] == 'oneshot' for layer in layers)
            and duration > 2.5*max(layer['event_seconds'] for layer in layers)):
        warnings.append('The requested duration is much longer than this one-shot sound; the remainder of '
                        'the file is silence. Ask for a repeat count or omit duration_seconds.')

    unknown = [token for token in tokens if token not in consumed and token not in _STOPWORDS]
    return {'prompt': str(prompt), 'normalized_prompt': ' '.join(tokens), 'seed': int(seed),
            'sample_rate': int(sample_rate), 'duration_seconds': round(duration, 4),
            'natural_duration_seconds': round(float(np.clip(natural, MIN_DURATION, MAX_DURATION)), 4),
            'target_peak_dbfs': round(float(peak_dbfs)+modifiers['level_db'], 3),
            'layers': layers, 'modifiers': {key: round(float(value), 4) if key != 'repeats' else int(value)
                                            for key, value in modifiers.items()},
            'unrecognized_words': unknown, 'warnings': warnings}


def _layer_seed(recipe, index):
    digest = hashlib.sha256(f"{recipe['seed']}|{index}|{recipe['layers'][index]['archetype']}".encode()).digest()
    return int.from_bytes(digest[:8], 'big')


def render(recipe, *, cancellation=None, progress=None):
    """Render a recipe produced by build_recipe. Returns mono float32 audio."""
    rate = int(recipe['sample_rate'])
    total = _n(recipe['duration_seconds'], rate)
    modifiers = dict(recipe['modifiers'])
    modifiers['metallic'] = bool(modifiers['metallic'])
    mix = np.zeros(total, dtype=np.float32)
    for index, layer in enumerate(recipe['layers']):
        if cancellation: cancellation.check()
        renderer, kind = ARCHETYPES[layer['archetype']][0], layer['kind']
        rng = dsp.generator(_layer_seed(recipe, index))
        gain = 10.0**(layer['gain_db']/20.0)
        if kind == 'oneshot':
            repeats = max(int(modifiers['repeats']), 1)
            event = float(np.clip(layer['event_seconds'], MIN_DURATION*0.05, recipe['duration_seconds']))
            spacing = (total/repeats) if repeats > 1 else 0.0
            for step in range(repeats):
                if cancellation: cancellation.check()
                block = renderer(rng, rate, event, modifiers)
                dsp.place(mix, dsp.fade(block, rate, 0.004)*gain, int(step*spacing))
        else:
            block = renderer(rng, rate, recipe['duration_seconds'], modifiers)
            mix += dsp.fade(block[:total] if block.size >= total else np.resize(block, total), rate, 0.01)*gain
        if progress: progress(index+1, len(recipe['layers']))
    if cancellation: cancellation.check()
    if modifiers['distance'] > 0:
        mix = dsp.lowpass(mix, rate, 1300.0)
    if modifiers['metallic']:
        mix = dsp.ring_modulate(mix, rate, 1450.0, 0.22)
    if modifiers['drive']:
        mix = dsp.saturate(mix, 3.2)
    if modifiers['reverb'] > 0.01:
        mix = dsp.reverb(mix, rate, 0.55+1.6*modifiers['reverb'], modifiers['reverb'], dsp.generator(recipe['seed']+7))
    mix = np.nan_to_num(mix, nan=0.0, posinf=0.0, neginf=0.0)
    return dsp.normalize(dsp.fade(mix, rate, 0.006), recipe['target_peak_dbfs'])
