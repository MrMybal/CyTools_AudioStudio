---
id: operation-batch-process
title: batch_process
description: Render the same workflow over several files. Each output keeps the source name plus a suffix.
section: Reference
order: 200
parent: operations
revision: 47e9638848134a91
---

Render the same workflow over several files. Each output keeps the source name plus a suffix.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `inputs` | `array` | Yes | Audio files  |
| `workflow` | `object` | No | Inline workflow document (format cytools-audiostudio-workflow). Use workflow_name instead to reference a saved workflow.  |
| `workflow_name` | `string` | No | Name of a workflow saved in data/workflows (see list_workflows). Empty = no processing. `default=""` |
| `output_format` | `value` | No | Output audio format `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | No | Sample format for WAV/FLAC/AIFF (ignored by lossy formats) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | No | Bitrate in kbit/s for MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `suffix` | `string` | No | Suffix appended to each output name `default="_processed"` |
| `tail` | `object` | No | Tail rendering override; when omitted the workflow settings apply.  |
| `continue_on_error` | `boolean` | No | Keep going when one file fails `default=true` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `results` | `array` | Yes | See the operation parameters.  |
| `failed` | `array` | No | See the operation parameters.  |
| `count` | `integer` | Yes | Processed files `default=0` |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation batch_process
```
