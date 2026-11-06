---
id: operation-render-session
title: render_session
description: Mix an editor session (tracks, insert chains, automation lanes, master bus) to a file; stateful inserts ring out after the end (tail).
section: Reference
order: 200
parent: operations
revision: 2758125ec6a2f40a
---

Mix an editor session (tracks, insert chains, automation lanes, master bus) to a file; stateful inserts ring out after the end (tail).

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `session` | `string` | Yes | Session folder or session.json saved by the editor  |
| `output_format` | `value` | No | Output audio format `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | No | Sample format for WAV/FLAC/AIFF (ignored by lossy formats) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | No | Bitrate in kbit/s for MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `tail` | `object` | No | Tail rendering override; when omitted the workflow settings apply.  |
| `selection` | `array/null` | No | Optional [start, end] seconds to render instead of the whole session `default=null` |
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
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation render_session
```
