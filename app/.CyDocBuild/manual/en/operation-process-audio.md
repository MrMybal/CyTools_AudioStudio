---
id: operation-process-audio
title: process_audio
description: Render a workflow (effects, VST3/CLAP/LV2/JSFX plugins, models) over a file, with tail rendering so reverb and delay decays are never cut. A selection processes only that region and overlaps its tail onto the following audio.
section: Reference
order: 200
parent: operations
revision: e985451e54271f79
---

Render a workflow (effects, VST3/CLAP/LV2/JSFX plugins, models) over a file, with tail rendering so reverb and delay decays are never cut. A selection processes only that region and overlaps its tail onto the following audio.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `input` | `string` | Yes | Audio file to process  |
| `workflow` | `object` | No | Inline workflow document (format cytools-audiostudio-workflow). Use workflow_name instead to reference a saved workflow.  |
| `workflow_name` | `string` | No | Name of a workflow saved in data/workflows (see list_workflows). Empty = no processing. `default=""` |
| `output_format` | `value` | No | Output audio format `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | No | Sample format for WAV/FLAC/AIFF (ignored by lossy formats) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | No | Bitrate in kbit/s for MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `selection_start` | `number` | No | Start of the region to process (s); -1 = whole file `default=-1.0`, `minimum=-1.0`, `maximum=360000.0` |
| `selection_end` | `number` | No | End of the region to process (s); -1 = end of file `default=-1.0`, `minimum=-1.0`, `maximum=360000.0` |
| `tail` | `object` | No | Tail rendering override; when omitted the workflow settings apply.  |
| `output_name` | `string` | No | Output file name without extension; default = input name + suffix `default=""` |
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
runtime\python\Scripts\python.exe app\tool.py describe-operation process_audio
```
