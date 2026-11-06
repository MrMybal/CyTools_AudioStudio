---
id: operation-batch-session
title: batch_session
description: Render a session once per input sound: each sound is placed in a slot track (an existing placeholder track whose audio is replaced, keeping its inserts and automation, or a new track), the mix is rendered with the tail, then…
section: Reference
order: 200
parent: operations
revision: 6fad77828f65a529
---

Render a session once per input sound: each sound is placed in a slot track (an existing placeholder track whose audio is replaced, keeping its inserts and automation, or a new track), the mix is rendered with the tail, then the next sound takes its place.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `session` | `string` | Yes | Session folder or session.json  |
| `inputs` | `array` | Yes | Sounds to batch  |
| `slot` | `object` | No | See the operation parameters.  |
| `output_dir` | `string` | No | Output folder; empty = job workspace  |
| `suffix` | `string` | No | Suffix appended to each output name `default=""` |
| `output_format` | `value` | No | Output audio format `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | No | Sample format for WAV/FLAC/AIFF (ignored by lossy formats) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | No | Bitrate in kbit/s for MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `tail` | `object` | No | Tail rendering override; when omitted the workflow settings apply.  |
| `selection` | `array/null` | No | Optional [start, end] seconds to render `default=null` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `results` | `array` | Yes | See the operation parameters.  |
| `failed` | `array` | No | See the operation parameters.  |
| `count` | `integer` | Yes | Rendered files `default=0` |
| `outputDir` | `string` | No | Folder  |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation batch_session
```
