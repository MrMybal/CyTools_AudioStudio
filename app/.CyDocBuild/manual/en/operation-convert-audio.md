---
id: operation-convert-audio
title: convert_audio
description: Change format, sample rate, bit depth or channel count.
section: Reference
order: 200
parent: operations
revision: 855f4d4a43a35d09
---

Change format, sample rate, bit depth or channel count.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `input` | `string` | Yes | Audio file  |
| `output_format` | `value` | No | Output audio format `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | No | Sample format for WAV/FLAC/AIFF (ignored by lossy formats) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | No | Bitrate in kbit/s for MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `samplerate` | `value` | No | Target sample rate; 0 keeps the source rate `default=0`, `enum=[0, 8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000]` |
| `channels` | `value` | No | Target channels; 0 keeps the source layout `default=0`, `enum=[0, 1, 2]` |
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
runtime\python\Scripts\python.exe app\tool.py describe-operation convert_audio
```
