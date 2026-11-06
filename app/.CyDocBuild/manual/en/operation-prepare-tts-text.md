---
id: operation-prepare-tts-text
title: prepare_tts_text
description: Turn plain text into the markup a voice backend expects: [tone]/[pause] annotations for Qwen3-TTS, dialogue turns with expressions for Fish Speech, sentence-per-line text for Piper. Method heuristic needs no model; method llm…
section: Reference
order: 200
parent: operations
revision: 815dce9e3292c662
---

Turn plain text into the markup a voice backend expects: [tone]/[pause] annotations for Qwen3-TTS, dialogue turns with expressions for Fish Speech, sentence-per-line text for Piper. Method heuristic needs no model; method llm uses the local Qwen3-1.7B assistant and falls back to the heuristic when its output is not usable. An AI client can skip this and annotate itself.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `text` | `string` | Yes | Plain text  |
| `target` | `value` | No | Voice backend `default="qwen3tts"`, `enum=["qwen3tts", "fishspeech", "piper"]` |
| `method` | `value` | No | Annotation method `default="heuristic"`, `enum=["heuristic", "llm"]` |
| `style` | `string` | No | Overall delivery wanted (e.g. warm and calm narration) `default=""` |
| `language` | `string` | No | Language hint for the assistant `default=""` |
| `pause_ms` | `integer` | No | Pause inserted between paragraphs (heuristic) `default=500`, `minimum=0`, `maximum=3000` |
| `device` | `value` | No | Compute device `default="cuda"`, `enum=["cuda", "cpu"]` |
| `max_new_tokens` | `integer` | No | Assistant output budget `default=1024`, `minimum=64`, `maximum=4096` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `target` | `string` | Yes | Backend  |
| `method` | `string` | Yes | Method actually used  |
| `text` | `string` | No | Annotated text (qwen3tts, piper) `default=""` |
| `turns` | `array` | No | See the operation parameters.  |
| `textAnnotations` | `boolean` | No | Pass text_annotations=true to voice_qwen3tts `default=false` |
| `fallbackReason` | `string` | No | Why the llm output was replaced by the heuristic `default=""` |
| `raw` | `string` | No | Raw assistant output `default=""` |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation prepare_tts_text
```
