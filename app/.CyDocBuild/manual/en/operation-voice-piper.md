---
id: operation-voice-piper
title: voice_piper
description: CPU text-to-speech with a Piper ONNX voice (22.05 kHz mono). Raw text only, no annotations.
section: Reference
order: 200
parent: operations
revision: 5d6ae1698b56cc94
---

CPU text-to-speech with a Piper ONNX voice (22.05 kHz mono). Raw text only, no annotations.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `text` | `string` | Yes | Text to speak  |
| `voice` | `string` | No | Voice key, e.g. fr_FR-siwis-medium (see list_voices) `default="fr_FR-siwis-medium"` |
| `speaker` | `integer` | No | Speaker index for multi-speaker voices `default=0`, `minimum=0`, `maximum=1000` |
| `length_scale` | `number` | No | Speed (1 = normal, 2 = twice slower) `default=1.0`, `minimum=0.25`, `maximum=4.0` |
| `noise_scale` | `number` | No | Expressiveness `default=0.667`, `minimum=0.0`, `maximum=2.0` |
| `noise_w_scale` | `number` | No | Phoneme width variation `default=0.8`, `minimum=0.0`, `maximum=2.0` |
| `volume` | `number` | No | Volume `default=1.0`, `minimum=0.01`, `maximum=2.0` |
| `normalize` | `boolean` | No | Normalise output `default=true` |
| `threads` | `integer` | No | CPU threads `default=2`, `minimum=1`, `maximum=16` |
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
- Backends: `piper`
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation voice_piper
```
