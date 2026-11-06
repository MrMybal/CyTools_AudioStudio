---
id: operation-voice-qwen3tts
title: voice_qwen3tts
description: Expressive text-to-speech: preset speakers with natural-language instructions (custom), voice cloning from a reference recording (clone) or voice design from a description (design). Inline [tone: ...] and [pause: 500ms]…
section: Reference
order: 200
parent: operations
revision: 009c4a9416040e22
---

Expressive text-to-speech: preset speakers with natural-language instructions (custom), voice cloning from a reference recording (clone) or voice design from a description (design). Inline [tone: ...] and [pause: 500ms] annotations are supported with the 1.7B CustomVoice model. 24 kHz mono.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `text` | `string` | Yes | Text to speak; paragraphs separated by blank lines  |
| `model` | `value` | No | Model variant (custom needs CustomVoice, clone needs Base, design needs VoiceDesign) `default="1.7B-CustomVoice"`, `enum=["0.6B-CustomVoice", "1.7B-CustomVoice", "0.6B-Base", "1.7B-Base", "1.7B-VoiceDesign"]` |
| `mode` | `value` | No | Mode `default="custom"`, `enum=["custom", "clone", "design"]` |
| `language` | `value` | No | Language `default="French"`, `enum=["Auto", "French", "English", "Chinese", "Japanese", "Korean", "German", "Russian", "Portuguese", "Spanish", "Italian"]` |
| `speaker` | `value` | No | Preset speaker (custom) `default="Ryan"`, `enum=["Ryan", "Aiden", "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ono_Anna", "Sohee"]` |
| `instruction` | `string` | No | Delivery instruction (custom, 1.7B) or voice description (design) `default=""` |
| `reference_audio` | `string` | No | Reference recording (clone) `default=""` |
| `reference_text` | `string` | No | Exact transcription of the reference (clone) `default=""` |
| `x_vector_only` | `boolean` | No | Clone from the speaker embedding only, no transcription `default=false` |
| `device` | `value` | No | Compute device `default="cuda"`, `enum=["cuda", "cpu"]` |
| `delivery` | `value` | No | Split the text into passages `default="paragraphs"`, `enum=["paragraphs", "segments", "complete"]` |
| `temperature` | `number` | No | Temperature `default=0.9`, `minimum=0.1`, `maximum=2.0` |
| `top_k` | `integer` | No | Top-k `default=50`, `minimum=1`, `maximum=200` |
| `top_p` | `number` | No | Top-p `default=1.0`, `minimum=0.05`, `maximum=1.0` |
| `repetition_penalty` | `number` | No | Repetition penalty `default=1.05`, `minimum=1.0`, `maximum=2.0` |
| `max_new_tokens` | `integer` | No | Max new tokens per passage `default=2048`, `minimum=32`, `maximum=4096` |
| `seed` | `integer` | No | Seed `default=42`, `minimum=0`, `maximum=2147483647` |
| `text_annotations` | `boolean` | No | Enable [tone: ...] / [pause: ...] annotations (1.7B CustomVoice only) `default=false` |
| `post_workflow` | `string` | No | Optional workflow (saved name) applied to the generated audio, with tail rendering. `default=""` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `file` | `string` | Yes | Speech WAV  |
| `mimeType` | `string` | Yes | MIME type  |
| `sampleRate` | `integer` | Yes | Sample rate `default=24000` |
| `channels` | `integer` | Yes | Channels `default=1` |
| `durationSeconds` | `number` | Yes | Duration (s) `default=0.0` |
| `backend` | `string` | Yes | Backend id  |
| `model` | `string` | No | Model id  |
| `processedFile` | `string` | No | Result after the post workflow, when one was applied `default=""` |
| `generationSeconds` | `number` | No | Generation time (s) `default=0.0` |
| `preset` | `object` | No | Reusable preset (parameters without text) to regenerate the same voice  |
| `warnings` | `array` | No | See the operation parameters.  |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: `qwen3tts`
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation voice_qwen3tts
```
