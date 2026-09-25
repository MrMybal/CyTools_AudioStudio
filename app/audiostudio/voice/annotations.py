"""Inline speech directions compiled to a plan of passages and pauses.

Grammar (ported from the Qwen3-TTS tool, kept identical):
  [tone: <direction>] / [ton: <direction>]  persistent delivery direction, reset with
                                            reset|normal|default|neutre|neutral
  [pause: 500ms] / [pause: 1s]              exact silence (max 10 s each, 60 s total)
Tags never reach the spoken text. This is Tool-side orchestration, not native markup
support in any model. Backends that cannot follow a direction ignore it (Piper) or
map it to their own expression field (Fish Speech) — see ``plan_for_backend``.

Raises ``AnnotationError`` (a ValueError) on invalid input so that both the runtime
handler (-> InvalidParameters) and the workers can use it.
"""
import re

TAG = re.compile(r'\[\s*(ton|tone|pause)\s*:', re.I)
RESET_WORDS = ('reset', 'normal', 'default', 'neutre', 'neutral')
MAX_SEGMENTS = 128
MAX_PAUSE_SECONDS = 10.0
MAX_TOTAL_PAUSE_SECONDS = 60.0


class AnnotationError(ValueError):
    pass


def split_delivery(text, delivery):
    if delivery == 'segments':
        parts = re.split(r'(?<=[.!?;])\s+|\n+', text)
    elif delivery == 'paragraphs':
        parts = re.split(r'\r?\n[ \t]*\r?\n+', text)
    else:
        parts = [text]
    return [p.strip() for p in parts if p and p.strip()]


def build_plan(text, *, enabled=True, delivery='complete', base_instruction=''):
    """Return a list of {'text', 'instruction', 'direction'} and {'pauseSeconds'} items."""
    plan = []
    style = ''
    cursor = 0
    pause_total = 0.0

    def speech(value):
        for part in split_delivery(value, delivery):
            instruction = base_instruction
            if style:
                instruction = (base_instruction + '\n' if base_instruction else '') + 'For this passage, use this delivery (overrides conflicting tone directions): ' + style
            plan.append({'text': part, 'instruction': instruction, 'direction': style})

    if enabled:
        for match in TAG.finditer(text):
            if match.start() < cursor:
                continue
            speech(text[cursor:match.start()])
            end = text.find(']', match.end())
            if end < 0:
                raise AnnotationError('Unclosed text annotation; expected ].')
            value = text[match.end():end].strip()
            kind = match.group(1).lower()
            if kind == 'pause':
                amount = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*(ms|s)', value, re.I)
                if not amount:
                    raise AnnotationError('Use [pause: 500ms] or [pause: 1s].')
                seconds = float(amount[1].replace(',', '.')) / (1000 if amount[2].lower() == 'ms' else 1)
                pause_total += seconds
                if seconds > MAX_PAUSE_SECONDS or pause_total > MAX_TOTAL_PAUSE_SECONDS:
                    raise AnnotationError('Pauses: maximum 10 seconds each and 60 seconds total.')
                if seconds:
                    plan.append({'pauseSeconds': seconds})
            else:
                if not value or len(value) > 256 or '[' in value:
                    raise AnnotationError('Tone annotation must contain 1 to 256 characters.')
                style = '' if value.lower() in RESET_WORDS else value
            cursor = end + 1
        speech(text[cursor:])
    else:
        speech(text)
    if not any('text' in item for item in plan):
        raise AnnotationError('Provide text to speak, not only annotations.')
    if len(plan) > MAX_SEGMENTS:
        raise AnnotationError(f'Maximum {MAX_SEGMENTS} speech/pause segments per generation.')
    return plan


def strip_tags(text):
    """Plain text without annotations (for backends that speak everything)."""
    return ''.join(item['text'] + ' ' for item in build_plan(text, enabled=True) if 'text' in item).strip()


def render_plan(plan, synthesize, emit):
    """Keep one engine loaded, insert exact silence, preserve order.

    synthesize(item) -> (audio float32 1-D, samplerate); emit(audio, rate, item).
    Returns the sample rate used.
    """
    import numpy as np
    rate = None
    pending = []
    for item in plan:
        if 'pauseSeconds' in item:
            if rate is None:
                pending.append(item)
            else:
                emit(np.zeros(round(item['pauseSeconds'] * rate), dtype=np.float32), rate, item)
            continue
        wav, current_rate = synthesize(item)
        audio = np.asarray(wav, dtype=np.float32)
        if audio.ndim == 2:
            audio = audio[0] if audio.shape[0] <= 2 else audio[:, 0]
        if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
            raise RuntimeError('Invalid model audio')
        if rate is not None and rate != current_rate:
            raise RuntimeError('Sample rate changed between passages')
        rate = current_rate
        for pause in pending:
            emit(np.zeros(round(pause['pauseSeconds'] * rate), dtype=np.float32), rate, pause)
        pending.clear()
        emit(audio, rate, item)
    return rate
