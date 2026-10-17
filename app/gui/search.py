"""Text search for the effect and plugin pickers: accent- and case-insensitive, every word must match."""
import unicodedata


def fold(text):
    """Lower case without accents: 'Réverbération' -> 'reverberation'."""
    decomposed = unicodedata.normalize('NFKD', str(text))
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).lower()


def matches(query, haystack):
    words = fold(query).split()
    if not words:
        return True
    target = fold(haystack)
    return all(word in target for word in words)


def filter_indices(query, haystacks):
    return [index for index, text in enumerate(haystacks) if matches(query, text)]


def effect_haystack(spec, tr=lambda t: t):
    """Everything a user may type to find an effect, in English and in the interface language."""
    parts = [spec.name, tr(spec.name), spec.id.replace('_', ' '), spec.category, tr(spec.category)]
    if spec.help:
        parts += [spec.help, tr(spec.help)]
    return ' '.join(parts)


def plugin_haystack(info):
    return ' '.join(str(info.get(key) or '') for key in ('name', 'manufacturer', 'category', 'format', 'path'))
