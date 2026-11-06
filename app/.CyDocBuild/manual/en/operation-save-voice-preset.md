---
id: operation-save-voice-preset
title: save_voice_preset
description: Store the parameters of a voice (without text) as a reusable preset.
section: Reference
order: 200
parent: operations
revision: 80428cce99925f6a
---

Store the parameters of a voice (without text) as a reusable preset.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | `string` | Yes | Preset name  |
| `backend` | `value` | Yes | Voice backend `default="qwen3tts"`, `enum=["piper", "qwen3tts", "fishspeech"]` |
| `parameters` | `object` | Yes | Parameters of the corresponding voice_* operation (text is ignored)  |
| `post_workflow` | `string` | No | Optional workflow (saved name) applied to the generated audio, with tail rendering. `default=""` |
| `notes` | `string` | No | Notes `default=""` |
| `preset_id` | `string` | No | Existing preset id to overwrite `default=""` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `id` | `string` | Yes | Preset id  |
| `path` | `string` | Yes | Saved path  |
| `preset` | `object` | No | See the operation parameters.  |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: not declared.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation save_voice_preset
```
