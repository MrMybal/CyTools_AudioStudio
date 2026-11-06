---
id: operation-master-audio
title: master_audio
description: Mastering: match a reference recording (Matchering: spectrum, dynamics and loudness) or normalise to a loudness target with a true-peak limiter. Optional post workflow.
section: Reference
order: 200
parent: operations
revision: ff08599f2d461100
---

Mastering: match a reference recording (Matchering: spectrum, dynamics and loudness) or normalise to a loudness target with a true-peak limiter. Optional post workflow.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `input` | `string` | Yes | Track to master  |
| `reference` | `string` | No | Reference recording to match (mode reference) `default=""` |
| `mode` | `value` | No | Mode `default="loudness"`, `enum=["reference", "loudness"]` |
| `target_lufs` | `number` | No | Integrated loudness target (mode loudness) `default=-14.0`, `minimum=-30.0`, `maximum=-5.0` |
| `ceiling_db` | `number` | No | True-peak ceiling (dBTP) `default=-1.0`, `minimum=-6.0`, `maximum=0.0` |
| `output_format` | `value` | No | Output audio format `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | No | Sample format for WAV/FLAC/AIFF (ignored by lossy formats) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | No | Bitrate in kbit/s for MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `post_workflow` | `string` | No | Optional workflow (saved name) applied to the generated audio, with tail rendering. `default=""` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `file` | `string` | Yes | Result file  |
| `mimeType` | `string` | Yes | MIME type  |
| `sampleRate` | `integer` | Yes | Sample rate `default=48000` |
| `channels` | `integer` | Yes | Channels `default=2` |
| `durationSeconds` | `number` | Yes | Duration (s) `default=0.0` |
| `sizeBytes` | `integer` | No | Size in bytes `default=0` |
| `report` | `object` | No | Render report  |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: `matchering`
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation master_audio
```
