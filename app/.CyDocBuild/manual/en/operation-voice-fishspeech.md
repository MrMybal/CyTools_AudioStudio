---
id: operation-voice-fishspeech
title: voice_fishspeech
description: Multi-speaker dialogue with natural-language expressions per turn and voice cloning from short references (0.1-30 s with their transcription). CUDA only, 44.1 kHz mono.
section: Reference
order: 200
parent: operations
revision: f976716ee1e2b315
---

Multi-speaker dialogue with natural-language expressions per turn and voice cloning from short references (0.1-30 s with their transcription). CUDA only, 44.1 kHz mono.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `turns` | `array` | Yes | Dialogue turns in order  |
| `references` | `array` | No | Reference recordings per speaker index `default=[]` |
| `temperature` | `number` | No | Temperature `default=0.8`, `minimum=0.1`, `maximum=1.5` |
| `top_p` | `number` | No | Top-p `default=0.8`, `minimum=0.1`, `maximum=1.0` |
| `top_k` | `integer` | No | Top-k `default=30`, `minimum=1`, `maximum=100` |
| `seed` | `integer` | No | Seed `default=42`, `minimum=0`, `maximum=2147483647` |
| `max_new_tokens` | `integer` | No | Max new tokens `default=1024`, `minimum=128`, `maximum=4096` |
| `chunk_length` | `integer` | No | Chunk length `default=200`, `minimum=50`, `maximum=500` |
| `precision` | `value` | No | Precision `default="bfloat16"`, `enum=["bfloat16", "float16"]` |
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
- Backends: `fishspeech`
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation voice_fishspeech
```
