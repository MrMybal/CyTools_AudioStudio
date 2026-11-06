---
id: operation-list-voices
title: list_voices
description: Voices per backend: Piper voice catalogue (installed and downloadable), Qwen3-TTS speakers and modes, Fish Speech capabilities, and saved presets.
section: Reference
order: 200
parent: operations
revision: f71f5fca93217581
---

Voices per backend: Piper voice catalogue (installed and downloadable), Qwen3-TTS speakers and modes, Fish Speech capabilities, and saved presets.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `backend` | `value` | No | Backend filter `default="all"`, `enum=["all", "piper", "qwen3tts", "fishspeech"]` |
| `language` | `string` | No | Language filter (e.g. fr, en) `default=""` |
| `installed_only` | `boolean` | No | Only installed Piper voices `default=false` |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: not declared.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation list_voices
```
