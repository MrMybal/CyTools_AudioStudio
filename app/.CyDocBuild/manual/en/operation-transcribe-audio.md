---
id: operation-transcribe-audio
title: transcribe_audio
description: Speech to text with Whisper large-v3 turbo (99 languages, segment timestamps). Used to get the exact transcription of a reference recording before cloning a voice.
section: Reference
order: 200
parent: operations
revision: d7f6ccd8340dc5ae
---

Speech to text with Whisper large-v3 turbo (99 languages, segment timestamps). Used to get the exact transcription of a reference recording before cloning a voice.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `input` | `string` | Yes | Recording to transcribe  |
| `language` | `string` | No | Language code (fr, en, ...); empty = automatic detection `default=""` |
| `device` | `value` | No | Compute device `default="cuda"`, `enum=["cuda", "cpu"]` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `text` | `string` | Yes | Transcription  |
| `segments` | `array` | No | See the operation parameters.  |
| `durationSeconds` | `number` | No | Audio duration `default=0.0` |
| `language` | `string` | No | Language used  |
| `seconds` | `number` | No | Processing time `default=0.0` |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: `whisper`
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation transcribe_audio
```
