---
id: operation-generate-sfx
title: generate_sfx
description: Text to sound effect. Backend sfxprocedural synthesises deterministically from a catalogue of 36 archetypes (no model, instant); backend audioldm runs the AudioLDM diffusion model on CPU or CUDA.
section: Reference
order: 200
parent: operations
revision: e73ac535a0d93f6f
---

Text to sound effect. Backend sfx_procedural synthesises deterministically from a catalogue of 36 archetypes (no model, instant); backend audioldm runs the AudioLDM diffusion model on CPU or CUDA.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `prompt` | `string` | Yes | Description of the sound (English or French)  |
| `negative_prompt` | `string` | No | What to avoid (audioldm only) `default=""` |
| `duration_seconds` | `number/null` | No | Length in seconds; null = natural length (procedural) or 5 s (audioldm) `default=null`, `minimum=0.2`, `maximum=30.0` |
| `seed` | `integer` | No | Seed; variation N uses seed+N `default=0`, `minimum=0`, `maximum=2147483647` |
| `variations` | `integer` | No | Number of variations `default=1`, `minimum=1`, `maximum=4` |
| `sample_rate` | `value` | No | Output sample rate `default=44100`, `enum=[16000, 22050, 24000, 44100, 48000]` |
| `bit_depth` | `value` | No | WAV bit depth `default=16`, `enum=[16, 24]` |
| `peak_dbfs` | `number` | No | Peak normalisation target (dBFS) `default=-1.0`, `minimum=-40.0`, `maximum=0.0` |
| `steps` | `integer` | No | Diffusion steps (audioldm only) `default=20`, `minimum=5`, `maximum=100` |
| `guidance_scale` | `number` | No | Guidance scale (audioldm only) `default=2.5`, `minimum=1.0`, `maximum=15.0` |
| `device` | `value` | No | Compute device (audioldm only) `default="cuda"`, `enum=["cuda", "cpu"]` |
| `post_workflow` | `string` | No | Optional workflow (saved name) applied to the generated audio, with tail rendering. `default=""` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `variations` | `array` | Yes | Generated files  |
| `backend` | `string` | Yes | Backend id  |
| `engine` | `string` | No | Engine name  |
| `sampleRate` | `integer` | Yes | Sample rate `default=44100` |
| `recipe` | `object/null` | No | Procedural recipe (sfx_procedural only)  |
| `warnings` | `array` | No | See the operation parameters.  |
| `report` | `object` | No | See the operation parameters.  |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: `sfx_procedural`, `audioldm`
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation generate_sfx
```
