"""Prepare plain text for a voice backend: pauses, delivery directions, dialogue turns.

Two paths give the same output shape:
  * heuristic  - no model: paragraph breaks become pauses, sentence punctuation is kept, an
                 optional global style is applied. Deterministic and instant.
  * llm        - a local language model (Qwen3-1.7B in the torch engine) rewrites the text
                 with the markup of the target backend. Its output is validated and falls
                 back to the heuristic when it is not usable.
The AI client driving the Tool through MCP can skip both and pass annotated text itself.

Target formats:
  qwen3tts   -> text with [tone: ...] / [pause: 500ms] tags (see voice.annotations)
  fishspeech -> turns: [{"speaker": n, "text": "...", "expression": "..."}]
  piper      -> plain text; pauses become sentence breaks (Piper has no markup)
"""
import json
import re

from .annotations import build_plan, AnnotationError

TARGETS = ('qwen3tts', 'fishspeech', 'piper')

SYSTEM_QWEN = (
    "You prepare narration text for a text-to-speech engine. Rewrite the user's text so it is ready to be spoken.\n"
    "Rules: keep every word of the original text in the same order and language; do not add commentary; you may insert\n"
    "[tone: <short delivery direction in English>] before a passage whose delivery should change (e.g. warm, whispered, excited,\n"
    "calm and slow, sad), [tone: reset] to return to the default, and [pause: 400ms] / [pause: 1s] between sentences or\n"
    "paragraphs where a breath or a dramatic pause helps (max 3s each). Use at most one tone tag per paragraph. Output only the\n"
    "annotated text, nothing else.")
SYSTEM_FISH = (
    "You prepare a dialogue for a multi-speaker text-to-speech engine. Split the user's text into turns and answer ONLY with a JSON\n"
    "array of objects {\"speaker\": <integer 0-4>, \"text\": \"...\", \"expression\": \"<short natural-language emotion or style in English>\"}.\n"
    "Keep every word of the original text in the same order and language. Assign speaker numbers consistently to the characters\n"
    "(0 for the narrator or the first voice). Expressions are short: cheerful, whisper, sad, excited, calm, professional broadcast tone...")
SYSTEM_PIPER = (
    "You prepare narration text for a simple text-to-speech engine that reads punctuation only. Rewrite the user's text so it is\n"
    "easy to read aloud: expand abbreviations and numbers into words in the same language, add commas where a breath helps, put one\n"
    "sentence per line and keep every idea and word order. Output only the text.")


def heuristic(text, target, style='', pause_ms=500):
    text = text.replace('\r\n', '\n').strip()
    paragraphs = [p.strip() for p in re.split(r'\n[ \t]*\n+', text) if p.strip()]
    if target == 'qwen3tts':
        parts = []
        for index, paragraph in enumerate(paragraphs):
            if index:
                parts.append(f'[pause: {int(pause_ms)}ms]')
            parts.append(paragraph)
        body = '\n\n'.join(parts)
        if style:
            body = f'[tone: {style}]\n' + body
        return {'target': target, 'text': body, 'method': 'heuristic', 'textAnnotations': True}
    if target == 'fishspeech':
        turns = []
        for paragraph in paragraphs:
            match = re.match(r'^\s*([A-Za-zÀ-ÿ0-9 _-]{1,24})\s*:\s*(.+)$', paragraph, re.S)
            speaker = 0
            body = paragraph
            if match:
                name = match.group(1).strip().lower()
                names = [t.get('_name') for t in turns if t.get('_name')]
                if name not in names:
                    names.append(name)
                speaker = min(4, names.index(name))
                body = match.group(2).strip()
                turns.append({'speaker': speaker, 'text': body, 'expression': style, '_name': name})
            else:
                turns.append({'speaker': 0, 'text': body, 'expression': style})
        for turn in turns:
            turn.pop('_name', None)
        return {'target': target, 'turns': turns or [{'speaker': 0, 'text': text, 'expression': style}], 'method': 'heuristic'}
    sentences = []
    for paragraph in paragraphs:
        sentences.extend(s.strip() for s in re.split(r'(?<=[.!?;])\s+', paragraph) if s.strip())
    return {'target': target, 'text': '\n'.join(sentences) if sentences else text, 'method': 'heuristic'}


