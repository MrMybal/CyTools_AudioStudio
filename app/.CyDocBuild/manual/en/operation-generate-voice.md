---
id: operation-generate-voice
title: generate_voice
description: Regenerate a voice from a saved preset (backend, model, every parameter) with new text. Warns when a reference recording changed.
section: Reference
order: 200
parent: operations
revision: 6b561e02fe90b0d5
---

Regenerate a voice from a saved preset (backend, model, every parameter) with new text. Warns when a reference recording changed.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `preset` | `string` | Yes | Preset id (see list_voice_presets)  |
| `text` | `string` | Yes | Text to speak  |
| `seed` | `integer/null` | No | Override the preset seed `default=null`, `minimum=0`, `maximum=2147483647` |
| `post_workflow` | `string/null` | No | Override the preset post workflow (empty string = none) `default=null` |
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
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation generate_voice
```
