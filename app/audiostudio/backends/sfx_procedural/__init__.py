"""Procedural sound-effect synthesizer (no model, no download, pure NumPy).

Ported from the reference ``sfx.py``/``dsp.py`` of the previous tool. A prompt
("explosion lointaine", "slow deep thunder", ...) is matched against a catalogue
of 36 archetypes with EN/FR keywords, turned into a deterministic JSON recipe
and rendered to float32 audio. For a given (prompt, seed, sample_rate) the
samples are identical to what the original tool produced; the only difference
is that audio is returned as a ``(1, frames)`` array instead of a WAV file.

Public API:
    catalogue(language='all', query='')
    build_recipe(prompt, seed=0, sample_rate=44100, duration_seconds=None, peak_dbfs=-1.0)
    render(recipe, cancellation=None, progress=None)              -> ndarray (1, frames)
    generate(prompt, seed=0, sample_rate=44100, duration_seconds=None, peak_dbfs=-1.0,
             variations=1, cancellation=None, progress=None)     -> [{'audio', 'seed', 'recipe'}]

``cancellation`` is any object with a ``check()`` method that raises to abort;
it is polled between layers, repeats and variations exactly like the original.
``progress`` is an optional ``callable(fraction: float, message: str)``.
"""
import numpy as np

from . import archetypes as _archetypes
from . import synth
from .archetypes import (ARCHETYPES, MAX_DURATION, MAX_LAYERS, MIN_DURATION, SAMPLE_RATES,
                         catalogue, normalize_text, tokenize)

__all__ = ['ARCHETYPES', 'MAX_DURATION', 'MAX_LAYERS', 'MIN_DURATION', 'SAMPLE_RATES',
           'build_recipe', 'catalogue', 'generate', 'normalize_text', 'render', 'synth',
           'tokenize', 'MAX_VARIATIONS']

MAX_VARIATIONS = 4


def build_recipe(prompt, seed=0, sample_rate=44100, duration_seconds=None, peak_dbfs=-1.0):
    """Turn a prompt into a deterministic, fully explicit synthesis recipe (JSON-serialisable dict)."""
    return _archetypes.build_recipe(prompt, duration_seconds=duration_seconds, seed=int(seed),
                                    sample_rate=int(sample_rate), peak_dbfs=float(peak_dbfs))


def render(recipe, cancellation=None, progress=None):
    """Render a recipe. Returns float32 audio shaped ``(1, frames)`` (mono).

    ``progress``, when given, receives ``(fraction, message)`` once per rendered layer.
    """
    def _layer_progress(done, count):
        progress(done/max(count, 1), f"layer {done}/{count}: {recipe['layers'][done-1]['archetype']}")

    mono = _archetypes.render(recipe, cancellation=cancellation,
                              progress=_layer_progress if progress else None)
    return np.ascontiguousarray(mono, dtype=np.float32).reshape(1, -1)


def generate(prompt, seed=0, sample_rate=44100, duration_seconds=None, peak_dbfs=-1.0,
             variations=1, cancellation=None, progress=None):
    """Build and render ``variations`` takes of ``prompt``; variation ``i`` uses seed ``seed+i``.

    Returns a list of ``{'audio': ndarray(1, frames), 'seed': int, 'recipe': dict}``.
    """
    count = int(variations)
    if not 1 <= count <= MAX_VARIATIONS:
        raise ValueError(f'variations must be between 1 and {MAX_VARIATIONS}')
    # As in the original tool: one recipe, each variation re-seeded with seed+index.
    base = build_recipe(prompt, seed=seed, sample_rate=sample_rate,
                        duration_seconds=duration_seconds, peak_dbfs=peak_dbfs)
    results = []
    for index in range(count):
        if cancellation: cancellation.check()
        take_seed = base['seed']+index
        recipe = dict(base, seed=take_seed)

        def _take_progress(fraction, message, _index=index):
            if progress:
                progress((_index+fraction)/count, f'variation {_index+1}/{count}, {message}')

        audio = render(recipe, cancellation=cancellation, progress=_take_progress if progress else None)
        results.append({'audio': audio, 'seed': take_seed, 'recipe': recipe})
        if progress:
            progress((index+1)/count, f'variation {index+1}/{count} done')
    return results