SYSTEM_QWEN_PARAGRAPH = (
    "You prepare one paragraph of narration for a text-to-speech engine. Answer with the same paragraph, every word kept in the same\n"
    "order and language, optionally preceded by ONE tag [tone: <short delivery direction in English, e.g. warm, whispered, excited,\n"
    "calm and slow, sad>] and optionally with [pause: 300ms] or [pause: 1s] inserted between sentences where a breath helps.\n"
    "No commentary, no quotes, output only the paragraph.")


def paragraphs_of(text):
    return [p.strip() for p in re.split(r'\n[ \t]*\n+', text.replace('\r\n', '\n').strip()) if p.strip()]


def validate_paragraph(raw, paragraph):
    """Annotated paragraph from the model, or None when it lost words or produced bad tags."""
    raw = re.sub(r'<think>.*?</think>', '', raw or '', flags=re.S).strip().strip('"')
    if not raw:
        return None
    try:
        plan = build_plan(raw, enabled=True)
    except AnnotationError:
        return None
    spoken = _words(' '.join(item['text'] for item in plan if 'text' in item))
    return raw if _similar(_words(paragraph), spoken) else None


def system_prompt(target):
    return {'qwen3tts': SYSTEM_QWEN, 'fishspeech': SYSTEM_FISH, 'piper': SYSTEM_PIPER}[target]


def user_prompt(text, target, style='', language=''):
    hints = []
    if style:
        hints.append('Overall delivery wanted: ' + style + '.')
    if language:
        hints.append('The text is in ' + language + '; keep that language.')
    return ('\n'.join(hints) + '\n\n' if hints else '') + text.strip()


def _words(text):
    return re.findall(r'\w+', text.lower())


def validate_llm_output(raw, text, target, style=''):
    """Accept the model output only when it keeps the words of the source; else None."""
    raw = (raw or '').strip()
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.S).strip()
    if not raw:
        return None
    source_words = _words(text)
    if target == 'fishspeech':
        # Speaker labels ("Marie : ...") are not spoken: compare with the heuristic split instead.
        source_words = _words(' '.join(t['text'] for t in heuristic(text, 'fishspeech')['turns']))
        start, end = raw.find('['), raw.rfind(']')
        if start < 0 or end < start:
            return None
        try:
            turns = json.loads(raw[start:end + 1])
        except ValueError:
            return None
        cleaned = []
        for item in turns:
            if not isinstance(item, dict) or not str(item.get('text', '')).strip():
                continue
            cleaned.append({'speaker': max(0, min(4, int(item.get('speaker', 0) or 0))), 'text': str(item['text']).strip(), 'expression': str(item.get('expression', style or ''))[:150]})
        if not cleaned:
            return None
        spoken = _words(' '.join(t['text'] for t in cleaned))
        if not _similar(source_words, spoken):
            return None
        return {'target': target, 'turns': cleaned[:30], 'method': 'llm'}
    if target == 'qwen3tts':
        try:
            plan = build_plan(raw, enabled=True)
        except AnnotationError:
            return None
        spoken = _words(' '.join(item['text'] for item in plan if 'text' in item))
        if not _similar(source_words, spoken):
            return None
        return {'target': target, 'text': raw, 'method': 'llm', 'textAnnotations': True}
    spoken = _words(raw)
    if not spoken or len(spoken) < 0.5 * len(source_words):
        return None
    return {'target': target, 'text': raw, 'method': 'llm'}


def _similar(source, spoken):
    if not source:
        return bool(spoken)
    kept = sum(1 for word in source if word in set(spoken))
    return kept / len(source) >= 0.8 and len(spoken) <= 1.6 * len(source) + 20
